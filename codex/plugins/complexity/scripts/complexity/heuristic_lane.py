"""Heuristic-lane execution behind the canonical analysis seam."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from analysis_contract import (
    PLUGIN_VERSION,
    AdapterState,
    AnalysisInputError,
)
from heuristic_scanner import (
    SCAN_SUFFIXES,
    Hotspot,
    WrapperEvidence,
    collect_repo_python_wrapper_evidence,
    read_text,
    scan_text_by_language,
)


class HeuristicLedger(Protocol):
    paths: Sequence[Path]
    heuristic_analysed: set[Path]

    def fail(self, path: Path, stage: str, reason: str) -> None: ...

    def fail_read(self, path: Path, stage: str, reason: str) -> None: ...

    def has_failure(self, stage: str) -> bool: ...

    def mark_heuristic_analysed(self, path: Path) -> None: ...


TextReader = Callable[[Path], str | None]
WrapperCollector = Callable[[Sequence[Path], Path], dict[str, WrapperEvidence]]
TextScanner = Callable[[Path, Path, str, dict[str, WrapperEvidence]], list[Hotspot]]


def run_heuristic_lane(
    root: Path,
    ledger: HeuristicLedger,
    *,
    reader: TextReader = read_text,
    wrapper_collector: WrapperCollector = collect_repo_python_wrapper_evidence,
    scanner: TextScanner = scan_text_by_language,
) -> tuple[list[Hotspot], AdapterState]:
    """Scan eligible source paths and keep failures visible in the ledger."""
    paths = heuristic_paths(ledger.paths)
    repo_wrappers = wrapper_collector(paths, root)
    findings = [
        finding
        for path in paths
        for finding in scan_heuristic_path(
            path,
            root,
            ledger,
            repo_wrappers,
            reader,
            scanner,
        )
    ]
    return findings, heuristic_adapter_state(ledger, paths)


def heuristic_paths(paths: Sequence[Path]) -> list[Path]:
    return [path for path in paths if path.suffix.lower() in SCAN_SUFFIXES]


def scan_heuristic_path(
    path: Path,
    root: Path,
    ledger: HeuristicLedger,
    repo_wrappers: dict[str, WrapperEvidence],
    reader: TextReader,
    scanner: TextScanner,
) -> list[Hotspot]:
    try:
        text = reader(path)
        if text is None:
            ledger.fail_read(path, "heuristic", "unable to decode or read source file")
            return []
        findings = scanner(path, root, text, repo_wrappers)
        ledger.mark_heuristic_analysed(path)
        return findings
    except AnalysisInputError:
        raise
    except Exception as error:  # noqa: BLE001 - preserve per-file adapter failures
        ledger.fail(path, "heuristic", f"{type(error).__name__}: {error}")
        return []


def heuristic_adapter_state(
    ledger: HeuristicLedger, paths: Sequence[Path]
) -> AdapterState:
    if not paths:
        return AdapterState("text-heuristic", "not-applicable", version=PLUGIN_VERSION)
    failed = ledger.has_failure("heuristic")
    analysed = len(ledger.heuristic_analysed)
    status = "partial" if failed and analysed else ("failed" if failed else "complete")
    return AdapterState("text-heuristic", status, version=PLUGIN_VERSION)
