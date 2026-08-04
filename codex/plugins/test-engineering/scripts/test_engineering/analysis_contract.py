from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .adapters import SOURCE_TEST_ADAPTERS, AdapterCapabilities
from .constants import (
    MAX_PROJECT_FILES,
    MAX_TEXT_BYTES,
    SCOPED_EVIDENCE,
    SUCCESSFULLY_ANALYSED_FILES,
    UNAVAILABLE,
)
from .coverage import COVERAGE_ADAPTER
from .files import rel
from .models import (
    ActionRecommendation,
    AdapterRuntime,
    AnalysisOutcome,
    AnalysisRun,
    AssertionLightFinding,
    CoverageGapAssessment,
    CoverageLoadResult,
    Diagnostic,
    EntrypointExample,
    EntrypointGroup,
    FunctionFinding,
    FunctionGrade,
    HeuristicExamples,
    HighSignalFile,
    LowSignalFinding,
    MockHeavyFinding,
    MonolithFinding,
    OrientationAssessment,
    PlaceholderFinding,
    ProjectionScope,
    RedundancyFinding,
    RepoConfig,
    RiskFunctionFinding,
    SourceReference,
    TaxonomyAssessment,
    TestCaseReference,
    TestCaseInfo,
    TestCreationFinding,
    TestFileInfo,
    TestReference,
    TrustAssessment,
    TrustQuestion,
)
from .test_files import sum_test_cases


SCHEMA_VERSION = "1.0"
STATUS_EXIT_CODES = {"complete": 0, "partial": 1, "unsupported": 1, "error": 2}
RENDER_LIMITS = {
    "coverage_gap_examples": 3,
    "coverage_gap_groups": 5,
    "diagnostics": 10,
    "high_signal_files": 8,
    "heuristic_examples": 5,
    "highest_risk_functions": 8,
    "action_plan": 12,
    "test_files": 80,
    "function_grades": 120,
    "taxonomy_section": 30,
}


def serialise_analysis_outcome(outcome: AnalysisOutcome) -> dict[str, Any]:
    run = outcome.run
    assessment = outcome.assessment
    scope = assessment.scope
    trust_verdict, trust_report = trust_payloads(assessment.trust, scope)
    return {
        "repo": str(run.root),
        "framework_hints": assessment.framework_hints,
        "source_file_count": len(run.source_files),
        "test_file_count": len(run.test_files),
        "function_count": len(run.source_functions),
        "test_case_count": sum_test_cases(run.tests),
        "test_files": [serialise_test_file(info, run.root) for info in run.tests],
        "function_grades": [function_grade_payload(item, scope) for item in assessment.function_grades],
        "taxonomy": taxonomy_payload(assessment.taxonomy, scope),
        "orientation_brief": orientation_payload(assessment.orientation, scope),
        "trust_verdict": trust_verdict,
        "trust_report": trust_report,
        "action_plan": [action_payload(item, scope) for item in assessment.action_plan],
        "coverage_xml": str(run.coverage_xml) if run.coverage_xml else None,
        "repo_config": repo_config_payload(run.repo_config),
        "schema_version": SCHEMA_VERSION,
        "status": scope.status,
        "diagnostics": [diagnostic_payload(item) for item in run.diagnostics],
        "inventory": inventory_payload(run),
        "parsing": parsing_payload(run),
        "coverage": coverage_payload(run.coverage),
        "adapters": adapter_payload(run),
        "limits": limits_payload(),
        "manual_review_required": True,
        "assessment": projection_scope_payload(scope),
    }


def projection_scope_payload(scope: ProjectionScope) -> dict[str, Any]:
    return {
        "status": scope.status,
        "evidence_scope": scope.evidence_scope,
        "repository_verdict_available": scope.repository_verdict_available,
        "projections": scope.projections,
    }


def repo_config_payload(config: RepoConfig) -> dict[str, list[str]]:
    return {
        "ignore_path_contains": list(config.ignore_path_contains),
        "generated_path_contains": list(config.generated_path_contains),
    }


def diagnostic_payload(item: Diagnostic) -> dict[str, str]:
    payload = {"severity": item.severity, "code": item.code, "message": item.message}
    if item.path is not None:
        payload["path"] = item.path
    return payload


def serialise_test_file(info: TestFileInfo, root: Path) -> dict[str, Any]:
    return {
        "file": rel(info.path, root),
        "framework": info.framework,
        "line_count": info.line_count,
        "test_count": info.test_count,
        "assertion_count": info.assertion_count,
        "helper_count": len(info.helpers),
        "helpers": list(info.helpers),
        "fixture_count": len(info.fixtures),
        "fixtures": list(info.fixtures),
        "cases": [serialise_test_case(case) for case in info.cases],
    }


def serialise_test_case(case: TestCaseInfo) -> dict[str, Any]:
    return {
        "name": case.name,
        "line": case.line,
        "end_line": case.end_line,
        "assertions": case.assertions,
        "branches": case.branches,
        "fixtures": list(case.fixtures),
        "parametrized": case.parametrized,
        "framework": case.framework,
        "kind": case.kind,
        "assertion_kinds": list(case.assertion_kinds),
        "assertion_samples": list(case.assertion_samples),
        "mock_count": case.mock_count,
        "confidence": case.confidence,
        "evidence_type": case.evidence_type,
        "risk_notes": list(case.risk_notes),
    }


def function_grade_payload(item: FunctionGrade, scope: ProjectionScope) -> dict[str, Any]:
    payload = {
        "function": item.function,
        "simple_name": item.simple_name,
        "file": item.file,
        "line": item.line,
        "end_line": item.end_line,
        "language": item.language,
        "grade": item.grade,
        "score": item.score,
        "evidence_labels": list(item.evidence_labels),
        "evidence_type": item.evidence_type,
        "confidence": item.confidence,
        "primary_evidence": item.primary_evidence,
        "evidence_confidence": item.evidence_confidence,
        "source_ref": source_reference_payload(item.source_ref),
        "test_refs": list(item.test_refs),
        "direct_call_test_refs": list(item.direct_call_test_refs),
        "test_case_refs": [test_case_reference_payload(ref) for ref in item.test_case_refs],
        "assertion_evidence": item.assertion_evidence,
        "assertion_scope": item.assertion_scope,
        "mapping_method": item.mapping_method,
        "manual_review_required": item.manual_review_required,
        "coverage_status": item.coverage_status,
        "covered_lines": item.covered_lines,
        "executable_lines": item.executable_lines,
        "recommendation": item.recommendation,
    }
    return scope_function_grade_payload(payload, item, scope)


def source_reference_payload(item: SourceReference) -> dict[str, Any]:
    return {"file": item.file, "line": item.line}


def test_case_reference_payload(item: TestCaseReference) -> dict[str, Any]:
    return {"test": item.test, "file": item.file, "line": item.line, "assertions": item.assertions}


def function_finding_payload(item: FunctionFinding, scope: ProjectionScope) -> dict[str, Any]:
    payload = function_grade_payload(item.grade, scope)
    if item.static_mapping_status is not None:
        payload["static_mapping_status"] = item.static_mapping_status
    if item.entrypoint_group is not None:
        payload["entrypoint_group"] = item.entrypoint_group
    return payload


def taxonomy_payload(taxonomy: TaxonomyAssessment, scope: ProjectionScope) -> dict[str, Any]:
    payload = {
        "covered": [function_finding_payload(item, scope) for item in taxonomy.covered],
        "missing": [function_finding_payload(item, scope) for item in taxonomy.missing],
        "probably_untested": [function_finding_payload(item, scope) for item in taxonomy.probably_untested],
        "not_directly_mapped": [function_finding_payload(item, scope) for item in taxonomy.not_directly_mapped],
        "missing_by_entrypoint": [entrypoint_group_payload(item, scope) for item in taxonomy.missing_by_entrypoint],
        "improvable": [function_finding_payload(item, scope) for item in taxonomy.improvable],
        "assertion_light": [assertion_light_payload(item, scope) for item in taxonomy.assertion_light],
        "needs_to_create": [test_creation_payload(item, scope) for item in taxonomy.needs_to_create],
        "redundant": [redundancy_payload(item, scope) for item in taxonomy.redundant],
        "low_signal": [low_signal_payload(item, scope) for item in taxonomy.low_signal],
        "placeholder": [placeholder_payload(item, scope) for item in taxonomy.placeholder],
        "monolith_candidates": [monolith_payload(item, scope) for item in taxonomy.monolith_candidates],
    }
    if not scope.repository_verdict_available:
        payload.update(
            {
                "assessment_status": SCOPED_EVIDENCE,
                "evidence_scope": SUCCESSFULLY_ANALYSED_FILES,
            }
        )
    return payload


def entrypoint_example_payload(item: EntrypointExample) -> dict[str, Any]:
    return {"function": item.function, "file": item.file, "line": item.line, "risk_reasons": list(item.risk_reasons)}


def entrypoint_group_payload(item: EntrypointGroup, scope: ProjectionScope) -> dict[str, Any]:
    payload = {
        "group": item.group,
        "count": item.count,
        "examples": [entrypoint_example_payload(example) for example in item.examples],
        "files": list(item.files),
        "evidence_type": item.evidence_type,
        "confidence": item.confidence,
        "recommendation": item.recommendation,
    }
    return scope_recommendation_payload(payload, scope)


def assertion_light_payload(item: AssertionLightFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_evidence_payload(
        {
            "test": item.test,
            "file": item.file,
            "line": item.line,
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "evidence_lines": list(item.evidence_lines),
            "reason": item.reason,
        },
        scope,
    )


def test_creation_payload(item: TestCreationFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_evidence_payload(
        {
            "function": item.function,
            "file": item.file,
            "line": item.line,
            "test_name": item.test_name,
            "assertion_goal": item.assertion_goal,
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "risk_level": item.risk_level,
            "risk_reasons": list(item.risk_reasons),
            "source_ref": source_reference_payload(item.source_ref),
        },
        scope,
    )


def test_reference_payload(item: TestReference) -> dict[str, Any]:
    payload = {"test": item.test, "line": item.line, "confidence": item.confidence}
    if item.file is not None:
        payload["file"] = item.file
    return payload


def redundancy_payload(item: RedundancyFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_evidence_payload(
        {
            "normalised_intent": item.normalised_intent,
            "tests": [test_reference_payload(ref) for ref in item.tests],
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "reason": item.reason,
        },
        scope,
    )


def low_signal_payload(item: LowSignalFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_evidence_payload(
        {
            "file": item.file,
            "reason": item.reason,
            "tests": [test_reference_payload(ref) for ref in item.tests],
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
        },
        scope,
    )


def placeholder_payload(item: PlaceholderFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_evidence_payload(
        {
            "file": item.file,
            "line": item.line,
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "reason": item.reason,
        },
        scope,
    )


def monolith_payload(item: MonolithFinding, scope: ProjectionScope) -> dict[str, Any]:
    return scope_recommendation_payload(
        {
            "test": item.test,
            "file": item.file,
            "line": item.line,
            "reasons": list(item.reasons),
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "evidence_lines": list(item.evidence_lines),
            "recommendation": item.recommendation,
        },
        scope,
    )


def orientation_payload(item: OrientationAssessment, scope: ProjectionScope) -> dict[str, Any]:
    observed = {
        "summary": list(item.summary),
        "runner_clues": list(item.runner_clues),
        "fixture_shape": fixture_shape_payload(item),
        "high_signal_files": [high_signal_payload(file) for file in item.high_signal_files],
    }
    if scope.repository_verdict_available:
        return observed
    summary = [
        f"Orientation verdict unavailable: analysis status is {scope.status}.",
        "Observed orientation evidence is scoped to successfully analysed files.",
    ]
    if item.summary:
        summary.append(item.summary[-1])
    return {
        "summary": summary,
        "runner_clues": [],
        "fixture_shape": {
            "fixtures": None,
            "helpers": None,
            "parametrized_tests": None,
            "over_mocked_tests": None,
            "assessment_status": UNAVAILABLE,
            "evidence_scope": SUCCESSFULLY_ANALYSED_FILES,
        },
        "high_signal_files": [],
        "observed_summary": observed["summary"],
        "observed_runner_clues": observed["runner_clues"],
        "observed_fixture_shape": observed["fixture_shape"],
        "observed_high_signal_files": observed["high_signal_files"],
        "assessment_status": SCOPED_EVIDENCE,
        "evidence_scope": SUCCESSFULLY_ANALYSED_FILES,
        "repository_verdict_available": False,
    }


def fixture_shape_payload(item: OrientationAssessment) -> dict[str, int]:
    shape = item.fixture_shape
    return {
        "fixtures": shape.fixtures,
        "helpers": shape.helpers,
        "parametrized_tests": shape.parametrized_tests,
        "over_mocked_tests": shape.over_mocked_tests,
    }


def high_signal_payload(item: HighSignalFile) -> dict[str, Any]:
    return {
        "file": item.file,
        "framework": item.framework,
        "tests": item.tests,
        "assertions": item.assertions,
        "fixtures": item.fixtures,
        "helpers": item.helpers,
    }


def trust_payloads(trust: TrustAssessment, scope: ProjectionScope) -> tuple[dict[str, Any], dict[str, Any]]:
    coverage_gap = coverage_gap_payload(trust.coverage_gap)
    examples = heuristic_examples_payload(trust.heuristic_examples)
    risky = [risk_function_payload(item, scope) for item in trust.highest_risk_functions]
    questions = [trust_question_payload(item, scope) for item in trust.questions]
    verdict = {
        "summary": trust.summary,
        "mocked_unit_trust": trust.mocked_unit_trust,
        "behavioural_coverage": trust.behavioural_coverage,
        "refactor_readiness": trust.refactor_readiness,
        "confidence": trust.confidence,
        "evidence_type": trust.evidence_type,
        "coverage_gap_summary": coverage_gap,
        "static_confidence_caveat": trust.static_confidence_caveat,
        "highest_risk_functions": risky,
        "heuristic_examples": examples,
    }
    report = {
        "grade_counts": dict(trust.grade_counts),
        "confidence_counts": dict(trust.confidence_counts),
        "coverage_gap_summary": coverage_gap,
        "static_confidence_caveat": trust.static_confidence_caveat,
        "risk_counts": dict(trust.risk_counts),
        "heuristic_examples": examples,
        "refactor_readiness": trust.refactor_readiness,
        "highest_risk_functions": risky,
        "questions": questions,
    }
    if scope.repository_verdict_available:
        return verdict, report
    unavailable_gap = {
        "assessment_status": UNAVAILABLE,
        "evidence_scope": SUCCESSFULLY_ANALYSED_FILES,
        "observed": coverage_gap,
    }
    scoped_examples = {**examples, "assessment_status": SCOPED_EVIDENCE}
    verdict.update(
        {
            "summary": f"Analysis status is {scope.status}; incomplete evidence prevents a trustworthy clean verdict.",
            "mocked_unit_trust": UNAVAILABLE,
            "behavioural_coverage": UNAVAILABLE,
            "refactor_readiness": UNAVAILABLE,
            "confidence": "low",
            "evidence_type": "diagnostic",
            "coverage_gap_summary": unavailable_gap,
            "heuristic_examples": scoped_examples,
        }
    )
    report.update(
        {
            "observed_grade_counts": dict(trust.grade_counts),
            "observed_confidence_counts": dict(trust.confidence_counts),
            "observed_risk_counts": dict(trust.risk_counts),
            "grade_counts": {},
            "confidence_counts": {},
            "risk_counts": {},
            "grade_counts_status": UNAVAILABLE,
            "confidence_counts_status": UNAVAILABLE,
            "risk_counts_status": UNAVAILABLE,
            "coverage_gap_summary": unavailable_gap,
            "heuristic_examples": scoped_examples,
            "refactor_readiness": UNAVAILABLE,
            "assessment_status": UNAVAILABLE,
        }
    )
    return verdict, report


def coverage_gap_payload(item: CoverageGapAssessment) -> dict[str, Any]:
    return {
        "probably_untested": item.probably_untested,
        "not_directly_mapped": item.not_directly_mapped,
        "missing_by_entrypoint": [entrypoint_group_payload(group, repository_scope()) for group in item.missing_by_entrypoint],
    }


def heuristic_examples_payload(item: HeuristicExamples) -> dict[str, Any]:
    return {
        "over_mocked": [mock_heavy_payload(finding) for finding in item.over_mocked],
        "low_signal": [low_signal_payload(finding, repository_scope()) for finding in item.low_signal],
        "placeholder": [placeholder_payload(finding, repository_scope()) for finding in item.placeholder],
    }


def mock_heavy_payload(item: MockHeavyFinding) -> dict[str, Any]:
    return {
        "test": item.test,
        "file": item.file,
        "line": item.line,
        "mock_count": item.mock_count,
        "confidence": item.confidence,
        "evidence_type": item.evidence_type,
        "reason": item.reason,
    }


def risk_function_payload(item: RiskFunctionFinding, scope: ProjectionScope) -> dict[str, Any]:
    grade = item.grade
    payload = {
        "function": grade.function,
        "file": grade.file,
        "line": grade.line,
        "grade": grade.grade,
        "confidence": grade.confidence,
        "evidence_type": grade.evidence_type,
        "evidence_labels": list(grade.evidence_labels),
        "risk_level": item.risk_level,
        "risk_reasons": list(item.risk_reasons),
        "recommendation": grade.recommendation,
    }
    return scope_function_grade_payload(payload, grade, scope)


def trust_question_payload(item: TrustQuestion, scope: ProjectionScope) -> dict[str, str]:
    if scope.repository_verdict_available:
        return {
            "question": item.question,
            "answer": item.answer,
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
        }
    return {
        "question": item.question,
        "answer": f"unavailable: analysis status is {scope.status}",
        "evidence_type": "diagnostic",
        "confidence": "low",
    }


def action_payload(item: ActionRecommendation, scope: ProjectionScope) -> dict[str, Any]:
    payload = {
        "kind": item.kind,
        "target": item.target,
        "file": item.file,
        "line": item.line,
        "recommendation": item.recommendation,
        "evidence_type": item.evidence_type,
        "confidence": item.confidence,
    }
    if item.candidate_count is not None:
        payload["candidate_count"] = item.candidate_count
        payload["examples"] = [entrypoint_example_payload(example) for example in item.examples]
    return scope_recommendation_payload(payload, scope)


def scope_recommendation_payload(payload: dict[str, Any], scope: ProjectionScope) -> dict[str, Any]:
    if scope.repository_verdict_available:
        return payload
    scoped = dict(payload)
    observed = str(scoped.get("recommendation", ""))
    scoped.update(
        {
            "assessment_status": SCOPED_EVIDENCE,
            "repository_verdict_available": False,
            "observed_recommendation": observed,
            "recommendation": scoped_recommendation(observed),
        }
    )
    return scoped


def scope_function_grade_payload(
    payload: dict[str, Any],
    grade: FunctionGrade,
    scope: ProjectionScope,
) -> dict[str, Any]:
    if scope.repository_verdict_available:
        return payload
    return {
        **payload,
        "observed_grade": grade.grade,
        "observed_score": grade.score,
        "observed_recommendation": grade.recommendation,
        "grade": UNAVAILABLE,
        "score": None,
        "assessment_status": SCOPED_EVIDENCE,
        "repository_verdict_available": False,
        "recommendation": scoped_recommendation(grade.recommendation),
    }


def scope_evidence_payload(payload: dict[str, Any], scope: ProjectionScope) -> dict[str, Any]:
    if scope.repository_verdict_available:
        return payload
    return {
        **payload,
        "assessment_status": SCOPED_EVIDENCE,
        "repository_verdict_available": False,
    }


def scoped_recommendation(observed: str) -> str:
    suffix = f" Observed evidence suggested: {observed}" if observed else ""
    return f"Scoped evidence only; repository-wide recommendation unavailable.{suffix}"


def repository_scope() -> ProjectionScope:
    return ProjectionScope(
        status="complete",
        evidence_scope="repository",
        repository_verdict_available=True,
        projections={},
    )


def inventory_payload(run: AnalysisRun) -> dict[str, Any]:
    root = run.root
    inventory = run.inventory
    return {
        "discovered_file_count": inventory.discovered_file_count,
        "supported_candidate_count": inventory.supported_candidate_count,
        "analysed_file_count": len(run.source_files) + len(run.test_files),
        "source_file_count": len(run.source_files),
        "test_file_count": len(run.test_files),
        "unsupported_code_file_count": len(inventory.unsupported_code_files),
        "unsupported_code_files": [rel(path, root) for path in inventory.unsupported_code_files],
        "excluded_by_config_count": len(run.excluded_files),
        "excluded_by_config_files": [rel(path, root) for path in run.excluded_files],
        "oversized_file_count": len(inventory.oversized_files),
        "oversized_files": [rel(path, root) for path in inventory.oversized_files],
        "unreadable_file_count": len(inventory.unreadable_files),
        "unreadable_files": [rel(path, root) for path in inventory.unreadable_files],
        "symlink_file_count": len(inventory.symlink_files),
        "symlink_files": [rel(path, root) for path in inventory.symlink_files],
        "traversal_error_count": len(inventory.traversal_errors),
        "traversal_errors": [
            {"path": rel(Path(item.path), root) if item.path else "", "message": item.message}
            for item in inventory.traversal_errors
        ],
        "excluded_directory_count": inventory.excluded_directory_count,
        "truncated": inventory.truncated,
    }


def parsing_payload(run: AnalysisRun) -> dict[str, Any]:
    attempted_files = [*run.attempted_source_files, *run.attempted_test_files]
    return {
        "attempted_file_count": len(attempted_files),
        "succeeded_file_count": len(attempted_files) - len(run.analysis_failures),
        "failed_file_count": len(run.analysis_failures),
        "failed_files": [item.path or "" for item in run.analysis_failures],
    }


def coverage_payload(result: CoverageLoadResult) -> dict[str, Any]:
    return {
        "state": result.state,
        "available": result.state == "loaded",
        "path": str(result.path) if result.path else None,
        "class_count": result.class_count if result.state in {"loaded", "empty"} else None,
        "line_count": result.line_count if result.state in {"loaded", "empty"} else None,
        "adapter": "coverage-xml" if result.path else None,
    }


def adapter_payload(run: AnalysisRun) -> list[dict[str, Any]]:
    source_adapters = [
        adapter_capability_payload(
            adapter.capabilities,
            adapter_runtime_payload(run.adapter_runtime[adapter.capabilities.name]),
        )
        for adapter in SOURCE_TEST_ADAPTERS
    ]
    coverage = adapter_capability_payload(COVERAGE_ADAPTER, {"state": run.coverage.state})
    return [*source_adapters, coverage]


def adapter_capability_payload(capabilities: AdapterCapabilities, runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": capabilities.name,
        "version": capabilities.version,
        "languages": list(capabilities.languages),
        "frameworks": list(capabilities.frameworks),
        "capability": capabilities.capability,
        "runtime": runtime,
    }


def adapter_runtime_payload(runtime: AdapterRuntime) -> dict[str, Any]:
    return {
        "analysed_source_files": runtime.analysed_source_files,
        "analysed_test_files": runtime.analysed_test_files,
        "attempted_source_files": runtime.attempted_source_files,
        "attempted_test_files": runtime.attempted_test_files,
        "failed_files": runtime.failed_files,
        "state": runtime.state,
    }


def limits_payload() -> dict[str, Any]:
    return {
        "analysis": {"max_discovered_files": MAX_PROJECT_FILES, "max_text_bytes_per_file": MAX_TEXT_BYTES},
        "render": RENDER_LIMITS,
    }


def command_context(report: dict[str, Any], command: str, repo: Path, coverage_xml: Path | None) -> dict[str, Any]:
    contextual = dict(report)
    contextual["command"] = command
    contextual["reproduction"] = reproduction_commands(command, repo, coverage_xml)
    contextual["truncation"] = truncation_payload(report)
    return contextual


def reproduction_commands(command: str, repo: Path, coverage_xml: Path | None) -> dict[str, str]:
    base = [f"scripts/{command}", str(repo), "--format"]
    coverage = ["--coverage-xml", str(coverage_xml)] if coverage_xml else []
    return {
        "markdown": shlex.join([*base, "markdown", *coverage]),
        "json": shlex.join([*base, "json", *coverage]),
    }


def truncation_payload(report: dict[str, Any]) -> dict[str, dict[str, int | bool]]:
    taxonomy = report.get("taxonomy", {})
    sections = {
        "diagnostics": (len(report.get("diagnostics", [])), RENDER_LIMITS["diagnostics"]),
        "orientation_brief.high_signal_files": (
            len(report.get("orientation_brief", {}).get("high_signal_files", [])),
            RENDER_LIMITS["high_signal_files"],
        ),
        "trust_report.highest_risk_functions": (
            len(report.get("trust_report", {}).get("highest_risk_functions", [])),
            RENDER_LIMITS["highest_risk_functions"],
        ),
        "test_files": (len(report.get("test_files", [])), RENDER_LIMITS["test_files"]),
        "function_grades": (len(report.get("function_grades", [])), RENDER_LIMITS["function_grades"]),
        "action_plan": (len(report.get("action_plan", [])), RENDER_LIMITS["action_plan"]),
        "trust_report.coverage_gap_groups": (
            len(report.get("trust_report", {}).get("coverage_gap_summary", {}).get("missing_by_entrypoint", [])),
            RENDER_LIMITS["coverage_gap_groups"],
        ),
        "trust_report.heuristic_examples.over_mocked": (
            len(report.get("trust_report", {}).get("heuristic_examples", {}).get("over_mocked", [])),
            RENDER_LIMITS["heuristic_examples"],
        ),
    }
    for index, group in enumerate(
        report.get("trust_report", {}).get("coverage_gap_summary", {}).get("missing_by_entrypoint", [])
    ):
        sections[f"trust_report.coverage_gap_groups.{index}.examples"] = (
            len(group.get("examples", [])),
            RENDER_LIMITS["coverage_gap_examples"],
        )
    for name, items in taxonomy.items():
        if isinstance(items, list):
            sections[f"taxonomy.{name}"] = (len(items), RENDER_LIMITS["taxonomy_section"])
    return {name: section_limit(total, limit) for name, (total, limit) in sections.items()}


def section_limit(total: int, limit: int) -> dict[str, int | bool]:
    shown = min(total, limit)
    return {"total": total, "shown": shown, "omitted": total - shown, "truncated": total > limit}


def exit_code_for(report: dict[str, Any]) -> int:
    return STATUS_EXIT_CODES.get(report.get("status", "error"), 2)
