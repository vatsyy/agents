from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from test_engineering.analysis import (  # noqa: E402
    CoverageIndex,
    FunctionInfo,
    build_test_reference_index,
    coverage_status_for,
    find_test_references,
)


class TestEngineeringScripts(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.write("src/app.py", PYTHON_SOURCE)
        self.write("tests/test_app.py", PYTEST_SOURCE)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(clean(text), encoding="utf-8")
        return path

    def run_script(self, name: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPTS / name), str(self.repo), *args],
            text=True,
            capture_output=True,
            check=True,
        )

    def json_report(self, name: str, *args: str) -> dict:
        return json.loads(self.run_script(name, *args, "--format", "json").stdout)

    def function_grade(self, payload: dict, name: str) -> dict:
        return next(item for item in payload["function_grades"] if item["simple_name"] == name)

    def test_grade_report_contains_required_sections(self) -> None:
        output = self.run_script("grade-function-tests", "--format", "markdown").stdout
        for heading in REQUIRED_HEADINGS:
            self.assertIn(heading, output)
        self.assertIn("confidence", output)
        self.assertIn("Report Basis", output)
        self.assertIn("Orientation Brief", output)
        self.assertIn("Trust Verdict", output)
        self.assertIn("Trust Report", output)
        self.assertIn("Highest-risk functions", output)
        self.assertIn("Action Plan", output)
        self.assertIn("No deterministic duplicate tests or redundancy candidates", output)

    def test_json_inventory_is_machine_readable(self) -> None:
        payload = self.json_report("test-inventory")
        self.assertEqual(payload["test_file_count"], 1)
        self.assertEqual(payload["test_case_count"], 2)
        self.assertIn("pytest/python", payload["framework_hints"])
        self.assertIn("orientation_brief", payload)
        self.assertIn("trust_verdict", payload)
        self.assertIn("trust_report", payload)
        self.assertIn("action_plan", payload)
        self.assertIn("highest_risk_functions", payload["trust_report"])
        self.assertEqual(payload["trust_verdict"]["refactor_readiness"], "partial")

    def test_nested_helper_functions_are_not_test_cases(self) -> None:
        self.write("tests/test_helpers.py", NESTED_HELPER_TEST)
        payload = self.json_report("test-inventory")
        helper_file = by_file(payload["test_files"], "tests/test_helpers.py")
        self.assertEqual(helper_file["test_count"], 1)
        self.assertEqual(helper_file["helper_count"], 1)
        self.assertEqual(helper_file["helpers"], ["test_inner_helper"])

    def test_pytest_fixtures_and_parametrisation_are_classified(self) -> None:
        self.write("tests/test_parametrized.py", PYTEST_PARAMETRIZED)
        payload = self.json_report("test-inventory")
        item = by_file(payload["test_files"], "tests/test_parametrized.py")
        self.assertEqual(item["fixture_count"], 1)
        self.assertTrue(item["cases"][0]["parametrized"])

    def test_behaviour_signals_capture_assertion_intent(self) -> None:
        self.write("tests/test_behaviour.py", BEHAVIOUR_TEST)
        payload = self.json_report("test-inventory")
        case = by_case(by_file(payload["test_files"], "tests/test_behaviour.py"), "test_error_boundary_and_external_call")
        self.assertIn("error-path", case["assertion_kinds"])
        self.assertIn("external-call", case["assertion_kinds"])
        self.assertIn("state-change", case["assertion_kinds"])
        self.assertIn("persistence", case["assertion_kinds"])
        self.assertIn("permission/security", case["assertion_kinds"])
        self.assertIn("observable assertion", case["assertion_kinds"])

    def test_repo_local_ignore_config_filters_generated_files(self) -> None:
        self.write(".test-engineering.json", IGNORE_CONFIG)
        self.write("generated/test_generated.py", GENERATED_TEST)
        payload = self.json_report("test-inventory")
        self.assertNotIn("generated/test_generated.py", [item["file"] for item in payload["test_files"]])

    def test_unittest_lifecycle_methods_are_not_counted(self) -> None:
        self.write("tests/test_unittest_app.py", UNITTEST_SOURCE)
        payload = self.json_report("test-inventory")
        item = by_file(payload["test_files"], "tests/test_unittest_app.py")
        self.assertEqual(item["framework"], "unittest/python")
        self.assertEqual(item["test_count"], 1)
        self.assertEqual(item["cases"][0]["name"], "CalculatorTests.test_add")

    def test_framework_specific_adapter_pattern_stays_scoped(self) -> None:
        self.write("tests/test_framework_adapter.py", FRAMEWORK_ADAPTER_TEST)
        payload = self.json_report("test-inventory")
        item = by_file(payload["test_files"], "tests/test_framework_adapter.py")
        self.assertEqual(item["framework"], "framework-adapter/python")
        self.assertIn("framework-adapter/python", payload["framework_hints"])

    def test_jest_fixture_produces_inventory_and_grades(self) -> None:
        self.write("src/math.js", JS_SOURCE)
        self.write("tests/math.test.js", JEST_TEST)
        payload = self.json_report("grade-function-tests")
        self.assertIn("jest/javascript", payload["framework_hints"])
        grade = self.function_grade(payload, "add")
        self.assertIn("direct test reference", grade["evidence_labels"])

    def test_vitest_fixture_produces_inventory_and_grades(self) -> None:
        self.write("src/maths.ts", TS_SOURCE)
        self.write("tests/maths.test.ts", VITEST_TEST)
        payload = self.json_report("grade-function-tests")
        self.assertIn("vitest/javascript", payload["framework_hints"])
        grade = self.function_grade(payload, "multiply")
        self.assertEqual(grade["language"], "javascript")

    def test_coverage_xml_adds_evidence_label(self) -> None:
        coverage = self.write("coverage.xml", COVERAGE_XML)
        payload = self.json_report("grade-function-tests", "--coverage-xml", str(coverage))
        grade = self.function_grade(payload, "add")
        self.assertIn("coverage XML evidence", grade["evidence_labels"])
        self.assertEqual(grade["coverage_status"], "covered")

    def test_private_helper_recommendation_prefers_public_behaviour(self) -> None:
        payload = self.json_report("grade-function-tests")
        grade = self.function_grade(payload, "_normalise")
        self.assertIn("Prefer testing the public behaviour", grade["recommendation"])

    def test_static_gap_summary_splits_unmapped_from_probably_untested(self) -> None:
        self.write("scripts/cli.py", PUBLIC_SCRIPT)
        self.write("src/internal.py", LOW_RISK_HELPER)

        payload = self.json_report("grade-function-tests")
        summary = payload["trust_report"]["coverage_gap_summary"]
        question = next(item for item in payload["trust_report"]["questions"] if item["question"] == "What behaviour is unprotected?")
        probable = {item["simple_name"] for item in payload["taxonomy"]["probably_untested"]}
        unmapped = {item["simple_name"] for item in payload["taxonomy"]["not_directly_mapped"]}
        group_names = {item["group"] for item in summary["missing_by_entrypoint"]}

        self.assertIn("main", probable)
        self.assertIn("_format_label", unmapped)
        self.assertGreaterEqual(summary["probably_untested"], 1)
        self.assertGreaterEqual(summary["not_directly_mapped"], 1)
        self.assertIn("CLI commands and scripts", group_names)
        self.assertEqual(question["evidence_type"], "heuristic")
        self.assertIn("not_directly_mapped", payload["trust_report"]["static_confidence_caveat"])

    def test_action_plan_groups_public_missing_evidence(self) -> None:
        self.write("scripts/cli.py", PUBLIC_SCRIPT)

        payload = self.json_report("grade-function-tests")
        action = payload["action_plan"][0]

        self.assertEqual(action["kind"], "add-entrypoint-tests")
        self.assertEqual(action["target"], "CLI commands and scripts")
        self.assertGreaterEqual(action["candidate_count"], 1)
        self.assertTrue(action["examples"])

    def test_entrypoint_groups_include_reports_hooks_and_doctype_methods(self) -> None:
        self.write("reports/sales.py", REPORT_ENDPOINT)
        self.write("hooks.py", SCHEDULER_HOOK)
        self.write("doctype/invoice.py", DOCTYPE_METHOD)

        payload = self.json_report("grade-function-tests")
        group_names = {item["group"] for item in payload["taxonomy"]["missing_by_entrypoint"]}

        self.assertIn("reports", group_names)
        self.assertIn("framework hooks and scheduler jobs", group_names)
        self.assertIn("DocType methods", group_names)

    def test_over_mocked_count_includes_examples(self) -> None:
        self.write("tests/test_mock_heavy.py", MOCK_HEAVY_TEST)
        payload = self.json_report("grade-function-tests")
        examples = payload["trust_report"]["heuristic_examples"]["over_mocked"]
        self.assertGreaterEqual(payload["trust_report"]["risk_counts"]["over_mocked"], 1)
        self.assertEqual(examples[0]["test"], "test_mock_heavy_flow")
        self.assertGreaterEqual(examples[0]["mock_count"], 4)

    def test_placeholder_file_is_not_redundant(self) -> None:
        self.write("tests/test_placeholder.py", PLACEHOLDER_TEST)
        payload = self.json_report("test-inventory")
        placeholders = payload["taxonomy"]["placeholder"]
        redundant = payload["taxonomy"]["redundant"]
        self.assertEqual(placeholders[0]["file"], "tests/test_placeholder.py")
        self.assertEqual(redundant, [])

    def test_javascript_constants_are_not_function_grade_targets(self) -> None:
        self.write("src/constants.js", JS_CONSTANTS)
        payload = self.json_report("grade-function-tests")
        names = {item["simple_name"] for item in payload["function_grades"]}
        self.assertNotIn("API_BASE", names)
        self.assertNotIn("SETTINGS", names)

    def test_high_risk_missing_coverage_outranks_private_helper_noise(self) -> None:
        self.write("patches/remove_legacy.py", HIGH_RISK_PATCH)
        self.write("src/internal.py", LOW_RISK_HELPER)
        payload = self.json_report("grade-function-tests")
        highest = payload["trust_report"]["highest_risk_functions"][0]
        self.assertEqual(highest["function"], "execute")
        self.assertEqual(highest["risk_level"], "high")
        self.assertIn("migration/destructive data change", highest["risk_reasons"])

    def test_monolith_report_flags_many_assertions(self) -> None:
        output = self.run_script("monolith-test-report", "--format", "markdown").stdout
        self.assertIn("test_subtract_monolith", output)
        self.assertIn("8 assertions", output)

    def test_reference_index_maps_function_names_to_tests(self) -> None:
        test_path = self.repo / "tests" / "test_app.py"
        index = build_test_reference_index({test_path: "assert add(1, 2) == 3"})
        function = FunctionInfo("add", "add", self.repo / "src" / "app.py", 1, 2)
        self.assertEqual(find_test_references(function, index), [test_path])

    def test_coverage_status_uses_basename_fallback(self) -> None:
        function = FunctionInfo("add", "add", self.repo / "src" / "app.py", 1, 2)
        coverage = CoverageIndex({}, {"app.py": {1: 1, 2: 0}})
        self.assertEqual(coverage_status_for(function, coverage), ("partial", 1, 2))

    def test_metadata_has_no_placeholder_urls(self) -> None:
        plugin_text = (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        root_text = (PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8")
        self.assertNotIn("example.com", plugin_text + root_text)

    def test_front_door_skill_requires_complete_triage_sections(self) -> None:
        skill_text = (PLUGIN_ROOT / "skills" / "using-test-engineering" / "SKILL.md").read_text(encoding="utf-8")
        for term in REQUIRED_SKILL_TERMS:
            self.assertIn(term, skill_text)
        self.assertIn("If a section has no findings", skill_text)
        self.assertIn("Do not overstate heuristic findings", skill_text)


def by_file(items: list[dict], file_name: str) -> dict:
    return next(item for item in items if item["file"] == file_name)


def by_case(test_file: dict, case_name: str) -> dict:
    return next(item for item in test_file["cases"] if item["name"] == case_name)


def clean(text: str) -> str:
    return textwrap.dedent(text).strip() + "\n"


REQUIRED_HEADINGS = [
    "## Trust Verdict",
    "## Covered",
    "## Missing",
    "## Redundant",
    "## Low Signal",
    "## Placeholder",
    "## Improvable",
    "## Needs To Create",
    "## Monolith Candidates",
    "## Function Grades",
]

REQUIRED_SKILL_TERMS = [
    "`orientation_brief`",
    "`trust_verdict`",
    "`covered`",
    "`missing`",
    "`redundant`",
    "`low_signal`",
    "`placeholder`",
    "`improvable`",
    "`needs_to_create`",
    "`monolith_candidates`",
    "`function_grades`",
    "`smallest_next_action_plan`",
]

PYTHON_SOURCE = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def _normalise(value):
    return str(value).strip().lower()

def untested(value):
    if value:
        return "yes"
    return "no"
"""

PYTEST_SOURCE = """
from src.app import add, subtract

def test_add():
    assert add(1, 2) == 3

def test_subtract_monolith():
    assert subtract(3, 2) == 1
    assert subtract(5, 2) == 3
    assert subtract(8, 2) == 6
    assert subtract(13, 3) == 10
    assert subtract(21, 8) == 13
    assert subtract(34, 13) == 21
    assert subtract(55, 21) == 34
    assert subtract(89, 34) == 55
"""

NESTED_HELPER_TEST = """
from src.app import add

def test_outer():
    def test_inner_helper():
        assert add(1, 2) == 3
    assert add(2, 2) == 4
"""

PYTEST_PARAMETRIZED = """
import pytest
from src.app import add

@pytest.fixture
def base_value():
    return 1

@pytest.mark.parametrize("left,right,total", [(1, 2, 3)])
def test_add_matrix(base_value, left, right, total):
    assert add(left, right) == total
"""

UNITTEST_SOURCE = """
import unittest
from src.app import add

class CalculatorTests(unittest.TestCase):
    def setUp(self):
        self.left = 1

    def helper(self):
        return self.left

    def test_add(self):
        self.assertEqual(add(self.helper(), 2), 3)
"""

FRAMEWORK_ADAPTER_TEST = """
from src.app import add

class FeatureTests(FrameworkTestCase):
    def setUp(self):
        self.left = 1

    def test_framework_workflow(self):
        assert add(self.left, 2) == 3
"""

BEHAVIOUR_TEST = """
from unittest.mock import patch
import pytest
from src.app import add

def test_error_boundary_and_external_call():
    with patch("client.api.call") as mock_call:
        with pytest.raises(ValueError):
            raise ValueError("boom")
        assert add(0, 1) == 1
        assert record.status == "saved"
        assert permission_allowed is True
        assert mock_call.called is False
"""

MOCK_HEAVY_TEST = """
from unittest.mock import MagicMock, patch

def test_mock_heavy_flow():
    with patch("client.first") as first, patch("client.second") as second:
        mocked = MagicMock()
        assert first.called is False
        assert second.called is False
        assert mocked is not None
"""

PLACEHOLDER_TEST = """
class TestBackupLog:
    pass
"""

JS_CONSTANTS = """
export const API_BASE = "/api";
export const SETTINGS = { retries: 3 };
export const buildUrl = (path) => `${API_BASE}/${path}`;
"""

HIGH_RISK_PATCH = """
def execute():
    db.delete("Singles", {"field": "legacy"})
"""

LOW_RISK_HELPER = """
def _format_label(value):
    return str(value)
"""

PUBLIC_SCRIPT = """
def main(argv=None):
    return 0 if argv is None else len(argv)
"""

REPORT_ENDPOINT = """
def query_report(filters=None):
    return [{"filters": filters or {}}]
"""

SCHEDULER_HOOK = """
def hourly():
    return "queued"
"""

DOCTYPE_METHOD = """
def validate(doc):
    return doc
"""

IGNORE_CONFIG = """
{
  "generated_path_contains": ["generated/"]
}
"""

GENERATED_TEST = """
def test_generated_noise():
    assert False
"""

JS_SOURCE = """
export function add(left, right) {
  return left + right;
}
"""

JEST_TEST = """
import { add } from "../src/math";

test("adds numbers", () => {
  expect(add(1, 2)).toBe(3);
});
"""

TS_SOURCE = """
export const multiply = (left: number, right: number) => left * right;
"""

VITEST_TEST = """
import { test, expect, vi } from "vitest";
import { multiply } from "../src/maths";

test("multiplies numbers", () => {
  expect(multiply(2, 3)).toBe(6);
  vi.fn();
});
"""

COVERAGE_XML = """
<coverage>
  <packages>
    <package name="src">
      <classes>
        <class name="app.py" filename="src/app.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


if __name__ == "__main__":
    unittest.main()
