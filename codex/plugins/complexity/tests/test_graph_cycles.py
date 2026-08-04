from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts" / "complexity"
sys.path.insert(0, str(SCRIPT_ROOT))

from function_complexity.graph import nodes_in_cycles
from function_complexity.python_ast import analyse_python


class OperationCounter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.edge_visits = 0

    def record(self, count: int) -> None:
        self.edge_visits += count
        if self.edge_visits > self.limit:
            raise AssertionError("cycle analysis exceeded its linear operation budget")


class CountingNeighbours(set[str]):
    def __init__(self, values: set[str], counter: OperationCounter) -> None:
        super().__init__(values)
        self.counter = counter

    def __iter__(self):
        for value in super().__iter__():
            self.counter.record(1)
            yield value

    def difference(self, other):
        self.counter.record(len(self))
        return super().difference(other)


class GraphCycleTests(unittest.TestCase):
    def test_multi_node_cycles_include_every_member(self) -> None:
        graph = {
            "a": {"b"},
            "b": {"c"},
            "c": {"a", "d"},
            "d": {"e"},
            "e": {"d"},
            "sink": set(),
        }

        self.assertEqual(nodes_in_cycles(graph), {"a", "b", "c", "d", "e"})

    def test_disconnected_cycles_do_not_pull_in_acyclic_tails(self) -> None:
        graph = {
            "left_a": {"left_b"},
            "left_b": {"left_a", "left_tail"},
            "left_tail": set(),
            "right_a": {"right_b"},
            "right_b": {"right_a"},
            "isolated": set(),
        }

        self.assertEqual(
            nodes_in_cycles(graph), {"left_a", "left_b", "right_a", "right_b"}
        )

    def test_dense_acyclic_graph_has_no_cycle_nodes(self) -> None:
        nodes = [f"node_{index}" for index in range(24)]
        graph = {
            node: set(nodes[index + 1 :]) for index, node in enumerate(nodes)
        }

        self.assertEqual(nodes_in_cycles(graph), set())

    def test_dense_acyclic_graph_stays_within_linear_operation_budget(self) -> None:
        nodes = [f"node_{index}" for index in range(24)]
        edge_count = len(nodes) * (len(nodes) - 1) // 2
        counter = OperationCounter(limit=8 * (len(nodes) + edge_count))
        graph = {
            node: CountingNeighbours(set(nodes[index + 1 :]), counter)
            for index, node in enumerate(nodes)
        }

        self.assertEqual(nodes_in_cycles(graph), set())
        self.assertLessEqual(counter.edge_visits, 8 * (len(nodes) + edge_count))

    def test_self_calls_remain_direct_not_indirect_recursion(self) -> None:
        self.assertEqual(nodes_in_cycles({"recursive": {"recursive"}}), set())

    def test_cycle_and_review_flags_are_stable_across_runs(self) -> None:
        source = textwrap.dedent(
            """
            def direct():
                return direct()

            def first():
                return second()

            def second():
                return first()

            def plain():
                return 1
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycles.py"
            path.write_text(source, encoding="utf-8")
            first_run = analyse_python(path)
            second_run = analyse_python(path)

        def state(metrics):
            return {
                metric.name: (
                    metric.direct_recursion,
                    metric.indirect_recursion,
                    metric.review_flags,
                )
                for metric in metrics
            }

        expected = {
            "direct": (True, False, "direct recursion"),
            "first": (False, True, "indirect recursion"),
            "second": (False, True, "indirect recursion"),
            "plain": (False, False, ""),
        }
        self.assertEqual(state(first_run), expected)
        self.assertEqual(state(second_run), expected)


if __name__ == "__main__":
    unittest.main()
