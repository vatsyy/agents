from __future__ import annotations

import re
from pathlib import Path

from .behaviour import assertion_kinds, mock_count, risk_notes, test_confidence
from .constants import JS_ASSERTION_RE, JS_FUNCTION_RE, JS_TEST_RE
from .models import FunctionInfo, TestCaseInfo, TestParseResult


def javascript_cases(path: Path, text: str) -> list[TestCaseInfo]:
    return javascript_parse_result(path, text).cases


def javascript_parse_result(path: Path, text: str) -> TestParseResult:
    framework = detect_javascript_test_framework(text)
    cases = [javascript_case(path, text, match, framework) for match in JS_TEST_RE.finditer(text)]
    return TestParseResult(cases=cases, framework=framework)


def javascript_case(path: Path, text: str, match: re.Match[str], framework: str) -> TestCaseInfo:
    line = line_for_offset(text, match.start())
    case_text = javascript_case_text(text, match)
    mocks = mock_count(case_text.lower())
    assertions = count_javascript_assertions(case_text)
    return TestCaseInfo(
        name=javascript_case_name(match, line),
        path=path,
        line=line,
        end_line=line_for_offset(text, match.start() + len(case_text)),
        assertions=assertions,
        branches=0,
        framework=framework,
        assertion_kinds=assertion_kinds(javascript_assertion_samples(case_text), case_text),
        assertion_samples=javascript_assertion_samples(case_text),
        mock_count=mocks,
        confidence=test_confidence(assertions, mocks),
        risk_notes=risk_notes(assertions, mocks, 0),
    )


def javascript_case_name(match: re.Match[str], line: int) -> str:
    return match.group(2).strip() or f"anonymous_test_{line}"


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def count_javascript_assertions(text: str) -> int:
    return len(JS_ASSERTION_RE.findall(text))


def javascript_case_text(text: str, match: re.Match[str]) -> str:
    return text[match.start() : next_case_offset(text, match.end())]


def next_case_offset(text: str, offset: int) -> int:
    next_match = JS_TEST_RE.search(text, offset)
    return next_match.start() if next_match else len(text)


def javascript_assertion_samples(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if JS_ASSERTION_RE.search(line)][:3]


def assign_javascript_assertions(cases: list[TestCaseInfo], assertion_count: int) -> None:
    if not cases:
        return
    if assertion_count == 0:
        return
    set_case_assertions(cases, max(1, assertion_count // len(cases)))


def set_case_assertions(cases: list[TestCaseInfo], assertion_count: int) -> None:
    for case in cases:
        case.assertions = assertion_count
        case.confidence = test_confidence(assertion_count, case.mock_count)
        case.risk_notes = risk_notes(assertion_count, case.mock_count, case.branches)


def detect_javascript_test_framework(text: str) -> str:
    lowered = text.lower()
    if "vitest" in lowered or re.search(r"\bvi\.", text):
        return "vitest/javascript"
    if "jest" in lowered or has_jest_style_globals(text):
        return "jest/javascript"
    return "javascript"


def has_jest_style_globals(text: str) -> bool:
    return bool(re.search(r"\b(?:test|it)\s*\(", text) and re.search(r"\bexpect\s*\(", text))


def javascript_functions_from_file(path: Path, text: str) -> list[FunctionInfo]:
    return [javascript_function(path, text, match) for match in JS_FUNCTION_RE.finditer(text)]


def javascript_function(path: Path, text: str, match: re.Match[str]) -> FunctionInfo:
    name = javascript_function_name(match)
    line = line_for_offset(text, match.start())
    return FunctionInfo(name, name, path, line, line, language="javascript")


def javascript_function_name(match: re.Match[str]) -> str:
    return next(group for group in match.groups() if group)
