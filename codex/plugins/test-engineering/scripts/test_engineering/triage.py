from __future__ import annotations

from pathlib import Path

from .files import rel
from .models import (
    ActionRecommendation,
    AssertionLightFinding,
    EntrypointGroup,
    FixtureShape,
    FunctionGrade,
    HighSignalFile,
    MockHeavyFinding,
    MonolithFinding,
    OrientationAssessment,
    TaxonomyAssessment,
    TestCaseInfo,
    TestFileInfo,
)
from .taxonomy import iter_test_cases, missing_priority_key, probably_untested


def build_orientation(
    root: Path,
    source_files: list[Path],
    test_files: list[Path],
    tests: list[TestFileInfo],
    framework_hints: list[str],
    coverage_state: str,
) -> OrientationAssessment:
    return OrientationAssessment(
        summary=tuple(orientation_summary(source_files, test_files, tests, framework_hints, coverage_state)),
        runner_clues=tuple(runner_clues(root, framework_hints)),
        fixture_shape=fixture_shape(tests),
        high_signal_files=tuple(high_signal_files(tests, root)),
    )


def orientation_summary(
    source_files: list[Path],
    test_files: list[Path],
    tests: list[TestFileInfo],
    framework_hints: list[str],
    coverage_state: str,
) -> list[str]:
    return [
        f"{len(source_files)} source files and {len(test_files)} test files inspected.",
        f"{sum(info.test_count for info in tests)} test cases found across {', '.join(framework_hints)}.",
        coverage_summary(coverage_state),
    ]


def coverage_summary(coverage_state: str) -> str:
    messages = {
        "not-requested": "No coverage XML requested.",
        "loaded": "Coverage XML loaded as line execution evidence.",
        "missing": "Coverage XML unavailable: file is missing.",
        "malformed": "Coverage XML unavailable: file is malformed.",
        "unreadable": "Coverage XML unavailable: file could not be read.",
        "empty": "Coverage XML unavailable: file contained no usable line execution data.",
    }
    return messages.get(coverage_state, f"Coverage XML state is {coverage_state}; execution evidence is unavailable.")


def runner_clues(root: Path, framework_hints: list[str]) -> list[str]:
    clues: list[str] = []
    add_existing_file_clue(clues, root, "pyproject.toml", "Python project configuration found.")
    add_existing_file_clue(clues, root, "pytest.ini", "Pytest configuration found.")
    add_existing_file_clue(clues, root, "package.json", "JavaScript package configuration found.")
    clues.extend(f"Framework hint: {hint}." for hint in framework_hints if hint != "unknown")
    return clues or ["No explicit runner configuration found by static scan."]


def add_existing_file_clue(clues: list[str], root: Path, name: str, message: str) -> None:
    if (root / name).exists():
        clues.append(message)


def fixture_shape(tests: list[TestFileInfo]) -> FixtureShape:
    return FixtureShape(
        fixtures=sum(len(info.fixtures) for info in tests),
        helpers=sum(len(info.helpers) for info in tests),
        parametrized_tests=sum(1 for case in iter_test_cases(tests) if case.parametrized),
        over_mocked_tests=len(over_mocked_cases(tests)),
    )


def high_signal_files(tests: list[TestFileInfo], root: Path) -> list[HighSignalFile]:
    return [test_file_signal(info, root) for info in sorted(tests, key=test_file_signal_score, reverse=True)[:10]]


def test_file_signal_score(info: TestFileInfo) -> int:
    return info.assertion_count + info.test_count + len(info.fixtures)


def test_file_signal(info: TestFileInfo, root: Path) -> HighSignalFile:
    return HighSignalFile(
        file=rel(info.path, root),
        framework=info.framework,
        tests=info.test_count,
        assertions=info.assertion_count,
        fixtures=len(info.fixtures),
        helpers=len(info.helpers),
    )


def build_action_plan(
    function_grades: list[FunctionGrade],
    tests: list[TestFileInfo],
    taxonomy: TaxonomyAssessment,
    root: Path,
) -> tuple[ActionRecommendation, ...]:
    actions = grouped_missing_actions(taxonomy)
    if not actions:
        actions.extend(missing_actions(function_grades))
    actions.extend(assertion_light_actions(taxonomy))
    actions.extend(monolith_actions(taxonomy))
    actions.extend(over_mocked_actions(tests, root))
    return tuple(actions[:12])


def grouped_missing_actions(taxonomy: TaxonomyAssessment) -> list[ActionRecommendation]:
    return [grouped_missing_action(group) for group in taxonomy.missing_by_entrypoint[:4]]


def grouped_missing_action(group: EntrypointGroup) -> ActionRecommendation:
    first = group.examples[0] if group.examples else None
    return ActionRecommendation(
        kind="add-entrypoint-tests",
        target=group.group,
        file=first.file if first else "multiple",
        line=first.line if first else 0,
        recommendation=f"{group.recommendation} ({group.count} candidates).",
        evidence_type="heuristic",
        confidence=group.confidence,
        candidate_count=group.count,
        examples=group.examples,
    )


def missing_actions(function_grades: list[FunctionGrade]) -> list[ActionRecommendation]:
    risky = [item for item in sorted(function_grades, key=missing_priority_key) if item.grade == "E" and probably_untested(item)]
    return [missing_action(item) for item in risky[:4]]


def missing_action(item: FunctionGrade) -> ActionRecommendation:
    return ActionRecommendation(
        kind="add-test",
        target=item.function,
        file=item.file,
        line=item.line,
        recommendation=item.recommendation,
        evidence_type="heuristic",
        confidence=item.confidence,
    )


def assertion_light_actions(taxonomy: TaxonomyAssessment) -> list[ActionRecommendation]:
    return [assertion_action(item) for item in taxonomy.assertion_light[:3]]


def assertion_action(item: AssertionLightFinding) -> ActionRecommendation:
    return ActionRecommendation(
        kind="strengthen-assertion",
        target=item.test,
        file=item.file,
        line=item.line,
        recommendation=item.reason,
        evidence_type="heuristic",
        confidence="high",
    )


def monolith_actions(taxonomy: TaxonomyAssessment) -> list[ActionRecommendation]:
    return [monolith_action(item) for item in taxonomy.monolith_candidates[:3]]


def monolith_action(item: MonolithFinding) -> ActionRecommendation:
    return ActionRecommendation(
        kind="split-test",
        target=item.test,
        file=item.file,
        line=item.line,
        recommendation=item.recommendation,
        evidence_type="heuristic",
        confidence="medium",
    )


def over_mocked_actions(tests: list[TestFileInfo], root: Path) -> list[ActionRecommendation]:
    return [
        ActionRecommendation(
            kind="review-mocks",
            target=case.name,
            file=rel(case.path, root),
            line=case.line,
            recommendation="Check whether mocks assert behaviour or implementation wiring.",
            evidence_type="heuristic",
            confidence="medium",
        )
        for case in over_mocked_cases(tests)[:2]
    ]


def over_mocked_cases(tests: list[TestFileInfo]) -> list[TestCaseInfo]:
    return [case for case in iter_test_cases(tests) if case.mock_count >= 4]


def over_mocked_findings(tests: list[TestFileInfo], root: Path) -> tuple[MockHeavyFinding, ...]:
    return tuple(over_mocked_finding(case, root) for case in sorted(over_mocked_cases(tests), key=mock_sort_key)[:8])


def mock_sort_key(case: TestCaseInfo) -> tuple[int, str, int]:
    return (-case.mock_count, str(case.path), case.line)


def over_mocked_finding(case: TestCaseInfo, root: Path) -> MockHeavyFinding:
    return MockHeavyFinding(
        test=case.name,
        file=rel(case.path, root),
        line=case.line,
        mock_count=case.mock_count,
        confidence="medium",
        evidence_type="heuristic",
        reason="Static scan counted repeated mock/patch terms; manual review should confirm whether the test is implementation-shaped.",
    )
