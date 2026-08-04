from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from test_engineering.analysis import analyse_repo  # noqa: E402
from test_engineering.analysis_contract import command_context  # noqa: E402
from test_engineering.coverage import coverage_from_tree, coverage_status_for  # noqa: E402
from test_engineering.files import inventory_project  # noqa: E402
from test_engineering.frameworks import detect_frameworks  # noqa: E402
from test_engineering.models import FunctionInfo  # noqa: E402


class AnalysisContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo with spaces"
        self.repo.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_command(self, name: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_command_with_format(name, "json", *extra)

    def run_command_with_format(self, name: str, output_format: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPTS / name), str(self.repo), *extra, "--format", output_format],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_complete_outcome_has_stable_legacy_shape_and_contract(self) -> None:
        self.write("src/app.py", "def add(left, right):\n    return left + right\n")
        self.write("tests/test_app.py", "from src.app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")

        result = self.run_command("grade-function-tests")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["schema_version"], "1.0")
        for legacy_key in ("repo", "framework_hints", "test_files", "function_grades", "taxonomy", "trust_report"):
            self.assertIn(legacy_key, payload)
        self.assertEqual(payload["coverage"]["state"], "not-requested")
        self.assertIsNone(payload["coverage"]["line_count"])
        self.assertIn("'", payload["reproduction"]["json"])

    def test_malformed_python_is_partial_and_gates_trust(self) -> None:
        self.write("src/broken.py", "def broken(:\n")
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")

        result = self.run_command("grade-function-tests")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["parsing"]["failed_file_count"], 1)
        self.assertEqual(payload["trust_verdict"]["mocked_unit_trust"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["behavioural_coverage"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["refactor_readiness"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["evidence_type"], "diagnostic")
        for question in payload["trust_report"]["questions"]:
            self.assertEqual(question["answer"], "unavailable: analysis status is partial")
        self.assertIn("python-parse-failed", {item["code"] for item in payload["diagnostics"]})

    def test_missing_and_malformed_coverage_are_not_zero_coverage(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        missing = self.repo / "missing.xml"
        malformed = self.write("coverage.xml", "<coverage>")

        missing_payload = json.loads(self.run_command("function-test-map", "--coverage-xml", str(missing)).stdout)
        malformed_payload = json.loads(self.run_command("function-test-map", "--coverage-xml", str(malformed)).stdout)

        self.assertEqual(missing_payload["coverage"]["state"], "missing")
        self.assertIsNone(missing_payload["coverage"]["line_count"])
        self.assertEqual(missing_payload["orientation_brief"]["summary"][-1], "Coverage XML unavailable: file is missing.")
        self.assertEqual(malformed_payload["coverage"]["state"], "malformed")
        self.assertIsNone(malformed_payload["coverage"]["line_count"])
        self.assertEqual(malformed_payload["orientation_brief"]["summary"][-1], "Coverage XML unavailable: file is malformed.")

    def test_empty_and_unreadable_coverage_are_not_execution_evidence(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        empty = self.write("empty-coverage.xml", "<coverage></coverage>")
        unreadable = self.write("unreadable-coverage.xml", "<coverage></coverage>")
        unreadable.chmod(0)
        try:
            empty_payload = analyse_repo(self.repo, empty)
            unreadable_payload = analyse_repo(self.repo, unreadable)
        finally:
            unreadable.chmod(0o600)

        self.assertEqual(empty_payload["coverage"]["state"], "empty")
        self.assertEqual(
            empty_payload["orientation_brief"]["summary"][-1],
            "Coverage XML unavailable: file contained no usable line execution data.",
        )
        self.assertEqual(unreadable_payload["coverage"]["state"], "unreadable")
        self.assertEqual(
            unreadable_payload["orientation_brief"]["summary"][-1],
            "Coverage XML unavailable: file could not be read.",
        )

    def test_mocked_unreadable_coverage_is_deterministic(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        coverage = self.write("coverage.xml", "<coverage></coverage>")

        with patch("test_engineering.coverage.ET.parse", side_effect=PermissionError("permission denied")):
            payload = analyse_repo(self.repo, coverage)

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["coverage"]["state"], "unreadable")
        self.assertIsNone(payload["coverage"]["line_count"])
        self.assertEqual(
            payload["orientation_brief"]["summary"][-1],
            "Coverage XML unavailable: file could not be read.",
        )

    def test_empty_unsupported_and_mixed_scopes_are_explicit(self) -> None:
        empty = analyse_repo(self.repo)
        self.assertEqual(empty["status"], "unsupported")

        self.write("src/main.go", "package main\n")
        unsupported = analyse_repo(self.repo)
        self.assertEqual(unsupported["status"], "unsupported")
        self.assertEqual(unsupported["inventory"]["unsupported_code_file_count"], 1)

        self.write("src/app.py", "def ready():\n    return True\n")
        mixed = analyse_repo(self.repo)
        self.assertEqual(mixed["status"], "partial")
        self.assertIn("unsupported-language-files", {item["code"] for item in mixed["diagnostics"]})

    def test_unsupported_outcome_gates_every_nested_trust_claim(self) -> None:
        payload = analyse_repo(self.repo)

        self.assertEqual(payload["status"], "unsupported")
        self.assertEqual(payload["trust_verdict"]["mocked_unit_trust"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["behavioural_coverage"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["refactor_readiness"], "unavailable")
        self.assertEqual(payload["trust_report"]["refactor_readiness"], "unavailable")
        for question in payload["trust_report"]["questions"]:
            self.assertEqual(question["answer"], "unavailable: analysis status is unsupported")
            self.assertEqual(question["confidence"], "low")
            self.assertEqual(question["evidence_type"], "diagnostic")

    def test_unsupported_markdown_gates_all_empty_projection_prose(self) -> None:
        result = self.run_command_with_format("grade-function-tests", "markdown")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Analysis status: **unsupported**", result.stdout)
        self.assertIn("Repository-wide verdict unavailable", result.stdout)
        self.assertNotIn("No immediate action candidates found", result.stdout)
        self.assertNotIn("No supported source functions found", result.stdout)
        self.assertNotIn("None found by deterministic scan", result.stdout)
        self.assertNotIn("No monolithic test candidates found", result.stdout)
        self.assertNotIn("Highest-risk functions: none found", result.stdout)

    def test_invalid_config_is_partial_and_reported(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        self.write(".test-engineering.json", "{not json")

        payload = analyse_repo(self.repo)

        self.assertEqual(payload["status"], "partial")
        self.assertIn("config-invalid", {item["code"] for item in payload["diagnostics"]})

    def test_javascript_assertions_are_counted_per_case(self) -> None:
        self.write(
            "tests/example.test.js",
            "test('asserted', () => { expect(1).toBe(1); });\n"
            "test('smoke', () => { runThing(); });\n",
        )

        payload = analyse_repo(self.repo)
        cases = payload["test_files"][0]["cases"]

        self.assertEqual([case["assertions"] for case in cases], [1, 0])

    def test_command_context_records_explicit_render_denominators(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        report = command_context(analyse_repo(self.repo), "test-inventory", self.repo, None)

        self.assertEqual(report["truncation"]["function_grades"]["total"], 1)
        self.assertEqual(report["truncation"]["function_grades"]["omitted"], 0)

    def test_name_only_match_is_a_heuristic_not_credible_coverage(self) -> None:
        self.write("src/app.py", "def charge(value):\n    return value\n")
        self.write("tests/test_app.py", "def test_other():\n    label = 'charge'\n    assert label\n")

        grade = analyse_repo(self.repo)["function_grades"][0]

        self.assertEqual(grade["grade"], "E")
        self.assertEqual(grade["mapping_method"], "function_name_token")
        self.assertEqual(grade["evidence_type"], "heuristic")
        self.assertEqual(grade["evidence_labels"], ["name/static heuristic"])
        self.assertEqual(grade["assertion_evidence"], 0)

    def test_duplicate_coverage_basenames_do_not_cross_map(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                "<coverage><class filename='one/app.py'><lines><line number='1' hits='1'/></lines></class>"
                "<class filename='two/app.py'><lines><line number='1' hits='0'/></lines></class></coverage>"
            )
        )
        coverage = coverage_from_tree(tree, self.repo)
        function = FunctionInfo("ready", "ready", self.repo / "other" / "app.py", 1, 1)

        self.assertNotIn("app.py", coverage.by_name)
        self.assertEqual(coverage_status_for(function, coverage), ("not-in-report", None, None))

    def test_duplicate_coverage_entries_merge_lines_conservatively(self) -> None:
        self.write("src/app.py", "def ready(value):\n    if value:\n        return True\n")
        coverage = self.write(
            "coverage.xml",
            (
                "<coverage>"
                "<class filename='src/app.py'><lines>"
                "<line number='1' hits='0'/><line number='2' hits='1'/>"
                "</lines></class>"
                "<class filename='src/app.py'><lines>"
                "<line number='1' hits='3'/><line number='3' hits='1'/>"
                "</lines></class>"
                "</coverage>"
            ),
        )
        payload = analyse_repo(self.repo, coverage)
        grade = payload["function_grades"][0]

        self.assertEqual(payload["coverage"]["line_count"], 3)
        self.assertEqual(grade["coverage_status"], "partial")
        self.assertEqual(grade["covered_lines"], 2)
        self.assertEqual(grade["executable_lines"], 3)

    def test_inventory_limit_is_deterministic_and_explicit(self) -> None:
        for index in range(3):
            self.write(f"src/{index}.py", "def ready():\n    return True\n")

        inventory = inventory_project(self.repo, max_files=2)

        self.assertTrue(inventory.truncated)
        self.assertEqual(inventory.discovered_file_count, 2)
        self.assertEqual([path.name for path in inventory.files], ["0.py", "1.py"])

    def test_unreadable_directory_makes_repository_analysis_partial(self) -> None:
        self.write("src/visible.py", "def visible():\n    return True\n")
        blocked = self.repo / "blocked"
        blocked.mkdir()
        (blocked / "hidden.py").write_text("def hidden():\n    return True\n", encoding="utf-8")
        blocked.chmod(0)
        try:
            payload = analyse_repo(self.repo)
        finally:
            blocked.chmod(0o700)

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["inventory"]["traversal_error_count"], 1)
        self.assertEqual(payload["source_file_count"], 1)
        self.assertIn("inventory-traversal-failed", {item["code"] for item in payload["diagnostics"]})

    def test_read_failed_file_is_attempted_but_not_analysed_or_parse_successful(self) -> None:
        self.write("src/visible.py", "def visible():\n    return True\n")
        unreadable = self.write("src/unreadable.py", "def hidden():\n    return True\n")
        unreadable.chmod(0)
        try:
            payload = analyse_repo(self.repo)
        finally:
            unreadable.chmod(0o600)

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["inventory"]["supported_candidate_count"], 2)
        self.assertEqual(payload["inventory"]["analysed_file_count"], 1)
        self.assertEqual(payload["source_file_count"], 1)
        self.assertEqual(payload["parsing"]["attempted_file_count"], 2)
        self.assertEqual(payload["parsing"]["succeeded_file_count"], 1)
        self.assertEqual(payload["parsing"]["failed_file_count"], 1)
        self.assertEqual(payload["parsing"]["failed_files"], ["src/unreadable.py"])
        self.assertIn("source-unreadable", {item["code"] for item in payload["diagnostics"]})

    def test_mocked_traversal_failure_is_deterministic_and_partial(self) -> None:
        self.write("visible.py", "def visible():\n    return True\n")

        def failing_walk(root: Path, onerror):
            onerror(PermissionError(13, "Permission denied", str(Path(root) / "blocked")))
            yield str(root), [], ["visible.py"]

        with patch("test_engineering.files.os.walk", side_effect=failing_walk):
            payload = analyse_repo(self.repo)

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["inventory"]["traversal_error_count"], 1)
        self.assertEqual(payload["inventory"]["traversal_errors"][0]["path"], "blocked")
        self.assertIn("inventory-traversal-failed", {item["code"] for item in payload["diagnostics"]})

    def test_mocked_read_failure_is_deterministic_and_updates_adapter_runtime(self) -> None:
        visible = self.write("src/visible.py", "def visible():\n    return True\n")
        unreadable = self.write("src/unreadable.py", "def hidden():\n    return True\n")
        original_read_text = Path.read_text

        def selective_read(path: Path, *args, **kwargs):
            if path.name == unreadable.name:
                raise PermissionError(13, "Permission denied", str(path))
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=selective_read):
            payload = analyse_repo(self.repo)

        python_runtime = next(item["runtime"] for item in payload["adapters"] if item["name"] == "python-ast")
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["inventory"]["analysed_file_count"], 1)
        self.assertEqual(payload["parsing"]["failed_files"], ["src/unreadable.py"])
        self.assertEqual(python_runtime["attempted_source_files"], 2)
        self.assertEqual(python_runtime["analysed_source_files"], 1)
        self.assertEqual(python_runtime["failed_files"], 1)
        self.assertEqual(python_runtime["state"], "partial")
        self.assertTrue(visible.exists())

    def test_json_input_error_has_machine_readable_shape(self) -> None:
        missing = self.repo / "does not exist"
        result = subprocess.run(
            [str(SCRIPTS / "test-inventory"), str(missing), "--format", "json"],
            text=True,
            capture_output=True,
            check=False,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["diagnostics"][0]["code"], "input-error")

    def test_scope_named_tests_does_not_turn_all_source_into_tests(self) -> None:
        nested = self.repo / "tests"
        nested.mkdir()
        (nested / "app.py").write_text("def ready():\n    return True\n", encoding="utf-8")

        payload = analyse_repo(nested)

        self.assertEqual(payload["source_file_count"], 1)
        self.assertEqual(payload["test_file_count"], 0)

    def test_loaded_coverage_missing_target_is_unavailable_not_zero(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring("<coverage><class filename='src/other.py'><lines><line number='1' hits='1'/></lines></class></coverage>")
        )
        coverage = coverage_from_tree(tree, self.repo)
        function = FunctionInfo("ready", "ready", self.repo / "src" / "app.py", 1, 1)

        self.assertEqual(coverage_status_for(function, coverage), ("not-in-report", None, None))

    def test_unrequested_function_coverage_has_no_numeric_denominator(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        grade = analyse_repo(self.repo)["function_grades"][0]

        self.assertEqual(grade["coverage_status"], "unknown")
        self.assertIsNone(grade["covered_lines"])
        self.assertIsNone(grade["executable_lines"])

    def test_nonnumeric_coverage_hits_are_malformed(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        coverage = self.write(
            "coverage.xml",
            "<coverage><class filename='src/app.py'><lines><line number='1' hits='many'/></lines></class></coverage>",
        )

        result = self.run_command("function-test-map", "--coverage-xml", str(coverage))
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["coverage"]["state"], "malformed")
        self.assertIsNone(payload["coverage"]["line_count"])

    def test_loaded_coverage_is_the_only_state_described_as_execution_evidence(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        coverage = self.write(
            "coverage.xml",
            "<coverage><class filename='src/app.py'><lines><line number='1' hits='1'/></lines></class></coverage>",
        )

        payload = analyse_repo(self.repo, coverage)

        self.assertEqual(payload["coverage"]["state"], "loaded")
        self.assertEqual(payload["orientation_brief"]["summary"][-1], "Coverage XML loaded as line execution evidence.")

    def test_partial_run_scopes_strong_function_evidence_and_every_verdict_projection(self) -> None:
        self.write("src/app.py", "def add(left, right):\n    return left + right\n")
        self.write(
            "tests/test_app.py",
            "from src.app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        )
        missing_coverage = self.repo / "missing-coverage.xml"

        json_result = self.run_command("grade-function-tests", "--coverage-xml", str(missing_coverage))
        markdown_result = self.run_command_with_format(
            "grade-function-tests",
            "markdown",
            "--coverage-xml",
            str(missing_coverage),
        )
        payload = json.loads(json_result.stdout)
        grade = payload["function_grades"][0]
        covered = payload["taxonomy"]["covered"][0]

        self.assertEqual(json_result.returncode, 1)
        self.assertEqual(markdown_result.returncode, 1)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["assessment"]["evidence_scope"], "successfully-analysed-files-only")
        self.assertFalse(payload["assessment"]["repository_verdict_available"])
        self.assertEqual(
            payload["assessment"]["projections"],
            {
                "action_plan": "scoped-evidence-only",
                "empty_sections": "unavailable",
                "function_grades": "scoped-evidence-only",
                "orientation_brief": "scoped-evidence-only",
                "taxonomy": "scoped-evidence-only",
                "trust": "unavailable",
            },
        )
        self.assertEqual(grade["observed_grade"], "B")
        self.assertEqual(grade["grade"], "unavailable")
        self.assertEqual(grade["assessment_status"], "scoped-evidence-only")
        self.assertTrue(grade["test_refs"])
        self.assertEqual(covered["observed_grade"], "B")
        self.assertEqual(covered["grade"], "unavailable")
        self.assertEqual(payload["taxonomy"]["assessment_status"], "scoped-evidence-only")
        self.assertEqual(payload["trust_report"]["grade_counts"], {})
        self.assertEqual(payload["trust_report"]["grade_counts_status"], "unavailable")
        self.assertEqual(payload["trust_report"]["observed_grade_counts"], {"B": 1})
        self.assertEqual(payload["trust_report"]["confidence_counts"], {})
        self.assertEqual(payload["trust_report"]["confidence_counts_status"], "unavailable")
        self.assertEqual(payload["trust_report"]["observed_confidence_counts"], {"low": 1})
        self.assertEqual(payload["trust_report"]["risk_counts"], {})
        self.assertEqual(payload["trust_report"]["risk_counts_status"], "unavailable")
        self.assertEqual(payload["trust_report"]["coverage_gap_summary"]["assessment_status"], "unavailable")
        self.assertEqual(payload["trust_verdict"]["coverage_gap_summary"]["assessment_status"], "unavailable")
        self.assertNotIn("No immediate action candidates found", markdown_result.stdout)
        self.assertNotIn("None found by deterministic scan", markdown_result.stdout)
        self.assertNotIn("Grade counts: B=1", markdown_result.stdout)
        self.assertNotIn("Coverage gap split: 0 probably untested", markdown_result.stdout)
        self.assertNotIn("Mock-heavy examples: none found", markdown_result.stdout)
        self.assertNotIn("Highest-risk functions: none found", markdown_result.stdout)
        self.assertIn("Observed grade counts (scoped): B=1", markdown_result.stdout)
        self.assertIn("Scoped evidence only", markdown_result.stdout)
        self.assertIn("Repository-wide verdict unavailable", markdown_result.stdout)

    def test_partial_run_gates_orientation_verdicts_and_labels_observations(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        self.write("tests/test_app.py", "from src.app import ready\n\ndef test_ready():\n    assert ready()\n")
        missing_coverage = self.repo / "missing-coverage.xml"

        payload = analyse_repo(self.repo, missing_coverage)
        markdown = self.run_command_with_format(
            "grade-function-tests",
            "markdown",
            "--coverage-xml",
            str(missing_coverage),
        ).stdout
        orientation = payload["orientation_brief"]

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["assessment"]["projections"]["orientation_brief"], "scoped-evidence-only")
        self.assertEqual(orientation["assessment_status"], "scoped-evidence-only")
        self.assertFalse(orientation["repository_verdict_available"])
        self.assertEqual(orientation["high_signal_files"], [])
        self.assertTrue(orientation["observed_high_signal_files"])
        self.assertEqual(orientation["fixture_shape"]["assessment_status"], "unavailable")
        self.assertIsNone(orientation["fixture_shape"]["over_mocked_tests"])
        self.assertEqual(orientation["observed_fixture_shape"]["over_mocked_tests"], 0)
        self.assertIn("Orientation verdict unavailable", markdown)
        self.assertNotIn("| High-signal file |", markdown)

    def test_partial_trust_report_explicitly_scopes_retained_findings(self) -> None:
        self.write("cli/delete.py", "def main():\n    return delete_records()\n")
        self.write(
            "tests/test_mocked.py",
            "from unittest.mock import MagicMock, patch\n\n"
            "def test_mocked():\n"
            "    with patch('client.first') as first, patch('client.second') as second:\n"
            "        mocked = MagicMock()\n"
            "        assert mocked is not None\n",
        )
        missing_coverage = self.repo / "missing-coverage.xml"

        result = self.run_command_with_format(
            "grade-function-tests",
            "markdown",
            "--coverage-xml",
            str(missing_coverage),
        )
        trust_report = result.stdout.split("## Trust Report", 1)[1].split("## Action Plan", 1)[0]

        self.assertEqual(result.returncode, 1)
        self.assertIn("Scoped evidence only: results below cover successfully analysed files.", trust_report)
        self.assertIn("Mock-heavy examples:", trust_report)
        self.assertIn("Highest-risk functions:", trust_report)

    def test_invalid_config_field_schema_is_partial(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        self.write(".test-engineering.json", '{"ignore_path_contains": "src"}')

        payload = analyse_repo(self.repo)

        self.assertEqual(payload["status"], "partial")
        self.assertIn("config-invalid-field", {item["code"] for item in payload["diagnostics"]})

    def test_assertions_from_another_case_do_not_inflate_call_grade(self) -> None:
        self.write("src/app.py", "def charge(value):\n    return value\n")
        self.write(
            "tests/test_app.py",
            "from src.app import charge\n\n"
            "def test_charge_smoke():\n    charge(1)\n\n"
            "def test_unrelated_assertion():\n    assert True\n",
        )

        grade = analyse_repo(self.repo)["function_grades"][0]

        self.assertEqual(grade["grade"], "C")
        self.assertEqual(grade["assertion_evidence"], 0)
        self.assertEqual(grade["mapping_method"], "static_call_reference")

    def test_framework_detection_uses_supplied_text_cache(self) -> None:
        package = self.write("package.json", '{"devDependencies": {"vitest": "1"}}')
        test_file = self.write("tests/app.test.js", "import { test } from 'vitest';\ntest('ok', () => {});\n")
        texts = {package: package.read_text(), test_file: test_file.read_text()}

        with patch("test_engineering.frameworks.read_text", side_effect=AssertionError("unexpected reread")):
            hints = detect_frameworks(self.repo, [test_file], [package, test_file], texts)

        self.assertIn("vitest/javascript", hints)

    def test_canonical_analysis_parses_each_python_file_once(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        self.write("tests/test_app.py", "from src.app import ready\n\ndef test_ready():\n    assert ready()\n")

        with patch("ast.parse", wraps=ast.parse) as parse:
            payload = analyse_repo(self.repo)

        self.assertEqual(payload["status"], "complete")
        self.assertEqual(parse.call_count, 2)

    def test_adapter_capabilities_include_actual_runtime_dispatch_state(self) -> None:
        self.write("src/app.py", "def ready():\n    return True\n")
        self.write("tests/test_app.py", "from src.app import ready\n\ndef test_ready():\n    assert ready()\n")
        self.write("src/math.ts", "export const add = (left: number, right: number) => left + right;\n")
        self.write("tests/math.test.ts", "test('adds', () => { expect(add(1, 2)).toBe(3); });\n")

        payload = analyse_repo(self.repo)
        adapters = {item["name"]: item for item in payload["adapters"]}

        self.assertEqual(
            adapters["python-ast"]["runtime"],
            {
                "analysed_source_files": 1,
                "analysed_test_files": 1,
                "attempted_source_files": 1,
                "attempted_test_files": 1,
                "failed_files": 0,
                "state": "complete",
            },
        )
        self.assertEqual(adapters["javascript-static"]["runtime"]["analysed_source_files"], 1)
        self.assertEqual(adapters["javascript-static"]["runtime"]["analysed_test_files"], 1)
        self.assertEqual(adapters["javascript-static"]["runtime"]["state"], "complete")
        self.assertEqual(adapters["coverage-xml"]["runtime"], {"state": "not-requested"})


if __name__ == "__main__":
    unittest.main()
