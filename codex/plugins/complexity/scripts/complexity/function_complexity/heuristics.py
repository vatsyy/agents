from __future__ import annotations

import ast
import math
from collections.abc import Callable, Sequence
from typing import Protocol

MUTATING_METHODS = {
    "add",
    "append",
    "clear",
    "discard",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "update",
    "write",
    "writelines",
}

ALLOCATION_CALLS = {
    "bytes",
    "bytearray",
    "dict",
    "list",
    "set",
    "sorted",
    "tuple",
}

TASK_CALLS = {
    "asyncio.create_task",
    "asyncio.gather",
    "asyncio.wait",
    "asyncio.wait_for",
    "asyncio.to_thread",
}

TASK_CALL_SUFFIXES = (
    ".create_task",
    ".gather",
    ".wait",
    ".wait_for",
    ".to_thread",
)

LOCK_CALLS = {
    "asyncio.Lock",
    "threading.Lock",
    "threading.RLock",
    "multiprocessing.Lock",
}

LOCK_CALL_SUFFIXES = (".acquire", ".release")

DB_PREFIXES = ("frappe.db.", "self.db.", "db.")
DB_SUFFIXES = (".sql", ".execute", ".executemany", ".get_all", ".get_list")
DB_EXACT_NAMES = {"sql", "execute", "executemany", "get_all", "get_list"}
NETWORK_ROOTS = {"requests", "httpx", "urllib", "aiohttp"}
NETWORK_EXACT_NAMES = {"urlopen", "fetch"}
FILE_ROOTS = {"open", "pathlib", "shutil"}
FILE_PARTS = {
    "open",
    "read",
    "read_text",
    "read_bytes",
    "write",
    "write_text",
    "write_bytes",
    "unlink",
    "remove",
    "rename",
}


def classify_call(name: str) -> str | None:
    lowered = name.lower()
    return first_matching_call_category(lowered, tuple(lowered.split(".")))


def first_matching_call_category(lowered: str, parts: tuple[str, ...]) -> str | None:
    for category, predicate in CALL_CLASSIFIERS:
        if predicate(lowered, parts):
            return category
    return None


def is_db_call(lowered: str, _parts: tuple[str, ...]) -> bool:
    return (
        lowered.startswith(DB_PREFIXES)
        or ".db." in lowered
        or lowered.endswith(DB_SUFFIXES)
        or lowered in DB_EXACT_NAMES
    )


def is_network_call(lowered: str, parts: tuple[str, ...]) -> bool:
    return parts[0] in NETWORK_ROOTS or lowered in NETWORK_EXACT_NAMES


def is_subprocess_call(lowered: str, parts: tuple[str, ...]) -> bool:
    return parts[0] == "subprocess" or lowered.startswith("subprocess.")


def is_file_call(_lowered: str, parts: tuple[str, ...]) -> bool:
    return parts[0] in FILE_ROOTS or bool(FILE_PARTS.intersection(parts))


CALL_CLASSIFIERS: tuple[tuple[str, Callable[[str, tuple[str, ...]], bool]], ...] = (
    ("db", is_db_call),
    ("network", is_network_call),
    ("subprocess", is_subprocess_call),
    ("file", is_file_call),
)


class MetricCounter(Protocol):
    """Metric facts consumed by heuristic classification rules."""

    direct_recursion: bool
    max_loop_depth: int
    comprehensions: int
    max_literal_size: int
    allocation_ops: int
    loops: int
    io_calls_in_loops: int
    db_calls: int
    network_calls: int
    file_calls: int
    subprocess_calls: int
    awaits: int
    task_calls: int
    lock_calls: int
    mutations: int
    global_writes: int
    exceptions: int
    raises: int
    cognitive: int


def call_name_for(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if not isinstance(node, ast.Attribute):
        return ""
    return attribute_call_name(node)


def attribute_call_name(node: ast.Attribute) -> str:
    if is_super_call(node.value):
        return f"super.{node.attr}"
    base = call_name_for(node.value)
    return f"{base}.{node.attr}" if base else node.attr


def is_super_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "super"
    )


def is_mutating_target(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute | ast.Subscript)


def time_complexity_hint(counter: MetricCounter) -> str:
    return first_matching_hint(counter, TIME_COMPLEXITY_RULES, "O(1) syntax candidate")


def first_matching_hint(
    counter: MetricCounter,
    rules: Sequence[tuple[Callable[[MetricCounter], bool], str]],
    default: str,
) -> str:
    for predicate, hint in rules:
        if predicate(counter):
            return hint
    return default


TIME_COMPLEXITY_RULES: tuple[tuple[Callable[[MetricCounter], bool], str], ...] = (
    (lambda counter: counter.direct_recursion, "recursive"),
    (lambda counter: counter.max_loop_depth >= 3, "O(n^3+) candidate"),
    (lambda counter: counter.max_loop_depth == 2, "O(n^2) candidate"),
    (
        lambda counter: counter.max_loop_depth == 1 or bool(counter.comprehensions),
        "O(n) candidate",
    ),
)


def space_complexity_hint(counter: MetricCounter) -> str:
    if counter.max_literal_size >= 100 or counter.allocation_ops >= 5:
        return "materialisation-heavy"
    if counter.comprehensions or counter.allocation_ops:
        return "allocates collections"
    return "low allocation signal"


def build_review_flags(
    counter: MetricCounter, cyclomatic: int, sloc: int | None
) -> list[str]:
    return [
        flag
        for flag, applies in review_flag_states(counter, cyclomatic, sloc)
        if applies
    ]


def review_flag_states(
    counter: MetricCounter, cyclomatic: int, sloc: int | None
) -> tuple[tuple[str, bool], ...]:
    return tuple(
        (flag, predicate(counter, cyclomatic, sloc))
        for flag, predicate in REVIEW_FLAG_RULES
    )


ReviewRule = Callable[[MetricCounter, int, int | None], bool]

REVIEW_FLAG_RULES: tuple[tuple[str, ReviewRule], ...] = (
    ("direct recursion", lambda counter, _cyclomatic, _sloc: counter.direct_recursion),
    (
        "review Big-O",
        lambda counter, _cyclomatic, _sloc: counter.loops >= 2
        or counter.max_loop_depth >= 2,
    ),
    ("I/O in loop", lambda counter, _cyclomatic, _sloc: bool(counter.io_calls_in_loops)),
    ("DB access", lambda counter, _cyclomatic, _sloc: bool(counter.db_calls)),
    (
        "N+1 risk",
        lambda counter, _cyclomatic, _sloc: bool(
            counter.io_calls_in_loops and counter.db_calls
        ),
    ),
    ("network access", lambda counter, _cyclomatic, _sloc: bool(counter.network_calls)),
    ("file I/O", lambda counter, _cyclomatic, _sloc: bool(counter.file_calls)),
    ("subprocess", lambda counter, _cyclomatic, _sloc: bool(counter.subprocess_calls)),
    ("async/concurrency", lambda counter, _cyclomatic, _sloc: bool(counter.awaits)),
    ("task fan-out", lambda counter, _cyclomatic, _sloc: bool(counter.task_calls)),
    (
        "lock/concurrency primitive",
        lambda counter, _cyclomatic, _sloc: bool(counter.lock_calls),
    ),
    ("mutation-heavy", lambda counter, _cyclomatic, _sloc: counter.mutations >= 3),
    ("global state write", lambda counter, _cyclomatic, _sloc: bool(counter.global_writes)),
    (
        "allocation pressure",
        lambda counter, _cyclomatic, _sloc: counter.allocation_ops >= 5
        or counter.max_literal_size >= 100,
    ),
    (
        "exception flow",
        lambda counter, _cyclomatic, _sloc: counter.exceptions >= 2
        or bool(counter.raises),
    ),
    (
        "high control-flow complexity",
        lambda counter, cyclomatic, _sloc: cyclomatic >= 11 or counter.cognitive >= 11,
    ),
    (
        "large function",
        lambda _counter, _cyclomatic, sloc: sloc is not None and sloc >= 80,
    ),
)


def rank_complexity(complexity: int) -> str:
    if complexity <= 5:
        return "A"
    if complexity <= 10:
        return "B"
    if complexity <= 20:
        return "C"
    if complexity <= 30:
        return "D"
    return "E"


def calculate_maintainability_index(
    *, volume: float, cyclomatic: int, sloc: int | None
) -> float | None:
    if sloc is None or sloc <= 0:
        return None
    safe_volume = max(volume, 1.0)
    raw = (
        171
        - 5.2 * math.log(safe_volume)
        - 0.23 * cyclomatic
        - 16.2 * math.log(sloc)
    )
    return round(max(0.0, min(100.0, raw * 100 / 171)), 2)
