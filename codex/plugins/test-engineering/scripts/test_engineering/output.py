from __future__ import annotations

import json
from typing import Any

from .analysis_contract import RENDER_LIMITS
from .constants import SCOPED_EVIDENCE, UNAVAILABLE


def render(report: dict[str, Any], command: str, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, sort_keys=True)
    return render_markdown(report, command)


def render_markdown(report: dict[str, Any], command: str) -> str:
    lines: list[str] = []
    title = command.replace("-", " ").title()
    taxonomy = report["taxonomy"]
    assessment = report.get("assessment", {})
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Repo: `{report['repo']}`")
    lines.append(f"- Analysis status: **{report.get('status', 'unknown')}**")
    lines.append(f"- Schema version: {report.get('schema_version', 'legacy')}")
    lines.append(f"- Framework hints: {', '.join(report['framework_hints'])}")
    lines.append(f"- Source files: {report['source_file_count']}")
    lines.append(f"- Test files: {report['test_file_count']}")
    lines.append(f"- Functions: {report['function_count']}")
    lines.append(f"- Test cases: {report['test_case_count']}")
    if report.get("coverage_xml"):
        lines.append(f"- Coverage XML: `{report['coverage_xml']}`")
    else:
        lines.append("- Coverage XML: not provided")
    lines.append("")
    append_report_basis(lines, report)
    append_orientation_brief(lines, report.get("orientation_brief", {}))
    append_trust_verdict(lines, report.get("trust_verdict", {}))
    append_trust_report(lines, report.get("trust_report", {}), assessment)
    append_action_plan(lines, report.get("action_plan", []), assessment)

    if command == "test-inventory":
        append_test_inventory(lines, report, assessment)
    elif command == "monolith-test-report":
        append_monoliths(lines, taxonomy, assessment)
    else:
        append_function_grades(lines, report, assessment)

    append_taxonomy(lines, taxonomy, assessment)
    return "\n".join(lines).rstrip() + "\n"


def append_report_basis(lines: list[str], report: dict[str, Any]) -> None:
    lines.append("## Report Basis")
    lines.append("")
    inventory = report.get("inventory", {})
    parsing = report.get("parsing", {})
    coverage = report.get("coverage", {})
    lines.append(
        f"- Inventory: {inventory.get('analysed_file_count', 0)} analysed / "
        f"{inventory.get('supported_candidate_count', 0)} supported candidates / "
        f"{inventory.get('discovered_file_count', 0)} discovered files."
    )
    lines.append(
        f"- Parsing: {parsing.get('succeeded_file_count', 0)} succeeded / "
        f"{parsing.get('attempted_file_count', 0)} attempted; {parsing.get('failed_file_count', 0)} failed."
    )
    coverage_count = coverage.get("line_count")
    coverage_denominator = UNAVAILABLE if coverage_count is None else str(coverage_count)
    lines.append(f"- Coverage evidence: {coverage.get('state', 'unknown')} ({coverage_denominator} lines indexed).")
    append_diagnostics(lines, report.get("diagnostics", []))
    append_adapter_summary(lines, report.get("adapters", []))
    append_limits(lines, report.get("limits", {}))
    append_truncation(lines, report.get("truncation", {}))
    lines.append("")


def append_diagnostics(lines: list[str], diagnostics: list[dict[str, Any]]) -> None:
    if not diagnostics:
        lines.append("- Diagnostics: none.")
        return
    lines.append(f"- Diagnostics: {len(diagnostics)} issue(s) constrain this report:")
    limit = RENDER_LIMITS["diagnostics"]
    for item in diagnostics[:limit]:
        location = f" `{item['path']}`" if item.get("path") else ""
        lines.append(f"  - [{item.get('code', 'unknown')}]{location}: {item.get('message', '')}")
    if len(diagnostics) > limit:
        lines.append(f"  - ... {len(diagnostics) - limit} more diagnostics")


def append_adapter_summary(lines: list[str], adapters: list[dict[str, Any]]) -> None:
    if adapters:
        lines.append("- Adapters: " + ", ".join(f"{item['name']}@{item['version']}" for item in adapters) + ".")


def append_limits(lines: list[str], limits: dict[str, Any]) -> None:
    analysis = limits.get("analysis", {})
    render = limits.get("render", {})
    if analysis:
        lines.append(
            f"- Analysis limits: {analysis.get('max_discovered_files')} discovered files; "
            f"{analysis.get('max_text_bytes_per_file')} bytes per file."
        )
    if render:
        lines.append("- Render limits: " + ", ".join(f"{name}={value}" for name, value in sorted(render.items())) + ".")


def append_truncation(lines: list[str], truncation: dict[str, dict[str, Any]]) -> None:
    if not truncation:
        return
    lines.append("- Render denominators (total/shown/omitted):")
    for name, counts in sorted(truncation.items()):
        lines.append(f"  - {name}: {counts['total']}/{counts['shown']}/{counts['omitted']}")


def append_orientation_brief(lines: list[str], brief: dict[str, Any]) -> None:
    lines.append("## Orientation Brief")
    lines.append("")
    append_string_items(lines, brief.get("summary", []))
    append_runner_clues(lines, brief.get("runner_clues", []))
    append_high_signal_files(lines, brief.get("high_signal_files", []))


def append_string_items(lines: list[str], items: list[str]) -> None:
    for item in items:
        lines.append(f"- {item}")
    if items:
        lines.append("")


def append_runner_clues(lines: list[str], clues: list[str]) -> None:
    if clues:
        lines.append("Runner clues: " + "; ".join(clues))
        lines.append("")


def append_high_signal_files(lines: list[str], files: list[dict[str, Any]]) -> None:
    if not files:
        return
    lines.append("| High-signal file | Framework | Tests | Assertions | Fixtures |")
    lines.append("| --- | --- | ---: | ---: | ---: |")
    for item in files[: RENDER_LIMITS["high_signal_files"]]:
        lines.append(f"| `{item['file']}` | {item['framework']} | {item['tests']} | {item['assertions']} | {item['fixtures']} |")
    lines.append("")


def append_trust_verdict(lines: list[str], verdict: dict[str, Any]) -> None:
    lines.append("## Trust Verdict")
    lines.append("")
    if not verdict:
        lines.append("No trust verdict available from this report.")
        lines.append("")
        return
    lines.append(verdict.get("summary", "No summary available."))
    lines.append("")
    lines.append(f"- Mocked unit trust: {verdict.get('mocked_unit_trust', 'unknown')}")
    lines.append(f"- Behavioural coverage trust: {verdict.get('behavioural_coverage', 'unknown')}")
    lines.append(f"- Refactor readiness: {verdict.get('refactor_readiness', 'unknown')}")
    lines.append(f"- Evidence: {verdict.get('confidence', 'unknown')} confidence, {verdict.get('evidence_type', 'unknown')}")
    if verdict.get("static_confidence_caveat"):
        lines.append(f"- Static caveat: {verdict['static_confidence_caveat']}")
    lines.append("")


def append_trust_report(lines: list[str], report: dict[str, Any], assessment: dict[str, Any]) -> None:
    lines.append("## Trust Report")
    lines.append("")
    append_projection_scope(lines, assessment)
    unavailable = report.get("assessment_status") == UNAVAILABLE
    lines.append(f"- Refactor readiness: {report.get('refactor_readiness', 'unknown')}")
    if unavailable:
        lines.append(f"- Observed grade counts (scoped): {format_counts(report.get('observed_grade_counts', {}))}")
        lines.append(f"- Observed risk counts (scoped): {format_counts(report.get('observed_risk_counts', {}))}")
    else:
        lines.append(f"- Grade counts: {format_counts(report.get('grade_counts', {}))}")
        lines.append(f"- Risk counts: {format_counts(report.get('risk_counts', {}))}")
    append_coverage_gap_summary(lines, report.get("coverage_gap_summary", {}))
    if report.get("static_confidence_caveat"):
        lines.append(f"- Static caveat: {report['static_confidence_caveat']}")
    append_heuristic_examples(lines, report.get("heuristic_examples", {}))
    append_highest_risk_functions(lines, report.get("highest_risk_functions", []), unavailable)
    append_trust_questions(lines, report.get("questions", []))


def append_coverage_gap_summary(lines: list[str], summary: dict[str, Any]) -> None:
    if not summary:
        return
    if summary.get("assessment_status") == UNAVAILABLE:
        lines.append("- Coverage-gap verdict unavailable; observed evidence is scoped to successfully analysed files.")
        return
    lines.append(
        "- Coverage gap split: "
        f"{summary.get('probably_untested', 0)} probably untested; "
        f"{summary.get('not_directly_mapped', 0)} not directly mapped."
    )
    groups = summary.get("missing_by_entrypoint", [])
    if groups:
        lines.append("- Missing evidence grouped by public surface:")
        for group in groups[: RENDER_LIMITS["coverage_gap_groups"]]:
            examples = ", ".join(
                example["function"] for example in group.get("examples", [])[: RENDER_LIMITS["coverage_gap_examples"]]
            )
            suffix = f" examples: {examples}" if examples else ""
            lines.append(f"  - {group['group']}: {group['count']} candidates;{suffix}")


def format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def append_trust_questions(lines: list[str], questions: list[dict[str, str]]) -> None:
    if not questions:
        lines.append("")
        return
    lines.append("")
    for item in questions:
        lines.append(f"- {item['question']} {item['answer']} ({item['confidence']} confidence, {item['evidence_type']}).")
    lines.append("")


def append_heuristic_examples(lines: list[str], examples: dict[str, list[dict[str, Any]]]) -> None:
    over_mocked = examples.get("over_mocked", [])
    if examples.get("assessment_status") == SCOPED_EVIDENCE and not over_mocked:
        lines.append("- Mock-heavy verdict unavailable; no scoped example was retained.")
        return
    if not over_mocked:
        lines.append("- Mock-heavy examples: none found by static scan.")
        return
    lines.append("- Mock-heavy examples: static scan suggests these tests deserve manual review:")
    for item in over_mocked[: RENDER_LIMITS["heuristic_examples"]]:
        lines.append(
            f"  - `{item['test']}` in `{item['file']}:{item['line']}` "
            f"({item['mock_count']} mock terms; {item['confidence']} confidence, {item['evidence_type']})"
        )


def append_highest_risk_functions(
    lines: list[str],
    functions: list[dict[str, Any]],
    unavailable: bool = False,
) -> None:
    if not functions:
        message = "- Highest-risk function verdict unavailable; no scoped example was retained."
        lines.append(message if unavailable else "- Highest-risk functions: none found.")
        return
    lines.append("- Highest-risk functions:")
    for item in functions[: RENDER_LIMITS["highest_risk_functions"]]:
        risk = risk_summary(item)
        lines.append(
            f"  - `{item['function']}` grade {item['grade']} in `{item['file']}:{item['line']}` "
            f"({item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')}; {risk})"
        )


def risk_summary(item: dict[str, Any]) -> str:
    reasons = item.get("risk_reasons", [])
    if not reasons:
        return f"{item.get('risk_level', 'low')} behavioural risk"
    return f"{item.get('risk_level', 'unknown')} behavioural risk: {', '.join(reasons[:3])}"


def append_action_plan(lines: list[str], actions: list[dict[str, Any]], assessment: dict[str, Any]) -> None:
    lines.append("## Action Plan")
    lines.append("")
    append_projection_scope(lines, assessment)
    if not actions:
        lines.append(empty_projection_message(assessment, "No immediate action candidates found by static triage."))
        lines.append("")
        return
    lines.append("| Action | Target | Evidence | Recommendation |")
    lines.append("| --- | --- | --- | --- |")
    for item in actions[: RENDER_LIMITS["action_plan"]]:
        target = f"`{item['target']}` in `{item['file']}:{item['line']}`"
        evidence = f"{item['confidence']} confidence, {item['evidence_type']}"
        lines.append(f"| {item['kind']} | {target} | {evidence} | {item['recommendation']} |")
    lines.append("")
    lines.append("- Deterministic static evidence from files, names, assertions, and optional existing coverage XML.")
    lines.append("- Heuristic findings require manual review before creating, deleting, or rewriting tests.")
    lines.append("")


def append_test_inventory(lines: list[str], report: dict[str, Any], assessment: dict[str, Any]) -> None:
    lines.append("## Test Files")
    if not report["test_files"]:
        lines.append("")
        lines.append(empty_projection_message(assessment, "No test files found."))
        lines.append("")
        return
    lines.append("")
    lines.append("| File | Framework | Tests | Assertions | Helpers | Fixtures | Lines |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for item in report["test_files"][: RENDER_LIMITS["test_files"]]:
        lines.append(
            f"| `{item['file']}` | {item['framework']} | {item['test_count']} | {item['assertion_count']} | "
            f"{item.get('helper_count', 0)} | {item.get('fixture_count', 0)} | {item['line_count']} |"
        )
    lines.append("")


def append_function_grades(lines: list[str], report: dict[str, Any], assessment: dict[str, Any]) -> None:
    lines.append("## Function Grades")
    grades = report["function_grades"]
    lines.append("")
    append_projection_scope(lines, assessment)
    if not grades:
        lines.append(empty_projection_message(assessment, "No supported source functions found in non-test source files."))
        lines.append("")
        return
    lines.append("| Grade | Function | File | Evidence | Recommendation |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in grades[: RENDER_LIMITS["function_grades"]]:
        evidence = evidence_summary(item)
        lines.append(
            f"| {item['grade']} | `{item['function']}` | `{item['file']}:{item['line']}` | {evidence} | {item['recommendation']} |"
        )
    lines.append("")


def append_monoliths(lines: list[str], taxonomy: dict[str, Any], assessment: dict[str, Any]) -> None:
    lines.append("## Monolith Candidates")
    candidates = taxonomy.get("monolith_candidates", [])
    lines.append("")
    append_projection_scope(lines, assessment)
    if not candidates:
        lines.append(empty_projection_message(assessment, "No monolithic test candidates found by the current thresholds."))
        lines.append("")
        return
    lines.append("| Test | File | Reasons | Recommendation |")
    lines.append("| --- | --- | --- | --- |")
    for item in candidates:
        reasons = ", ".join(item["reasons"])
        lines.append(
            f"| `{item['test']}` | `{item['file']}:{item['line']}` | {reasons} | {item['recommendation']} |"
        )
    lines.append("")


def append_taxonomy(lines: list[str], taxonomy: dict[str, Any], assessment: dict[str, Any]) -> None:
    append_simple_section(lines, "Covered", taxonomy.get("covered", []), describe_function_item, assessment)
    append_simple_section(lines, "Missing", taxonomy.get("missing", []), describe_function_item, assessment)
    append_simple_section(lines, "Redundant", taxonomy.get("redundant", []), describe_redundant_item, assessment)
    append_simple_section(lines, "Low Signal", taxonomy.get("low_signal", []), describe_low_signal_item, assessment)
    append_simple_section(lines, "Placeholder", taxonomy.get("placeholder", []), describe_placeholder_item, assessment)
    append_simple_section(lines, "Improvable", taxonomy.get("improvable", []), describe_function_item, assessment)
    append_simple_section(lines, "Needs To Create", taxonomy.get("needs_to_create", []), describe_create_item, assessment)
    append_simple_section(lines, "Monolith Candidates", taxonomy.get("monolith_candidates", []), describe_monolith_item, assessment)
    assertion_light = taxonomy.get("assertion_light", [])
    append_simple_section(lines, "Assertion Light", assertion_light, describe_assertion_light_item, assessment)


def append_simple_section(
    lines: list[str],
    heading: str,
    items: list[dict[str, Any]],
    describe,
    assessment: dict[str, Any],
) -> None:
    lines.append(f"## {heading}")
    lines.append("")
    append_projection_scope(lines, assessment)
    if not items:
        lines.append(empty_section_message(heading, assessment))
        lines.append("")
        return
    limit = RENDER_LIMITS["taxonomy_section"]
    for item in items[:limit]:
        lines.append(f"- {describe(item)}")
    if len(items) > limit:
        lines.append(f"- ... {len(items) - limit} more")
    lines.append("")


def empty_section_message(heading: str, assessment: dict[str, Any]) -> str:
    if not assessment.get("repository_verdict_available", True):
        return "Repository-wide verdict unavailable; no scoped evidence was retained for this section."
    messages = {
        "Redundant": "No deterministic duplicate tests or redundancy candidates found by the current static scan.",
        "Low Signal": "No low-signal test files found by the current static scan.",
        "Placeholder": "No empty placeholder test files found by the current static scan.",
        "Monolith Candidates": "No monolithic test candidates found by the current thresholds.",
        "Function Grades": "No supported source functions found in non-test source files.",
    }
    return messages.get(heading, "None found by deterministic scan.")


def append_projection_scope(lines: list[str], assessment: dict[str, Any]) -> None:
    if not assessment.get("repository_verdict_available", True):
        lines.append(
            "Scoped evidence only: results below cover successfully analysed files. "
            "Repository-wide verdict unavailable."
        )
        lines.append("")


def empty_projection_message(assessment: dict[str, Any], complete_message: str) -> str:
    if assessment.get("repository_verdict_available", True):
        return complete_message
    return "Repository-wide verdict unavailable; no scoped evidence was retained for this projection."


def evidence_summary(item: dict[str, Any]) -> str:
    refs = item.get("test_refs", [])
    ref_text = f"{len(refs)} test file ref" if len(refs) == 1 else f"{len(refs)} test file refs"
    assertions = item.get("assertion_evidence", 0)
    coverage = item.get("coverage_status", "unknown")
    confidence = item.get("evidence_confidence", "unknown")
    labels = ", ".join(item.get("evidence_labels", []))
    return f"{ref_text}; {assertions} assertions; coverage {coverage}; confidence {confidence}; {labels}"


def describe_function_item(item: dict[str, Any]) -> str:
    return (
        f"`{item['function']}` in `{item['file']}:{item['line']}` grade {item['grade']} "
        f"({item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')}): {item['recommendation']}"
    )


def describe_create_item(item: dict[str, Any]) -> str:
    risk = risk_summary(item)
    return (
        f"`{item['test_name']}` for `{item['function']}` in `{item['file']}:{item.get('line', '?')}` "
        f"({item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')}; {risk}): {item['assertion_goal']}"
    )


def describe_redundant_item(item: dict[str, Any]) -> str:
    if "normalised_intent" in item:
        tests = item.get("tests", [])
        refs = ", ".join(f"`{test.get('test')}`" for test in tests[:4])
        return f"{evidence_tag(item)} {item['reason']} Intent `{item['normalised_intent']}` appears in {refs}."
    return f"{evidence_tag(item)} {item.get('reason', 'Redundancy candidate.')}"


def describe_low_signal_item(item: dict[str, Any]) -> str:
    tests = item.get("tests", [])
    refs = ", ".join(f"`{test.get('test')}` line {test.get('line')}" for test in tests[:4])
    return f"{evidence_tag(item)} {item.get('reason', 'Low-signal test candidate.')} Examples: {refs}."


def describe_placeholder_item(item: dict[str, Any]) -> str:
    return f"{evidence_tag(item)} `{item['file']}`: {item['reason']}"


def describe_monolith_item(item: dict[str, Any]) -> str:
    return (
        f"`{item['test']}` in `{item['file']}:{item['line']}` ({', '.join(item['reasons'])}; "
        f"{item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')}): {item['recommendation']}"
    )


def describe_assertion_light_item(item: dict[str, Any]) -> str:
    return (
        f"`{item['test']}` in `{item['file']}:{item['line']}` "
        f"({item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')}): {item['reason']}"
    )


def evidence_tag(item: dict[str, Any]) -> str:
    return f"({item.get('confidence', 'unknown')} confidence, {item.get('evidence_type', 'unknown')})"
