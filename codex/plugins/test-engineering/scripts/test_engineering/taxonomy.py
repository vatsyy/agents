from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .files import rel
from .models import (
    AssertionLightFinding,
    EntrypointExample,
    EntrypointGroup,
    FunctionFinding,
    FunctionGrade,
    LowSignalFinding,
    MonolithFinding,
    PlaceholderFinding,
    RedundancyFinding,
    TaxonomyAssessment,
    TestCaseInfo,
    TestCreationFinding,
    TestFileInfo,
    TestReference,
)

RISK_PATTERNS = {
    "migration/destructive data change": ("migration", "patch", "execute", "delete", "remove", "drop", "cleanup"),
    "permission/security": ("permission", "auth", "role", "token", "secret", "credential", "security"),
    "persistence/state": ("save", "insert", "update", "state", "persist", "commit", "rollback", "db"),
    "external call": ("api", "http", "request", "client", "upload", "download", "webhook", "sync"),
    "date/money logic": ("date", "time", "rate", "amount", "price", "currency", "tax", "total"),
    "scheduler/hook entrypoint": ("hook", "hooks", "schedule", "cron", "daily", "hourly", "weekly", "monthly", "task", "tasks"),
    "public entrypoint": ("command", "cli", "handler", "endpoint", "view", "route", "whitelist"),
    "report endpoint": ("query_report", "execute_report", "report_endpoint", "report_view", "reports"),
    "doctype method": ("doctype", "validate", "before_save", "after_insert", "on_update", "on_submit", "on_cancel"),
}

ENTRYPOINT_REASON_LABELS = {
    "scheduler/hook entrypoint",
    "public entrypoint",
    "report endpoint",
    "doctype method",
}


def build_full_taxonomy(
    function_grades: list[FunctionGrade],
    tests: list[TestFileInfo],
    root: Path,
) -> TaxonomyAssessment:
    taxonomy = build_taxonomy(function_grades, tests, root)
    return replace(
        taxonomy,
        redundant=tuple(find_redundancy_candidates(tests, root)),
        low_signal=tuple(low_signal_candidates(tests, root)),
        placeholder=tuple(placeholder_candidates(tests, root)),
        monolith_candidates=tuple(find_monolith_candidates(tests, root)),
    )


def build_taxonomy(
    function_grades: list[FunctionGrade],
    tests: list[TestFileInfo],
    root: Path,
) -> TaxonomyAssessment:
    missing = functions_with_grades(function_grades, {"E"})
    probably_missing = probably_untested_functions(missing)
    not_mapped = not_directly_mapped_functions(missing)
    return TaxonomyAssessment(
        covered=functions_with_grades(function_grades, {"A", "B"}),
        missing=missing,
        probably_untested=probably_missing,
        not_directly_mapped=not_mapped,
        missing_by_entrypoint=tuple(group_missing_by_entrypoint(probably_missing)),
        improvable=functions_with_grades(function_grades, {"C", "D"}),
        assertion_light=tuple(assertion_light_tests(tests, root)),
        needs_to_create=tuple(missing_test_cases(probably_missing)),
        redundant=(),
        low_signal=(),
        placeholder=(),
        monolith_candidates=(),
    )


def functions_with_grades(function_grades: list[FunctionGrade], grades: set[str]) -> tuple[FunctionFinding, ...]:
    return tuple(FunctionFinding(item) for item in function_grades if item.grade in grades)


def assertion_light_tests(tests: list[TestFileInfo], root: Path) -> list[AssertionLightFinding]:
    return [build_assertion_light_finding(case, root) for case in iter_test_cases(tests) if case.assertions == 0]


def build_assertion_light_finding(case: TestCaseInfo, root: Path) -> AssertionLightFinding:
    return AssertionLightFinding(
        test=case.name,
        file=rel(case.path, root),
        line=case.line,
        evidence_type="deterministic",
        confidence="high",
        evidence_lines=(case.line,),
        reason="No direct assertion found in this test case.",
    )


def missing_test_cases(functions: tuple[FunctionFinding, ...]) -> list[TestCreationFinding]:
    return [missing_test_case(item) for item in sorted(functions, key=missing_priority_key)[:25]]


def probably_untested_functions(missing: tuple[FunctionFinding, ...]) -> tuple[FunctionFinding, ...]:
    return tuple(annotate_missing_mapping(item, "probably_untested") for item in missing if probably_untested(item))


def not_directly_mapped_functions(missing: tuple[FunctionFinding, ...]) -> tuple[FunctionFinding, ...]:
    return tuple(annotate_missing_mapping(item, "not_directly_mapped") for item in missing if not probably_untested(item))


def annotate_missing_mapping(item: FunctionFinding, status: str) -> FunctionFinding:
    return FunctionFinding(
        grade=item.grade,
        static_mapping_status=status,
        entrypoint_group=entrypoint_group(item),
    )


def probably_untested(item: FunctionFinding | FunctionGrade) -> bool:
    reasons = set(behavioural_risk_reasons(item))
    return bool(reasons & ENTRYPOINT_REASON_LABELS) or behavioural_risk_score(item) >= 2


def group_missing_by_entrypoint(items: tuple[FunctionFinding, ...]) -> list[EntrypointGroup]:
    groups: dict[str, list[FunctionFinding]] = {}
    for item in sorted(items, key=missing_priority_key):
        groups.setdefault(entrypoint_group(item), []).append(item)
    return [build_entrypoint_group(group, grouped) for group, grouped in groups.items()]


def build_entrypoint_group(group: str, items: list[FunctionFinding]) -> EntrypointGroup:
    examples = items[:5]
    return EntrypointGroup(
        group=group,
        count=len(items),
        examples=tuple(
            EntrypointExample(
                function=item.grade.function,
                file=item.grade.file,
                line=item.grade.line,
                risk_reasons=tuple(behavioural_risk_reasons(item)),
            )
            for item in examples
        ),
        files=tuple(sorted({item.grade.file for item in items})),
        evidence_type="heuristic",
        confidence="medium",
        recommendation=grouped_missing_recommendation(group, examples),
    )


def grouped_missing_recommendation(group: str, examples: list[FunctionFinding]) -> str:
    names = ", ".join(item.grade.simple_name for item in examples[:3])
    suffix = f" starting with {names}" if names else ""
    return f"Add behaviour tests for the {group} surface{suffix}; assert public outcomes before private helpers."


def entrypoint_group(item: FunctionFinding | FunctionGrade) -> str:
    reasons = behavioural_risk_reasons(item)
    text = risk_text(item)
    if "scheduler/hook entrypoint" in reasons:
        return "framework hooks and scheduler jobs"
    if "report endpoint" in reasons:
        return "reports"
    if "doctype method" in reasons:
        return "DocType methods"
    if "public entrypoint" in reasons or contains_pattern(text, ("main", "script", "scripts")):
        return "CLI commands and scripts"
    return "public behaviours"


def missing_test_case(item: FunctionFinding) -> TestCreationFinding:
    grade = item.grade
    return TestCreationFinding(
        function=grade.function,
        file=grade.file,
        line=grade.line,
        test_name=f"test_{grade.simple_name}_behaviour",
        assertion_goal=grade.recommendation,
        evidence_type="heuristic",
        confidence=grade.confidence,
        risk_level=behavioural_risk_level(item),
        risk_reasons=tuple(behavioural_risk_reasons(item)),
        source_ref=grade.source_ref,
    )


def find_redundancy_candidates(tests: list[TestFileInfo], root: Path) -> list[RedundancyFinding]:
    groups = grouped_test_cases(tests)
    return [build_redundancy_finding(key, cases, root) for key, cases in sorted(groups.items()) if len(cases) >= 2]


def grouped_test_cases(tests: list[TestFileInfo]) -> dict[str, list[TestCaseInfo]]:
    groups: dict[str, list[TestCaseInfo]] = {}
    for case in iter_test_cases(tests):
        groups.setdefault(normalise_test_name(case.name), []).append(case)
    return groups


def build_redundancy_finding(key: str, cases: list[TestCaseInfo], root: Path) -> RedundancyFinding:
    return RedundancyFinding(
        normalised_intent=key,
        tests=tuple(test_case_reference(case, root) for case in cases),
        evidence_type="heuristic",
        confidence="low",
        reason="Multiple tests have the same normalised name. Confirm assertion intent before merging.",
    )


def test_case_reference(case: TestCaseInfo, root: Path) -> TestReference:
    return TestReference(
        test=case.name,
        file=rel(case.path, root),
        line=case.line,
        confidence=case.confidence,
    )


def low_signal_candidates(tests: list[TestFileInfo], root: Path) -> list[LowSignalFinding]:
    return [build_low_signal_finding(info, root) for info in tests if len(zero_assertion_cases(info)) >= 3]


def zero_assertion_cases(info: TestFileInfo) -> list[TestCaseInfo]:
    return [case for case in info.cases if case.assertions == 0]


def build_low_signal_finding(info: TestFileInfo, root: Path) -> LowSignalFinding:
    zero_asserts = zero_assertion_cases(info)
    return LowSignalFinding(
        file=rel(info.path, root),
        reason=f"{len(zero_asserts)} tests have no direct assertions.",
        tests=tuple(TestReference(test=case.name, line=case.line, confidence=case.confidence) for case in zero_asserts[:10]),
        evidence_type="deterministic",
        confidence="medium",
    )


def placeholder_candidates(tests: list[TestFileInfo], root: Path) -> list[PlaceholderFinding]:
    return [build_placeholder_finding(info, root) for info in tests if info.test_count == 0]


def build_placeholder_finding(info: TestFileInfo, root: Path) -> PlaceholderFinding:
    return PlaceholderFinding(
        file=rel(info.path, root),
        line=1,
        evidence_type="deterministic",
        confidence="high",
        reason="Test file contains no recognised test cases; classify as placeholder or empty test surface, not duplicate intent.",
    )


def find_monolith_candidates(tests: list[TestFileInfo], root: Path) -> list[MonolithFinding]:
    return [finding for case in iter_test_cases(tests) if (finding := build_monolith_finding(case, root))]


def build_monolith_finding(case: TestCaseInfo, root: Path) -> MonolithFinding | None:
    reasons = monolith_reasons(case)
    if not reasons:
        return None
    return MonolithFinding(
        test=case.name,
        file=rel(case.path, root),
        line=case.line,
        reasons=tuple(reasons),
        evidence_type="heuristic",
        confidence="medium",
        evidence_lines=(case.line,),
        recommendation="Split by independently named behaviour while preserving any workflow-level regression intent.",
    )


def monolith_reasons(case: TestCaseInfo) -> list[str]:
    reasons: list[str] = []
    add_threshold_reason(reasons, max(1, case.end_line - case.line + 1), 80, "lines")
    add_threshold_reason(reasons, case.assertions, 8, "assertions")
    add_threshold_reason(reasons, case.branches, 6, "branches")
    add_threshold_reason(reasons, len(case.fixtures), 6, "fixtures")
    return reasons


def add_threshold_reason(reasons: list[str], value: int, threshold: int, label: str) -> None:
    if value >= threshold:
        reasons.append(f"{value} {label}")


def iter_test_cases(tests: list[TestFileInfo]) -> list[TestCaseInfo]:
    return [case for info in tests for case in info.cases]


def normalise_test_name(name: str) -> str:
    name = name.split(".")[-1]
    name = re.sub(r"^test_", "", name)
    name = re.sub(r"\[[^\]]+\]", "", name)
    name = re.sub(r"\d+", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return name or "anonymous"


def missing_priority_key(item: FunctionFinding | FunctionGrade) -> tuple[int, int, str, int]:
    grade = function_grade(item)
    return (-behavioural_risk_score(item), helper_rank(item), grade.file, grade.line)


def behavioural_risk_score(item: FunctionFinding | FunctionGrade) -> int:
    text = risk_text(item)
    return sum(1 for patterns in RISK_PATTERNS.values() if contains_pattern(text, patterns))


def behavioural_risk_reasons(item: FunctionFinding | FunctionGrade) -> list[str]:
    text = risk_text(item)
    return [label for label, patterns in RISK_PATTERNS.items() if contains_pattern(text, patterns)]


def behavioural_risk_level(item: FunctionFinding | FunctionGrade) -> str:
    if "migration/destructive data change" in behavioural_risk_reasons(item):
        return "high"
    score = behavioural_risk_score(item)
    if score >= 2:
        return "high"
    if score == 1:
        return "medium"
    return "low"


def risk_text(item: FunctionFinding | FunctionGrade) -> str:
    grade = function_grade(item)
    return " ".join((grade.function, grade.simple_name, grade.file)).lower()


def function_grade(item: FunctionFinding | FunctionGrade) -> FunctionGrade:
    return item.grade if isinstance(item, FunctionFinding) else item


def contains_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(pattern)}(?![A-Za-z0-9])", text) for pattern in patterns)


def helper_rank(item: FunctionFinding | FunctionGrade) -> int:
    name = function_grade(item).simple_name
    if name.startswith("_"):
        return 2
    if "." in function_grade(item).function:
        return 1
    return 0
