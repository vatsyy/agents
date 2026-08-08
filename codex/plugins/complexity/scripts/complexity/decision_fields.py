"""Decision summaries derived from one canonical analysis outcome."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from analysis_contract import MeasuredMetric, RepoContextSummary
from function_complexity.output import runtime_flags
from heuristic_scanner import Hotspot
from ranking import DecisionScope, deterministic_complexity_key, is_performance_finding


def build_decision_fields(
    status: str,
    verdict: dict[str, str] | None,
    metrics: Sequence[MeasuredMetric],
    findings: Sequence[Hotspot],
    repo_context: RepoContextSummary,
    is_material: Callable[[Hotspot], bool] | None = None,
    *,
    scope: DecisionScope | None = None,
) -> dict[str, object]:
    """Build agent-facing decision fields without changing the raw evidence."""
    authority = scope or DecisionScope()
    materiality = (
        authority.is_material_finding
        if scope is not None
        else (is_material or authority.is_material_finding)
    )
    return {
        "complexity": complexity_fields(metrics, authority),
        "performance": performance_fields(
            metrics, findings, materiality, scope=authority
        ),
        "testability": testability_fields(metrics, repo_context),
        "refactor_priority": (
            "analysis incomplete; no clean refactor verdict"
            if status != "complete"
            else (verdict or {}).get("overall", "review ranked findings")
        ),
    }


def complexity_fields(
    metrics: Sequence[MeasuredMetric], scope: DecisionScope | None = None
) -> dict[str, object]:
    authority = scope or DecisionScope()
    decision_metrics = [item for item in metrics if authority.includes(item.path)]
    risk_counts: dict[str, int] = {}
    for item in decision_metrics:
        risk = item.metric.risk or "unknown"
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    top_function = min(
        decision_metrics, key=deterministic_complexity_key, default=None
    )
    return {
        "risk_counts": risk_counts,
        "non_a_functions": sum(
            1 for item in decision_metrics if item.metric.risk not in {"", "A"}
        ),
        "top_function": (
            {
                "path": top_function.path,
                "name": top_function.metric.name,
                "line": top_function.metric.start,
                "risk": top_function.metric.risk,
            }
            if top_function
            else None
        ),
    }


def performance_fields(
    metrics: Sequence[MeasuredMetric],
    findings: Sequence[Hotspot],
    is_material: Callable[[Hotspot], bool],
    scope: DecisionScope | None = None,
) -> dict[str, object]:
    authority = scope or DecisionScope()
    decision_metrics = [item for item in metrics if authority.includes(item.path)]
    material_findings = [
        item for item in findings if is_performance_finding(item) and is_material(item)
    ]
    top_hotspot = material_findings[0] if material_findings else None
    return {
        "material_hotspots": len(material_findings),
        "runtime_flagged_functions": sum(
            bool(runtime_flags(item.metric)) for item in decision_metrics
        ),
        "top_hotspot": (
            {
                "path": top_hotspot.path,
                "line": top_hotspot.line,
                "kind": top_hotspot.kind,
            }
            if top_hotspot
            else None
        ),
    }


def testability_fields(
    metrics: Sequence[MeasuredMetric], repo_context: RepoContextSummary
) -> dict[str, object]:
    coverage_signal = next(
        (
            signal
            for signal in repo_context.signals
            if signal.identifier == "coverage-xml"
        ),
        None,
    )
    return {
        "low_coverage_functions_in_sample": sum(
            item.metric.coverage_percent is not None
            and item.metric.coverage_percent < 60
            for item in metrics
        ),
        "coverage_signal_available": bool(
            coverage_signal is not None and coverage_signal.available
        ),
        "coverage_sampled": repo_context.sampled,
        "coverage_eligible_functions": repo_context.eligible_functions,
        "coverage_selected_functions": repo_context.selected_functions,
        "coverage_functions_with_value": (
            coverage_signal.with_value if coverage_signal is not None else 0
        ),
    }
