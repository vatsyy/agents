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

    def test_child_collection_names_and_subscripts_are_traversal_not_nested_scans(self) -> None:
        source = """
        def visit(graph):
            for node, children in graph.items():
                for child in children:
                    keep(child)
                for child in graph[node]:
                    keep(child)
        """

        findings = scan_python(
            Path("graph.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        traversals = [item for item in findings if item.kind == "nested-traversal"]
        self.assertEqual([item.line for item in traversals], [3, 5])
        self.assertTrue(
            all(item.loop_classification == "traversal loop" for item in traversals)
        )
        self.assertFalse([item for item in findings if item.kind == "nested-loop"])

    def test_outer_name_in_generator_filter_does_not_hide_repeated_full_scan(self) -> None:
        source = """
        def compare(groups, candidates):
            for group in groups:
                for candidate in (item for item in candidates if item not in group):
                    keep(candidate)
        """

        findings = scan_python(
            Path("compare.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        nested = [item for item in findings if item.kind == "nested-loop"]
        self.assertEqual([item.line for item in nested], [3])

    def test_outer_name_passed_to_iterator_factory_is_traversal_evidence(self) -> None:
        source = """
        def index_calls(test_texts):
            for path, text in test_texts.items():
                for name, line in call_locations(path, text):
                    keep(name, line)
        """

        findings = scan_python(
            Path("grading.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        traversals = [item for item in findings if item.kind == "nested-traversal"]
        self.assertEqual([item.line for item in traversals], [3])
        self.assertFalse([item for item in findings if item.kind == "nested-loop"])

    def test_nested_worklist_loop_is_traversal_not_a_quadratic_scan(self) -> None:
        source = """
        def visit(graph):
            for start in graph:
                stack = [start]
                while stack:
                    node = stack.pop()
                    stack.extend(graph[node])
        """

        findings = scan_python(
            Path("graph.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        traversal = next(item for item in findings if item.kind == "nested-traversal")
        self.assertEqual(traversal.line, 4)
        self.assertEqual(traversal.loop_classification, "traversal loop")
        self.assertFalse([item for item in findings if item.kind == "nested-loop"])

    def test_per_directory_sort_is_calibrated_as_traversal_work(self) -> None:
        source = """
        def inventory(root, excluded):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(name for name in dirnames if name not in excluded)
        """

        findings = scan_python(
            Path("inventory.py"), Path("."), textwrap.dedent(source).strip() + "\n"
        )

        sort_finding = next(item for item in findings if item.kind == "sort-in-loop")
        self.assertEqual(sort_finding.confidence, "low")
        self.assertEqual(sort_finding.loop_classification, "traversal loop")

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
