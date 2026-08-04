from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts" / "complexity"
sys.path.insert(0, str(SCRIPT_ROOT))

from heuristic_scanner import (
    python_complexity_score,
    scan_python,
    scan_text,
    scan_text_by_language,
    should_scan_path,
)


class HeuristicScannerScopeRegressionTests(unittest.TestCase):
    def test_nested_function_and_class_bodies_are_scored_independently(self) -> None:
        inner_body = branch_chain("        ")
        method_body = branch_chain("            ")
        source = f"""\
def outer(value):
    class Nested:
        if value:
            marker = value

        def method(value):
{method_body}
            return None

    def inner(value):
{inner_body}
        return None

    if value:
        return inner(value)
    return None
"""
        outer = ast.parse(source).body[0]

        self.assertEqual(python_complexity_score(outer), 2)

        findings = scan_python(Path("sample.py"), Path("."), source)
        complex_symbols = {
            finding.symbol
            for finding in findings
            if finding.kind == "high-function-complexity"
        }
        self.assertNotIn("outer", complex_symbols)
        self.assertIn("outer.inner", complex_symbols)
        self.assertIn("outer.method", complex_symbols)

    def test_nested_function_does_not_inherit_outer_loop_scope(self) -> None:
        source = """
        def outer(items):
            for item in items:
                def inner():
                    return requests.get(item)
                keep(inner)
            return None
        """

        findings = scan_python(
            Path("sample.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        self.assertFalse(
            [
                finding
                for finding in findings
                if finding.kind == "io-in-loop" and finding.symbol == "outer.inner"
            ]
        )

    def test_closed_javascript_loop_does_not_capture_following_top_level_work(self) -> None:
        source = """
        function process(items, others) {
          for (const item of items) {
            handle(item);
          }
          fetch('/later');
          for (const other of others) {
            query(other);
          }
        }
        """

        findings = scan_text(
            Path("sample.js"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        self.assertEqual(
            [(finding.kind, finding.line) for finding in findings],
            [("io-in-loop", 7)],
        )

    def test_nested_javascript_loops_remain_nested(self) -> None:
        source = """
        function process(items) {
          for (const item of items) {
            for (const child of item.children) {
              query(child);
            }
          }
        }
        """

        findings = scan_text(
            Path("sample.js"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        nested = [finding for finding in findings if finding.kind == "nested-or-callback-loop"]
        self.assertEqual(
            [(finding.line, finding.evidence) for finding in nested],
            [(3, "for (const child of item.children) {")],
        )
        self.assertEqual(
            [
                (finding.kind, finding.line)
                for finding in findings
                if finding.kind == "io-in-loop"
            ],
            [("io-in-loop", 4)],
        )

    def test_javascript_allman_loop_binds_after_blank_and_comment_lines(self) -> None:
        source = """
        function process(items) {
          for (const item of items)

          // The opening brace is intentionally separated from the header.
          {
            fetch(item);
          }
          fetch('/later');
        }
        """

        findings = scan_text(
            Path("sample.js"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        self.assertEqual(
            [(finding.kind, finding.line) for finding in findings],
            [("io-in-loop", 6)],
        )

    def test_java_allman_loop_binds_and_closes_at_matching_brace(self) -> None:
        source = """
        class Worker {
          void process(List<Item> items) {
            for (Item item : items)

            // Java Allman style also permits comments between header and brace.
            {
              client.request(item);
            }
            client.request(later);
          }
        }
        """

        findings = scan_text_by_language(
            Path("Sample.JAVA"),
            Path("."),
            textwrap.dedent(source).strip() + "\n",
        )

        self.assertEqual(
            [(finding.kind, finding.line) for finding in findings],
            [("io-in-loop", 7)],
        )

    def test_nested_javascript_allman_loops_remain_nested(self) -> None:
        source = """
        function process(items) {
          for (const item of items)
          {
            for (const child of item.children)

            {
              query(child);
            }
          }
          query(later);
        }
        """

        findings = scan_text(
            Path("sample.js"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        nested = [finding for finding in findings if finding.kind == "nested-or-callback-loop"]
        self.assertEqual(
            [(finding.line, finding.evidence) for finding in nested],
            [(4, "for (const child of item.children)")],
        )
        self.assertEqual(
            [(finding.kind, finding.line) for finding in findings if finding.kind == "io-in-loop"],
            [("io-in-loop", 7)],
        )

    def test_render_detection_and_case_insensitive_suffix_dispatch_are_preserved(self) -> None:
        render_source = """
        function RenderItems(items) {
          return items.filter((item) => item.active).map((item) => item.name);
        }
        """
        render_findings = scan_text_by_language(
            Path("sample.JS"),
            Path("."),
            textwrap.dedent(render_source).strip() + "\n",
        )

        self.assertTrue(
            [finding for finding in render_findings if finding.kind == "render-derived-work"]
        )
        self.assertTrue(should_scan_path(Path("sample.PY")))

        python_findings = scan_text_by_language(
            Path("sample.PY"),
            Path("."),
            "def collect(items):\n    for item in items:\n        requests.get(item)\n",
        )
        self.assertTrue(
            [
                finding
                for finding in python_findings
                if finding.kind == "io-in-loop" and finding.symbol == "collect"
            ]
        )


def branch_chain(indent: str) -> str:
    return "\n".join(
        f"{indent}if value == {index}:\n{indent}    return {index}"
        for index in range(15)
    )


if __name__ == "__main__":
    unittest.main()
