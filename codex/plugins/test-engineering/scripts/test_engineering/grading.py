from __future__ import annotations

from pathlib import Path

from .adapters import adapter_by_name, adapter_for
from .constants import COVERAGE_SCORE, WORD_RE
from .coverage import coverage_status_for
from .files import rel
from .models import (
    CoverageIndex,
    FunctionGrade,
    FunctionInfo,
    GradeEvidence,
    PreparedFile,
    SourceReference,
    TestCaseInfo,
    TestCaseReference,
    TestFileInfo,
)


def grade_functions(
    functions: list[FunctionInfo],
    tests: list[TestFileInfo],
    test_texts: dict[Path, str],
    coverage: CoverageIndex,
    root: Path,
    prepared_files: dict[Path, PreparedFile] | None = None,
) -> list[FunctionGrade]:
    lookup = test_file_lookup(tests)
    reference_index = build_test_reference_index(test_texts)
    call_line_index = build_test_call_line_index(test_texts, prepared_files)
    return [grade_function(function, lookup, reference_index, call_line_index, coverage, root) for function in functions]


def test_file_lookup(tests: list[TestFileInfo]) -> dict[Path, TestFileInfo]:
    return {info.path: info for info in tests}


def build_test_reference_index(test_texts: dict[Path, str]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path, text in test_texts.items():
        add_text_references(index, path, text)
    return {name: sorted(paths) for name, paths in index.items()}


def add_text_references(index: dict[str, list[Path]], path: Path, text: str) -> None:
    for word in unique_words(text):
        index.setdefault(word, []).append(path)


def unique_words(text: str) -> set[str]:
    return set(WORD_RE.findall(text))


def build_test_call_index(test_texts: dict[Path, str]) -> dict[str, list[Path]]:
    line_index = build_test_call_line_index(test_texts)
    return {name: sorted(paths) for name, paths in line_index.items()}


def build_test_call_line_index(
    test_texts: dict[Path, str],
    prepared_files: dict[Path, PreparedFile] | None = None,
) -> dict[str, dict[Path, set[int]]]:
    index: dict[str, dict[Path, set[int]]] = {}
    for path, text in test_texts.items():
        for name, line in call_locations(path, text, prepared_files.get(path) if prepared_files else None):
            index.setdefault(name, {}).setdefault(path, set()).add(line)
    return index


def call_locations(path: Path, text: str, prepared: PreparedFile | None = None) -> set[tuple[str, int]]:
    if prepared is not None:
        return adapter_by_name(prepared.adapter_name).call_locations(prepared)
    adapter = adapter_for(path)
    if adapter is None:
        return set()
    result = adapter.prepare(path, text, path.parent)
    return adapter.call_locations(result.prepared) if result.prepared is not None else set()


def call_names(path: Path, text: str) -> set[str]:
    return {name for name, _ in call_locations(path, text)}


def grade_function(
    function: FunctionInfo,
    lookup: dict[Path, TestFileInfo],
    reference_index: dict[str, list[Path]],
    call_line_index: dict[str, dict[Path, set[int]]],
    coverage: CoverageIndex,
    root: Path,
) -> FunctionGrade:
    evidence = collect_grade_evidence(function, lookup, reference_index, call_line_index, coverage)
    grade = score_to_grade(score_evidence(evidence))
    return build_function_grade(function, evidence, grade, root)


def collect_grade_evidence(
    function: FunctionInfo,
    lookup: dict[Path, TestFileInfo],
    reference_index: dict[str, list[Path]],
    call_line_index: dict[str, dict[Path, set[int]]],
    coverage: CoverageIndex,
) -> GradeEvidence:
    name_refs = find_test_references(function, reference_index)
    cases = cases_containing_calls(function.name, call_line_index, lookup)
    refs = sorted({case.path for case in cases})
    status, covered, executable = coverage_status_for(function, coverage)
    return GradeEvidence(refs, name_refs, sum(case.assertions for case in cases), cases, status, covered, executable)


def cases_containing_calls(
    function_name: str,
    call_line_index: dict[str, dict[Path, set[int]]],
    lookup: dict[Path, TestFileInfo],
) -> list[TestCaseInfo]:
    matched: list[TestCaseInfo] = []
    for path, lines in call_line_index.get(function_name, {}).items():
        info = lookup.get(path)
        if info is None:
            continue
        matched.extend(case for case in info.cases if any(case.line <= line <= case.end_line for line in lines))
    return matched


def referenced_assertions(refs: list[Path], lookup: dict[Path, TestFileInfo]) -> int:
    return sum(lookup[path].assertion_count for path in refs if path in lookup)


def referenced_cases(refs: list[Path], lookup: dict[Path, TestFileInfo]) -> list[TestCaseInfo]:
    cases: list[TestCaseInfo] = []
    for path in refs:
        cases.extend(cases_for_path(path, lookup))
    return cases


def cases_for_path(path: Path, lookup: dict[Path, TestFileInfo]) -> list[TestCaseInfo]:
    info = lookup.get(path)
    return info.cases if info else []


def score_evidence(evidence: GradeEvidence) -> int:
    score = 0
    if evidence.refs:
        score += 45
    if evidence.assertions:
        score += 25
    score += coverage_score(evidence)
    if has_parametrized_case(evidence.cases):
        score += 5
    return score


def coverage_score(evidence: GradeEvidence) -> int:
    if evidence.coverage_status == "unknown" and evidence.refs:
        return 5
    return COVERAGE_SCORE.get(evidence.coverage_status, 0)


def has_parametrized_case(cases: list[TestCaseInfo]) -> bool:
    return any(case.parametrized for case in cases)


def build_function_grade(
    function: FunctionInfo,
    evidence: GradeEvidence,
    grade: str,
    root: Path,
) -> FunctionGrade:
    labels = evidence_labels(evidence)
    confidence = evidence_confidence(labels)
    return FunctionGrade(
        function=function.qualified_name,
        simple_name=function.name,
        file=rel(function.path, root),
        line=function.line,
        end_line=function.end_line,
        language=function.language,
        grade=grade,
        score=score_evidence(evidence),
        evidence_labels=tuple(labels),
        evidence_type=evidence_type(labels),
        confidence=confidence,
        primary_evidence=primary_evidence_label(labels),
        evidence_confidence=confidence,
        source_ref=source_ref(function, root),
        test_refs=tuple(rel(path, root) for path in evidence.name_refs),
        direct_call_test_refs=tuple(rel(path, root) for path in evidence.refs),
        test_case_refs=tuple(case_ref(case, root) for case in evidence.cases),
        assertion_evidence=evidence.assertions,
        assertion_scope="direct_call_test_files" if evidence.refs else "none",
        mapping_method=mapping_method(evidence),
        manual_review_required=True,
        coverage_status=evidence.coverage_status,
        covered_lines=evidence.covered_lines,
        executable_lines=evidence.executable_lines,
        recommendation=recommendation_for_grade(function, grade, evidence),
    )


def find_test_references(function: FunctionInfo, reference_index: dict[str, list[Path]]) -> list[Path]:
    if len(function.name) < 3:
        return []
    return reference_index.get(function.name, [])


def score_to_grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    if score >= 25:
        return "D"
    return "E"


def evidence_labels(evidence: GradeEvidence) -> list[str]:
    labels: list[str] = []
    add_reference_label(labels, evidence)
    add_coverage_labels(labels, evidence)
    return labels or ["no evidence"]


def add_reference_label(labels: list[str], evidence: GradeEvidence) -> None:
    if not evidence.refs and not evidence.name_refs:
        return
    if evidence.refs and evidence.assertions:
        labels.append("direct test reference")
    else:
        labels.append("name/static heuristic")


def mapping_method(evidence: GradeEvidence) -> str:
    if evidence.refs:
        return "static_call_reference"
    if evidence.name_refs:
        return "function_name_token"
    return "none"


def add_coverage_labels(labels: list[str], evidence: GradeEvidence) -> None:
    if evidence.coverage_status not in {"covered", "partial"}:
        return
    if not evidence.refs:
        labels.append("indirect behavioural evidence")
    labels.append("coverage XML evidence")


def primary_evidence_label(labels: list[str]) -> str:
    return labels[0]


def evidence_confidence(labels: list[str]) -> str:
    if "direct test reference" in labels and "coverage XML evidence" in labels:
        return "high"
    if "direct test reference" in labels:
        return "low"
    if labels == ["no evidence"]:
        return "none"
    return "low"


def evidence_type(labels: list[str]) -> str:
    if labels == ["no evidence"]:
        return "deterministic"
    if "name/static heuristic" in labels or "direct test reference" in labels:
        return "heuristic"
    return "deterministic"


def source_ref(function: FunctionInfo, root: Path) -> SourceReference:
    return SourceReference(file=rel(function.path, root), line=function.line)


def case_ref(case: TestCaseInfo, root: Path) -> TestCaseReference:
    return TestCaseReference(
        test=case.name,
        file=rel(case.path, root),
        line=case.line,
        assertions=case.assertions,
    )


def recommendation_for_grade(
    function: FunctionInfo,
    grade: str,
    evidence: GradeEvidence,
) -> str:
    if grade in {"A", "B"}:
        return "Static evidence is strong; confirm the same-case assertions protect this behaviour and review critical boundaries."
    if is_private_helper(function):
        return private_helper_recommendation(function)
    if grade == "C":
        return "Add sharper assertions for the named behaviour and boundary cases."
    if grade == "D":
        return grade_d_recommendation(evidence.coverage_status, bool(evidence.assertions))
    return f"Create a focused test for {function.qualified_name} with setup, action, and observable assertions."


def is_private_helper(function: FunctionInfo) -> bool:
    return function.name.startswith("_") and not function.name.startswith("__")


def private_helper_recommendation(function: FunctionInfo) -> str:
    return (
        f"Prefer testing the public behaviour protected by {function.qualified_name}; add a direct helper test only "
        "if this helper owns tricky parsing, branching, state handling, or boundary logic."
    )


def grade_d_recommendation(coverage_status: str, has_assertions: bool) -> str:
    if coverage_status in {"covered", "partial"} and not has_assertions:
        return "Convert execution evidence into behaviour assertions."
    return "Add a direct test that names this function's externally visible behaviour."
