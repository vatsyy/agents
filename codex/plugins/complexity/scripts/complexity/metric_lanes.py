"""Metric-lane execution behind the canonical analysis seam.

The canonical analysis owns policy and the coverage ledger.  This module owns
tool execution and translates each concrete adapter's failures into the stable
metric outcome contract.
"""

from __future__ import annotations

import platform
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from analysis_contract import AdapterState, Diagnostic, MeasuredMetric
from function_complexity.lizard_adapter import (
    CAPABILITY_VERSION as LIZARD_CAPABILITY_VERSION,
)
from function_complexity.lizard_adapter import (
    LizardBatchError,
    analyse_many_with_lizard_cli,
)
from function_complexity.models import FunctionMetric
from function_complexity.python_ast import analyse_python


class MetricLedger(Protocol):
    """The coverage operations required by metric adapters."""

    metric_eligible: set[Path]
    metric_analysed: set[Path]

    def fail(self, path: Path, stage: str, reason: str) -> None: ...

    def fail_read(self, path: Path, stage: str, reason: str) -> None: ...

    def mark_metric_analysed(self, path: Path) -> None: ...


MetricAnalyser = Callable[[Path], Sequence[FunctionMetric]]
LizardRunner = Callable[[Sequence[Path]], Sequence[tuple[Path, FunctionMetric]]]


def run_metric_lanes(
    root: Path,
    ledger: MetricLedger,
    *,
    python_analyser: MetricAnalyser = analyse_python,
    lizard_runner: LizardRunner = analyse_many_with_lizard_cli,
) -> tuple[list[MeasuredMetric], list[Diagnostic], list[AdapterState]]:
    """Run every requested metric adapter and preserve partial coverage."""
    rows: list[MeasuredMetric] = []
    diagnostics: list[Diagnostic] = []
    adapter_states: list[AdapterState] = []

    python_paths, other_paths = partition_metric_paths(ledger.metric_eligible)
    rows.extend(
        run_python_lane(
            root,
            ledger,
            python_paths,
            python_analyser,
            adapter_states,
        )
    )
    rows.extend(
        run_lizard_lane(
            root,
            ledger,
            other_paths,
            lizard_runner,
            adapter_states,
        )
    )
    return rows, diagnostics, adapter_states


def partition_metric_paths(paths: set[Path]) -> tuple[list[Path], list[Path]]:
    ordered = sorted(paths, key=str)
    return (
        [path for path in ordered if path.suffix.lower() == ".py"],
        [path for path in ordered if path.suffix.lower() != ".py"],
    )


def run_python_lane(
    root: Path,
    ledger: MetricLedger,
    paths: Sequence[Path],
    analyser: MetricAnalyser,
    adapter_states: list[AdapterState],
) -> list[MeasuredMetric]:
    rows: list[MeasuredMetric] = []
    failed = False
    for path in paths:
        try:
            rows.extend(
                MeasuredMetric(relative_path(path, root), metric)
                for metric in analyser(path)
            )
            ledger.mark_metric_analysed(path)
        except OSError as error:
            failed = True
            ledger.fail_read(path, "python-ast", str(error))
        except SystemExit as error:
            failed = True
            ledger.fail(path, "python-ast", str(error))
        except Exception as error:  # noqa: BLE001 - preserve per-file adapter failures
            failed = True
            ledger.fail(path, "python-ast", f"{type(error).__name__}: {error}")

    adapter_states.append(
        AdapterState(
            "python-ast",
            python_adapter_status(paths, ledger, failed),
            version=platform.python_version(),
        )
    )
    return rows


def python_adapter_status(
    paths: Sequence[Path], ledger: MetricLedger, failed: bool
) -> str:
    if not paths:
        return "not-applicable"
    if failed and ledger.metric_analysed & set(paths):
        return "partial"
    return "failed" if failed else "complete"


def run_lizard_lane(
    root: Path,
    ledger: MetricLedger,
    paths: Sequence[Path],
    runner: LizardRunner,
    adapter_states: list[AdapterState],
) -> list[MeasuredMetric]:
    if not paths:
        adapter_states.append(
            AdapterState("lizard", "not-applicable", version=LIZARD_CAPABILITY_VERSION)
        )
        return []

    try:
        by_path = runner(paths)
        return complete_lizard_lane(root, ledger, paths, by_path, adapter_states)
    except LizardBatchError as error:
        return partial_lizard_lane(root, ledger, error, adapter_states)
    except SystemExit as error:
        return failed_lizard_lane(ledger, paths, "unavailable", str(error), adapter_states)
    except Exception as error:  # noqa: BLE001 - preserve a truthful adapter status
        return failed_lizard_lane(
            ledger,
            paths,
            "failed",
            f"{type(error).__name__}: {error}",
            adapter_states,
        )


def complete_lizard_lane(
    root: Path,
    ledger: MetricLedger,
    paths: Sequence[Path],
    by_path: Sequence[tuple[Path, FunctionMetric]],
    adapter_states: list[AdapterState],
) -> list[MeasuredMetric]:
    rows = [
        MeasuredMetric(relative_path(path, root), metric)
        for path, metric in by_path
    ]
    for path in paths:
        ledger.mark_metric_analysed(path)
    adapter_states.append(
        AdapterState("lizard", "complete", version=LIZARD_CAPABILITY_VERSION)
    )
    return rows


def partial_lizard_lane(
    root: Path,
    ledger: MetricLedger,
    error: LizardBatchError,
    adapter_states: list[AdapterState],
) -> list[MeasuredMetric]:
    rows = [
        MeasuredMetric(relative_path(path, root), metric)
        for path, metric in error.rows
    ]
    for path in error.completed_paths:
        ledger.mark_metric_analysed(path)
    for path in error.failed_paths:
        ledger.fail(path, "lizard", error.reason)
    adapter_states.append(
        AdapterState(
            "lizard",
            "partial" if error.completed_paths else "failed",
            error.reason,
            version=LIZARD_CAPABILITY_VERSION,
        )
    )
    return rows


def failed_lizard_lane(
    ledger: MetricLedger,
    paths: Sequence[Path],
    status: str,
    reason: str,
    adapter_states: list[AdapterState],
) -> list[MeasuredMetric]:
    for path in paths:
        ledger.fail(path, "lizard", reason)
    adapter_states.append(
        AdapterState("lizard", status, reason, version=LIZARD_CAPABILITY_VERSION)
    )
    return []


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
