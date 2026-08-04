from __future__ import annotations

import json
import io
import os
import subprocess
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts" / "complexity"
sys.path.insert(0, str(SCRIPT_ROOT))

import analysis  # noqa: E402
from analysis import AnalysisInputError, AnalysisRequest, analyse  # noqa: E402
from analysis_output import (  # noqa: E402
    canonical_analysis_payload,
    render,
    render_with_output,
)
from function_complexity.lizard_adapter import parse_lizard_csv  # noqa: E402
from function_complexity.cli import analyse_file  # noqa: E402
from function_complexity.cli import main as measure_complexity_main  # noqa: E402
from function_complexity.python_ast import analyse_python  # noqa: E402
from repo_triage import (  # noqa: E402
    collect_integrated_report,
    parse_args,
    render_markdown_report,
    report_to_json,
)
from scan_hotspots import collect_report, limit_findings  # noqa: E402


class AnalysisContractTests(unittest.TestCase):
    def test_empty_directory_is_unsupported_without_a_verdict(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            outcome = analyse(AnalysisRequest(target=Path(tmp)))

        self.assertEqual(outcome.status, "unsupported")
        self.assertIsNone(outcome.verdict)
        self.assertEqual(outcome.coverage.discovered_files, 0)
        self.assertEqual(outcome.coverage.eligible_files, 0)

    def test_shell_only_directory_is_unsupported_without_a_verdict(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plugin.zsh").write_text("echo hello\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "unsupported")
        self.assertIsNone(outcome.verdict)
        self.assertEqual(outcome.coverage.unsupported_files, 1)

    def test_regular_python_file_is_analysed(self) -> None:

        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 1)
        self.assertEqual(len(outcome.metrics), 1)

    def test_mixed_supported_and_unsupported_scope_is_partial_with_supported_evidence(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            (root / "plugin.zsh").write_text("echo hello\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.unsupported_files, 1)
        self.assertEqual(
            outcome.verdict["overall"],
            "inconclusive; required analysis did not cover the full eligible scope",
        )

    def test_missing_lizard_is_partial_not_a_clean_verdict(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.js").write_text("function useful() { return 1; }\n", encoding="utf-8")
            with mock.patch.object(
                analysis,
                "analyse_many_with_lizard_cli",
                side_effect=SystemExit("lizard unavailable"),
            ):
                outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.metric_eligible_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 0)
        self.assertNotEqual(outcome.verdict["overall"], "no immediate refactor")

    def test_metrics_only_missing_lizard_is_partial(self) -> None:

        with temporary_source("function useful() { return 1; }", "ordinary.js") as path:
            with mock.patch.object(
                analysis,
                "analyse_many_with_lizard_cli",
                side_effect=SystemExit("lizard unavailable"),
            ):
                outcome = analyse(AnalysisRequest.for_compatibility(path, "metrics"))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.failed_files, 1)
        self.assertEqual(
            [(item.path, item.stage) for item in outcome.diagnostics],
            [(str(path.resolve()), "lizard")],
        )

    def test_later_lizard_chunk_failure_keeps_completed_chunk_coverage(self) -> None:
        import function_complexity.lizard_adapter as lizard_adapter  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(101):
                (root / f"source_{index:03}.rs").write_text(
                    "fn useful() {}\n", encoding="utf-8"
                )
            with (
                mock.patch.object(
                    lizard_adapter.shutil, "which", return_value="/usr/local/bin/lizard"
                ),
                mock.patch.object(
                    lizard_adapter,
                    "analyse_lizard_chunk",
                    side_effect=[[], SystemExit("later chunk failed")],
                ) as chunks,
            ):
                outcome = analyse(AnalysisRequest(target=root))

        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(chunks.call_count, 2)
        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.metric_analysed_files, 100)
        self.assertEqual(outcome.coverage.failed_files, 1)
        self.assertEqual(states["lizard"], "partial")

    def test_malformed_python_is_partial_with_coverage_and_diagnostic(self) -> None:

        with temporary_source("def broken(:\n", "broken.py") as path:
            outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.metric_eligible_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 0)
        self.assertEqual(outcome.coverage.failed_files, 1)
        self.assertTrue(any(item.stage == "python-ast" for item in outcome.diagnostics))

    def test_mixed_valid_and_malformed_python_keeps_valid_metric_evidence(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "valid.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.metric_analysed_files, 1)
        self.assertEqual(len(outcome.metrics), 1)
        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(states["python-ast"], "partial")

    def test_lizard_supported_rust_is_metric_eligible(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.rs").write_text("fn useful() {}\n", encoding="utf-8")
            with mock.patch.object(analysis, "analyse_many_with_lizard_cli", return_value=[]):
                outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.coverage.heuristic_eligible_files, 0)
        self.assertEqual(outcome.coverage.heuristic_analysed_files, 0)
        self.assertEqual(outcome.coverage.metric_eligible_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 1)
        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(states["text-heuristic"], "not-applicable")
        self.assertEqual(states["python-ast"], "not-applicable")
        self.assertEqual(states["lizard"], "complete")

    def test_standard_cjs_runs_every_applicable_lane(self) -> None:

        with temporary_source("function useful() {}", "ordinary.cjs") as path:
            with mock.patch.object(analysis, "analyse_many_with_lizard_cli", return_value=[]):
                outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.coverage.eligible_files, 1)
        self.assertEqual(outcome.coverage.heuristic_eligible_files, 1)
        self.assertEqual(outcome.coverage.heuristic_analysed_files, 1)
        self.assertEqual(outcome.coverage.metric_eligible_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 1)

    def test_lizard_capability_manifest_covers_current_reader_extensions(self) -> None:

        suffixes = {
            ".c", ".cc", ".cjs", ".cpp", ".cs", ".cxx", ".erl", ".es", ".escript",
            ".f", ".f03", ".f08", ".f70", ".f90", ".f95", ".for", ".fpp", ".ftn",
            ".gd", ".go", ".h", ".hpp", ".hrl", ".java", ".js", ".jsx", ".kt", ".kts",
            ".lua", ".m", ".mjs", ".mm", ".pck", ".php", ".pkb", ".pks", ".pl",
            ".plb", ".pls", ".pm", ".r", ".rb", ".rs", ".scala", ".sol", ".sql",
            ".st", ".swift", ".ts", ".tsx", ".ttcn", ".ttcnpp", ".vue", ".zig",
        }
        with mock.patch.object(analysis, "analyse_many_with_lizard_cli", return_value=[]):
            for suffix in sorted(suffixes):
                with self.subTest(suffix=suffix):
                    with temporary_source("", f"ordinary{suffix}") as path:
                        outcome = analyse(AnalysisRequest(target=path))
                    self.assertEqual(outcome.coverage.metric_eligible_files, 1)
                    self.assertEqual(outcome.coverage.metric_analysed_files, 1)

    def test_ttcn3_language_name_is_not_treated_as_a_file_extension(self) -> None:

        with temporary_source("", "ordinary.ttcn3") as path:
            with mock.patch.object(analysis, "analyse_many_with_lizard_cli", return_value=[]):
                outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "unsupported")
        self.assertEqual(outcome.coverage.metric_eligible_files, 0)

    def test_integrated_analysis_preserves_cross_file_wrapper_evidence(self) -> None:

        outcome = analyse(AnalysisRequest(target=GOLDEN_ROOT / "cross_file_wrapper"))

        self.assertTrue(any(item.kind == "wrapper-io-in-loop" for item in outcome.findings))

    def test_adapter_states_reflect_requested_scope_and_failures(self) -> None:

        with temporary_source("function useful() { return 1; }", "ordinary.js") as path:
            with mock.patch.object(
                analysis,
                "analyse_many_with_lizard_cli",
                side_effect=SystemExit("lizard unavailable"),
            ):
                outcome = analyse(AnalysisRequest(target=path))

        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(states["text-heuristic"], "complete")
        self.assertEqual(states["python-ast"], "not-applicable")
        self.assertEqual(states["lizard"], "unavailable")

    def test_machine_output_includes_status_and_full_coverage_ledger(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(render(analyse(AnalysisRequest(target=Path(tmp))), "json"))

        self.assertEqual(payload["status"], "unsupported")
        self.assertEqual(
            set(payload["coverage"]),
            {
                "discovered_files", "eligible_files", "analysed_files", "metric_eligible_files",
                "heuristic_eligible_files", "heuristic_analysed_files", "metric_analysed_files",
                "skipped_files", "unsupported_files", "failed_files",
                "per_language",
            },
        )

    def test_inventory_is_built_once_per_analysis_run(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            original_walk = analysis.os.walk
            with mock.patch.object(analysis.os, "walk", wraps=original_walk) as walk:
                analyse(AnalysisRequest(target=root))

        self.assertEqual(walk.call_count, 1)

    def test_empty_python_file_is_complete_even_without_functions(self) -> None:

        with temporary_source("", "empty.py") as path:
            outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.metric_analysed_files, 1)
        self.assertFalse(outcome.metrics)

    def test_unreadable_child_is_partial_with_a_diagnostic(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                outcome = analyse(AnalysisRequest(target=root, mode="quick"))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.failed_files, 1)
        self.assertTrue(any(item.stage == "heuristic" for item in outcome.diagnostics))
        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(states["text-heuristic"], "failed")

    def test_unreadable_named_target_is_an_input_error(self) -> None:

        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                with self.assertRaises(AnalysisInputError):
                    analyse(AnalysisRequest(target=path, mode="quick"))

    def test_directory_traversal_error_is_partial_with_a_diagnostic(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")

            def walk_with_error(target: Path, *, onerror):
                yield str(target), [], ["ordinary.py"]
                error = PermissionError("denied")
                error.filename = str(root / "locked")
                onerror(error)

            with mock.patch.object(analysis.os, "walk", side_effect=walk_with_error):
                outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.failed_files, 1)
        self.assertTrue(
            any(
                item.path == str(root / "locked") and item.stage == "inventory"
                for item in outcome.diagnostics
            )
        )

    def test_paths_with_spaces_are_analysed(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "space name.py"
            path.write_text("def useful():\n    return 1\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=path))

        self.assertEqual(outcome.status, "complete")

    def test_missing_target_is_an_input_error(self) -> None:

        with self.assertRaises(AnalysisInputError):
            analyse(AnalysisRequest(target=Path("/definitely/not/a/complexity-target")))

    def test_integrated_wrapper_returns_exit_two_for_missing_target(self) -> None:
        result = subprocess.run(
            [str(PLUGIN_ROOT / "scripts" / "complexity-triage"), "/definitely/not/a/complexity-target"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Target not found", result.stderr)
        self.assertFalse(result.stdout)

    def test_integrated_limits_apply_to_markdown_and_json(self) -> None:
        source = """
        def one(value):
            if value:
                return 1
            return 0

        def two(value):
            if value:
                return 2
            return 0
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(normalise_source(source), encoding="utf-8")
            args = parse_args([str(root), "--max-top", "0", "--max-findings", "0"])
            report = collect_integrated_report(root, args)
            markdown = render_markdown_report(report, max_top=args.max_top)
            payload = report_to_json(report, max_top=args.max_top)

        self.assertEqual(payload["top_files"], [])
        self.assertEqual(payload["top_functions"], [])
        self.assertEqual(payload["heuristic_hotspots"], [])
        self.assertNotIn("| module.py |", markdown)
        self.assertEqual(payload["analysis"]["status"], "complete")
        self.assertIn("coverage", payload["analysis"])

    def test_integrated_renderer_never_describes_partial_or_unsupported_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            (root / "plugin.zsh").write_text("echo hello\n", encoding="utf-8")
            report = collect_integrated_report(root, parse_args([str(root)]))
            partial_markdown = render_markdown_report(report, max_top=8)
            partial_json = report_to_json(report)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plugin.zsh").write_text("echo hello\n", encoding="utf-8")
            report = collect_integrated_report(root, parse_args([str(root)]))
            unsupported_markdown = render_markdown_report(report, max_top=8)
            unsupported_json = report_to_json(report)

        for rendered in (partial_markdown, unsupported_markdown):
            self.assertNotIn("no immediate refactor", rendered)
            self.assertNotIn("clean first-pass baseline", rendered)
            self.assertNotIn("low; every measured function is `Risk A`", rendered)
        self.assertEqual(
            partial_json["verdict"]["overall"],
            "inconclusive; required analysis did not cover the full eligible scope",
        )
        self.assertIsNone(unsupported_json["verdict"])

    def test_measure_complexity_rejects_unsupported_single_file(self) -> None:
        with temporary_source("echo hello", "plugin.zsh") as path:
            result = measure_complexity_main([str(path)])

        self.assertEqual(result, 4)

    def test_scan_hotspots_unsupported_output_never_looks_clean(self) -> None:
        with temporary_source("echo hello", "plugin.zsh") as path:
            for output_format in ("markdown", "json"):
                with self.subTest(output_format=output_format):
                    result = subprocess.run(
                        [
                            str(PLUGIN_ROOT / "scripts" / "scan-hotspots"),
                            str(path),
                            "--format",
                            output_format,
                        ],
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                    self.assertEqual(result.returncode, 4)
                    self.assertFalse(result.stdout)
                    self.assertEqual(result.stderr.count("Analysis unsupported"), 1)
                    self.assertNotIn("Analysis partial", result.stderr)
                    self.assertNotIn("No obvious complexity hotspots", result.stdout)

    def test_measure_complexity_missing_lizard_returns_partial_exit_code(self) -> None:

        with temporary_source("function useful() { return 1; }", "ordinary.js") as path:
            with mock.patch.object(
                analysis,
                "analyse_many_with_lizard_cli",
                side_effect=SystemExit("lizard unavailable"),
            ):
                result = measure_complexity_main([str(path), "--format", "json"])

        self.assertEqual(result, 3)

    def test_negative_integrated_limits_are_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args([".", "--max-findings", "-1"])
        with self.assertRaises(SystemExit):
            parse_args([".", "--max-top", "-1"])

    def test_runtime_launcher_runs_with_active_interpreter(self) -> None:
        launcher = PLUGIN_ROOT / "scripts" / "complexity-python"
        result = subprocess.run(
            [str(launcher), "-c", "import sys; print(sys.version_info[:2])"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(sys.version_info.major), result.stdout)

    def test_runtime_launcher_rejects_an_old_fake_interpreter(self) -> None:
        launcher = PLUGIN_ROOT / "scripts" / "complexity-python"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python-old"
            fake.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
            fake.chmod(0o755)
            result = subprocess.run(
                [str(launcher), "-c", "print('should not run')"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "COMPLEXITY_PYTHON": str(fake)},
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires Python 3.10+", result.stderr)
        self.assertIn(str(fake), result.stderr)

    @unittest.skipUnless(Path("/usr/bin/python3").exists(), "macOS system Python is absent")
    def test_runtime_launcher_rejects_old_macos_python_when_present(self) -> None:
        version = subprocess.run(
            ["/usr/bin/python3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        if tuple(map(int, version.split("."))) >= (3, 10):
            self.skipTest("/usr/bin/python3 is already Python 3.10+")
        result = subprocess.run(
            [str(PLUGIN_ROOT / "scripts" / "complexity-python"), "-c", "print('should not run')"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "COMPLEXITY_PYTHON": "/usr/bin/python3"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires Python 3.10+", result.stderr)


class CanonicalOutputTests(unittest.TestCase):
    def test_complete_python_json_uses_the_versioned_outcome_envelope(self) -> None:

        with temporary_source("", "empty.py") as path:
            payload = json.loads(render(analyse(AnalysisRequest(target=path)), "json"))

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["plugin_version"], "0.1.0")
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["request"]["mode"], "standard")
        self.assertEqual(payload["request"]["required_lanes"], ["heuristic", "metrics"])
        self.assertEqual(payload["coverage"]["analysed_files"], 1)
        self.assertEqual(payload["verdict"]["overall"], "no immediate refactor")
        self.assertIsInstance(payload["metrics"], list)
        self.assertIsInstance(payload["findings"], list)
        self.assertIsInstance(payload["inspection_queue"], list)

    def test_default_json_keeps_raw_metrics_without_a_projection_marker(self) -> None:
        source = """
        def first(items):
            return [item for item in items]

        def second(items):
            return len(items)
        """
        with temporary_source(source, "ordinary.py") as path:
            payload = json.loads(render(analyse(AnalysisRequest(target=path)), "json"))

        self.assertNotIn("projection", payload)
        self.assertEqual(payload["counts"]["metrics"]["returned"], 2)
        self.assertFalse(payload["counts"]["metrics"]["truncated"])
        self.assertEqual(len(payload["metrics"]), 2)

    def test_summary_projection_is_explicit_and_compact(self) -> None:
        source = """
        def first(items):
            return [item for item in items]

        def second(items):
            return len(items)
        """
        with temporary_source(source, "ordinary.py") as path:
            outcome = analyse(AnalysisRequest(target=path))
            full = render(outcome, "json")
            summary = render(outcome, "json", projection="summary")
            markdown_summary = render(outcome, "markdown", projection="summary")
            payload = json.loads(summary)

        self.assertLess(len(summary.encode()), len(full.encode()))
        self.assertEqual(payload["projection"]["name"], "summary")
        self.assertFalse(payload["projection"]["raw_metrics"]["included"])
        self.assertEqual(payload["projection"]["raw_metrics"]["total"], 2)
        self.assertEqual(payload["metrics"], [])
        self.assertEqual(
            payload["counts"]["metrics"],
            {"total": 2, "returned": 0, "truncated": True},
        )
        self.assertTrue(payload["top_functions"])
        self.assertIn("## Output", markdown_summary)
        self.assertIn("Raw metrics: omitted", markdown_summary)

    def test_output_file_writes_full_evidence_and_returns_summary_for_spaced_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complexity output ") as tmp:
            root = Path(tmp)
            source = root / "source file.py"
            output_file = root / "full evidence file.json"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=source))
            summary = json.loads(
                render_with_output(outcome, "json", output_file=output_file)
            )
            full = json.loads(output_file.read_text(encoding="utf-8"))

        self.assertEqual(
            summary["projection"]["raw_metrics"]["full_output_file"],
            str(output_file.resolve()),
        )
        self.assertEqual(summary["metrics"], [])
        self.assertTrue(full["metrics"])
        self.assertNotIn("projection", full)
        self.assertIn("--output-file", full["request"]["reproducible_command"])

    def test_markdown_summary_and_output_file_remain_renderable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complexity markdown output ") as tmp:
            source = Path(tmp) / "source.py"
            output_file = Path(tmp) / "full evidence.md"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")
            outcome = analyse(AnalysisRequest(target=source))
            summary = render_with_output(outcome, "markdown", output_file=output_file)
            full = output_file.read_text(encoding="utf-8")

        self.assertIn("## Output", summary)
        self.assertIn("Raw metrics: omitted", summary)
        self.assertNotIn("## Output", full)
        self.assertIn("## Scope", full)

    def test_canonical_summary_and_output_file_cli_accept_paths_with_spaces(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "analyse-complexity"
        with tempfile.TemporaryDirectory(prefix="complexity cli output ") as tmp:
            root = Path(tmp)
            source = root / "source file.py"
            output_file = root / "full evidence file.json"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")
            result = subprocess.run(
                [
                    str(script),
                    str(source),
                    "--format",
                    "json",
                    "--output-file",
                    str(output_file),
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            summary = json.loads(result.stdout)
            full = json.loads(output_file.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["projection"]["name"], "summary")
        self.assertEqual(
            summary["projection"]["raw_metrics"]["full_output_file"],
            str(output_file.resolve()),
        )
        self.assertTrue(full["metrics"])

    def test_output_file_parent_failure_is_a_cli_input_error(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "analyse-complexity"
        with temporary_source("def useful():\n    return 1\n", "ordinary.py") as path:
            result = subprocess.run(
                [
                    str(script),
                    str(path),
                    "--format",
                    "json",
                    "--output-file",
                    str(path.parent / "missing" / "evidence.json"),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(result.stdout)
        self.assertIn("Could not write output file", result.stderr)

    def test_output_file_option_requires_a_path(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "analyse-complexity"
        with temporary_source("def useful():\n    return 1\n", "ordinary.py") as path:
            result = subprocess.run(
                [str(script), str(path), "--format", "json", "--output-file"],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(result.stdout)
        self.assertIn("expected one argument", result.stderr)

    def test_compatibility_wrappers_propagate_summary_and_output_file_controls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complexity wrapper output ") as tmp:
            root = Path(tmp)
            source = root / "source file.py"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")
            commands = (
                (PLUGIN_ROOT / "scripts" / "complexity-triage", root),
                (PLUGIN_ROOT / "scripts" / "scan-hotspots", root),
                (PLUGIN_ROOT / "scripts" / "measure-complexity", source),
            )
            for script, target in commands:
                with self.subTest(script=script.name):
                    summary = subprocess.run(
                        [str(script), str(target), "--format", "json", "--summary"],
                        check=False,
                        text=True,
                        capture_output=True,
                    )
                    output_file = root / f"{script.name} full evidence.json"
                    stored = subprocess.run(
                        [
                            str(script),
                            str(target),
                            "--format",
                            "json",
                            "--output-file",
                            str(output_file),
                        ],
                        check=False,
                        text=True,
                        capture_output=True,
                    )

                    summary_payload = json.loads(summary.stdout)
                    stored_summary_payload = json.loads(stored.stdout)
                    stored_payload = json.loads(output_file.read_text(encoding="utf-8"))
                    self.assertEqual(summary.returncode, 0, summary.stderr)
                    self.assertEqual(stored.returncode, 0, stored.stderr)
                    self.assertEqual(summary_payload["projection"]["name"], "summary")
                    self.assertEqual(
                        stored_summary_payload["projection"]["name"], "summary"
                    )
                    self.assertEqual(
                        stored_summary_payload["projection"]["raw_metrics"][
                            "full_output_file"
                        ],
                        str(output_file.resolve()),
                    )
                    self.assertNotIn(
                        "projection",
                        stored_payload if isinstance(stored_payload, dict) else {},
                    )

    def test_all_entrypoints_document_output_controls_in_help(self) -> None:
        scripts = (
            PLUGIN_ROOT / "scripts" / "analyse-complexity",
            PLUGIN_ROOT / "scripts" / "complexity-triage",
            PLUGIN_ROOT / "scripts" / "scan-hotspots",
            PLUGIN_ROOT / "scripts" / "measure-complexity",
        )
        for script in scripts:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [str(script), "--help"],
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--summary", result.stdout)
                self.assertIn("--output-file", result.stdout)

    def test_delimited_compact_controls_are_rejected_without_stdout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complexity delimited ") as tmp:
            root = Path(tmp)
            source = root / "source.py"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")
            cases = (
                (PLUGIN_ROOT / "scripts" / "scan-hotspots", root, "csv"),
                (PLUGIN_ROOT / "scripts" / "measure-complexity", source, "csv"),
                (PLUGIN_ROOT / "scripts" / "measure-complexity", source, "tsv"),
            )
            for script, target, output_format in cases:
                with self.subTest(script=script.name, format=output_format):
                    for control in ("--summary", "--output-file"):
                        output_file = root / f"{script.name}-{output_format}.out"
                        command = [
                            str(script),
                            str(target),
                            "--format",
                            output_format,
                            control,
                        ]
                        if control == "--output-file":
                            command.append(str(output_file))
                        result = subprocess.run(
                            command,
                            check=False,
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertFalse(result.stdout)
                        self.assertIn("require Markdown or JSON", result.stderr)
                        self.assertFalse(output_file.exists())

    def test_delimited_defaults_keep_legacy_row_shapes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complexity delimited defaults ") as tmp:
            root = Path(tmp)
            source = root / "source.py"
            source.write_text("def useful():\n    return 1\n", encoding="utf-8")

            scan = subprocess.run(
                [
                    str(PLUGIN_ROOT / "scripts" / "scan-hotspots"),
                    str(root),
                    "--format",
                    "csv",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            measure_csv = subprocess.run(
                [
                    str(PLUGIN_ROOT / "scripts" / "measure-complexity"),
                    str(source),
                    "--format",
                    "csv",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            measure_tsv = subprocess.run(
                [
                    str(PLUGIN_ROOT / "scripts" / "measure-complexity"),
                    str(source),
                    "--format",
                    "tsv",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertTrue(scan.stdout.startswith("path,line,severity,confidence,"))
        self.assertNotIn("\"schema_version\"", scan.stdout)
        self.assertEqual(measure_csv.returncode, 0, measure_csv.stderr)
        self.assertTrue(measure_csv.stdout.startswith("name,kind,start,"))
        self.assertNotIn("\"schema_version\"", measure_csv.stdout)
        self.assertEqual(measure_tsv.returncode, 0, measure_tsv.stderr)
        self.assertTrue(measure_tsv.stdout.startswith("name\tkind\tstart\t"))
        self.assertNotIn("\"schema_version\"", measure_tsv.stdout)

    def test_canonical_cli_needs_only_a_target_for_the_common_case(self) -> None:
        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            result = subprocess.run(
                [str(PLUGIN_ROOT / "scripts" / "analyse-complexity"), str(path), "--format", "json"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["request"]["mode"], "standard")

    def test_canonical_cli_rejects_negative_presentation_limits(self) -> None:
        for option in ("--max-findings", "--max-top"):
            with self.subTest(option=option):
                result = subprocess.run(
                    [str(PLUGIN_ROOT / "scripts" / "analyse-complexity"), ".", option, "-1"],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                self.assertEqual(result.returncode, 2)
                self.assertFalse(result.stdout)
                self.assertIn("must be non-negative", result.stderr)

    def test_canonical_limits_preserve_totals_and_raw_metrics(self) -> None:

        source = """
        def expensive(items, frappe):
            for item in items:
                frappe.db.get_value("Item", item, "item_name")
        """
        with temporary_source(source, "ordinary.py") as path:
            outcome = analyse(AnalysisRequest(target=path, max_findings=0, max_top=0))
            payload = json.loads(render(outcome, "json"))

        self.assertTrue(payload["metrics"])
        self.assertFalse(payload["findings"])
        self.assertFalse(payload["top_files"])
        self.assertFalse(payload["top_functions"])
        self.assertFalse(payload["inspection_queue"])
        self.assertGreater(payload["counts"]["findings"]["total"], 0)
        self.assertTrue(payload["counts"]["findings"]["truncated"])
        self.assertGreater(payload["counts"]["top_functions"]["total"], 0)
        self.assertTrue(payload["counts"]["top_functions"]["truncated"])

    def test_reproducible_command_safely_round_trips_paths_and_excludes(self) -> None:
        import shlex


        with tempfile.TemporaryDirectory(prefix="complexity path ") as tmp:
            path = Path(tmp) / "source file.py"
            path.write_text("def useful():\n    return 1\n", encoding="utf-8")
            outcome = analyse(
                AnalysisRequest(target=path, excludes=frozenset({"generated files"}))
            )
            payload = json.loads(render(outcome, "json"))

        command = shlex.split(payload["request"]["reproducible_command"])
        self.assertEqual(command[0], "analyse-complexity")
        self.assertEqual(command[1], str(path.resolve()))
        self.assertIn("generated files", command)
        self.assertEqual(payload["request"]["target_kind"], "file")
        self.assertIn("generated files", payload["request"]["requested_excludes"])
        self.assertIn("node_modules", payload["request"]["effective_excludes"])

    def test_canonical_cli_distinguishes_partial_unsupported_and_input_error(self) -> None:
        script = str(PLUGIN_ROOT / "scripts" / "analyse-complexity")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            (root / "plugin.zsh").write_text("echo hello\n", encoding="utf-8")
            partial = subprocess.run(
                [script, str(root), "--format", "json"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            unsupported = subprocess.run(
                [script, str(root / "plugin.zsh"), "--format", "json"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        invalid = subprocess.run(
            [script, "/definitely/not/a/complexity-target", "--format", "json"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        partial_payload = json.loads(partial.stdout)
        unsupported_payload = json.loads(unsupported.stdout)
        self.assertEqual(partial.returncode, 3)
        self.assertEqual(partial_payload["status"], "partial")
        self.assertEqual(
            partial_payload["verdict"]["overall"],
            "inconclusive; required analysis did not cover the full eligible scope",
        )
        self.assertEqual(unsupported.returncode, 4)
        self.assertEqual(unsupported_payload["status"], "unsupported")
        self.assertIsNone(unsupported_payload["verdict"])
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(invalid.stdout)
        self.assertIn("Target not found", invalid.stderr)

    def test_markdown_and_json_render_the_same_limited_evidence(self) -> None:

        source = """
        def first(items, frappe):
            for item in items:
                frappe.db.get_value("Item", item, "item_name")

        def second(items, frappe):
            for item in items:
                frappe.db.get_value("Item", item, "description")
        """
        with temporary_source(source, "ordinary.py") as path:
            outcome = analyse(AnalysisRequest(target=path, max_findings=1, max_top=1))
            payload = json.loads(render(outcome, "json"))
            markdown = render(outcome, "markdown")

        finding = payload["findings"][0]
        top_function = payload["top_functions"][0]
        self.assertIn(f"{finding['path']}:{finding['line']}", markdown)
        self.assertIn(top_function["name"], markdown)
        self.assertIn(
            f"Findings returned: {payload['counts']['findings']['returned']}/{payload['counts']['findings']['total']}",
            markdown,
        )
        self.assertIn(
            "Top functions returned: "
            f"{payload['counts']['top_functions']['returned']}/"
            f"{payload['counts']['top_functions']['total']}",
            markdown,
        )
        self.assertIn(
            "Top files returned: "
            f"{payload['counts']['top_files']['returned']}/"
            f"{payload['counts']['top_files']['total']}",
            markdown,
        )
        self.assertIn(
            "Inspection targets returned: "
            f"{payload['counts']['inspection_queue']['returned']}/"
            f"{payload['counts']['inspection_queue']['total']}",
            markdown,
        )
        self.assertIn("truncated: true", markdown)

    def test_timings_keep_unrequested_stages_distinct_from_zero(self) -> None:

        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            payload = json.loads(
                render(analyse(AnalysisRequest(target=path, mode="quick")), "json")
            )

        self.assertIsInstance(payload["timings"]["inventory_seconds"], float)
        self.assertIsInstance(payload["timings"]["heuristic_seconds"], float)
        self.assertIsNone(payload["timings"]["metrics_seconds"])
        self.assertIsNone(payload["timings"]["repo_context_seconds"])
        self.assertGreaterEqual(payload["timings"]["total_seconds"], 0.0)

    def test_root_and_skill_local_canonical_wrappers_are_equivalent(self) -> None:
        root_script = PLUGIN_ROOT / "scripts" / "analyse-complexity"
        skill_script = (
            PLUGIN_ROOT / "skills" / "analyse-complexity" / "scripts" / "analyse-complexity"
        )
        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            results = [
                subprocess.run(
                    [str(script), str(path), "--format", "json"],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for script in (root_script, skill_script)
            ]

        self.assertEqual([item.returncode for item in results], [0, 0])
        payloads = [json.loads(item.stdout) for item in results]
        self.assertEqual(payloads[0]["status"], payloads[1]["status"])
        self.assertEqual(payloads[0]["coverage"], payloads[1]["coverage"])

    def test_skill_local_canonical_wrapper_propagates_summary_controls(self) -> None:
        skill_script = (
            PLUGIN_ROOT / "skills" / "analyse-complexity" / "scripts" / "analyse-complexity"
        )
        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            result = subprocess.run(
                [str(skill_script), str(path), "--format", "json", "--summary"],
                check=False,
                text=True,
                capture_output=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["projection"]["name"], "summary")
        self.assertEqual(payload["metrics"], [])

    def test_render_does_not_reinspect_the_target_after_analysis(self) -> None:

        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            outcome = analyse(AnalysisRequest(target=path))

        payload = json.loads(render(outcome, "json"))
        self.assertEqual(payload["request"]["target_kind"], "file")

    def test_canonical_outcome_lists_all_stable_adapter_ids(self) -> None:

        with temporary_source("def useful():\n    return 1", "ordinary.py") as path:
            payload = json.loads(render(analyse(AnalysisRequest(target=path)), "json"))

        adapters = payload["adapters"]
        self.assertEqual(
            [item["identifier"] for item in adapters],
            [
                "python-ast",
                "lizard",
                "text-heuristic",
                "repo-context-rg",
                "repo-context-git",
                "coverage-xml",
            ],
        )
        self.assertTrue(all("version" in item for item in adapters))

    def test_unavailable_optional_context_is_diagnostic_not_partial(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ordinary.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(repo_context.shutil, "which", return_value=None):
                outcome = analyse(AnalysisRequest(target=root, repo_context=root))

        self.assertEqual(outcome.status, "complete")
        states = {item.identifier: item.status for item in outcome.adapters}
        self.assertEqual(states["repo-context-rg"], "unavailable")
        self.assertEqual(states["repo-context-git"], "unavailable")
        self.assertEqual(states["coverage-xml"], "unavailable")
        self.assertEqual(outcome.repo_context.eligible_functions, 1)
        self.assertEqual(outcome.repo_context.selected_functions, 1)
        self.assertFalse(outcome.repo_context.sampled)
        stages = {item.stage for item in outcome.diagnostics}
        self.assertTrue(
            {"repo-context-rg", "repo-context-git", "coverage-xml"}.issubset(stages)
        )

    def test_coverage_xml_without_explicit_repo_context_uses_target_scope(self) -> None:
        coverage_xml = """
        <coverage>
          <packages><package><classes>
            <class filename="module.py"><lines>
              <line number="1" hits="0" />
              <line number="2" hits="0" />
            </lines></class>
          </classes></package></packages>
        </coverage>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "module.py"
            coverage = root / "custom-coverage.xml"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            coverage.write_text(normalise_source(coverage_xml), encoding="utf-8")
            result = subprocess.run(
                [
                    str(PLUGIN_ROOT / "scripts" / "analyse-complexity"),
                    str(source),
                    "--format",
                    "json",
                    "--coverage-xml",
                    str(coverage),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        states = {item["identifier"]: item["status"] for item in payload["adapters"]}
        self.assertEqual(states["coverage-xml"], "complete")
        self.assertEqual(payload["metrics"][0]["coverage_percent"], 0.0)
        self.assertEqual(payload["repo_context"]["root"], str(source.parent.resolve()))
        self.assertTrue(payload["repo_context"]["signals"])

    def test_measure_complexity_uses_the_bounded_context_path(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        coverage_xml = """
        <coverage>
          <packages><package><classes>
            <class filename="module.py"><lines>
              <line number="1" hits="0" />
              <line number="2" hits="0" />
            </lines></class>
          </classes></package></packages>
        </coverage>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "module.py"
            coverage = root / "coverage.xml"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            coverage.write_text(normalise_source(coverage_xml), encoding="utf-8")
            output = io.StringIO()
            with (
                mock.patch.object(repo_context.shutil, "which", return_value=None),
                mock.patch("sys.stdout", output),
            ):
                exit_code = measure_complexity_main(
                    [str(source), "--format", "json", "--coverage-xml", str(coverage)]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload[0]["coverage_percent"], 0.0)

    def test_bounded_findings_do_not_create_a_refactor_verdict(self) -> None:

        scope = PLUGIN_ROOT / "tests" / "fixtures" / "golden" / "bounded_retry_loop"
        outcome = analyse(AnalysisRequest(target=scope, mode="quick"))

        self.assertEqual(outcome.status, "complete")
        self.assertTrue(outcome.findings)
        self.assertEqual(outcome.verdict["overall"], "no immediate refactor")
        self.assertEqual(outcome.decision_fields["performance"]["material_hotspots"], 0)
        self.assertEqual(outcome.top_files[0].material_hotspot_count, 0)

    def test_file_ranking_weights_material_not_bounded_hotspots(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bounded.py").write_text(
                "def bounded(frappe):\n"
                "    for field in ('name', 'description'):\n"
                "        frappe.db.get_value('Item', 'fixed', field)\n",
                encoding="utf-8",
            )
            (root / "material.py").write_text(
                "def material(items, frappe):\n"
                "    for item in items:\n"
                "        frappe.db.get_value('Item', item, 'name')\n",
                encoding="utf-8",
            )
            outcome = analyse(AnalysisRequest(target=root, mode="quick"))

        by_path = {item.path: item for item in outcome.top_files}
        self.assertEqual(outcome.top_files[0].path, "material.py")
        self.assertEqual(by_path["bounded.py"].material_hotspot_count, 0)
        self.assertGreater(by_path["bounded.py"].hotspot_count, 0)
        self.assertGreater(by_path["material.py"].material_hotspot_count, 0)

    def test_golden_ranking_prioritises_production_data_leads(self) -> None:
        scope = PLUGIN_ROOT / "tests" / "fixtures" / "golden" / "ranking_calibration"
        outcome = analyse(AnalysisRequest(target=scope, mode="standard"))
        legacy = collect_integrated_report(scope, parse_args([str(scope), "--format", "json"]))
        legacy_payload = report_to_json(legacy, max_top=20)
        limited_legacy = collect_integrated_report(
            scope,
            parse_args([str(scope), "--format", "json", "--max-findings", "0"]),
        )
        limited_legacy_payload = report_to_json(limited_legacy, max_top=20)

        self.assertEqual(outcome.status, "complete")
        ranked_names = [item.metric.name for item in outcome.top_functions]
        legacy_names = [item["name"] for item in legacy_payload["top_functions"]]
        risks = {item.metric.name: item.metric.risk for item in outcome.top_functions}
        self.assertEqual(risks["execute"], "A")
        self.assertNotEqual(risks["retry_request"], "A")
        self.assertEqual(ranked_names[0], "load_each_record")
        self.assertEqual(
            outcome.decision_fields["complexity"]["top_function"]["name"],
            "retry_request",
        )
        self.assertEqual(
            outcome.decision_fields["complexity"]["top_function"]["risk"], "C"
        )
        self.assertEqual(legacy_names, ranked_names)
        self.assertEqual(
            outcome.decision_fields["performance"]["material_hotspots"], 1
        )
        self.assertEqual(
            legacy_payload["decision_fields"]["performance"]["material_hotspots"], 1
        )
        self.assertFalse(limited_legacy_payload["heuristic_hotspots"])
        self.assertEqual(
            limited_legacy_payload["decision_fields"]["performance"]["material_hotspots"],
            1,
        )
        self.assertIn(
            "1 material hotspot leads",
            limited_legacy_payload["verdict"]["runtime"],
        )
        self.assertTrue(
            any(
                "validate `production.py:4` io-in-loop next"
                in action
                for action in limited_legacy_payload["smallest_next_action_plan"]
            )
        )
        self.assertLess(
            ranked_names.index("load_each_record"),
            ranked_names.index("retry_request"),
        )
        self.assertLess(
            ranked_names.index("load_each_record"),
            ranked_names.index("stream_chunks"),
        )
        self.assertLess(
            ranked_names.index("load_each_record"),
            ranked_names.index("list_pages"),
        )
        self.assertLess(
            ranked_names.index("load_each_record"),
            ranked_names.index("execute"),
        )
        self.assertLess(
            ranked_names.index("load_each_record"),
            ranked_names.index("test_reads_fixture"),
        )

    def test_skill_is_slim_and_all_relative_links_resolve(self) -> None:
        import re

        skill = PLUGIN_ROOT / "skills" / "analyse-complexity" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)

        self.assertGreaterEqual(line_count, 45)
        self.assertLessEqual(line_count, 60)
        self.assertIn("read-only static complexity analysis", text)
        self.assertIn("hotspot ranking", text)
        self.assertIn("source-based performance-risk review", text)
        self.assertTrue(links)
        for link in links:
            with self.subTest(link=link):
                self.assertTrue((skill.parent / link).resolve().is_file())

    def test_documentation_describes_the_canonical_contract(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        report_template = (
            PLUGIN_ROOT
            / "skills"
            / "analyse-complexity"
            / "references"
            / "report-template.md"
        ).read_text(encoding="utf-8")

        for phrase in (
            "Python 3.10+",
            "quick",
            "standard",
            "complete",
            "partial",
            "unsupported",
            "schema_version",
            "--summary",
            "--output-file",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        self.assertNotIn("## Change Summary", report_template)
        self.assertFalse((PLUGIN_ROOT / "references" / "report-template.md").exists())
        self.assertFalse((PLUGIN_ROOT / "references" / "optimisation-playbook.md").exists())


class ComplexityPluginRegressionTests(unittest.TestCase):
    def test_non_loop_high_confidence_findings_remain_material(self) -> None:
        from ranking import is_material_finding

        source = """
        def compare_groups(groups, candidates):
            matches = []
            for group in groups:
                for candidate in candidates:
                    if candidate in group:
                        matches.append(candidate)
            return matches
        """
        findings = scan_python_source(source)
        nested_loop = first_finding(findings, "nested-loop")

        self.assertEqual(nested_loop.loop_classification, "")
        self.assertTrue(is_material_finding(nested_loop))

    def test_bounded_retry_loop_is_not_reported_as_unbounded_n_plus_one(self) -> None:
        source = """
        MAX_RETRIES = 3

        class Client:
            def __init__(self, session):
                self.session = session

            def request(self, url):
                for attempt in range(MAX_RETRIES):
                    response = self.session.request("GET", url)
                    if response.ok:
                        return response
                return None
        """
        findings = scan_python_source(source)
        retry = first_finding(findings, "io-in-loop")
        self.assertEqual(retry.loop_classification, "retry loop")
        self.assertIn("bounded retry", retry.current_pattern)
        self.assertIn("not an unbounded N+1", retry.estimated_complexity)

    def test_fixed_small_loop_db_call_is_calibrated_as_bounded(self) -> None:
        source = """
        def has_legacy_values(frappe):
            for fieldname in ("sharepoint_site_url", "sharepoint_document_library"):
                rows = frappe.db.sql("select value", ("OneDrive Settings", fieldname))
                if rows:
                    return True
            return False
        """
        findings = scan_python_source(source)
        db_loop = first_finding(findings, "io-in-loop")
        self.assertEqual(db_loop.loop_classification, "fixed-size loop")
        self.assertIn("fixed-size loop", db_loop.current_pattern)
        self.assertIn("database", db_loop.calibration)

    def test_set_and_dict_membership_are_not_flagged_as_list_scans(self) -> None:
        source = """
        def dedupe(items):
            seen = set()
            result = []
            for item in items:
                if item in seen:
                    continue
                if "name" in item:
                    result.append(item)
                seen.add(item)
            return result
        """
        findings = scan_python_source(source)
        self.assertFalse([item for item in findings if item.kind == "membership-in-loop"])

    def test_wrapper_io_inside_loop_is_surfaced_with_low_confidence(self) -> None:
        source = """
        import requests

        class Client:
            def _request(self, url):
                return requests.get(url)

            def upload_many(self, urls):
                results = []
                for url in urls:
                    results.append(self._request(url))
                return results
        """
        findings = scan_python_source(source)
        wrapper = first_finding(findings, "wrapper-io-in-loop")
        self.assertEqual(wrapper.confidence, "low")
        self.assertIn("_request", wrapper.current_pattern)

    def test_super_init_is_not_direct_recursion(self) -> None:
        source = """
        class AppError(Exception):
            def __init__(self, message):
                super().__init__(message)
        """
        with temporary_source(source, "sample.py") as path:
            metric = analyse_python(path)[0]
        self.assertEqual(metric.name, "AppError.__init__")
        self.assertFalse(metric.direct_recursion)
        self.assertNotIn("direct recursion", metric.review_flags)

    def test_lizard_csv_without_header_is_parsed_reliably(self) -> None:
        output = (
            '7,2,33,1,8,"update_notice@5-12@/tmp/form.js",'
            '"/tmp/form.js","update_notice","update_notice ( frm )",5,12\n'
        )
        metrics = parse_lizard_csv(output)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].name, "update_notice")
        self.assertEqual(metrics[0].start, 5)
        self.assertEqual(metrics[0].end, 12)
        self.assertEqual(metrics[0].cyclomatic, 2)

    def test_framework_db_api_in_data_loop_is_surfaced(self) -> None:
        source = """
        def load_values(frappe, names):
            values = []
            for name in names:
                values.append(frappe.db.get_value("Item", name, "item_name"))
            return values
        """
        findings = scan_python_source(source)
        db_loop = first_finding(findings, "io-in-loop")
        self.assertEqual(db_loop.loop_classification, "data loop")
        self.assertIn("database", db_loop.calibration)

    def test_js_lizard_output_is_explicitly_limited_or_unavailable(self) -> None:
        source = """
        function renderItems(items) {
          return items.filter((item) => item.active).map((item) => item.name);
        }
        """
        with temporary_source(source, "sample.js") as path:
            if shutil.which("lizard") is None:
                with self.assertRaises(SystemExit) as raised:
                    analyse_file(path)
                self.assertIn("Non-Python analysis requires lizard", str(raised.exception))
                return
            metrics = analyse_file(path)
        self.assertTrue(metrics)
        self.assertIn("lower-detail", metrics[0].calibration)
        self.assertIn("lizard", metrics[0].claim_type)

    def test_integrated_report_uses_readable_headings_and_function_first_action(self) -> None:
        source = """
        def tangled(items):
            total = 0
            for item in items:
                if item.get("a"):
                    total += 1
                elif item.get("b"):
                    total += 2
                elif item.get("c"):
                    total += 3
                elif item.get("d"):
                    total += 4
                elif item.get("e"):
                    total += 5
                else:
                    total -= 1
            return total
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(normalise_source(source), encoding="utf-8")
            args = parse_args([str(root)])
            report = collect_integrated_report(root, args)
            output = render_markdown_report(report, max_top=8)

        self.assertIn("## Orientation Brief", output)
        self.assertIn("## Smallest Next Action Plan", output)
        self.assertNotIn("## orientation_brief", output)
        self.assertIn(
            "- inspect `module.py:1` `tangled` first because it is the highest deterministic complexity row",
            output,
        )


    def test_integrated_json_exposes_agent_decision_fields(self) -> None:
        source = """
        def tangled(items):
            total = 0
            for item in items:
                if item.get("a"):
                    total += 1
                elif item.get("b"):
                    total += 2
                elif item.get("c"):
                    total += 3
                elif item.get("d"):
                    total += 4
                elif item.get("e"):
                    total += 5
                else:
                    total -= 1
            return total
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(normalise_source(source), encoding="utf-8")
            args = parse_args([str(root)])
            report = collect_integrated_report(root, args)
            payload = report_to_json(report)

            self.assertIn("verdict", payload)
            self.assertEqual(payload["analysis"], canonical_analysis_payload(report.outcome))
            self.assertIn("decision_fields", payload)
            self.assertIn("missing_signals", payload)
            self.assertIn("evidence_confidence", payload)
            self.assertIn("smallest_next_action_plan", payload)
            self.assertEqual(
                payload["verdict"]["refactor_priority"],
                "inspect top runtime and non-A maintainability rows before changing code",
            )
            self.assertEqual(payload["decision_fields"]["complexity"]["non_a_functions"], 1)
            self.assertTrue(payload["smallest_next_action_plan"])

    @unittest.skipUnless(shutil.which("rg"), "repo context enrichment needs rg")
    def test_integrated_report_enriches_top_candidate_repo_context(self) -> None:
        target = """
        def target(items):
            total = 0
            for item in items:
                if item.get("a"):
                    total += 1
                elif item.get("b"):
                    total += 2
                elif item.get("c"):
                    total += 3
                elif item.get("d"):
                    total += 4
                elif item.get("e"):
                    total += 5
                else:
                    total -= 1
            return total
        """
        caller = """
        from module import target

        def caller(items):
            return target(items)
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(normalise_source(target), encoding="utf-8")
            (root / "caller.py").write_text(normalise_source(caller), encoding="utf-8")
            args = parse_args([str(root)])
            report = collect_integrated_report(root, args)

            target_metric = next(
                item.metric for item in report.metrics if item.metric.name == "target"
            )
            self.assertIsNotNone(target_metric.repo_references)
            self.assertGreaterEqual(target_metric.repo_references, 1)

    def test_integrated_context_reports_sampling_denominators(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        source = "\n\n".join(
            f"def function_{index}():\n    return {index}" for index in range(30)
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(source + "\n", encoding="utf-8")
            coverage_lines = "\n".join(
                f'<line number="{number}" hits="0" />'
                for number in range(1, 91)
            )
            (root / "coverage.xml").write_text(
                "<coverage><packages><package><classes>"
                '<class filename="module.py"><lines>'
                f"{coverage_lines}"
                "</lines></class></classes></package></packages></coverage>",
                encoding="utf-8",
            )
            with mock.patch.object(repo_context.shutil, "which", return_value=None):
                report = collect_integrated_report(root, parse_args([str(root)]))
            payload = report_to_json(report)

        summary = payload["repo_context"]
        self.assertEqual(summary["eligible_functions"], 30)
        self.assertEqual(summary["requested_top_k"], 25)
        self.assertEqual(summary["selected_functions"], 25)
        self.assertEqual(summary["enriched_functions"], 25)
        self.assertTrue(summary["sampled"])
        testability = payload["decision_fields"]["testability"]
        self.assertNotIn("low_coverage_functions", testability)
        self.assertEqual(testability["low_coverage_functions_in_sample"], 25)
        self.assertTrue(testability["coverage_signal_available"])
        self.assertTrue(testability["coverage_sampled"])
        self.assertEqual(testability["coverage_eligible_functions"], 30)
        self.assertEqual(testability["coverage_selected_functions"], 25)
        self.assertEqual(testability["coverage_functions_with_value"], 25)
        self.assertEqual(report.outcome.status, "complete")

    def test_invalid_coverage_is_parsed_once_and_reported(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first.py").write_text("def first():\n    return 1\n", encoding="utf-8")
            (root / "second.py").write_text("def second():\n    return 2\n", encoding="utf-8")
            (root / "coverage.xml").write_text("<coverage>", encoding="utf-8")
            with (
                mock.patch.object(repo_context.shutil, "which", return_value=None),
                mock.patch.object(
                    repo_context.ElementTree,
                    "parse",
                    wraps=repo_context.ElementTree.parse,
                ) as parse,
            ):
                report = collect_integrated_report(root, parse_args([str(root)]))

        self.assertEqual(parse.call_count, 1)
        self.assertEqual(report.outcome.status, "complete")
        coverage_diagnostics = [
            item for item in report.outcome.diagnostics if item.stage == "coverage-xml"
        ]
        self.assertEqual(len(coverage_diagnostics), 1)
        self.assertIn("could not be parsed", coverage_diagnostics[0].reason)

    def test_invalid_numeric_coverage_is_diagnostic_not_an_internal_failure(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        coverage_xml = """
        <coverage><packages><package><classes>
          <class filename="module.py"><lines>
            <line number="1" hits="not-a-number" />
          </lines></class>
        </classes></package></packages></coverage>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8"
            )
            (root / "coverage.xml").write_text(
                normalise_source(coverage_xml), encoding="utf-8"
            )
            with mock.patch.object(repo_context.shutil, "which", return_value=None):
                report = collect_integrated_report(root, parse_args([str(root)]))

        states = {item.identifier: item.status for item in report.outcome.adapters}
        self.assertEqual(report.outcome.status, "complete")
        self.assertEqual(states["coverage-xml"], "failed")
        self.assertTrue(
            any(
                item.stage == "coverage-xml"
                and "invalid line data" in item.reason
                for item in report.outcome.diagnostics
            )
        )

    def test_zero_percent_coverage_is_a_concrete_enrichment_value(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        coverage_xml = """
        <coverage>
          <packages><package><classes>
            <class filename="module.py"><lines>
              <line number="1" hits="0" />
              <line number="2" hits="0" />
            </lines></class>
          </classes></package></packages>
        </coverage>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text("def target():\n    return 1\n", encoding="utf-8")
            (root / "coverage.xml").write_text(
                normalise_source(coverage_xml), encoding="utf-8"
            )
            with mock.patch.object(repo_context.shutil, "which", return_value=None):
                report = collect_integrated_report(root, parse_args([str(root)]))

        metric = report.metrics[0].metric
        coverage_signal = next(
            item
            for item in report.outcome.repo_context.signals
            if item.identifier == "coverage-xml"
        )
        self.assertEqual(metric.coverage_percent, 0.0)
        self.assertEqual(coverage_signal.with_value, 1)
        self.assertEqual(report.outcome.repo_context.enriched_functions, 1)

    def test_context_enrichment_accepts_signal_adapters(self) -> None:
        from function_complexity.repo_context import (
            ContextAdapters,
            enrich_ranked_metrics,
        )

        class FakeReference:
            identifier = "repo-context-rg"
            available = True
            version = "fake-rg"

            def search(self, repo, function_name, deadline):
                return "other.py:1:target()\n", None

        class FakeGit:
            identifier = "repo-context-git"
            available = True
            version = "fake-git"

            def churn(self, repo, path, start, end, deadline):
                return (2, 50), None

        class FakeCoverage:
            identifier = "coverage-xml"
            state = "complete"
            reason = ""
            version = "fake-coverage"

            def percent(self, repo, path, start, end):
                return 42.5

        with temporary_source("def target():\n    return 1\n", "target.py") as path:
            metric = analyse_python(path)[0]
            summary, diagnostics, adapters = enrich_ranked_metrics(
                [(path, metric)],
                repo_context=path.parent,
                coverage_xml=None,
                requested_top_k=1,
                adapters=ContextAdapters(FakeReference(), FakeGit(), FakeCoverage()),
            )

        self.assertFalse(diagnostics)
        self.assertEqual(summary.enriched_functions, 1)
        self.assertEqual(metric.repo_references, 1)
        self.assertEqual(metric.git_commits, 2)
        self.assertEqual(metric.git_churn_lines, 50)
        self.assertEqual(metric.coverage_percent, 42.5)
        self.assertEqual({item.status for item in adapters}, {"complete"})

    def test_available_context_adapters_report_versions(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        coverage_xml = """
        <coverage version="7.0"><packages><package><classes>
          <class filename="module.py"><lines>
            <line number="1" hits="1" />
            <line number="2" hits="1" />
          </lines></class>
        </classes></package></packages></coverage>
        """

        def command_result(command, **_kwargs):
            if command[-1] == "--version":
                output = (
                    "ripgrep 15.0.0\n"
                    if Path(command[0]).name == "rg"
                    else "git version 2.49.0\n"
                )
                return subprocess.CompletedProcess(command, 0, output, "")
            if command[0] == "rg":
                return subprocess.CompletedProcess(command, 1, "", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8"
            )
            (root / "coverage.xml").write_text(
                normalise_source(coverage_xml), encoding="utf-8"
            )
            with (
                mock.patch.object(
                    repo_context.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    repo_context.subprocess, "run", side_effect=command_result
                ),
            ):
                report = collect_integrated_report(root, parse_args([str(root)]))

        versions = {
            item.identifier: item.version for item in report.outcome.adapters
        }
        self.assertEqual(versions["repo-context-rg"], "ripgrep 15.0.0")
        self.assertEqual(versions["repo-context-git"], "git version 2.49.0")
        self.assertEqual(versions["coverage-xml"], "7.0")

    def test_undecodable_context_output_is_diagnostic(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        decode_error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8"
            )
            with (
                mock.patch.object(
                    repo_context.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    repo_context, "command_version", return_value="test version"
                ),
                mock.patch.object(
                    repo_context.subprocess, "run", side_effect=decode_error
                ),
            ):
                report = collect_integrated_report(root, parse_args([str(root)]))

        self.assertEqual(report.outcome.status, "complete")
        context_diagnostics = [
            item
            for item in report.outcome.diagnostics
            if item.stage in {"repo-context-rg", "repo-context-git"}
        ]
        self.assertEqual(len(context_diagnostics), 2)
        self.assertTrue(
            all("could not be decoded" in item.reason for item in context_diagnostics)
        )

    def test_reference_budget_exhaustion_is_bounded_and_truthful(self) -> None:
        import function_complexity.repo_context as repo_context  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "def first():\n    return 1\n\ndef second():\n    return 2\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(["rg"], 1, "", "")
            with (
                mock.patch.object(repo_context, "REFERENCE_SEARCH_BUDGET", 1),
                mock.patch.object(
                    repo_context.shutil,
                    "which",
                    side_effect=lambda name: "/opt/homebrew/bin/rg" if name == "rg" else None,
                ),
                mock.patch.object(repo_context.subprocess, "run", return_value=completed) as run,
            ):
                report = collect_integrated_report(root, parse_args([str(root)]))

        reference_signal = next(
            item
            for item in report.outcome.repo_context.signals
            if item.identifier == "repo-context-rg"
        )
        states = {item.identifier: item.status for item in report.outcome.adapters}
        reference_calls = [
            call for call in run.call_args_list if "-n" in call.args[0]
        ]
        self.assertEqual(len(reference_calls), 1)
        self.assertEqual(reference_signal.attempted, 1)
        self.assertEqual(reference_signal.completed, 1)
        self.assertEqual(reference_signal.with_value, 1)
        self.assertEqual(states["repo-context-rg"], "partial")
        self.assertEqual(report.outcome.status, "complete")
        self.assertTrue(
            any("budget exhausted" in item.reason for item in report.outcome.diagnostics)
        )


class GoldenCorpusTests(unittest.TestCase):
    def test_golden_corpus_expected_findings_and_false_positive_budgets(self) -> None:
        for case in load_manifest():
            with self.subTest(case=case["name"]):
                findings = scan_fixture_scope(case["scope"])
                self.assert_expected_findings(case, findings)
                self.assert_forbidden_findings(case, findings)
                self.assert_false_positive_budget(case, findings)

    def assert_expected_findings(self, case: dict, findings: list) -> None:
        for expected in case["expected"]:
            self.assertTrue(
                any(finding_matches(finding, expected) for finding in findings),
                f"{case['name']} missing expected {expected}; got {finding_summary(findings)}",
            )

    def assert_forbidden_findings(self, case: dict, findings: list) -> None:
        for forbidden in case["forbidden"]:
            matches = [finding for finding in findings if finding_matches(finding, forbidden)]
            self.assertFalse(
                matches,
                f"{case['name']} had forbidden {forbidden}; got {finding_summary(matches)}",
            )

    def assert_false_positive_budget(self, case: dict, findings: list) -> None:
        expected = case["expected"]
        unmatched = [
            finding
            for finding in findings
            if not any(finding_matches(finding, item) for item in expected)
        ]
        self.assertLessEqual(
            len(unmatched),
            case["false_positive_budget"],
            f"{case['name']} exceeded false-positive budget with {finding_summary(unmatched)}",
        )


def scan_python_source(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.py"
        path.write_text(normalise_source(source), encoding="utf-8")
        report = collect_report(Path(tmp), set(), "test-scan")
        return limit_findings(report.findings, 80)


def scan_fixture_scope(scope: str):
    report = collect_report(GOLDEN_ROOT / scope, set(), "golden-corpus")
    return limit_findings(report.findings, 80)


def load_manifest() -> list[dict]:
    return json.loads((GOLDEN_ROOT / "manifest.json").read_text(encoding="utf-8"))


def finding_matches(finding, criteria: dict) -> bool:
    return fields_equal(finding, criteria) and fields_contain(
        finding, criteria.get("field_contains", {})
    )


def fields_equal(finding, criteria: dict) -> bool:
    return all(
        key == "field_contains" or getattr(finding, key) == value
        for key, value in criteria.items()
    )


def fields_contain(finding, expected: dict[str, str]) -> bool:
    return all(value in getattr(finding, field) for field, value in expected.items())


def finding_summary(findings: list) -> list[str]:
    return [
        f"{item.path}:{item.line}:{item.kind}:{item.loop_classification}:{item.evidence}"
        for item in findings
    ]


def first_finding(findings, kind: str):
    for finding in findings:
        if finding.kind == kind:
            return finding
    raise AssertionError(f"No finding of kind {kind}; got {[item.kind for item in findings]}")


class temporary_source:
    def __init__(self, source: str, filename: str) -> None:
        self.source = source
        self.filename = filename
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / self.filename
        self.path.write_text(normalise_source(self.source), encoding="utf-8")
        return self.path

    def __exit__(self, *_exc: object) -> None:
        if self.tmp is not None:
            self.tmp.cleanup()


def normalise_source(source: str) -> str:
    return textwrap.dedent(source).strip() + "\n"


GOLDEN_ROOT = PLUGIN_ROOT / "tests" / "fixtures" / "golden"


if __name__ == "__main__":
    unittest.main()
