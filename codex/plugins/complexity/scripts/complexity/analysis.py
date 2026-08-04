"""One-pass orchestration and validity policy for complexity analysis."""

from __future__ import annotations

import os
import platform
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from analysis_contract import (
    DEFAULT_EXCLUDES,
    PLUGIN_VERSION,
    AdapterState,
    AnalysisInputError,
    AnalysisOutcome,
    AnalysisRequest,
    AnalysisTimings,
    CoverageLedger,
    Diagnostic,
    InspectionTarget,
    MeasuredMetric,
    RepoContextSummary,
)
from decision_fields import build_decision_fields
from function_complexity.lizard_adapter import (
    CAPABILITY_VERSION as LIZARD_CAPABILITY_VERSION,
)
from function_complexity.lizard_adapter import (
    analyse_many_with_lizard_cli,
    supports_path,
)
from function_complexity.python_ast import analyse_python
from function_complexity.repo_context import enrich_ranked_metrics
from heuristic_lane import run_heuristic_lane
from heuristic_scanner import (
    SCAN_SUFFIXES,
    Hotspot,
    dedupe,
    sort_key,
)
from metric_lanes import run_metric_lanes
from ranking import (
    DecisionScope,
    decision_scope_for_target_kind,
    rank_files,
    rank_functions,
)

SHELL_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".fish"})
INVENTORY_SKIP_STAGE = "inventory-skip"


def analyse(request: AnalysisRequest) -> AnalysisOutcome:
    total_started = time.perf_counter()
    inventory_started = time.perf_counter()
    root, paths, inventory_diagnostics, named_target, skipped_paths = inventory(request)
    inventory_seconds = elapsed_since(inventory_started)
    required = request.required_lanes
    coverage = LedgerBuilder(
        paths, inventory_diagnostics, required, named_target, skipped_paths
    )
    diagnostics = inventory_diagnostics
    findings: list[Hotspot] = []
    metrics: list[MeasuredMetric] = []
    adapters: list[AdapterState] = []
    heuristic_seconds: float | None = None
    metrics_seconds: float | None = None
    repo_context_seconds: float | None = None

    if "heuristic" in required:
        heuristic_started = time.perf_counter()
        heuristic_findings, heuristic_adapter = run_heuristics(root, coverage)
        heuristic_seconds = elapsed_since(heuristic_started)
        findings.extend(heuristic_findings)
        adapters.append(heuristic_adapter)
    else:
        adapters.append(
            AdapterState("text-heuristic", "not-requested", version=PLUGIN_VERSION)
        )

    if "metrics" in required:
        metrics_started = time.perf_counter()
        metric_rows, metric_diagnostics, metric_adapter = run_metrics(root, coverage)
        metrics_seconds = elapsed_since(metrics_started)
        metrics.extend(metric_rows)
        diagnostics.extend(metric_diagnostics)
        adapters.extend(metric_adapter)
    else:
        adapters.extend(
            (
                AdapterState(
                    "python-ast", "not-requested", version=platform.python_version()
                ),
                AdapterState(
                    "lizard", "not-requested", version=LIZARD_CAPABILITY_VERSION
                ),
            )
        )

    findings = sorted(dedupe(findings), key=sort_key)
    metrics = sorted(metrics, key=metric_source_key)
    target_kind = "file" if named_target is not None else "directory"
    decision_scope = decision_scope_for_target_kind(target_kind)
    top_functions = rank_functions(metrics, findings, scope=decision_scope)
    repo_context = RepoContextSummary()
    context_root = request.repo_context
    if context_root is None and request.coverage_xml is not None:
        context_root = root
    if context_root is not None:
        context_started = time.perf_counter()
        repo_context, context_diagnostics, context_adapters = enrich_ranked_metrics(
            [((root / item.path).resolve(), item.metric) for item in top_functions],
            repo_context=context_root,
            coverage_xml=request.coverage_xml,
            requested_top_k=request.context_limit,
        )
        repo_context_seconds = elapsed_since(context_started)
        diagnostics.extend(context_diagnostics)
        adapters.extend(context_adapters)
    else:
        adapters.extend(
            (
                AdapterState("repo-context-rg", "not-requested"),
                AdapterState("repo-context-git", "not-requested"),
                AdapterState("coverage-xml", "not-requested"),
            )
        )
    adapters.sort(key=adapter_order)
    top_files = rank_files(metrics, findings, scope=decision_scope)
    inspection_queue = build_inspection_queue(top_functions, findings)
    ledger = coverage.freeze()
    status = derive_status(ledger, required)
    verdict = verdict_for(status, findings, metrics, decision_scope)
    decision_fields = build_decision_fields(
        status,
        verdict,
        top_functions,
        findings,
        repo_context,
        scope=decision_scope,
    )
    return AnalysisOutcome(
        status=status,
        target=str(request.target.expanduser().resolve()),
        target_kind=target_kind,
        request=request,
        coverage=ledger,
        diagnostics=tuple(diagnostics),
        findings=tuple(findings),
        metrics=tuple(metrics),
        adapters=tuple(adapters),
        verdict=verdict,
        decision_fields=decision_fields,
        top_files=tuple(top_files),
        top_functions=tuple(top_functions),
        inspection_queue=tuple(inspection_queue),
        repo_context=repo_context,
        timings=AnalysisTimings(
            inventory_seconds=inventory_seconds,
            heuristic_seconds=heuristic_seconds,
            metrics_seconds=metrics_seconds,
            repo_context_seconds=repo_context_seconds,
            total_seconds=elapsed_since(total_started),
        ),
    )


def inventory(
    request: AnalysisRequest,
) -> tuple[Path, list[Path], list[Diagnostic], Path | None, set[Path]]:
    """Resolve the requested scope and inventory only files within its root.

    Explicit file targets retain their existing resolved-target behaviour.
    Directory scans skip discovered file symlinks before resolving or admitting
    them, so every queued path is a directly discovered regular file.
    """
    target = request.target.expanduser()
    if not target.exists():
        raise AnalysisInputError(f"Target not found: {target}")
    if not os.access(target, os.R_OK):
        raise AnalysisInputError(f"Target is not readable: {target}")
    target = target.resolve()
    if target.is_file():
        return target.parent, [target], [], target, set()
    if not target.is_dir():
        raise AnalysisInputError(f"Target is not a regular file or directory: {target}")

    diagnostics: list[Diagnostic] = []
    skipped: set[Path] = set()
    files = inventory_files(
        target,
        DEFAULT_EXCLUDES | set(request.excludes),
        diagnostics,
        skipped,
    )
    return target, files, diagnostics, None, skipped


def inventory_files(
    target: Path,
    excludes: set[str],
    diagnostics: list[Diagnostic],
    skipped: set[Path],
) -> list[Path]:
    paths: list[Path] = []

    def onerror(error: OSError) -> None:
        diagnostics.append(
            Diagnostic(str(getattr(error, "filename", target)), "inventory", str(error))
        )

    for dirpath, dirnames, filenames in os.walk(target, onerror=onerror):
        dirnames[:] = sorted(name for name in dirnames if name not in excludes)
        paths.extend(
            inventory_files_in_directory(
                dirpath,
                filenames,
                diagnostics,
                skipped,
            )
        )
    return sorted(paths, key=str)


def inventory_files_in_directory(
    dirpath: str | os.PathLike[str],
    filenames: Iterable[str],
    diagnostics: list[Diagnostic],
    skipped: set[Path],
) -> list[Path]:
    paths: list[Path] = []
    for filename in sorted(filenames):
        path = Path(dirpath) / filename
        try:
            if path.is_symlink():
                record_inventory_skip(
                    path,
                    "skipped discovered file symlink",
                    diagnostics,
                    skipped,
                )
                continue
            if path.is_file():
                paths.append(path)
        except (OSError, RuntimeError) as error:
            diagnostics.append(Diagnostic(str(path), "inventory", str(error)))
    return paths


def record_inventory_skip(
    path: Path,
    reason: str,
    diagnostics: list[Diagnostic],
    skipped: set[Path],
) -> None:
    skipped.add(path)
    diagnostics.append(Diagnostic(str(path), INVENTORY_SKIP_STAGE, reason))


@dataclass(frozen=True)
class SourceClassification:
    heuristic_required: bool
    metric_required: bool
    recognized_source: bool
    supports_required: bool


def classify_source(path: Path, required: frozenset[str]) -> SourceClassification:
    suffix = path.suffix.lower()
    heuristic_supported = suffix in SCAN_SUFFIXES
    metric_supported = suffix == ".py" or supports_path(path)
    heuristic_required = "heuristic" in required and heuristic_supported
    metric_required = "metrics" in required and metric_supported
    return SourceClassification(
        heuristic_required=heuristic_required,
        metric_required=metric_required,
        recognized_source=(
            heuristic_supported or metric_supported or suffix in SHELL_SUFFIXES
        ),
        supports_required=heuristic_required or metric_required,
    )


class LedgerBuilder:
    def __init__(
        self,
        paths: Iterable[Path],
        diagnostics: list[Diagnostic],
        required: frozenset[str],
        named_target: Path | None,
        skipped: Iterable[Path],
    ) -> None:
        self.paths = list(paths)
        self.required = required
        self.diagnostics = diagnostics
        self.named_target = named_target
        self.discovered_files = len(self.paths)
        self.eligible: set[Path] = set()
        self.analysed: set[Path] = set()
        self.heuristic_eligible: set[Path] = set()
        self.heuristic_analysed: set[Path] = set()
        self.metric_eligible: set[Path] = set()
        self.metric_analysed: set[Path] = set()
        self.unsupported: set[Path] = set()
        self.failed: set[Path] = set()
        self.skipped: set[Path] = set(skipped)
        self.per_language = Counter(path.suffix or "[none]" for path in self.paths)
        self._classify()

    def _classify(self) -> None:
        for path in self.paths:
            self._record_classification(path, classify_source(path, self.required))

    def _record_classification(
        self, path: Path, classification: SourceClassification
    ) -> None:
        if classification.supports_required:
            self.eligible.add(path)
        if classification.heuristic_required:
            self.heuristic_eligible.add(path)
        if classification.metric_required:
            self.metric_eligible.add(path)
        if classification.recognized_source and not classification.supports_required:
            self.unsupported.add(path)
            self.diagnostics.append(
                Diagnostic(str(path), "adapter", "recognized source has no required adapter")
            )

    def fail(self, path: Path, stage: str, reason: str) -> None:
        self.failed.add(path)
        self.diagnostics.append(Diagnostic(str(path), stage, reason))

    def fail_read(self, path: Path, stage: str, reason: str) -> None:
        if path == self.named_target:
            raise AnalysisInputError(f"Target is not readable: {path}")
        self.fail(path, stage, reason)

    def has_failure(self, stage: str) -> bool:
        return any(diagnostic.stage == stage for diagnostic in self.diagnostics)

    def mark_heuristic_analysed(self, path: Path) -> None:
        self.heuristic_analysed.add(path)
        self.analysed.add(path)

    def mark_metric_analysed(self, path: Path) -> None:
        self.metric_analysed.add(path)
        self.analysed.add(path)

    def freeze(self) -> CoverageLedger:
        return CoverageLedger(
            discovered_files=self.discovered_files,
            eligible_files=len(self.eligible),
            analysed_files=len(self.analysed),
            heuristic_eligible_files=len(self.heuristic_eligible),
            heuristic_analysed_files=len(self.heuristic_analysed),
            metric_eligible_files=len(self.metric_eligible),
            metric_analysed_files=len(self.metric_analysed),
            skipped_files=len(self.skipped),
            unsupported_files=len(self.unsupported),
            failed_files=len(self.failed)
            + len(self.diagnostics_for_inventory_errors()),
            per_language=dict(sorted(self.per_language.items())),
        )

    def diagnostics_for_inventory_errors(self) -> list[Diagnostic]:
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.stage == "inventory"
        ]


def run_heuristics(
    root: Path, ledger: LedgerBuilder
) -> tuple[list[Hotspot], AdapterState]:
    return run_heuristic_lane(root, ledger)


def run_metrics(
    root: Path, ledger: LedgerBuilder
) -> tuple[list[MeasuredMetric], list[Diagnostic], list[AdapterState]]:
    return run_metric_lanes(
        root,
        ledger,
        python_analyser=analyse_python,
        lizard_runner=analyse_many_with_lizard_cli,
    )


def derive_status(ledger: CoverageLedger, required: frozenset[str]) -> str:
    if ledger.failed_files:
        return "partial"
    if ledger.analysed_files == 0:
        if ledger.skipped_files:
            return "partial"
        return "unsupported"
    if ledger.skipped_files:
        return "partial"
    if ledger.unsupported_files:
        return "partial"
    if (
        "heuristic" in required
        and ledger.heuristic_analysed_files != ledger.heuristic_eligible_files
    ):
        return "partial"
    if (
        "metrics" in required
        and ledger.metric_analysed_files != ledger.metric_eligible_files
    ):
        return "partial"
    return "complete"


def verdict_for(
    status: str,
    findings: list[Hotspot],
    metrics: list[MeasuredMetric],
    scope: DecisionScope | None = None,
) -> dict[str, str] | None:
    if status == "unsupported":
        return None
    if status == "partial":
        return {
            "overall": "inconclusive; required analysis did not cover the full eligible scope"
        }
    authority = scope or DecisionScope()
    material_findings = any(authority.is_material_finding(item) for item in findings)
    material_metrics = any(authority.is_material_metric(item) for item in metrics)
    return {
        "overall": "review ranked findings"
        if material_findings or material_metrics
        else "no immediate refactor"
    }


ADAPTER_ORDER = {
    "python-ast": 0,
    "lizard": 1,
    "text-heuristic": 2,
    "repo-context-rg": 3,
    "repo-context-git": 4,
    "coverage-xml": 5,
}


def adapter_order(item: AdapterState) -> int:
    return ADAPTER_ORDER.get(item.identifier, len(ADAPTER_ORDER))


def metric_source_key(item: MeasuredMetric) -> tuple[str, int, str]:
    return (item.path, item.metric.start, item.metric.name)


def build_inspection_queue(
    metrics: list[MeasuredMetric], findings: list[Hotspot]
) -> list[InspectionTarget]:
    queue: list[InspectionTarget] = []
    seen: set[tuple[str, int]] = set()
    for item in metrics:
        key = (item.path, item.metric.start)
        if key in seen:
            continue
        seen.add(key)
        queue.append(
            InspectionTarget(
                path=item.path,
                line=item.metric.start,
                name=item.metric.name,
                evidence_kind="deterministic-metric",
                reason="ranked deterministic complexity or runtime evidence",
            )
        )
    for item in findings:
        key = (item.path, item.line)
        if key in seen:
            continue
        seen.add(key)
        queue.append(
            InspectionTarget(
                path=item.path,
                line=item.line,
                name=item.symbol,
                evidence_kind="heuristic-hotspot",
                reason=f"{item.severity} severity, {item.confidence} confidence {item.kind}",
            )
        )
    return queue


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def elapsed_since(started: float) -> float:
    return round(time.perf_counter() - started, 6)
