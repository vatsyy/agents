from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .behaviour import assertion_kinds, mock_count, risk_notes, test_confidence
from .constants import PYTHON_FRAMEWORK_TEST_BASES, PYTHON_SUFFIX, PYTHON_TEST_LIFECYCLE_NAMES
from .files import read_text
from .models import FunctionInfo, TestCaseInfo, TestParseResult


def collect_functions(paths: list[Path]) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []
    for path in paths:
        functions.extend(functions_from_file(path))
    return sorted_functions(functions)


def functions_from_file(path: Path) -> list[FunctionInfo]:
    if path.suffix != PYTHON_SUFFIX:
        return []
    return functions_from_text(path, read_text(path))


def functions_from_text(path: Path, text: str) -> list[FunctionInfo]:
    if path.suffix != PYTHON_SUFFIX:
        return []
    tree = parse_python_text(text)
    if tree is None:
        return []
    return functions_from_tree(path, tree)


def functions_from_tree(path: Path, tree: ast.AST) -> list[FunctionInfo]:
    visitor = FunctionVisitor(path)
    visitor.visit(tree)
    return visitor.functions


def parse_python_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(read_text(path))
    except SyntaxError:
        return None


def parse_python_text(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def sorted_functions(functions: list[FunctionInfo]) -> list[FunctionInfo]:
    return sorted(functions, key=lambda item: (str(item.path), item.line, item.qualified_name))


class FunctionVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.class_stack: list[str] = []
        self.functions: list[FunctionInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._record(node, async_function=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._record(node, async_function=True)
        self.generic_visit(node)

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef, async_function: bool) -> None:
        qualified = qualify_function_name(self.class_stack, node.name)
        decorators = [safe_unparse(decorator) for decorator in node.decorator_list]
        self.functions.append(build_function_info(node, qualified, decorators, self.path, async_function))


def qualify_function_name(class_stack: list[str], name: str) -> str:
    return ".".join([*class_stack, name]) if class_stack else name


def build_function_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualified: str,
    decorators: list[str],
    path: Path,
    async_function: bool,
) -> FunctionInfo:
    return FunctionInfo(
        name=node.name,
        qualified_name=qualified,
        path=path,
        line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno),
        is_method="." in qualified,
        async_function=async_function,
        decorators=decorators,
    )


def python_test_cases(path: Path, tree: ast.AST) -> list[TestCaseInfo]:
    return python_test_parse_result(path, tree).cases


def python_test_parse_result(path: Path, tree: ast.AST) -> TestParseResult:
    visitor = PythonTestVisitor(path)
    visitor.visit(tree)
    return TestParseResult(visitor.cases, visitor.helpers, visitor.fixtures, visitor.framework())


class PythonClassContext:
    def __init__(self, name: str, bases: list[str]) -> None:
        self.name = name
        self.bases = bases


class PythonTestVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.class_stack: list[PythonClassContext] = []
        self.function_depth = 0
        self.cases: list[TestCaseInfo] = []
        self.helpers: list[str] = []
        self.fixtures: list[str] = []
        self.frameworks: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.class_stack.append(PythonClassContext(node.name, base_names(node)))
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.record_function(node)
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1

    def record_function(self, node: ast.FunctionDef) -> None:
        if self.record_fixture_if_needed(node):
            return
        if self.record_test_if_needed(node):
            return
        self.record_helper_if_needed(node)

    def record_fixture_if_needed(self, node: ast.FunctionDef) -> bool:
        if is_fixture(node):
            self.record_fixture(node)
            return True
        return False

    def record_test_if_needed(self, node: ast.FunctionDef) -> bool:
        if self._is_test(node):
            self.record_test_case(node)
            return True
        return False

    def record_helper_if_needed(self, node: ast.FunctionDef) -> None:
        if self.function_depth > 0:
            self.helpers.append(node.name)

    def _is_test(self, node: ast.FunctionDef) -> bool:
        if self.function_depth > 0 or is_fixture(node):
            return False
        if is_lifecycle_method(node.name):
            return False
        return is_test_function(node, self.class_stack)

    def record_fixture(self, node: ast.FunctionDef) -> None:
        self.fixtures.append(node.name)
        self.frameworks.add("pytest/python")

    def record_test_case(self, node: ast.FunctionDef) -> None:
        framework = framework_for_python_test(self.class_stack)
        self.frameworks.add(framework)
        self.cases.append(build_python_test_case(node, self.class_stack, self.path, framework))

    def framework(self) -> str:
        if len(self.frameworks) == 1:
            return next(iter(self.frameworks))
        if self.frameworks:
            return "python/mixed"
        return "python"


def base_names(node: ast.ClassDef) -> list[str]:
    return [name_from_expr(base) for base in node.bases]


def name_from_expr(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = name_from_expr(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return safe_unparse(node)


def is_fixture(node: ast.FunctionDef) -> bool:
    return any("fixture" in safe_unparse(decorator) for decorator in node.decorator_list)


def is_lifecycle_method(name: str) -> bool:
    return name in PYTHON_TEST_LIFECYCLE_NAMES


def is_test_function(node: ast.FunctionDef, class_stack: list[PythonClassContext]) -> bool:
    if not node.name.startswith("test"):
        return False
    if not class_stack:
        return node.name.startswith("test_")
    return has_test_class(class_stack)


def has_test_class(class_stack: list[PythonClassContext]) -> bool:
    return any(is_test_class(context) for context in class_stack)


def is_test_class(context: PythonClassContext) -> bool:
    return context.name.startswith("Test") or is_unittest_class(context) or is_framework_test_class(context)


def is_unittest_class(context: PythonClassContext) -> bool:
    return any(base.endswith("TestCase") and base not in PYTHON_FRAMEWORK_TEST_BASES for base in context.bases)


def is_framework_test_class(context: PythonClassContext) -> bool:
    return any(base in PYTHON_FRAMEWORK_TEST_BASES for base in context.bases)


def framework_for_python_test(class_stack: list[PythonClassContext]) -> str:
    return framework_for_context(current_class_context(class_stack))


def current_class_context(class_stack: list[PythonClassContext]) -> PythonClassContext | None:
    return class_stack[-1] if class_stack else None


def framework_for_context(context: PythonClassContext | None) -> str:
    if context is None:
        return "pytest/python"
    return framework_for_class_context(context)


def framework_for_class_context(context: PythonClassContext) -> str:
    if is_framework_test_class(context):
        return "framework-adapter/python"
    if is_unittest_class(context):
        return "unittest/python"
    return "pytest/python"


def build_python_test_case(
    node: ast.FunctionDef,
    class_stack: list[PythonClassContext],
    path: Path,
    framework: str,
) -> TestCaseInfo:
    samples = python_assertion_samples(node)
    body_text = safe_unparse(node)
    mocks = mock_count(body_text.lower())
    assertions = count_assertions(node)
    branches = count_branches(node)
    return TestCaseInfo(
        name=qualify_test_name(class_stack, node.name),
        path=path,
        line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno),
        assertions=assertions,
        branches=branches,
        fixtures=fixture_names(node),
        parametrized=is_parametrized(node),
        framework=framework,
        assertion_kinds=assertion_kinds(samples, body_text),
        assertion_samples=samples,
        mock_count=mocks,
        confidence=test_confidence(assertions, mocks),
        risk_notes=risk_notes(assertions, mocks, branches),
    )


def qualify_test_name(class_stack: list[PythonClassContext], name: str) -> str:
    names = [context.name for context in class_stack]
    return qualify_function_name(names, name)


def fixture_names(node: ast.FunctionDef) -> list[str]:
    return [arg.arg for arg in node.args.args if arg.arg != "self"]


def count_assertions(node: ast.AST) -> int:
    return sum(assertion_weight(child) for child in walk_body_without_nested_defs(node))


def python_assertion_samples(node: ast.AST) -> list[str]:
    samples = [safe_unparse(child) for child in walk_body_without_nested_defs(node) if is_assertion_node(child)]
    return [sample for sample in samples if sample][:3]


def is_assertion_node(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call):
        return is_assertion_call(node)
    return False


def assertion_weight(node: ast.AST) -> int:
    if isinstance(node, ast.Assert):
        return 1
    if isinstance(node, ast.Call):
        return int(is_assertion_call(node))
    return 0


def is_assertion_call(node: ast.Call) -> bool:
    name = call_name(node)
    return name.startswith("assert") or ".assert" in name


def count_branches(node: ast.AST) -> int:
    branch_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
    return sum(1 for child in walk_body_without_nested_defs(node) if isinstance(child, branch_types))


def walk_body_without_nested_defs(node: ast.AST) -> list[ast.AST]:
    body = getattr(node, "body", [])
    nodes: list[ast.AST] = []
    stack = list(reversed(body))
    while stack:
        child = stack.pop()
        nodes.append(child)
        if is_nested_definition(child):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(child))))
    return nodes


def is_nested_definition(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))


def is_parametrized(node: ast.FunctionDef) -> bool:
    return any("parametrize" in safe_unparse(decorator) for decorator in node.decorator_list)


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return attribute_call_name(func)
    return ""


def attribute_call_name(func: ast.Attribute) -> str:
    prefix = name_prefix(func.value)
    return f"{prefix}{func.attr}"


def name_prefix(node: ast.AST) -> str:
    return f"{node.id}." if isinstance(node, ast.Name) else ""


def safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""
