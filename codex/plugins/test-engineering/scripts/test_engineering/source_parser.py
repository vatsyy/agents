from __future__ import annotations

from pathlib import Path

from .adapters import adapter_by_name, adapter_for
from .files import read_text
from .models import FunctionInfo, PreparedFile
from .python_parser import sorted_functions


def collect_functions(
    paths: list[Path],
    prepared_files: dict[Path, PreparedFile],
) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []
    for path in paths:
        prepared = prepared_files[path]
        functions.extend(adapter_by_name(prepared.adapter_name).source_functions(prepared))
    return sorted_functions(functions)


def source_functions_from_file(path: Path) -> list[FunctionInfo]:
    return source_functions_from_text(path, read_text(path))


def source_functions_from_text(path: Path, text: str) -> list[FunctionInfo]:
    adapter = adapter_for(path)
    if adapter is None:
        return []
    result = adapter.prepare(path, text, path.parent)
    return adapter.source_functions(result.prepared) if result.prepared is not None else []
