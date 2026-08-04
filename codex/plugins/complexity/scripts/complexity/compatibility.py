"""Compatibility projections from the canonical analysis outcome.

Legacy commands retain their historical report shapes, but they no longer
construct independent evidence.  This module owns the translation from the
canonical :class:`AnalysisOutcome` to those shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analysis_contract import AnalysisOutcome
from function_complexity.models import FunctionMetric
from scan_hotspots import ScanReport, ScanStats, limit_findings


@dataclass
class MeasuredFunction:
    path: str
    metric: FunctionMetric


@dataclass
class MetricFailure:
    path: str
    message: str


@dataclass
class TimingSummary:
    scan_seconds: float
    metric_seconds: float
    total_seconds: float


@dataclass
class RepoTriageReport:
    root: Path
    command: str
    scan_report: ScanReport
    metrics: list[MeasuredFunction]
    metric_failures: list[MetricFailure]
    timings: TimingSummary
    outcome: AnalysisOutcome


@dataclass(frozen=True)
class CompatibilityPresentation:
    verdict: dict[str, str] | None
    verdict_markdown: str
    next_action_plan: str


def project_repo_triage_report(
    root: Path,
    outcome: AnalysisOutcome,
    *,
    command: str,
    max_findings: int,
) -> RepoTriageReport:
    """Project one canonical outcome into the integrated legacy report shape."""
    scan_report = ScanReport(
        stats=scan_stats_from_outcome(root, outcome),
        findings=limit_findings(outcome.findings, max_findings),
        command=command,
    )
    # Preserve the canonical order so legacy projections cannot silently
    # re-rank the same deterministic evidence with a different policy.
    metrics = [
        MeasuredFunction(item.path, item.metric)
        for item in outcome.top_functions
    ]
    failures = metric_failures_from_outcome(outcome)
    timings = TimingSummary(
        scan_seconds=outcome.timings.heuristic_seconds or 0.0,
        metric_seconds=outcome.timings.metrics_seconds or 0.0,
        total_seconds=outcome.timings.total_seconds,
    )
    return RepoTriageReport(
        root,
        command,
        scan_report,
        metrics,
        failures,
        timings,
        outcome,
    )


def scan_stats_from_outcome(root: Path, outcome: AnalysisOutcome) -> ScanStats:
    return ScanStats(
        root=str(root),
        files_scanned=outcome.coverage.analysed_files,
        files_skipped=outcome.coverage.skipped_files + outcome.coverage.failed_files,
        language_counts=outcome.coverage.per_language,
    )


def metric_failures_from_outcome(outcome: AnalysisOutcome) -> list[MetricFailure]:
    return [
        MetricFailure(diagnostic.path or "[adapter]", diagnostic.reason)
        for diagnostic in outcome.diagnostics
        if diagnostic.stage in {"python-ast", "lizard"}
    ]
