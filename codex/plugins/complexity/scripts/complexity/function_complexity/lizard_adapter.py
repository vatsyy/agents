from __future__ import annotations

import csv
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .heuristics import rank_complexity
from .models import FunctionMetric

CAPABILITY_VERSION = "1.23"
SUPPORTED_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cjs",
        ".cpp",
        ".cs",
        ".cxx",
        ".erl",
        ".es",
        ".escript",
        ".f",
        ".f03",
        ".f08",
        ".f70",
        ".f90",
        ".f95",
        ".for",
        ".fpp",
        ".ftn",
        ".gd",
        ".go",
        ".h",
        ".hpp",
        ".hrl",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".lua",
        ".m",
        ".mjs",
        ".mm",
        ".pck",
        ".php",
        ".pkb",
        ".pks",
        ".pl",
        ".plb",
        ".pls",
        ".pm",
        ".r",
        ".rb",
        ".rs",
        ".scala",
        ".sol",
        ".sql",
        ".st",
        ".swift",
        ".ts",
        ".tsx",
        ".ttcn",
        ".ttcnpp",
        ".vue",
        ".zig",
    }
)


class LizardBatchError(RuntimeError):
    def __init__(
        self,
        rows: Sequence[tuple[Path, FunctionMetric]],
        completed_paths: Sequence[Path],
        failed_paths: Sequence[Path],
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.rows = tuple(rows)
        self.completed_paths = tuple(completed_paths)
        self.failed_paths = tuple(failed_paths)
        self.reason = reason


def supports_path(path: Path) -> bool:
    """Return whether Lizard 1.23 has a reader for this file suffix."""
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def analyse_with_lizard(path: Path) -> list[FunctionMetric]:
    try:
        import lizard  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional adapter import may fail in many ways
        return analyse_with_lizard_cli(path)

    info = lizard.analyze_file(str(path))
    return [metric_from_lizard_function(function) for function in info.function_list]


def analyse_with_lizard_cli(path: Path) -> list[FunctionMetric]:
    if shutil.which("lizard") is None:
        raise SystemExit(
            "Non-Python analysis requires lizard. Install it with `python3 -m pip install lizard` "
            "or use a Python file supported by the bundled AST analyser."
        )

    proc = subprocess.run(
        ["lizard", "--csv", str(path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "lizard failed")
    return parse_lizard_csv(proc.stdout)


def analyse_many_with_lizard_cli(paths: Sequence[Path]) -> list[tuple[Path, FunctionMetric]]:
    if not paths:
        return []
    if shutil.which("lizard") is None:
        raise SystemExit(
            "Non-Python analysis requires lizard. Install it with `python3 -m pip install lizard` "
            "or skip non-Python files in the integrated repo workflow."
        )
    rows: list[tuple[Path, FunctionMetric]] = []
    completed_paths: list[Path] = []
    chunks = path_chunks(paths, 100)
    for index, chunk in enumerate(chunks):
        try:
            rows.extend(analyse_lizard_chunk(chunk))
        except (Exception, SystemExit) as error:
            failed_paths = [path for remaining in chunks[index:] for path in remaining]
            reason = str(error) or type(error).__name__
            raise LizardBatchError(
                rows, completed_paths, failed_paths, reason
            ) from error
        completed_paths.extend(chunk)
    return rows


def analyse_lizard_chunk(paths: Sequence[Path]) -> list[tuple[Path, FunctionMetric]]:
    proc = subprocess.run(
        ["lizard", "--csv", *(str(path) for path in paths)],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "lizard failed")
    return parse_lizard_csv_with_paths(proc.stdout)


def path_chunks(paths: Sequence[Path], size: int) -> list[Sequence[Path]]:
    return [paths[index : index + size] for index in range(0, len(paths), size)]


def metric_from_lizard_function(function: object) -> FunctionMetric:
    name = str(getattr(function, "long_name", "") or getattr(function, "name", ""))
    start = int(getattr(function, "start_line", 0))
    end = int(getattr(function, "end_line", 0)) or None
    loc = int(getattr(function, "nloc", 0)) or ((end - start + 1) if end else None)
    complexity = int(getattr(function, "cyclomatic_complexity", 0))
    return blank_metric(
        name=name,
        kind="function",
        start=start,
        end=end,
        loc=loc,
        params=int(getattr(function, "parameter_count", 0)),
        cyclomatic=complexity,
        risk=rank_complexity(complexity),
    )


def parse_lizard_csv(output: str) -> list[FunctionMetric]:
    return parse_lizard_lines(lizard_output_lines(output))


def parse_lizard_csv_with_paths(output: str) -> list[tuple[Path, FunctionMetric]]:
    return parse_lizard_path_lines(lizard_output_lines(output))


def lizard_output_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.strip()]


def parse_lizard_path_lines(lines: list[str]) -> list[tuple[Path, FunctionMetric]]:
    if not lines:
        return []
    if has_lizard_header(lines[0]):
        return parse_lizard_dict_rows_with_paths(lines)
    return [metric_with_path_from_lizard_values(row) for row in csv.reader(lines)]


def parse_lizard_lines(lines: list[str]) -> list[FunctionMetric]:
    if not lines:
        return []
    if has_lizard_header(lines[0]):
        return parse_lizard_dict_rows(lines)
    return [metric_from_lizard_values(row) for row in csv.reader(lines)]


def parse_lizard_dict_rows(lines: list[str]) -> list[FunctionMetric]:
    rows = list(csv.DictReader(lines))
    return [metric_from_lizard_row(row) for row in rows]


def parse_lizard_dict_rows_with_paths(lines: list[str]) -> list[tuple[Path, FunctionMetric]]:
    rows = list(csv.DictReader(lines))
    return [(lizard_row_path(row), metric_from_lizard_row(row)) for row in rows]


def has_lizard_header(line: str) -> bool:
    lowered = line.lower()
    return "ccn" in lowered and ("function" in lowered or "location" in lowered)


def metric_from_lizard_values(row: list[str]) -> FunctionMetric:
    values = padded_lizard_row(row)
    complexity = parse_int(values[1])
    start = parse_int(values[9])
    end = parse_int(values[10]) or None
    return blank_metric(
        name=values[7] or values[5],
        kind="function",
        start=start,
        end=end,
        loc=parse_optional_int(values[0]),
        params=parse_optional_int(values[3]),
        cyclomatic=complexity,
        risk=rank_complexity(complexity),
    )


def metric_with_path_from_lizard_values(row: list[str]) -> tuple[Path, FunctionMetric]:
    values = padded_lizard_row(row)
    return Path(values[6]), metric_from_lizard_values(row)


def padded_lizard_row(row: list[str]) -> list[str]:
    return [*row, *([""] * max(0, 11 - len(row)))]


def metric_from_lizard_row(row: dict[str, str]) -> FunctionMetric:
    complexity = parse_int(row.get("CCN"))
    start = parse_int(row.get("start line"))
    end = parse_int(row.get("end line")) or None
    return blank_metric(
        name=row.get("function", "") or row.get("name", ""),
        kind="function",
        start=start,
        end=end,
        loc=lizard_loc(row, start, end),
        params=parse_optional_int(row.get("param")),
        cyclomatic=complexity,
        risk=rank_complexity(complexity),
    )


def lizard_row_path(row: dict[str, str]) -> Path:
    return Path(row.get("filename", "") or row.get("file", "") or row.get("location", ""))


def lizard_loc(row: dict[str, str], start: int, end: int | None) -> int | None:
    loc = parse_int(row.get("NLOC"))
    if loc:
        return loc
    if end:
        return end - start + 1
    return None


def parse_int(value: str | None) -> int:
    return int(value or 0)


def blank_metric(
    *,
    name: str,
    kind: str,
    start: int,
    end: int | None,
    loc: int | None,
    params: int | None,
    cyclomatic: int,
    risk: str,
) -> FunctionMetric:
    return FunctionMetric(
        name=name,
        kind=kind,
        start=start,
        end=end,
        loc=loc,
        sloc=None,
        params=params,
        statements=None,
        returns=None,
        branches=None,
        loops=None,
        exceptions=None,
        bool_ops=None,
        comprehensions=None,
        calls=None,
        fan_out=None,
        called_symbols="",
        internal_fan_in=None,
        internal_fan_out=None,
        max_nesting=None,
        max_loop_depth=None,
        cyclomatic=cyclomatic,
        cognitive=None,
        halstead_vocab=None,
        halstead_length=None,
        halstead_volume=None,
        halstead_difficulty=None,
        halstead_effort=None,
        maintainability_index=None,
        direct_recursion=None,
        indirect_recursion=None,
        awaits=None,
        task_calls=None,
        lock_calls=None,
        raises=None,
        assignments=None,
        global_writes=None,
        mutations=None,
        allocation_ops=None,
        max_literal_size=None,
        db_calls=None,
        network_calls=None,
        file_calls=None,
        subprocess_calls=None,
        io_calls_in_loops=None,
        n_plus_one_risk=None,
        time_complexity_hint="",
        space_complexity_hint="",
        repo_references=None,
        git_commits=None,
        git_churn_lines=None,
        coverage_percent=None,
        review_flags="",
        risk=risk,
        evidence="lizard-derived metric row; Python AST-only detail is unavailable",
        claim_type="deterministic lizard metrics with limited detail",
        confidence="medium: lizard reports cyclomatic/LOC/name; Python-only fields are blank",
        calibration=(
            "Non-Python metrics are lower-detail than Python AST metrics. "
            "Treat blank fields as unavailable, not zero."
        ),
    )


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
