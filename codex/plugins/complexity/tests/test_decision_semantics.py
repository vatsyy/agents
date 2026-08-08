"""Regression tests for scope-aware complexity decisions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts" / "complexity"
sys.path.insert(0, str(SCRIPT_ROOT))

from analysis import AnalysisRequest, analyse
from analysis_output import render
from ranking import DecisionScope, classify_path_scope
from repo_triage import collect_integrated_report, parse_args, report_to_json

RUNTIME_LOOP = """
def read_each(items, frappe):
    for item in items:
        frappe.db.get_value("Item", item, "name")
"""

HIGH_CONTROL_FLOW = """
def classify(value):
    if value == 1:
        return 1
    if value == 2:
        return 2
    if value == 3:
        return 3
    if value == 4:
        return 4
    if value == 5:
        return 5
    if value == 6:
        return 6
    if value == 7:
        return 7
    if value == 8:
        return 8
    if value == 9:
        return 9
    if value == 10:
        return 10
    if value == 11:
        return 11
    if value == 12:
        return 12
    if value == 13:
        return 13
    if value == 14:
        return 14
    return 0
"""


class DecisionScopeTests(unittest.TestCase):
    def test_repository_scope_keeps_test_io_out_of_production_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def app():\n    return 1\n", encoding="utf-8"
            )
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text(
                RUNTIME_LOOP, encoding="utf-8"
            )

            canonical = analyse(AnalysisRequest(target=root))
            legacy = collect_integrated_report(
                root, parse_args([str(root), "--format", "json"])
            )
            legacy_payload = report_to_json(legacy)

        self.assertEqual(canonical.status, "complete")
        self.assertTrue(any(item.path == "tests/test_app.py" for item in canonical.findings))
        self.assertEqual(canonical.verdict, {"overall": "no immediate refactor"})
        self.assertEqual(canonical.decision_fields["performance"]["material_hotspots"], 0)
        self.assertEqual(
            canonical.decision_fields["performance"]["runtime_flagged_functions"], 0
        )
        self.assertEqual(canonical.top_files[0].path, "app.py")
        self.assertEqual(legacy_payload["analysis"]["verdict"], canonical.verdict)
        self.assertEqual(
            legacy_payload["decision_fields"]["performance"],
            canonical.decision_fields["performance"],
        )
        self.assertIn(
            "no high-confidence static runtime lead", legacy_payload["verdict"]["runtime"]
        )

    def test_explicitly_targeted_test_file_remains_material_and_ranked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "tests" / "test_app.py"
            target.parent.mkdir()
            target.write_text(RUNTIME_LOOP, encoding="utf-8")

            outcome = analyse(AnalysisRequest(target=target))

        self.assertEqual(outcome.target_kind, "file")
        self.assertEqual(outcome.verdict, {"overall": "review ranked findings"})
        self.assertEqual(outcome.decision_fields["performance"]["material_hotspots"], 1)
        self.assertEqual(
            outcome.decision_fields["performance"]["runtime_flagged_functions"], 1
        )
        self.assertEqual(
            outcome.decision_fields["performance"]["top_hotspot"]["path"], "test_app.py"
        )
        self.assertEqual(outcome.top_functions[0].path, "test_app.py")

    def test_explicitly_targeted_migration_file_remains_material_and_ranked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "patches" / "001_backfill.py"
            target.parent.mkdir()
            target.write_text(RUNTIME_LOOP, encoding="utf-8")

            outcome = analyse(AnalysisRequest(target=target))

        self.assertEqual(outcome.target_kind, "file")
        self.assertEqual(outcome.verdict, {"overall": "review ranked findings"})
        self.assertEqual(outcome.decision_fields["performance"]["material_hotspots"], 1)
        self.assertEqual(
            outcome.decision_fields["performance"]["top_hotspot"]["path"],
            "001_backfill.py",
        )

    def test_production_runtime_hotspot_still_drives_a_refactor_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app.py"
            target.write_text(RUNTIME_LOOP, encoding="utf-8")

            outcome = analyse(AnalysisRequest(target=target))

        self.assertEqual(outcome.verdict, {"overall": "review ranked findings"})
        self.assertEqual(outcome.decision_fields["performance"]["material_hotspots"], 1)
        self.assertEqual(
            outcome.decision_fields["performance"]["top_hotspot"]["path"], "app.py"
        )
        self.assertEqual(outcome.top_files[0].path, "app.py")

    def test_high_control_flow_is_complexity_evidence_not_a_performance_hotspot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "classifier.py"
            target.write_text(HIGH_CONTROL_FLOW, encoding="utf-8")

            outcome = analyse(AnalysisRequest(target=target))

        self.assertTrue(
            any(item.kind == "high-function-complexity" for item in outcome.findings)
        )
        self.assertEqual(
            outcome.decision_fields["performance"]["material_hotspots"], 0
        )
        self.assertIsNone(outcome.decision_fields["performance"]["top_hotspot"])

    def test_zero_findings_limit_cannot_change_scope_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app.py"
            target.write_text(RUNTIME_LOOP, encoding="utf-8")

            full = analyse(AnalysisRequest(target=target))
            zero = analyse(AnalysisRequest(target=target, max_findings=0))
            zero_document = json.loads(render(zero, "json"))
            legacy = collect_integrated_report(
                target,
                parse_args([str(target), "--format", "json", "--max-findings", "0"]),
            )
            legacy_payload = report_to_json(legacy)

        self.assertTrue(full.findings)
        self.assertEqual(zero.findings, full.findings)
        self.assertEqual(zero.verdict, full.verdict)
        self.assertEqual(zero.decision_fields, full.decision_fields)
        self.assertEqual(zero.top_files, full.top_files)
        self.assertEqual(zero_document["findings"], [])
        self.assertGreater(zero_document["counts"]["findings"]["total"], 0)
        self.assertEqual(
            legacy_payload["decision_fields"]["complexity"],
            full.decision_fields["complexity"],
        )
        self.assertEqual(
            legacy_payload["decision_fields"]["performance"],
            full.decision_fields["performance"],
        )
        self.assertEqual(legacy_payload["analysis"]["verdict"], full.verdict)
        self.assertEqual(legacy_payload["heuristic_hotspots"], [])

    def test_scope_classification_is_shared_and_explicit_targets_override_it(self) -> None:
        repository_scope = DecisionScope.for_target_kind("directory")
        targeted_scope = DecisionScope.for_target_kind("file")

        self.assertEqual(classify_path_scope("tests/test_app.py"), "test")
        self.assertEqual(classify_path_scope("patches/001_backfill.py"), "migration")
        self.assertFalse(repository_scope.includes("tests/test_app.py"))
        self.assertFalse(repository_scope.includes("patches/001_backfill.py"))
        self.assertTrue(targeted_scope.includes("tests/test_app.py"))
        self.assertTrue(targeted_scope.includes("patches/001_backfill.py"))


if __name__ == "__main__":
    unittest.main()
