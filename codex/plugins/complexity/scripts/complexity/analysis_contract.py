"""Stable contract for bounded complexity analysis."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from function_complexity.models import FunctionMetric
    from heuristic_scanner import Hotspot


AnalysisStatus = Literal["complete", "partial", "unsupported"]
AnalysisMode = Literal["quick", "standard"]
CompatibilityProfile = Literal["heuristic", "metrics", "integrated"]
EvidenceLane = Literal["heuristic", "metrics"]
AdapterStatus = Literal[
    "complete", "partial", "unavailable", "failed", "not-applicable", "not-requested"
]
SCHEMA_VERSION = 1
PLUGIN_VERSION = "0.2.1"
DEFAULT_EXCLUDES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "fixtures",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)


@dataclass(frozen=True)
class AnalysisRequest:
    target: Path
    mode: AnalysisMode = "standard"
    excludes: frozenset[str] = frozenset()
    max_findings: int = 80
    max_top: int = 8
    repo_context: Path | None = None
    coverage_xml: Path | None = None
    context_limit: int = 25
    _compatibility_profile: CompatibilityProfile | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        if self.mode not in {"quick", "standard"}:
            raise ValueError(f"Unsupported analysis mode: {self.mode}")
        if self.max_findings < 0:
            raise ValueError("max_findings must be non-negative")
        if self.max_top < 0:
            raise ValueError("max_top must be non-negative")
        if self.context_limit < 0:
            raise ValueError("context_limit must be non-negative")

    @classmethod
    def for_compatibility(
        cls,
        target: Path,
        profile: CompatibilityProfile,
        *,
        excludes: frozenset[str] = frozenset(),
        max_findings: int = 80,
        max_top: int = 8,
        repo_context: Path | None = None,
        coverage_xml: Path | None = None,
        context_limit: int = 25,
    ) -> AnalysisRequest:
        if profile not in {"heuristic", "metrics", "integrated"}:
            raise ValueError(f"Unsupported compatibility profile: {profile}")
        return cls(
            target=target,
            excludes=excludes,
            max_findings=max_findings,
            max_top=max_top,
            repo_context=repo_context,
            coverage_xml=coverage_xml,
            context_limit=context_limit,
            _compatibility_profile=profile,
        )

    @property
    def required_lanes(self) -> frozenset[EvidenceLane]:
        if self._compatibility_profile == "heuristic":
            return frozenset({"heuristic"})
        if self._compatibility_profile == "metrics":
            return frozenset({"metrics"})
        if self._compatibility_profile == "integrated":
            return frozenset({"heuristic", "metrics"})
        return (
            frozenset({"heuristic"})
            if self.mode == "quick"
            else frozenset({"heuristic", "metrics"})
        )


@dataclass(frozen=True)
class Diagnostic:
    path: str | None
    stage: str
    reason: str


@dataclass(frozen=True)
class CoverageLedger:
    discovered_files: int = 0
    eligible_files: int = 0
    analysed_files: int = 0
    heuristic_eligible_files: int = 0
    heuristic_analysed_files: int = 0
    metric_eligible_files: int = 0
    metric_analysed_files: int = 0
    skipped_files: int = 0
    unsupported_files: int = 0
    failed_files: int = 0
    per_language: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterState:
    identifier: str
    status: AdapterStatus
    detail: str = ""
    version: str | None = None


@dataclass(frozen=True)
class MeasuredMetric:
    path: str
    metric: FunctionMetric


@dataclass(frozen=True)
class RankedFile:
    path: str
    reason: str
    worst_risk: str
    non_a_functions: int
    runtime_flagged_functions: int
    material_hotspot_count: int
    hotspot_count: int
    function_count: int


@dataclass(frozen=True)
class InspectionTarget:
    path: str
    line: int
    name: str
    evidence_kind: str
    reason: str


@dataclass(frozen=True)
class AnalysisTimings:
    inventory_seconds: float | None = None
    heuristic_seconds: float | None = None
    metrics_seconds: float | None = None
    repo_context_seconds: float | None = None
    total_seconds: float = 0.0


@dataclass(frozen=True)
class ContextSignalSummary:
    identifier: str
    available: bool
    attempted: int = 0
    completed: int = 0
    with_value: int = 0


@dataclass(frozen=True)
class RepoContextSummary:
    root: str | None = None
    eligible_functions: int = 0
    requested_top_k: int = 0
    selected_functions: int = 0
    enriched_functions: int = 0
    sampled: bool = False
    signals: tuple[ContextSignalSummary, ...] = ()


@dataclass(frozen=True)
class AnalysisOutcome:
    status: AnalysisStatus
    target: str
    target_kind: Literal["file", "directory"]
    request: AnalysisRequest
    coverage: CoverageLedger
    diagnostics: tuple[Diagnostic, ...] = ()
    findings: tuple[Hotspot, ...] = ()
    metrics: tuple[MeasuredMetric, ...] = ()
    adapters: tuple[AdapterState, ...] = ()
    verdict: dict[str, str] | None = None
    decision_fields: dict[str, object] = field(default_factory=dict)
    top_files: tuple[RankedFile, ...] = ()
    top_functions: tuple[MeasuredMetric, ...] = ()
    inspection_queue: tuple[InspectionTarget, ...] = ()
    repo_context: RepoContextSummary = field(default_factory=RepoContextSummary)
    timings: AnalysisTimings = field(default_factory=AnalysisTimings)


class AnalysisInputError(ValueError):
    """A target cannot be analysed; command callers map this to exit status 2."""


def exit_code_for_status(status: AnalysisStatus) -> int:
    return {"complete": 0, "partial": 3, "unsupported": 4}[status]


def status_message(status: AnalysisStatus) -> str | None:
    return {
        "complete": None,
        "partial": "Analysis partial: required evidence coverage is incomplete.",
        "unsupported": "Analysis unsupported: no eligible source file was analysed.",
    }[status]


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed
