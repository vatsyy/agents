from __future__ import annotations

from pathlib import Path

from .adapters import adapter_by_name, adapter_for
from .files import read_text
from .models import PreparedFile, TestCaseInfo, TestFileInfo


def collect_tests(
    paths: list[Path],
    prepared_files: dict[Path, PreparedFile],
) -> list[TestFileInfo]:
    return [adapter_by_name(prepared_files[path].adapter_name).test_file(prepared_files[path]) for path in sorted(paths)]


def parse_test_file(path: Path) -> TestFileInfo:
    return parse_test_text(path, read_text(path))


def parse_test_text(path: Path, text: str) -> TestFileInfo:
    adapter = adapter_for(path)
    if adapter is None:
        raise ValueError(f"No test adapter for supported path: {path}")
    result = adapter.prepare(path, text, path.parent)
    if result.prepared is None:
        raise ValueError(result.failure.message if result.failure else f"Adapter failed for {path}")
    return adapter.test_file(result.prepared)


def sum_assertions(cases: list[TestCaseInfo]) -> int:
    return sum(case.assertions for case in cases)


def sum_test_cases(tests: list[TestFileInfo]) -> int:
    return sum(info.test_count for info in tests)
