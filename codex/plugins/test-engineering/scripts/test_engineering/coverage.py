from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .adapters import AdapterCapabilities
from .models import CoverageIndex, CoverageLoadResult, Diagnostic, FunctionInfo


COVERAGE_ADAPTER = AdapterCapabilities(
    name="coverage-xml",
    version="1",
    suffixes=frozenset(),
    languages=("path-and-line based",),
    frameworks=(),
    capability="existing Cobertura-style class and line execution evidence",
)


def empty_coverage() -> CoverageIndex:
    return CoverageIndex({}, {})


def load_coverage(path: Path, root: Path) -> CoverageIndex:
    return load_coverage_result(path, root).index


def load_coverage_result(path: Path | None, root: Path) -> CoverageLoadResult:
    if path is None:
        return CoverageLoadResult(empty_coverage(), "not-requested")
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return coverage_failure("missing", resolved, "Coverage file does not exist.")
    try:
        tree = ET.parse(resolved)
    except ET.ParseError as exc:
        return coverage_failure("malformed", resolved, f"Coverage XML is malformed: {exc}")
    except OSError as exc:
        return coverage_failure("unreadable", resolved, f"Coverage XML could not be read: {exc}")
    invalid_line = first_invalid_line(tree)
    if invalid_line:
        return coverage_failure("malformed", resolved, invalid_line)
    index = coverage_from_tree(tree, root)
    class_count = len(tree.findall(".//class"))
    line_count = sum(len(lines) for lines in index.by_path.values())
    state = "loaded" if class_count and line_count else "empty"
    diagnostic = None
    if state == "empty":
        diagnostic = coverage_diagnostic("coverage-empty", resolved, "Coverage XML contained no usable class line data.")
    return CoverageLoadResult(index, state, resolved, class_count, line_count, diagnostic)


def coverage_failure(state: str, path: Path, message: str) -> CoverageLoadResult:
    return CoverageLoadResult(empty_coverage(), state, path, diagnostic=coverage_diagnostic(f"coverage-{state}", path, message))


def coverage_diagnostic(code: str, path: Path, message: str) -> Diagnostic:
    return Diagnostic(severity="warning", code=code, path=str(path), message=message)


def first_invalid_line(tree: ET.ElementTree) -> str | None:
    for line in tree.findall(".//line"):
        number = line.attrib.get("number")
        hits = line.attrib.get("hits")
        if number is None or not number.isdigit():
            return "Coverage XML contains a line with a missing or nonnumeric number."
        if hits is None or not hits.isdigit():
            return f"Coverage XML line {number} has a missing or nonnumeric hit count."
    return None


def parse_coverage_xml(path: Path) -> ET.ElementTree | None:
    try:
        return ET.parse(path)
    except ET.ParseError:
        return None


def coverage_from_tree(tree: ET.ElementTree, root: Path) -> CoverageIndex:
    coverage: dict[Path, dict[int, int]] = {}
    paths_by_name: dict[str, set[Path]] = {}
    for class_node in tree.findall(".//class"):
        add_class_coverage(coverage, paths_by_name, class_node, root)
    names = {
        name: coverage[next(iter(paths))]
        for name, paths in paths_by_name.items()
        if len(paths) == 1
    }
    return CoverageIndex(coverage, names)


def add_class_coverage(
    coverage: dict[Path, dict[int, int]],
    paths_by_name: dict[str, set[Path]],
    class_node: ET.Element,
    root: Path,
) -> None:
    filename = class_node.attrib.get("filename")
    if not filename:
        return
    path = resolve_coverage_filename(filename, root)
    line_hits = coverage_line_hits(class_node)
    coverage[path] = merge_line_hits(coverage.get(path, {}), line_hits)
    paths_by_name.setdefault(path.name, set()).add(path)


def merge_line_hits(existing: dict[int, int], incoming: dict[int, int]) -> dict[int, int]:
    merged = dict(existing)
    for line, hits in incoming.items():
        merged[line] = min(merged[line], hits) if line in merged else hits
    return merged


def resolve_coverage_filename(filename: str, root: Path) -> Path:
    file_path = Path(filename)
    resolved = file_path if file_path.is_absolute() else root / file_path
    return resolved.resolve()


def coverage_line_hits(class_node: ET.Element) -> dict[int, int]:
    hits: dict[int, int] = {}
    for line in class_node.findall("./lines/line"):
        add_line_hit(hits, line)
    return hits


def add_line_hit(hits: dict[int, int], line: ET.Element) -> None:
    number = line.attrib.get("number")
    if number and number.isdigit():
        hits[int(number)] = parse_hits(line.attrib.get("hits", "0"))


def parse_hits(value: str) -> int:
    if not value.isdigit():
        raise ValueError(f"Coverage hit count must be a nonnegative integer: {value!r}")
    return int(value)


def coverage_status_for(function: FunctionInfo, coverage: CoverageIndex) -> tuple[str, int | None, int | None]:
    if has_no_coverage_data(coverage):
        return "unknown", None, None
    line_hits = coverage_lines_for(function, coverage)
    if line_hits is None:
        return "not-in-report", None, None
    return summarise_function_coverage(function, line_hits)


def has_no_coverage_data(coverage: CoverageIndex) -> bool:
    return not coverage.by_path and not coverage.by_name


def coverage_lines_for(function: FunctionInfo, coverage: CoverageIndex) -> dict[int, int] | None:
    exact = coverage.by_path.get(function.path.resolve())
    return exact if exact is not None else coverage.by_name.get(function.path.name)


def summarise_function_coverage(function: FunctionInfo, line_hits: dict[int, int]) -> tuple[str, int | None, int | None]:
    lines = executable_coverage_lines(function, line_hits)
    if not lines:
        return "not-measured", None, None
    return status_from_covered_lines(count_covered_lines(lines, line_hits), len(lines))


def executable_coverage_lines(function: FunctionInfo, line_hits: dict[int, int]) -> list[int]:
    return [line for line in range(function.line, function.end_line + 1) if line in line_hits]


def count_covered_lines(lines: list[int], line_hits: dict[int, int]) -> int:
    return sum(1 for line in lines if line_hits.get(line, 0) > 0)


def status_from_covered_lines(covered: int, total: int) -> tuple[str, int, int]:
    if covered == 0:
        return "not-covered", 0, total
    if covered == total:
        return "covered", covered, total
    return "partial", covered, total
