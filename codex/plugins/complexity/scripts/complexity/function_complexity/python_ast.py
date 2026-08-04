from __future__ import annotations

import ast
import math
from collections.abc import Sequence
from pathlib import Path

from .graph import enrich_internal_call_graph
from .heuristics import (
    ALLOCATION_CALLS,
    LOCK_CALL_SUFFIXES,
    LOCK_CALLS,
    MUTATING_METHODS,
    TASK_CALL_SUFFIXES,
    TASK_CALLS,
    build_review_flags,
    calculate_maintainability_index,
    call_name_for,
    classify_call,
    is_mutating_target,
    rank_complexity,
    space_complexity_hint,
    time_complexity_hint,
)
from .models import FunctionMetric


class FunctionComplexityVisitor(ast.NodeVisitor):
    def __init__(self, source_lines: Sequence[str]) -> None:
        self.source_lines = source_lines
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.metrics: list[FunctionMetric] = []
        self.calls_by_name: dict[str, set[str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node, "async function")

    def _record_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, default_kind: str
    ) -> None:
        name, kind = self._function_identity(node, default_kind)
        end, loc, sloc = self._function_extent(node)
        counter = self._function_counter(node)
        cyclomatic = counter.cyclomatic()
        self.metrics.append(
            build_function_metric(name, kind, node, end, loc, sloc, counter, cyclomatic)
        )
        self.calls_by_name[name] = set(counter.called_names)

        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def _function_identity(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, default_kind: str
    ) -> tuple[str, str]:
        name_parts = [*self.class_stack, *self.function_stack, node.name]
        kind = "method" if self.class_stack and not self.function_stack else default_kind
        return ".".join(name_parts), kind

    def _function_extent(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> tuple[int | None, int | None, int | None]:
        end = getattr(node, "end_lineno", None)
        loc = (end - node.lineno + 1) if end is not None else None
        sloc = self._function_sloc(node, end)
        return end, loc, sloc

    def _function_sloc(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, end: int | None
    ) -> int | None:
        if end is None:
            return None
        return count_sloc(self.source_lines[node.lineno - 1 : end])

    def _function_counter(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> PythonMetricCounter:
        counter = PythonMetricCounter(
            function_name=node.name,
            source_lines=self.source_lines,
        )
        for child in node.body:
            counter.visit(child)
        return counter


def build_function_metric(
    name: str,
    kind: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    end: int | None,
    loc: int | None,
    sloc: int | None,
    counter: PythonMetricCounter,
    cyclomatic: int,
) -> FunctionMetric:
    halstead = counter.halstead()
    return FunctionMetric(
        name=name,
        kind=kind,
        start=node.lineno,
        end=end,
        loc=loc,
        sloc=sloc,
        params=count_params(node),
        statements=counter.statements,
        returns=counter.returns,
        branches=counter.branches,
        loops=counter.loops,
        exceptions=counter.exceptions,
        bool_ops=counter.bool_ops,
        comprehensions=counter.comprehensions,
        calls=counter.calls,
        fan_out=len(counter.called_names),
        called_symbols=", ".join(sorted(counter.called_names)),
        internal_fan_in=None,
        internal_fan_out=None,
        max_nesting=counter.max_nesting,
        max_loop_depth=counter.max_loop_depth,
        cyclomatic=cyclomatic,
        cognitive=counter.cognitive,
        halstead_vocab=halstead["vocabulary"],
        halstead_length=halstead["length"],
        halstead_volume=round(halstead["volume"], 2),
        halstead_difficulty=round(halstead["difficulty"], 2),
        halstead_effort=round(halstead["effort"], 2),
        maintainability_index=calculate_maintainability_index(
            volume=halstead["volume"],
            cyclomatic=cyclomatic,
            sloc=sloc,
        ),
        direct_recursion=counter.direct_recursion,
        indirect_recursion=False,
        awaits=counter.awaits,
        task_calls=counter.task_calls,
        lock_calls=counter.lock_calls,
        raises=counter.raises,
        assignments=counter.assignments,
        global_writes=counter.global_writes,
        mutations=counter.mutations,
        allocation_ops=counter.allocation_ops,
        max_literal_size=counter.max_literal_size,
        db_calls=counter.db_calls,
        network_calls=counter.network_calls,
        file_calls=counter.file_calls,
        subprocess_calls=counter.subprocess_calls,
        io_calls_in_loops=counter.io_calls_in_loops,
        n_plus_one_risk=counter.io_calls_in_loops > 0 and counter.db_calls > 0,
        time_complexity_hint=time_complexity_hint(counter),
        space_complexity_hint=space_complexity_hint(counter),
        repo_references=None,
        git_commits=None,
        git_churn_lines=None,
        coverage_percent=None,
        review_flags=", ".join(build_review_flags(counter, cyclomatic, sloc)),
        risk=rank_complexity(max(cyclomatic, counter.cognitive)),
        evidence=counter.evidence_summary(),
        calibration=metric_calibration(counter),
    )


def metric_calibration(counter: PythonMetricCounter) -> str:
    notes = ["Deterministic AST metric counts are repeatable."]
    if counter.io_calls_in_loops:
        notes.append("I/O-in-loop is a heuristic risk; validate loop bounds and callee behaviour.")
    if counter.max_loop_depth >= 2:
        notes.append("Big-O hint is syntax-derived; confirm collection sizes before refactoring.")
    if counter.direct_recursion:
        notes.append("Direct recursion is syntactic and should be manually reviewed for termination.")
    return " ".join(notes)


class PythonMetricCounter(ast.NodeVisitor):
    def __init__(self, function_name: str, source_lines: Sequence[str]) -> None:
        self.function_name = function_name
        self.source_lines = source_lines
        self.evidence: list[str] = []
        self.statements = 0
        self.returns = 0
        self.branches = 0
        self.loops = 0
        self.exceptions = 0
        self.bool_ops = 0
        self.comprehensions = 0
        self.asserts = 0
        self.calls = 0
        self.called_names: set[str] = set()
        self.awaits = 0
        self.task_calls = 0
        self.lock_calls = 0
        self.raises = 0
        self.assignments = 0
        self.global_writes = 0
        self.mutations = 0
        self.allocation_ops = 0
        self.max_literal_size = 0
        self.db_calls = 0
        self.network_calls = 0
        self.file_calls = 0
        self.subprocess_calls = 0
        self.io_calls_in_loops = 0
        self.direct_recursion = False
        self.cognitive = 0
        self._nesting = 0
        self._loop_depth = 0
        self.max_nesting = 0
        self.max_loop_depth = 0
        self._operators: dict[str, int] = {}
        self._operands: dict[str, int] = {}

    def cyclomatic(self) -> int:
        return (
            1
            + self.branches
            + self.loops
            + self.exceptions
            + self.bool_ops
            + self.comprehensions
            + self.asserts
        )

    def halstead(self) -> dict[str, float | int]:
        n1 = len(self._operators)
        n2 = len(self._operands)
        big_n1 = sum(self._operators.values())
        big_n2 = sum(self._operands.values())
        vocabulary = n1 + n2
        length = big_n1 + big_n2
        volume = length * math.log2(vocabulary) if vocabulary > 0 else 0.0
        difficulty = (n1 / 2) * (big_n2 / n2) if n2 > 0 else 0.0
        effort = difficulty * volume
        return {
            "vocabulary": vocabulary,
            "length": length,
            "volume": volume,
            "difficulty": difficulty,
            "effort": effort,
        }

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt):
            self.statements += 1
            self._add_operator(type(node).__name__)
        super().generic_visit(node)

    def _visit_decision(self, node: ast.AST, *, branches: int = 1) -> None:
        self.branches += branches
        self._add_operator(type(node).__name__)
        self._add_cognitive(branches)
        self._add_evidence("control flow", node)
        self._visit_nested(node)

    def _visit_loop(self, node: ast.AST) -> None:
        self.loops += 1
        self._add_operator(type(node).__name__)
        self._add_cognitive(1)
        self._add_evidence("loop", node)
        self._loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self._loop_depth)
        self._visit_nested(node)
        self._loop_depth -= 1

    def _visit_nested(self, node: ast.AST) -> None:
        self._nesting += 1
        self.max_nesting = max(self.max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1

    def _add_cognitive(self, amount: int) -> None:
        self.cognitive += amount + self._nesting

    def _add_operator(self, value: str) -> None:
        self._operators[value] = self._operators.get(value, 0) + 1

    def _add_operand(self, value: str) -> None:
        self._operands[value] = self._operands.get(value, 0) + 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        self._visit_decision(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.branches += 1
        self._add_operator("IfExp")
        self._add_cognitive(1)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.exceptions += 1
        self._add_operator("ExceptHandler")
        self._add_cognitive(1)
        self._add_evidence("exception flow", node)
        self._visit_nested(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.asserts += 1
        self._add_operator("Assert")
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        extra = max(0, len(node.values) - 1)
        self.bool_ops += extra
        self.cognitive += extra
        self._add_operator(type(node.op).__name__)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self._add_operator(type(node.op).__name__)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        self._add_operator(type(node.op).__name__)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            self._add_operator(type(op).__name__)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        amount = 1 + len(node.ifs)
        self.comprehensions += amount
        self.cognitive += amount
        self._add_operator("comprehension")
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._visit_decision(node, branches=len(node.cases))

    def visit_Return(self, node: ast.Return) -> None:
        self.returns += 1
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        self.returns += 1
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.returns += 1
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.raises += 1
        self._add_evidence("raise", node)
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self.awaits += 1
        self._add_operator("Await")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_writes += len(node.names)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.assignments += 1
        if any(is_mutating_target(target) for target in node.targets):
            self.mutations += 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.assignments += 1
        if is_mutating_target(node.target):
            self.mutations += 1
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.assignments += 1
        self.mutations += 1
        self._add_operator(type(node.op).__name__)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls += 1
        call_name = call_name_for(node.func)
        if call_name:
            self._record_call_name(call_name, node)
        self._add_operator("Call")
        self.generic_visit(node)

    def _record_call_name(self, call_name: str, node: ast.Call) -> None:
        self.called_names.add(call_name)
        self._add_operand(call_name)
        self._record_direct_recursion(call_name, node)
        category = classify_call(call_name)
        self._record_call_category(category, node)
        self._record_loop_io(category, node)
        self._record_call_traits(call_name)

    def _record_direct_recursion(self, call_name: str, node: ast.Call) -> None:
        recursive_names = {
            self.function_name,
            f"self.{self.function_name}",
            f"cls.{self.function_name}",
        }
        if call_name in recursive_names:
            self.direct_recursion = True
            self._add_evidence("direct recursion", node)

    def _record_call_category(self, category: str | None, node: ast.Call) -> None:
        if category == "db":
            self.db_calls += 1
            self._add_evidence("DB access", node)
            return
        if category == "network":
            self.network_calls += 1
            self._add_evidence("network access", node)
            return
        if category == "file":
            self.file_calls += 1
            self._add_evidence("file I/O", node)
            return
        if category == "subprocess":
            self.subprocess_calls += 1
            self._add_evidence("subprocess", node)

    def _record_loop_io(self, category: str | None, node: ast.Call) -> None:
        if category and self._loop_depth > 0:
            self.io_calls_in_loops += 1
            self._add_evidence("I/O in loop", node)

    def _record_call_traits(self, call_name: str) -> None:
        tail = call_name.split(".")[-1]
        self._record_task_call(call_name)
        self._record_lock_call(call_name)
        self._record_mutating_call(tail)
        self._record_allocation_call(tail)

    def _record_task_call(self, call_name: str) -> None:
        if call_name in TASK_CALLS or call_name.endswith(TASK_CALL_SUFFIXES):
            self.task_calls += 1

    def _record_lock_call(self, call_name: str) -> None:
        if call_name in LOCK_CALLS or call_name.endswith(LOCK_CALL_SUFFIXES):
            self.lock_calls += 1

    def _record_mutating_call(self, tail: str) -> None:
        if tail in MUTATING_METHODS:
            self.mutations += 1

    def _record_allocation_call(self, tail: str) -> None:
        if tail in ALLOCATION_CALLS:
            self.allocation_ops += 1

    def _add_evidence(self, label: str, node: ast.AST) -> None:
        if len(self.evidence) >= 5:
            return
        line = self.source_line(node)
        if line:
            self.evidence.append(f"{label} line {getattr(node, 'lineno', '?')}: {line}")

    def source_line(self, node: ast.AST) -> str:
        lineno = getattr(node, "lineno", 0)
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def evidence_summary(self) -> str:
        return "; ".join(dict.fromkeys(self.evidence))

    def visit_List(self, node: ast.List) -> None:
        self.allocation_ops += 1
        self.max_literal_size = max(self.max_literal_size, len(node.elts))
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self.allocation_ops += 1
        self.max_literal_size = max(self.max_literal_size, len(node.elts))
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        self.allocation_ops += 1
        self.max_literal_size = max(self.max_literal_size, len(node.elts))
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        self.allocation_ops += 1
        self.max_literal_size = max(self.max_literal_size, len(node.keys))
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.allocation_ops += 1
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.allocation_ops += 1
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.allocation_ops += 1
        self._add_evidence("allocation", node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._add_operand(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._add_operand(node.attr)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self._add_operand(repr(node.value))


def analyse_python(path: Path) -> list[FunctionMetric]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"Python parse failed: {exc}") from exc

    visitor = FunctionComplexityVisitor(source.splitlines())
    visitor.visit(tree)
    enrich_internal_call_graph(visitor.metrics, visitor.calls_by_name)
    return visitor.metrics


def count_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    return (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )


def count_sloc(lines: Sequence[str]) -> int:
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))
