from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PLUGIN_ROOT / "tests" / "fixtures" / "ground_truth.json"
GRADE_SCRIPT = PLUGIN_ROOT / "scripts" / "grade-function-tests"


class GroundTruthCorpusTests(unittest.TestCase):
    def test_labelled_ground_truth_cases(self) -> None:
        for case in load_cases():
            with self.subTest(case=case["name"]):
                self.assert_case(case)

    def assert_case(self, case: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_case_files(repo, case["files"])
            payload = run_grade_report(repo, case.get("coverage_xml"))
            assert_expected(self, payload, case["expected"])


def load_cases() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def write_case_files(repo: Path, files: dict[str, list[str]]) -> None:
    for relative, lines in files.items():
        write_file(repo / relative, lines)


def write_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_grade_report(repo: Path, coverage_xml: str | None) -> dict[str, Any]:
    command = [str(GRADE_SCRIPT), str(repo), "--format", "json"]
    if coverage_xml:
        command.extend(["--coverage-xml", str(repo / coverage_xml)])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    payload = json.loads(result.stdout)
    payload["_exit_code"] = result.returncode
    return payload


def assert_expected(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    assert_framework_hints(test, payload, expected)
    assert_counts(test, payload, expected)
    assert_grade_labels(test, payload, expected)
    assert_action_kinds(test, payload, expected)
    assert_recommendations(test, payload, expected)
    assert_contract(test, payload, expected)


def assert_framework_hints(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    for hint in expected.get("framework_hints_include", []):
        test.assertIn(hint, payload["framework_hints"])


def assert_counts(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    if "test_case_count" in expected:
        test.assertEqual(payload["test_case_count"], expected["test_case_count"])
    if "covered_min" in expected:
        test.assertGreaterEqual(len(payload["taxonomy"]["covered"]), expected["covered_min"])
    for key, value in expected.get("risk_counts_at_least", {}).items():
        test.assertGreaterEqual(payload["trust_report"]["risk_counts"][key], value)


def assert_grade_labels(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    grades = grade_map(payload)
    for function, labels in expected.get("grade_labels", {}).items():
        assert_labels_present(test, grades[function], labels)


def assert_labels_present(test: unittest.TestCase, grade: dict[str, Any], labels: list[str]) -> None:
    missing = [label for label in labels if label not in grade["evidence_labels"]]
    test.assertEqual(missing, [])


def assert_action_kinds(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    action_kinds = {item["kind"] for item in payload["action_plan"]}
    for kind in expected.get("action_kinds_include", []):
        test.assertIn(kind, action_kinds)


def assert_recommendations(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    for function, text in expected.get("recommendation_contains", {}).items():
        test.assertIn(text, grade_for(payload, function)["recommendation"])


def assert_contract(test: unittest.TestCase, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    if "status" in expected:
        test.assertEqual(payload["status"], expected["status"])
    if "exit_code" in expected:
        test.assertEqual(payload["_exit_code"], expected["exit_code"])
    for code in expected.get("diagnostic_codes_include", []):
        test.assertIn(code, {item["code"] for item in payload["diagnostics"]})
    for key, value in expected.get("inventory_values", {}).items():
        test.assertEqual(payload["inventory"][key], value)
    for function, values in expected.get("grade_values", {}).items():
        grade = grade_for(payload, function)
        for key, value in values.items():
            test.assertEqual(grade[key], value)


def grade_for(payload: dict[str, Any], function: str) -> dict[str, Any]:
    return next(item for item in payload["function_grades"] if item["simple_name"] == function)


def grade_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["simple_name"]: item for item in payload["function_grades"]}


if __name__ == "__main__":
    unittest.main()
