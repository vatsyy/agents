"""Integrated repository-level complexity triage."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from analysis import analyse as analyse_request
from analysis_contract import (
    PLUGIN_VERSION,
    AnalysisInputError,
    AnalysisRequest,
    exit_code_for_status,
    non_negative_int,
    status_message,
)
from analysis_output import (
    OutputError,
    canonical_analysis_payload,
    render,
    write_text_file,
)
from compatibility import (
    CompatibilityPresentation,
    MeasuredFunction,
    MetricFailure,
    RepoTriageReport,
    project_repo_triage_report,
)
from function_complexity.models import FunctionMetric
from function_complexity.output import runtime_flags
from ranking import DecisionScope, decision_scope_for_target_kind, is_material_finding
from scan_hotspots import (
    Hotspot,
    escape_cell,
    is_bounded_loop_finding,
)

RISK_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
DEFAULT_CONTEXT_LIMIT = 25


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an integrated repo-level complexity and performance triage."
    )
    parser.add_argument("root", nargs="?", default=".", help="Repository or directory to scan.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--exclude", action="append", default=[], help="Additional directory name to exclude.")
    parser.add_argument("--max-findings", type=non_negative_int, default=80)
    parser.add_argument("--max-top", type=non_negative_int, default=8, help="Maximum top files/functions to show.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit a compact agent-safe projection without raw per-function metrics",
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        help="Write full legacy evidence to PATH and emit the compact projection on stdout",
    )
    return parser.parse_args(argv)


def collect_integrated_report(root: Path, args: argparse.Namespace) -> RepoTriageReport:
    outcome = analyse_request(
        AnalysisRequest.for_compatibility(
            root,
            "integrated",
            excludes=frozenset(args.exclude),
            max_findings=args.max_findings,
            max_top=args.max_top,
            repo_context=root,
            context_limit=DEFAULT_CONTEXT_LIMIT,
        )
    )
    return project_repo_triage_report(
        root,
        outcome,
        command=command_text(root, args),
        max_findings=args.max_findings,
    )


def render_markdown_report(report: RepoTriageReport, max_top: int) -> str:
    return "\n".join(
        [
            "## Orientation Brief",
            render_orientation(report),
            "## Complexity Verdict",
            render_verdict(report),
            "## Deterministic Metrics",
            render_deterministic_metrics(report, max_top),
            "## Heuristic Hotspots",
            render_heuristic_hotspots(report, max_top),
            "## Overstated Findings",
            render_overstated_findings(report),
            "## Understated Risks",
            render_understated_risks(report),
            "## False Positive Candidates",
            render_false_positive_candidates(report),
            "## Missing Signals",
            render_missing_signals(),
            "## Evidence and Confidence",
            render_evidence_and_confidence(report),
            "## Smallest Next Action Plan",
            render_next_action_plan(report),
        ]
    ) + "\n"


def render_orientation(report: RepoTriageReport) -> str:
    stats = report.scan_report.stats
    languages = ", ".join(
        f"{suffix}:{count}" for suffix, count in sorted(stats.language_counts.items())
    )
    return "\n".join(
        [
            f"- Scope: `{report.root}`",
            f"- Analysis status: {analysis_status(report)}",
            f"- Plugin version: `{PLUGIN_VERSION}`",
            f"- Files scanned: {stats.files_scanned}",
            f"- Files skipped: {stats.files_skipped}",
            f"- Functions measured: {len(report.metrics)}",
            f"- Metric failures: {len(report.metric_failures)}",
            f"- Language counts: {languages or 'none'}",
            (
                f"- Timing seconds: scan={report.timings.scan_seconds}, "
                f"metrics={report.timings.metric_seconds}, total={report.timings.total_seconds}"
            ),
            f"- Command: `{report.command}`",
        ]
    )


def render_verdict(report: RepoTriageReport) -> str:
    return compatibility_presentation(report).verdict_markdown


def compatibility_presentation(report: RepoTriageReport) -> CompatibilityPresentation:
    status = analysis_status(report)
    overall = (report.outcome.verdict or {}).get("overall", "unavailable")
    if status == "partial":
        return CompatibilityPresentation(
            verdict={"overall": overall},
            verdict_markdown="\n".join(
                [
                    f"- Overall verdict: {overall}",
                    "- Refactor priority: resolve incomplete coverage before treating findings as a clean baseline",
                ]
            ),
            next_action_plan=(
                "- analysis is partial; resolve failed or unsupported required "
                "coverage before proposing refactors"
            ),
        )
    if status == "unsupported":
        return CompatibilityPresentation(
            verdict=None,
            verdict_markdown=(
                "- Overall verdict: unavailable; no eligible source file was analysed\n"
                "- Refactor priority: analyse a supported source scope before drawing a complexity verdict"
            ),
            next_action_plan=(
                "- no eligible source file was analysed; choose a supported source "
                "scope before proposing refactors"
            ),
        )
    maintainability = maintainability_priority(report)
    runtime = runtime_priority(report)
    priority = (
        "no immediate refactor"
        if no_immediate_refactor(report)
        else "inspect top runtime and non-A maintainability rows before changing code"
    )
    return CompatibilityPresentation(
        verdict={
            "overall": overall,
            "maintainability": maintainability,
            "runtime": runtime,
            "refactor_priority": priority,
        },
        verdict_markdown="\n".join(
            [
                f"- Maintainability priority: {maintainability}",
                f"- Runtime priority: {runtime}",
                f"- Refactor priority: {priority}",
            ]
        ),
        next_action_plan=complete_next_action_plan(report),
    )


def maintainability_priority(report: RepoTriageReport) -> str:
    scope = decision_scope_for_target_kind(report.outcome.target_kind)
    non_a = non_a_metrics(report.metrics, scope)
    if not non_a:
        if non_a_metrics(report.metrics):
            return "low; every production-scoped measured function is `Risk A`"
        return "low; every measured function is `Risk A`"
    worst = top_functions(non_a, 1)[0]
    return f"inspect `{worst.path}:{worst.metric.start}` `{worst.metric.name}` first"


def runtime_priority(report: RepoTriageReport) -> str:
    scope = decision_scope_for_target_kind(report.outcome.target_kind)
    material = material_hotspots(report.outcome.findings, scope)
    runtime_count = runtime_metric_count(report.metrics, scope)
    if not material and runtime_count == 0:
        return "low; no high-confidence static runtime lead"
    return (
        "static scan suggests "
        f"{len(material)} material hotspot leads and "
        f"{runtime_count} metric rows with runtime review flags"
    )


def runtime_metric_count(
    metrics: Sequence[MeasuredFunction], scope: DecisionScope | None = None
) -> int:
    return sum(
        1
        for item in metrics
        if (scope is None or scope.includes(item.path)) and runtime_flags(item.metric)
    )


def no_immediate_refactor(report: RepoTriageReport) -> bool:
    return (report.outcome.verdict or {}).get("overall") == "no immediate refactor"


def material_hotspots(
    findings: Sequence[Hotspot], scope: DecisionScope | None = None
) -> list[Hotspot]:
    materiality = scope.is_material_finding if scope is not None else is_material_finding
    return [item for item in findings if materiality(item)]


def render_deterministic_metrics(report: RepoTriageReport, max_top: int) -> str:
    sections = [
        render_metric_counts(report),
        render_top_files(report, max_top),
        render_top_functions(report.metrics, max_top),
    ]
    if report.metric_failures:
        sections.append(render_metric_failures(report.metric_failures, max_top))
    return "\n\n".join(sections)


def render_metric_counts(report: RepoTriageReport) -> str:
    counts = risk_counts(report.metrics)
    rendered = ", ".join(f"{risk}:{counts[risk]}" for risk in sorted(counts, key=risk_sort_key))
    non_a = len(non_a_metrics(report.metrics))
    return "\n".join(
        [
            (
                f"- Deterministic scope facts: files_scanned={report.scan_report.stats.files_scanned}, "
                f"functions_measured={len(report.metrics)}"
            ),
            f"- Risk counts: {rendered or 'none'}",
            f"- Non-A functions: {non_a}",
            f"- Review-flagged functions: {sum(1 for item in report.metrics if item.metric.review_flags)}",
            f"- Metric failures: {len(report.metric_failures)}",
        ]
    )


def risk_counts(metrics: Sequence[MeasuredFunction]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in metrics:
        risk = item.metric.risk or "unknown"
        counts[risk] = counts.get(risk, 0) + 1
    return counts


def risk_sort_key(risk: str) -> tuple[int, str]:
    return (RISK_ORDER.get(risk, 99), risk)


def non_a_metrics(
    metrics: Sequence[MeasuredFunction], scope: DecisionScope | None = None
) -> list[MeasuredFunction]:
    return [
        item
        for item in metrics
        if item.metric.risk not in {"A", ""}
        and (scope is None or scope.includes(item.path))
    ]


def render_top_files(report: RepoTriageReport, max_top: int) -> str:
    rows = top_file_rows(report, max_top)
    if not rows:
        return "- top_files: none"
    lines = [
        "| File | Why selected | Worst Risk | Non-A | Runtime Flags | Hotspots | Functions |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(render_file_row(row) for row in rows)
    return "\n".join(lines)


def top_file_rows(report: RepoTriageReport, max_top: int) -> list[dict[str, object]]:
    return [
        {
            "path": item.path,
            "why": item.reason,
            "worst": item.worst_risk,
            "non_a": item.non_a_functions,
            "runtime": item.runtime_flagged_functions,
            "hotspots": item.hotspot_count,
            "functions": item.function_count,
        }
        for item in report.outcome.top_files[:max_top]
    ]


def render_file_row(row: dict[str, object]) -> str:
    values = (
        str(row["path"]),
        str(row["why"]),
        str(row["worst"]),
        str(row["non_a"]),
        str(row["runtime"]),
        str(row["hotspots"]),
        str(row["functions"]),
    )
    return "| " + " | ".join(escape_cell(value) for value in values) + " |"


def render_top_functions(metrics: Sequence[MeasuredFunction], max_top: int) -> str:
    rows = top_functions(metrics, max_top)
    if not rows:
        return "- top_functions: none"
    lines = [
        "| Function | Location | Risk | Cyclomatic | Cognitive | Why selected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(render_function_row(item) for item in rows)
    return "\n".join(lines)


def top_functions(metrics: Sequence[MeasuredFunction], max_top: int) -> list[MeasuredFunction]:
    """Project the canonical function order into the legacy report shape."""
    return list(metrics[:max_top])


def render_function_row(item: MeasuredFunction) -> str:
    metric = item.metric
    values = (
        metric.name,
        f"{item.path}:{metric.start}",
        metric.risk,
        str(metric.cyclomatic),
        str(metric.cognitive or ""),
        function_reason(metric),
    )
    return "| " + " | ".join(escape_cell(value) for value in values) + " |"


def function_reason(metric: FunctionMetric) -> str:
    if metric.risk not in {"A", ""}:
        return "non-A deterministic complexity bucket"
    flags = runtime_flags(metric)
    if flags:
        return f"runtime review flags: {', '.join(flags)}"
    return "highest remaining deterministic complexity row"


def render_metric_failures(failures: Sequence[MetricFailure], max_top: int) -> str:
    lines = ["| File | Failure |", "| --- | --- |"]
    lines.extend(
        "| " + " | ".join(escape_cell(value) for value in (item.path, item.message)) + " |"
        for item in failures[:max_top]
    )
    return "\n".join(lines)


def render_heuristic_hotspots(report: RepoTriageReport, max_top: int) -> str:
    findings = report.scan_report.findings[:max_top]
    if not findings:
        return "- none"
    lines = [
        "| Severity | Confidence | Kind | Location | Loop | Evidence | Calibration |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(render_hotspot_row(item) for item in findings)
    return "\n".join(lines)


def render_hotspot_row(item: Hotspot) -> str:
    values = (
        item.severity,
        item.confidence,
        item.kind,
        f"{item.path}:{item.line}",
        item.loop_classification,
        item.evidence,
        item.calibration or item.estimated_complexity,
    )
    return "| " + " | ".join(escape_cell(value) for value in values) + " |"


def render_overstated_findings(report: RepoTriageReport) -> str:
    candidates = [
        item for item in report.scan_report.findings if is_bounded_loop_finding(item)
    ]
    if not candidates:
        return "- none identified by calibration rules"
    return "\n".join(
        f"- `{item.path}:{item.line}` {item.kind}: {item.loop_classification}; "
        "manual validation needed before treating as unbounded N+1"
        for item in candidates[:8]
    )


def render_understated_risks(report: RepoTriageReport) -> str:
    lines = wrapper_understated_lines(report.scan_report.findings)
    if report.metric_failures:
        lines.append("- metric failures mean some non-Python detail is unavailable; see deterministic failure rows")
    return "\n".join(lines or ["- cross-file wrapper and framework latency can still be missed by static analysis"])


def wrapper_understated_lines(findings: Sequence[Hotspot]) -> list[str]:
    wrappers = [item for item in findings if item.kind == "wrapper-io-in-loop"]
    return [
        f"- `{item.path}:{item.line}` wrapper claim includes {item.confidence_reason}"
        for item in wrappers[:8]
    ]


def render_false_positive_candidates(report: RepoTriageReport) -> str:
    candidates = [item for item in report.scan_report.findings if item.confidence == "low"]
    if not candidates:
        return "- none from current confidence rules"
    return "\n".join(
        f"- `{item.path}:{item.line}` {item.kind}: low-confidence static scan; manual validation needed"
        for item in candidates[:8]
    )


def render_missing_signals() -> str:
    return (
        "- cannot prove input cardinality, hot-path frequency, cache invalidation, permissions, or retry safety\n"
        "- Big-O and space claims remain review prompts, not proven performance facts\n"
        "- lizard-derived non-Python rows are lower-detail than Python AST rows\n"
        "- benchmark timings show command cost, not application runtime impact"
    )


def render_evidence_and_confidence(report: RepoTriageReport) -> str:
    lines = [
        "- deterministic high confidence: file counts, function counts, risk buckets, cyclomatic and cognitive metrics",
        "- heuristic medium/low confidence: hotspot and wrapper claims are static leads requiring manual validation",
        (
            f"- timing evidence: scan={report.timings.scan_seconds}s, "
            f"metrics={report.timings.metric_seconds}s, total={report.timings.total_seconds}s"
        ),
    ]
    if report.metric_failures:
        lines.append("- explicit metric failures are reported instead of silently dropping unsupported files")
    return "\n".join(lines)


def render_next_action_plan(report: RepoTriageReport) -> str:
    return compatibility_presentation(report).next_action_plan


def complete_next_action_plan(report: RepoTriageReport) -> str:
    if no_immediate_refactor(report):
        return (
            "- no immediate refactor; use this as a clean first-pass baseline and "
            "investigate only if runtime symptoms exist"
        )
    lines: list[str] = []
    scope = decision_scope_for_target_kind(report.outcome.target_kind)
    first_function = top_functions(non_a_metrics(report.metrics, scope), 1)
    if first_function:
        item = first_function[0]
        metric = item.metric
        lines.append(
            f"- inspect `{item.path}:{metric.start}` `{metric.name}` first because it is "
            f"the highest deterministic complexity row (`Risk {metric.risk}`)"
        )
    elif report.metric_failures:
        lines.append("- inspect metric failures first, then rerun the integrated report")
    else:
        first_file = top_file_rows(report, 1)
        if first_file:
            lines.append(f"- inspect `{first_file[0]['path']}` first because {first_file[0]['why']}")

    first_hotspot = material_hotspots(report.outcome.findings, scope)
    if first_hotspot:
        item = first_hotspot[0]
        lines.append(
            f"- validate `{item.path}:{item.line}` {item.kind} next; confirm input size, "
            "loop bounds, and framework/wrapper semantics"
        )
    else:
        lines.append("- validate input sizes and wrapper/framework semantics before proposing changes")

    lines.append("- use targeted tests or timings only after a behaviour-preserving change is selected")
    if not lines:
        return "- inspect metric failures first, then rerun the integrated report"
    return "\n".join(lines)


def report_to_json(report: RepoTriageReport, max_top: int = 20) -> dict[str, object]:
    payload: dict[str, object] = {
        "orientation_brief": {
            "scope": str(report.root),
            "plugin_version": PLUGIN_VERSION,
            "files_scanned": report.scan_report.stats.files_scanned,
            "files_skipped": report.scan_report.stats.files_skipped,
            "functions_measured": len(report.metrics),
            "metric_failures": len(report.metric_failures),
            "language_counts": report.scan_report.stats.language_counts,
            "timings": asdict(report.timings),
            "command": report.command,
        },
        "verdict": compatibility_presentation(report).verdict,
        "decision_fields": report_decision_fields(report),
        "risk_counts": risk_counts(report.metrics),
        "non_a_functions": [measured_to_dict(item) for item in non_a_metrics(report.metrics)],
        "top_files": top_file_rows(report, max_top),
        "top_functions": [measured_to_dict(item) for item in top_functions(report.metrics, max_top)],
        "heuristic_hotspots": [asdict(item) for item in report.scan_report.findings],
        "overstated_findings": bullet_lines(render_overstated_findings(report)),
        "understated_risks": bullet_lines(render_understated_risks(report)),
        "false_positive_candidates": bullet_lines(render_false_positive_candidates(report)),
        "missing_signals": bullet_lines(render_missing_signals()),
        "evidence_confidence": bullet_lines(render_evidence_and_confidence(report)),
        "smallest_next_action_plan": bullet_lines(render_next_action_plan(report)),
        "repo_context": repo_context_summary(report),
        "metric_failures": [asdict(item) for item in report.metric_failures],
    }
    payload["analysis"] = canonical_analysis_payload(report.outcome)
    return payload


def report_decision_fields(report: RepoTriageReport) -> dict[str, object]:
    return report.outcome.decision_fields


def analysis_status(report: RepoTriageReport) -> str:
    return report.outcome.status


def repo_context_summary(report: RepoTriageReport) -> dict[str, object]:
    return asdict(report.outcome.repo_context)


def bullet_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lines.append(stripped[2:].strip() if stripped.startswith("- ") else stripped)
    return lines


def measured_to_dict(item: MeasuredFunction) -> dict[str, object]:
    data = asdict(item.metric)
    data["path"] = item.path
    return data


def render_report(report: RepoTriageReport, output_format: str, max_top: int) -> str:
    if output_format == "json":
        return json.dumps(report_to_json(report, max_top=max_top), indent=2) + "\n"
    return render_markdown_report(report, max_top)


def emit_report(
    report: RepoTriageReport,
    output_format: str,
    max_top: int,
    *,
    summary: bool = False,
    output_file: str | None = None,
) -> None:
    full_text = render_report(report, output_format, max_top)
    path = write_text_file(output_file, full_text) if output_file else None
    if summary or path is not None:
        print(
            render(
                report.outcome,
                output_format,
                projection="summary",
                output_file=path,
            ),
            end="",
        )
        return
    print(full_text, end="")


def command_text(root: Path, args: argparse.Namespace) -> str:
    command = [
        "complexity-triage",
        str(root),
        "--format",
        args.format,
        "--max-findings",
        str(args.max_findings),
        "--max-top",
        str(args.max_top),
    ]
    if args.summary:
        command.append("--summary")
    if args.output_file:
        command.extend(("--output-file", str(args.output_file)))
    return shlex.join(command)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).expanduser().resolve()
    try:
        report = collect_integrated_report(root, args)
    except AnalysisInputError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        emit_report(
            report,
            args.format,
            args.max_top,
            summary=args.summary,
            output_file=args.output_file,
        )
    except OutputError as error:
        print(str(error), file=sys.stderr)
        return 2
    if report.outcome.status != "complete":
        print(status_message(report.outcome.status), file=sys.stderr)
        return exit_code_for_status(report.outcome.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
