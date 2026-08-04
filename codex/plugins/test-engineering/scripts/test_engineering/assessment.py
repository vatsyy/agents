from __future__ import annotations

from collections.abc import Iterable

from .constants import SCOPED_EVIDENCE, SUCCESSFULLY_ANALYSED_FILES, UNAVAILABLE
from .frameworks import detect_frameworks
from .grading import grade_functions
from .models import (
    AnalysisAssessment,
    AnalysisRun,
    CoverageGapAssessment,
    FunctionGrade,
    HeuristicExamples,
    ProjectionScope,
    RiskFunctionFinding,
    TaxonomyAssessment,
    TrustAssessment,
    TrustQuestion,
)
from .taxonomy import behavioural_risk_level, behavioural_risk_reasons, behavioural_risk_score, build_full_taxonomy, probably_untested
from .triage import build_action_plan, build_orientation, coverage_summary, over_mocked_cases, over_mocked_findings

def assess_run(run: AnalysisRun) -> AnalysisAssessment:
    test_texts = {path: run.texts[path] for path in run.test_files}
    function_grades = grade_functions(
        run.source_functions,
        run.tests,
        test_texts,
        run.coverage.index,
        run.root,
        run.prepared_files,
    )
    taxonomy = build_full_taxonomy(function_grades, run.tests, run.root)
    framework_hints = detect_frameworks(
        run.root,
        run.test_files,
        [*run.source_files, *run.test_files],
        run.texts,
    )
    return AnalysisAssessment(
        scope=projection_scope(run),
        framework_hints=framework_hints,
        function_grades=tuple(function_grades),
        taxonomy=taxonomy,
        orientation=build_orientation(
            run.root,
            run.source_files,
            run.test_files,
            run.tests,
            framework_hints,
            run.coverage.state,
        ),
        trust=build_trust_assessment(run, function_grades, taxonomy),
        action_plan=build_action_plan(function_grades, run.tests, taxonomy, run.root),
    )


def projection_scope(run: AnalysisRun) -> ProjectionScope:
    status = analysis_status(run)
    if status == "complete":
        return ProjectionScope(
            status=status,
            evidence_scope="repository",
            repository_verdict_available=True,
            projections={
                "action_plan": "repository",
                "empty_sections": "repository",
                "function_grades": "repository",
                "orientation_brief": "repository",
                "taxonomy": "repository",
                "trust": "repository",
            },
        )
    return ProjectionScope(
        status=status,
        evidence_scope=SUCCESSFULLY_ANALYSED_FILES,
        repository_verdict_available=False,
        projections={
            "action_plan": SCOPED_EVIDENCE,
            "empty_sections": UNAVAILABLE,
            "function_grades": SCOPED_EVIDENCE,
            "orientation_brief": SCOPED_EVIDENCE,
            "taxonomy": SCOPED_EVIDENCE,
            "trust": UNAVAILABLE,
        },
    )


def analysis_status(run: AnalysisRun) -> str:
    if not run.source_files and not run.test_files:
        return "unsupported"
    inventory = run.inventory
    if (
        inventory.truncated
        or inventory.unsupported_code_files
        or inventory.symlink_files
        or inventory.traversal_errors
        or any(item.severity == "warning" for item in run.diagnostics)
    ):
        return "partial"
    return "complete"


def build_trust_assessment(
    run: AnalysisRun,
    function_grades: list[FunctionGrade],
    taxonomy: TaxonomyAssessment,
) -> TrustAssessment:
    readiness = refactor_readiness(function_grades, taxonomy)
    gap = CoverageGapAssessment(
        probably_untested=len(taxonomy.probably_untested),
        not_directly_mapped=len(taxonomy.not_directly_mapped),
        missing_by_entrypoint=taxonomy.missing_by_entrypoint,
    )
    return TrustAssessment(
        summary=trust_summary(readiness, taxonomy, run.coverage.state),
        mocked_unit_trust="medium" if over_mocked_cases(run.tests) else "unknown",
        behavioural_coverage=behavioural_coverage_trust(function_grades, taxonomy),
        refactor_readiness=readiness,
        confidence="high" if function_grades else "low",
        evidence_type="heuristic",
        coverage_gap=gap,
        static_confidence_caveat=static_confidence_caveat(),
        grade_counts=count_grade_values(function_grades),
        confidence_counts=count_confidence_values(function_grades),
        risk_counts=risk_counts(run, taxonomy),
        heuristic_examples=HeuristicExamples(
            over_mocked=over_mocked_findings(run.tests, run.root),
            low_signal=taxonomy.low_signal[:5],
            placeholder=taxonomy.placeholder[:5],
        ),
        highest_risk_functions=highest_risk_functions(function_grades),
        questions=trust_questions(function_grades, run, taxonomy),
    )


def trust_summary(readiness: str, taxonomy: TaxonomyAssessment, coverage_state: str) -> str:
    coverage_text = coverage_summary(coverage_state).rstrip(".").lower()
    return (
        f"Refactor readiness is {readiness}; {len(taxonomy.probably_untested)} public behaviour "
        f"candidates look probably untested, {len(taxonomy.not_directly_mapped)} functions are only "
        f"not directly mapped by the static scan, and {coverage_text}."
    )


def static_confidence_caveat() -> str:
    return (
        "Static grading reports direct mappings found by name, assertions, and optional coverage artefacts. "
        "A not_directly_mapped function is not automatically untested; probably_untested marks public or risky "
        "behaviour that deserves manual test inspection first."
    )


def behavioural_coverage_trust(function_grades: list[FunctionGrade], taxonomy: TaxonomyAssessment) -> str:
    if not function_grades:
        return "unknown"
    if len(taxonomy.missing) > len(function_grades) // 2:
        return "low"
    return "partial" if taxonomy.missing else "medium"


def refactor_readiness(function_grades: list[FunctionGrade], taxonomy: TaxonomyAssessment) -> str:
    if len(taxonomy.probably_untested) > len(function_grades) // 2:
        return "low"
    if taxonomy.probably_untested or taxonomy.not_directly_mapped or taxonomy.improvable:
        return "partial"
    return "strong"


def highest_risk_functions(function_grades: list[FunctionGrade]) -> tuple[RiskFunctionFinding, ...]:
    risky = [item for item in function_grades if item.grade == "D" or (item.grade == "E" and probably_untested(item))]
    if not risky:
        risky = [item for item in function_grades if item.grade in {"D", "E"}]
    return tuple(
        RiskFunctionFinding(
            grade=item,
            risk_level=behavioural_risk_level(item),
            risk_reasons=tuple(behavioural_risk_reasons(item)),
        )
        for item in sorted(risky, key=risk_sort_key)[:10]
    )


def risk_sort_key(item: FunctionGrade) -> tuple[int, int, int, int, str, int]:
    return (
        {"E": 0, "D": 1}.get(item.grade, 2),
        -behavioural_risk_score(item),
        {"none": 0, "low": 1, "medium": 2, "high": 3}.get(item.confidence, 4),
        function_visibility_rank(item),
        item.file,
        item.line,
    )


def function_visibility_rank(item: FunctionGrade) -> int:
    if item.simple_name.startswith("_"):
        return 2
    if "." in item.function:
        return 1
    return 0


def count_grade_values(items: list[FunctionGrade]) -> dict[str, int]:
    return count_values(item.grade for item in items)


def count_confidence_values(items: list[FunctionGrade]) -> dict[str, int]:
    return count_values(item.confidence for item in items)


def count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def risk_counts(run: AnalysisRun, taxonomy: TaxonomyAssessment) -> dict[str, int]:
    return {
        "missing": len(taxonomy.missing),
        "probably_untested": len(taxonomy.probably_untested),
        "not_directly_mapped": len(taxonomy.not_directly_mapped),
        "improvable": len(taxonomy.improvable),
        "assertion_light": len(taxonomy.assertion_light),
        "monolith_candidates": len(taxonomy.monolith_candidates),
        "redundant": len(taxonomy.redundant),
        "low_signal": len(taxonomy.low_signal),
        "placeholder": len(taxonomy.placeholder),
        "over_mocked": len(over_mocked_cases(run.tests)),
    }


def trust_questions(
    function_grades: list[FunctionGrade],
    run: AnalysisRun,
    taxonomy: TaxonomyAssessment,
) -> tuple[TrustQuestion, ...]:
    return (
        trust_question("Can I trust the tests around this code?", refactor_readiness(function_grades, taxonomy)),
        trust_question("What behaviour is unprotected?", missing_answer(taxonomy)),
        trust_question(
            "What tests are implementation-shaped or over-mocked?",
            f"Static scan suggests {len(over_mocked_cases(run.tests))} tests are mock-heavy; inspect representative examples before treating this as design debt.",
        ),
        trust_question(
            "What tests may fail for the wrong reason?",
            f"{len(taxonomy.assertion_light)} assertion-light tests need manual review.",
        ),
        trust_question(
            "What should I add before refactoring?",
            f"Start with {len(taxonomy.needs_to_create)} missing-test candidates.",
        ),
    )


def trust_question(question: str, answer: str) -> TrustQuestion:
    return TrustQuestion(question=question, answer=answer, evidence_type="heuristic", confidence="medium")


def missing_answer(taxonomy: TaxonomyAssessment) -> str:
    return (
        f"{len(taxonomy.probably_untested)} public behaviour candidates look probably untested; "
        f"{len(taxonomy.not_directly_mapped)} functions are only not directly mapped by static scan."
    )
