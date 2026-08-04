from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .constants import JS_TEST_SUFFIXES, PYTHON_SUFFIX
from .files import line_count, rel
from .javascript_parser import javascript_functions_from_file, javascript_parse_result
from .models import AdapterRuntime, Diagnostic, FunctionInfo, PreparedFile, TestFileInfo, TestParseResult
from .python_parser import functions_from_tree, python_test_parse_result


@dataclass(frozen=True)
class AdapterCapabilities:
    name: str
    version: str
    suffixes: frozenset[str]
    languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    capability: str


@dataclass(frozen=True)
class PreparationResult:
    prepared: PreparedFile | None
    failure: Diagnostic | None = None


@dataclass
class RuntimeCounter:
    attempted_source_files: int = 0
    attempted_test_files: int = 0
    analysed_source_files: int = 0
    analysed_test_files: int = 0

    def attempted(self, role: str) -> None:
        if role == "source":
            self.attempted_source_files += 1
        else:
            self.attempted_test_files += 1

    def analysed(self, role: str) -> None:
        if role == "source":
            self.analysed_source_files += 1
        else:
            self.analysed_test_files += 1

    def freeze(self) -> AdapterRuntime:
        attempted = self.attempted_source_files + self.attempted_test_files
        analysed = self.analysed_source_files + self.analysed_test_files
        return AdapterRuntime(
            analysed_source_files=self.analysed_source_files,
            analysed_test_files=self.analysed_test_files,
            attempted_source_files=self.attempted_source_files,
            attempted_test_files=self.attempted_test_files,
            failed_files=attempted - analysed,
            state="not-used" if attempted == 0 else "complete" if attempted == analysed else "partial",
        )


class SourceTestAdapter:
    capabilities: AdapterCapabilities

    def supports(self, path: Path) -> bool:
        return path.suffix in self.capabilities.suffixes

    def prepare(self, path: Path, text: str, root: Path) -> PreparationResult:
        raise NotImplementedError

    def source_functions(self, prepared: PreparedFile) -> list[FunctionInfo]:
        raise NotImplementedError

    def test_file(self, prepared: PreparedFile) -> TestFileInfo:
        raise NotImplementedError

    def call_locations(self, prepared: PreparedFile) -> set[tuple[str, int]]:
        raise NotImplementedError


class PythonAstAdapter(SourceTestAdapter):
    capabilities = AdapterCapabilities(
        name="python-ast",
        version="1",
        suffixes=frozenset({PYTHON_SUFFIX}),
        languages=("python",),
        frameworks=("pytest", "unittest", "Frappe test bases"),
        capability="AST-based source and test structure with static assertion signals",
    )

    def prepare(self, path: Path, text: str, root: Path) -> PreparationResult:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return PreparationResult(
                prepared=None,
                failure=Diagnostic(
                    severity="warning",
                    code="python-parse-failed",
                    path=rel(path, root),
                    message=f"Python parse failed at line {exc.lineno}: {exc.msg}",
                ),
            )
        return PreparationResult(PreparedFile(path, text, self.capabilities.name, tree))

    def source_functions(self, prepared: PreparedFile) -> list[FunctionInfo]:
        return functions_from_tree(prepared.path, python_tree(prepared))

    def test_file(self, prepared: PreparedFile) -> TestFileInfo:
        return test_file_from_result(
            prepared.path,
            prepared.text,
            python_test_parse_result(prepared.path, python_tree(prepared)),
        )

    def call_locations(self, prepared: PreparedFile) -> set[tuple[str, int]]:
        return {
            (name, node.lineno)
            for node in ast.walk(python_tree(prepared))
            if isinstance(node, ast.Call)
            for name in [python_call_name(node)]
            if name
        }


class JavaScriptStaticAdapter(SourceTestAdapter):
    capabilities = AdapterCapabilities(
        name="javascript-static",
        version="1",
        suffixes=frozenset(JS_TEST_SUFFIXES),
        languages=("javascript", "jsx", "typescript", "tsx"),
        frameworks=("Jest-style globals", "Vitest"),
        capability="pattern-based function and test discovery; not a full JavaScript parser",
    )

    def prepare(self, path: Path, text: str, root: Path) -> PreparationResult:
        return PreparationResult(PreparedFile(path, text, self.capabilities.name, text))

    def source_functions(self, prepared: PreparedFile) -> list[FunctionInfo]:
        return javascript_functions_from_file(prepared.path, javascript_text(prepared))

    def test_file(self, prepared: PreparedFile) -> TestFileInfo:
        text = javascript_text(prepared)
        return test_file_from_result(prepared.path, text, javascript_parse_result(prepared.path, text))

    def call_locations(self, prepared: PreparedFile) -> set[tuple[str, int]]:
        text = javascript_text(prepared)
        return {
            (match.group(1), text.count("\n", 0, match.start()) + 1)
            for match in re.finditer(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", text)
        }


SOURCE_TEST_ADAPTERS: tuple[SourceTestAdapter, ...] = (PythonAstAdapter(), JavaScriptStaticAdapter())


def adapter_for(path: Path) -> SourceTestAdapter | None:
    return next((adapter for adapter in SOURCE_TEST_ADAPTERS if adapter.supports(path)), None)


def adapter_by_name(name: str) -> SourceTestAdapter:
    return next(adapter for adapter in SOURCE_TEST_ADAPTERS if adapter.capabilities.name == name)


def prepare_analysis_files(
    attempted_source_files: list[Path],
    attempted_test_files: list[Path],
    texts: dict[Path, str],
    unavailable_paths: set[Path],
    root: Path,
) -> tuple[dict[Path, PreparedFile], list[Diagnostic], dict[str, AdapterRuntime]]:
    prepared: dict[Path, PreparedFile] = {}
    failures: list[Diagnostic] = []
    counters = {adapter.capabilities.name: RuntimeCounter() for adapter in SOURCE_TEST_ADAPTERS}
    for role, paths in (("source", attempted_source_files), ("test", attempted_test_files)):
        for path in paths:
            adapter = adapter_for(path)
            if adapter is None:
                raise ValueError(f"No adapter for supported path: {path}")
            counter = counters[adapter.capabilities.name]
            counter.attempted(role)
            if path in unavailable_paths:
                continue
            result = adapter.prepare(path, texts[path], root)
            if result.failure is not None:
                failures.append(result.failure)
                continue
            if result.prepared is None:
                raise RuntimeError(f"Adapter {adapter.capabilities.name} returned neither a file nor a failure")
            prepared[path] = result.prepared
            counter.analysed(role)
    runtime = {name: counter.freeze() for name, counter in counters.items()}
    return prepared, failures, runtime


def python_tree(prepared: PreparedFile) -> ast.AST:
    if not isinstance(prepared.artifact, ast.AST):
        raise TypeError(f"Python adapter received non-AST artifact for {prepared.path}")
    return prepared.artifact


def javascript_text(prepared: PreparedFile) -> str:
    if not isinstance(prepared.artifact, str):
        raise TypeError(f"JavaScript adapter received non-text artifact for {prepared.path}")
    return prepared.artifact


def test_file_from_result(path: Path, text: str, result: TestParseResult) -> TestFileInfo:
    return TestFileInfo(
        path,
        result.framework,
        line_count(text),
        len(result.cases),
        sum(case.assertions for case in result.cases),
        result.cases,
        result.helpers,
        result.fixtures,
    )


def python_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""
