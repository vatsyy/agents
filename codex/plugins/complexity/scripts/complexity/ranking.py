"""Stable ranking policy for complexity evidence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from analysis_contract import MeasuredMetric, RankedFile
from function_complexity.output import runtime_flags
from heuristic_scanner import Hotspot

RISK_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
MaterialFinding = Callable[[Hotspot], bool]
DecisionTargetKind = Literal["file", "directory"]
PathScope = Literal["production", "migration", "test"]
CALIBRATION_ONLY_LOOP_CLASSIFICATIONS = frozenset(
    {
        "retry loop",
        "fixed-size loop",
        "streaming loop",
        "pagination loop",
        "traversal loop",
    }
)
PERFORMANCE_FINDING_KINDS = frozenset(
    {
        "io-in-loop",
        "membership-in-loop",
        "nested-loop",
        "nested-or-callback-loop",
        "render-derived-work",
        "repeated-scan",
        "sort-in-loop",
        "wrapper-io-in-loop",
    }
)


@dataclass(frozen=True)
class DecisionScope:
    """Own the scope policy used by every decision-bearing projection.

    A repository analysis is production-oriented: test and migration support
    code remains visible evidence, but it cannot be the only reason to call
    for a production refactor.  An explicitly targeted file is different: the
    target itself is the user's requested scope, regardless of its path.
    """

    target_kind: DecisionTargetKind = "directory"

    @classmethod
    def for_target_kind(cls, target_kind: str) -> DecisionScope:
        if target_kind not in {"file", "directory"}:
            raise ValueError(f"Unsupported decision target kind: {target_kind}")
        return cls(target_kind="file" if target_kind == "file" else "directory")

    @property
    def explicitly_targeted(self) -> bool:
        return self.target_kind == "file"

    def path_scope(self, path: str) -> PathScope:
        return classify_path_scope(path)

    def includes(self, path: str) -> bool:
        """Whether a path can contribute to the current production decision."""
        return self.explicitly_targeted or self.path_scope(path) == "production"

    def is_material_finding(self, item: Hotspot) -> bool:
        """Return whether a heuristic lead is material in this scope."""
        return self.includes(item.path) and _base_material_finding(item)

    def is_material_performance_finding(self, item: Hotspot) -> bool:
        """Return whether a runtime heuristic is material in this scope."""
        return self.is_material_finding(item) and is_performance_finding(item)

    def is_material_metric(self, item: MeasuredMetric) -> bool:
        """Return whether deterministic evidence is material in this scope."""
        return self.includes(item.path) and (
            item.metric.risk not in {"", "A"} or bool(runtime_flags(item.metric))
        )


def decision_scope_for_target_kind(target_kind: str) -> DecisionScope:
    """Build the canonical decision scope from the analysis target shape."""
    return DecisionScope.for_target_kind(target_kind)


def classify_path_scope(path: str) -> PathScope:
    """Classify conventional test and migration paths without reading source."""
    parts = tuple(part.lower() for part in path.replace("\\", "/").split("/"))
    filename = parts[-1] if parts else ""
    if (
        "tests" in parts
        or "test" in parts
        or "unit_tests" in parts
        or filename in {"test.py", "tests.py", "conftest.py"}
        or filename.startswith(("test_", "test."))
        or "_test." in filename
        or ".test." in filename
    ):
        return "test"
    if (
        "patches" in parts
        or "migrations" in parts
        or "migration" in parts
        or filename.startswith(("patch_", "migration_"))
        or filename.endswith(("_patch.py", "_migration.py"))
    ):
        return "migration"
    return "production"


def _base_material_finding(item: Hotspot) -> bool:
    """Identify runtime leads whose cost depends on runtime input cardinality.

    Fixed-size, retry, streaming, and pagination loops are useful calibration
    evidence, but their presence alone does not establish a material refactor
    lead.  This predicate is the single authority for that distinction.
    """
    return item.confidence in {"high", "medium"} and (
        item.loop_classification not in CALIBRATION_ONLY_LOOP_CLASSIFICATIONS
    )


def is_material_finding(
    item: Hotspot, scope: DecisionScope | None = None
) -> bool:
    """Backward-compatible projection of the canonical scope-aware policy."""
    return (scope or DecisionScope()).is_material_finding(item)


def is_performance_finding(item: Hotspot) -> bool:
    """Return whether a heuristic belongs to the runtime-performance axis."""
    return item.kind in PERFORMANCE_FINDING_KINDS


def is_material_performance_finding(
    item: Hotspot, scope: DecisionScope | None = None
) -> bool:
    """Return whether a runtime heuristic should affect performance decisions."""
    return (scope or DecisionScope()).is_material_performance_finding(item)


def rank_functions(
    metrics: list[MeasuredMetric],
    findings: Sequence[Hotspot] = (),
    scope: DecisionScope | None = None,
) -> list[MeasuredMetric]:
    """Rank production evidence before test scaffolding and calibrated leads.

    Raw metric review flags are intentionally not a ranking boost.  They can
    describe bounded setup, streaming, or migration work just as easily as an
    unbounded production cost.  A boost requires a matching, material
    data-loop hotspot from the heuristic lane.
    """
    authority = scope or DecisionScope()
    return sorted(metrics, key=lambda item: function_rank_key(item, findings, authority))


def function_rank_key(
    item: MeasuredMetric,
    findings: Sequence[Hotspot] = (),
    scope: DecisionScope | None = None,
) -> tuple[int, int, int, int, str, int, str]:
    metric = item.metric
    authority = scope or DecisionScope()
    return (
        function_scope_rank(item.path),
        -material_runtime_lead_strength(item, findings, authority),
        -RISK_ORDER.get(metric.risk, 0),
        -max(metric.cyclomatic, metric.cognitive or 0),
        item.path,
        metric.start,
        metric.name,
    )


def deterministic_complexity_key(
    item: MeasuredMetric,
) -> tuple[int, int, str, int, str]:
    """Rank deterministic maintainability evidence without runtime lead boosts."""
    metric = item.metric
    return (
        -RISK_ORDER.get(metric.risk, 0),
        -max(metric.cyclomatic, metric.cognitive or 0),
        item.path,
        metric.start,
        metric.name,
    )


def function_scope_rank(path: str) -> int:
    """Keep production review ahead of migrations and test-only code."""
    return {"production": 0, "migration": 1, "test": 2}[classify_path_scope(path)]


def material_runtime_lead_strength(
    item: MeasuredMetric,
    findings: Sequence[Hotspot],
    scope: DecisionScope | None = None,
) -> int:
    """Give only unbounded, data-dependent runtime leads a ranking boost."""
    authority = scope or DecisionScope()
    matching = (
        finding
        for finding in findings
        if (
            authority.is_material_performance_finding(finding)
            and finding.path == item.path
            and finding_belongs_to_metric(finding, item)
        )
    )
    return max(
        (runtime_lead_strength(finding, authority) for finding in matching),
        default=0,
    )


def finding_belongs_to_metric(finding: Hotspot, item: MeasuredMetric) -> bool:
    metric = item.metric
    if metric.start <= finding.line <= (metric.end or metric.start):
        return True
    return finding.symbol == metric.name.rsplit(".", maxsplit=1)[-1]


def runtime_lead_strength(
    finding: Hotspot, scope: DecisionScope | None = None
) -> int:
    """Demote bounded, streaming, and pagination loops to calibration evidence."""
    if (
        not is_material_performance_finding(finding, scope)
        or finding.loop_classification != "data loop"
    ):
        return 0
    if finding.kind == "io-in-loop":
        return 2
    return 1


def rank_files(
    metrics: list[MeasuredMetric],
    findings: list[Hotspot],
    is_material: MaterialFinding | None = None,
    *,
    scope: DecisionScope | None = None,
) -> list[RankedFile]:
    if scope is not None:
        materiality = scope.is_material_performance_finding
    else:
        base_materiality = is_material or is_material_finding

        def materiality(item: Hotspot) -> bool:
            return is_performance_finding(item) and base_materiality(item)
    paths = {item.path for item in metrics} | {item.path for item in findings}
    rows = [
        rank_file(path, metrics, findings, materiality, scope=scope)
        for path in paths
    ]
    return sorted(rows, key=file_rank_key)


def rank_file(
    path: str,
    metrics: list[MeasuredMetric],
    findings: list[Hotspot],
    is_material: MaterialFinding,
    *,
    scope: DecisionScope | None = None,
) -> RankedFile:
    authority = scope or DecisionScope()
    file_metric_rows = [item for item in metrics if item.path == path]
    file_metrics = [item.metric for item in file_metric_rows]
    file_findings = [item for item in findings if item.path == path]
    material_findings = [item for item in file_findings if is_material(item)]
    decision_metrics = file_metric_rows if authority.includes(path) else []
    non_a = [
        item.metric for item in decision_metrics if item.metric.risk not in {"", "A"}
    ]
    runtime_count = sum(bool(runtime_flags(item.metric)) for item in decision_metrics)
    worst = max(
        (item.metric.risk for item in decision_metrics),
        key=lambda risk: RISK_ORDER.get(risk, 0),
        default="",
    )
    reason = file_rank_reason(non_a, material_findings, runtime_count, file_findings)
    return RankedFile(
        path=path,
        reason=reason,
        worst_risk=worst,
        non_a_functions=len(non_a),
        runtime_flagged_functions=runtime_count,
        material_hotspot_count=len(material_findings),
        hotspot_count=len(file_findings),
        function_count=len(file_metrics),
    )


def file_rank_reason(
    non_a: Sequence[object],
    material_findings: Sequence[Hotspot],
    runtime_count: int,
    file_findings: Sequence[Hotspot],
) -> str:
    if non_a:
        return "contains non-A deterministic metric rows"
    if material_findings:
        return "contains medium/high-confidence heuristic runtime leads"
    if runtime_count:
        return "contains runtime review flags"
    if file_findings:
        return "contains heuristic leads requiring calibration"
    return "highest remaining deterministic metric density"


def file_rank_key(item: RankedFile) -> tuple[int, int, int, int, int, str]:
    return (
        function_scope_rank(item.path),
        -(
            item.non_a_functions * 100
            + item.material_hotspot_count * 50
            + item.runtime_flagged_functions * 10
        ),
        -RISK_ORDER.get(item.worst_risk, 0),
        -item.function_count,
        -item.material_hotspot_count,
        item.path,
    )
