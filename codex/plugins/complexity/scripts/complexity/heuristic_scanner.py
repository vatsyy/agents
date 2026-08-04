"""Scan repositories for likely complexity and performance hotspots."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from analysis_contract import PLUGIN_VERSION

SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".java",
    ".go",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".swift",
}

BRACE_DELIMITED_SUFFIXES = SCAN_SUFFIXES - {".py", ".rb"}

__all__ = (
    "SCAN_SUFFIXES",
    "Hotspot",
    "ScanReport",
    "ScanStats",
    "WrapperEvidence",
    "collect_repo_python_wrapper_evidence",
    "dedupe",
    "is_bounded_loop_finding",
    "iter_source_files",
    "read_text",
    "relative_path",
    "scan_python",
    "scan_text",
    "scan_text_by_language",
    "sort_key",
)

ITERATION_RE = re.compile(r"\b(for|while|forEach|map|filter|reduce|some|every|find|findIndex)\b")
MEMBERSHIP_RE = re.compile(
    r"(\.includes\s*\(|\.indexOf\s*\(|\.find\s*\(|\.findIndex\s*\(|\bin_array\s*\(|\bcontains\s*\()"
)
SORT_RE = re.compile(r"(\.sort\s*\(|\bsorted\s*\(|\bsort\s*\()")
IO_RE = re.compile(
    r"\b(fetch|axios\.|request\s*\(|query\s*\(|execute\s*\(|findMany\s*\(|"
    r"findOne\s*\(|findUnique\s*\(|select\s*\(|where\s*\(|open\s*\(|"
    r"readFile|writeFile|subprocess\.)\b",
    re.IGNORECASE,
)
COMPONENT_RE = re.compile(
    r"\b(function\s+[A-Z][A-Za-z0-9_]*|const\s+[A-Z][A-Za-z0-9_]*\s*=|export\s+default\s+function\s+[A-Z])"
)

PYTHON_DECISION_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Match)
PYTHON_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

SORT_CALL_NAMES = {"sorted", "sort"}
REPEATED_SCAN_CALL_NAMES = {"map", "filter"}
IO_CALL_NAMES = {
    "db_set",
    "fetch",
    "get_all",
    "get_doc",
    "get_list",
    "get_value",
    "request",
    "query",
    "execute",
    "exists",
    "find_one",
    "find_many",
    "select",
    "where",
    "db_query",
    "open",
    "run",
    "popen",
    "sql",
}
ORM_CALL_NAMES = {
    "all",
    "bulk_create",
    "create",
    "delete",
    "execute",
    "filter",
    "get",
    "query",
    "scalars",
    "update",
}
EXTERNAL_IO_ROOTS = {
    "aiohttp",
    "db",
    "httpx",
    "requests",
    "subprocess",
    "urllib",
}
WRAPPER_IO_NAME_HINTS = {
    "_request",
    "request",
    "delete_folder",
    "download_file",
    "fetch",
    "list_folders",
    "upload_file",
}
EXTERNAL_CLIENT_NAMES = {
    "api",
    "bucket",
    "client",
    "container",
    "drive",
    "http",
    "service",
    "session",
    "storage",
}
STRONG_EXTERNAL_METHOD_HINTS = {
    "delete_folder",
    "download_file",
    "list_folders",
    "upload_file",
}

LIKELY_SET_NAMES = {
    "excludes",
    "seen",
    "interesting",
    "likely_set_names",
    "render_lines",
    "line",
    "stripped",
    "SCAN_SUFFIXES",
    "DEFAULT_EXCLUDES",
}
LIKELY_MAPPING_NAMES = {"item", "row", "payload", "data", "record", "document"}

MARKDOWN_HEADERS = (
    "Severity",
    "Confidence",
    "Kind",
    "Location",
    "Symbol",
    "Current Pattern",
    "Estimated Complexity",
    "Recommendation",
    "Expected Complexity",
    "Verification",
)

@dataclass
class Hotspot:
    path: str
    line: int
    severity: str
    confidence: str
    kind: str
    symbol: str
    current_pattern: str
    estimated_complexity: str
    recommendation: str
    expected_complexity: str
    verification: str
    claim_type: str = "heuristic"
    loop_classification: str = ""
    evidence: str = ""
    confidence_reason: str = ""
    calibration: str = ""


@dataclass(frozen=True)
class HotspotTemplate:
    severity: str
    confidence: str
    kind: str
    current_pattern: str
    estimated_complexity: str
    recommendation: str
    expected_complexity: str
    verification: str


@dataclass
class TextScanState:
    path: Path
    root: Path
    render_lines: set[int]
    findings: list[Hotspot]
    loop_stack: list[TextLoop]


@dataclass
class ComponentState:
    active_until: int = 0
    brace_balance: int = 0
    in_component: bool = False
    interesting: set[int] | None = None

    def __post_init__(self) -> None:
        if self.interesting is None:
            self.interesting = set()


@dataclass(frozen=True)
class TextLoop:
    indent: int
    line: int
    brace_depth: int | None = None
    brace_pending: bool = False
    fallback_consumed: bool = False


@dataclass(frozen=True)
class LoopContext:
    kind: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class WrapperEvidence:
    name: str
    scope: str
    path: str
    symbol: str
    confidence: str
    reason: str
    evidence: str


@dataclass
class ScanStats:
    root: str
    plugin_version: str = PLUGIN_VERSION
    files_scanned: int = 0
    files_skipped: int = 0
    language_counts: dict[str, int] | None = None
    skipped_paths: list[str] | None = None

    def __post_init__(self) -> None:
        if self.language_counts is None:
            self.language_counts = {}
        if self.skipped_paths is None:
            self.skipped_paths = []


@dataclass
class ScanReport:
    stats: ScanStats
    findings: list[Hotspot]
    command: str


NESTED_LOOP_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="medium",
    kind="nested-loop",
    current_pattern="Loop nested inside another loop.",
    estimated_complexity="often O(n*m) or O(n^2), depending on collection sizes",
    recommendation=(
        "Check whether grouping, indexing, batching, sort+two-pointers, "
        "or a single pass can replace the inner scan."
    ),
    expected_complexity="often O(n+m), O(n log n), or one batched I/O step",
    verification="Verify duplicate handling, ordering, missing values, and input-size assumptions.",
)

MEMBERSHIP_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="low",
    kind="membership-in-loop",
    current_pattern="Membership check inside a loop.",
    estimated_complexity="can become O(n*m) if the right side is a list or recomputed sequence",
    recommendation="Materialise a set or dictionary once when equality, ordering, and mutation semantics allow it.",
    expected_complexity="typically O(n+m)",
    verification="Check hashability, duplicates, ordering, and whether the collection mutates during iteration.",
)

SORT_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="medium",
    kind="sort-in-loop",
    current_pattern="Sort operation inside a loop.",
    estimated_complexity="often O(n*m log m) or worse",
    recommendation="Sort once, maintain a heap, or use binary insertion/search if intermediate ordering is required.",
    expected_complexity="often O(n log n) or O(n log k)",
    verification="Check whether intermediate sorted states and comparator side effects are observable.",
)

REPEATED_SCAN_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="low",
    kind="repeated-scan",
    current_pattern="Repeated transform inside a loop.",
    estimated_complexity="can repeatedly scan a collection",
    recommendation="Precompute an index/grouping or combine passes when semantics permit.",
    expected_complexity="often O(n+m)",
    verification="Check ordering, laziness, and memory pressure from precomputation.",
)

IO_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="medium",
    kind="io-in-loop",
    current_pattern="I/O or query-like call inside a loop.",
    estimated_complexity="static scan suggests possible N+1 risk or repeated external latency",
    recommendation="Batch, preload, join, cache with invalidation, or move I/O outside the loop.",
    expected_complexity="one bulk operation plus in-memory join where valid",
    verification="Preserve permissions, filters, pagination, ordering, error handling, retries, and rate limits.",
)

RETRY_IO_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="high",
    kind="io-in-loop",
    current_pattern="External call inside a bounded retry loop.",
    estimated_complexity="bounded retry latency amplification, not an unbounded N+1 data loop",
    recommendation="Validate retry count, backoff, idempotency, timeout, and terminal failure handling.",
    expected_complexity="same request count class with bounded retries",
    verification="Check retry guard, timeout budget, and whether the operation can be safely retried.",
)

FIXED_IO_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="medium",
    kind="io-in-loop",
    current_pattern="External call inside a fixed-size loop.",
    estimated_complexity="bounded repeated external calls; not proven to scale with user data",
    recommendation=(
        "Keep as-is when the bound is intentionally small, or collapse into one call "
        "if the fixed set grows."
    ),
    expected_complexity="same bounded count or one batched call where available",
    verification="Confirm the fixed bound and whether the loop is on a hot user-facing path.",
)

PAGINATION_IO_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="medium",
    kind="io-in-loop",
    current_pattern="External call inside a pagination loop.",
    estimated_complexity="one external request per page; latency scales with page count",
    recommendation="Validate page size, continuation handling, retry budget, and maximum expected pages.",
    expected_complexity="same page count unless API supports larger pages or server-side filters",
    verification="Check page bounds, rate limits, and partial-page failure behaviour.",
)

STREAMING_IO_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="medium",
    kind="io-in-loop",
    current_pattern="External or file call inside a streaming/chunk loop.",
    estimated_complexity="work scales with bytes/chunks rather than record count",
    recommendation="Validate chunk size, memory pressure, resumability, retries, and progress persistence.",
    expected_complexity="same byte complexity with bounded per-chunk overhead",
    verification="Benchmark representative file sizes and failure/resume paths.",
)

WRAPPER_IO_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="low",
    kind="wrapper-io-in-loop",
    current_pattern="Likely I/O wrapper inside a loop.",
    estimated_complexity="static scan suggests repeated external work through a wrapper",
    recommendation="Inspect the wrapper callee before treating this as a performance bug.",
    expected_complexity="depends on whether the wrapper performs external I/O, caching, or batching",
    verification="Trace the wrapper, input bounds, retry behaviour, and batching options.",
)

TEXT_NESTED_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="low",
    kind="nested-or-callback-loop",
    current_pattern="Iteration appears inside another loop or callback.",
    estimated_complexity="may be O(n*m) or repeated render work",
    recommendation="Inspect whether indexing, grouping, batching, or a single pass removes repeated work.",
    expected_complexity="often O(n+m) when data can be indexed",
    verification="Validate input sizes, ordering, duplicate handling, and callback side effects.",
)

TEXT_MEMBERSHIP_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="low",
    kind="membership-in-loop",
    current_pattern="Search or membership operation appears inside iterative code.",
    estimated_complexity="may repeatedly scan a collection",
    recommendation="Consider Set, Map, dictionary, or grouped lookup when semantics allow.",
    expected_complexity="often O(n+m)",
    verification="Check equality, ordering, mutation, and duplicate semantics.",
)

TEXT_SORT_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="low",
    kind="sort-in-loop",
    current_pattern="Sort appears inside iterative code.",
    estimated_complexity="often repeated O(n log n) work",
    recommendation="Move sorting out, use a heap, or change the algorithm around sorted input.",
    expected_complexity="often O(n log n) or O(n log k)",
    verification="Check comparator dependencies and intermediate ordering requirements.",
)

TEXT_IO_TEMPLATE = HotspotTemplate(
    severity="high",
    confidence="low",
    kind="io-in-loop",
    current_pattern="I/O or query-like operation appears inside iterative code.",
    estimated_complexity="N+1 risk or repeated external latency",
    recommendation="Batch, preload, join, cache, or move I/O outside the loop.",
    expected_complexity="one bulk operation plus in-memory join where valid",
    verification="Preserve auth, filters, pagination, ordering, error handling, and rate limits.",
)

RENDER_TEMPLATE = HotspotTemplate(
    severity="medium",
    confidence="low",
    kind="render-derived-work",
    current_pattern="Collection transform appears in a likely UI render path.",
    estimated_complexity="recomputed work per render",
    recommendation="Use selectors, memoisation with complete dependencies, server-side derivation, or virtualisation.",
    expected_complexity="same Big-O per derivation, fewer repeated derivations",
    verification="Check dependency completeness and mutation behaviour.",
)


@dataclass
class TextScanContext:
    path: Path
    root: Path
    render_lines: set[int]
    loop_stack: list[TextLoop]
    findings: list[Hotspot]
    brace_delimited: bool = False
    brace_depth: int = 0


def iter_source_files(root: Path, excludes: set[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = keep_unexcluded_dirs(dirnames, excludes)
        yield from iter_scannable_files(Path(dirpath), filenames)


def keep_unexcluded_dirs(dirnames: Sequence[str], excludes: set[str]) -> list[str]:
    return [name for name in dirnames if name not in excludes]


def iter_scannable_files(dirpath: Path, filenames: Sequence[str]) -> Iterable[Path]:
    for filename in filenames:
        path = dirpath / filename
        if should_scan_path(path):
            yield path


def should_scan_path(path: Path) -> bool:
    return path.suffix.lower() in SCAN_SUFFIXES


def read_text(path: Path) -> str | None:
    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


class PythonHotspotVisitor(ast.NodeVisitor):
    def __init__(
        self,
        path: Path,
        root: Path,
        text: str,
        wrappers: dict[str, WrapperEvidence],
    ) -> None:
        self.path = path
        self.root = root
        self.source_lines = text.splitlines()
        self.wrappers = wrappers
        self.loop_depth = 0
        self.benign_loop_stack: list[bool] = []
        self.loop_target_stack: list[set[str]] = []
        self.loop_context_stack: list[LoopContext] = []
        self.function_stack: list[str] = []
        self.findings: list[Hotspot] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.function_stack)

    def add(
        self,
        node: ast.AST,
        severity: str,
        confidence: str,
        kind: str,
        current_pattern: str,
        estimated_complexity: str,
        recommendation: str,
        expected_complexity: str,
        verification: str,
        *,
        claim_type: str = "heuristic",
        loop_classification: str = "",
        confidence_reason: str = "",
        calibration: str = "",
        evidence_note: str = "",
    ) -> None:
        evidence = self.source_line(node)
        if evidence_note:
            evidence = f"{evidence}; {evidence_note}" if evidence else evidence_note
        self.findings.append(
            Hotspot(
                path=relative_path(self.path, self.root),
                line=getattr(node, "lineno", 1),
                severity=severity,
                confidence=confidence,
                kind=kind,
                symbol=self.symbol,
                current_pattern=current_pattern,
                estimated_complexity=estimated_complexity,
                recommendation=recommendation,
                expected_complexity=expected_complexity,
                verification=verification,
                claim_type=claim_type,
                loop_classification=loop_classification,
                evidence=evidence,
                confidence_reason=confidence_reason,
                calibration=calibration,
            )
        )

    def source_line(self, node: ast.AST) -> str:
        lineno = getattr(node, "lineno", 0)
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        loop_state = self._save_loop_state()
        self._reset_loop_state()
        self.function_stack.append(node.name)
        try:
            score = python_complexity_score(node)
            if score >= 15:
                self.add(
                    node,
                    "high" if score >= 25 else "medium",
                    "medium",
                    "high-function-complexity",
                    f"Function has an approximate control-flow score of {score}.",
                    "hard to reason about; likely more paths than tests cover",
                    "Split validation, branching, and side-effect blocks only after tests pin behaviour.",
                    "same Big-O unless algorithmic work is also changed",
                    "Run the per-file measure-complexity command on this file and add focused tests around the branches.",
                )
            self.generic_visit(node)
        finally:
            self.function_stack.pop()
            self._restore_loop_state(loop_state)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        loop_state = self._save_loop_state()
        self._reset_loop_state()
        try:
            self.generic_visit(node)
        finally:
            self._restore_loop_state(loop_state)

    def _save_loop_state(
        self,
    ) -> tuple[int, list[bool], list[set[str]], list[LoopContext]]:
        return (
            self.loop_depth,
            self.benign_loop_stack,
            self.loop_target_stack,
            self.loop_context_stack,
        )

    def _reset_loop_state(self) -> None:
        self.loop_depth = 0
        self.benign_loop_stack = []
        self.loop_target_stack = []
        self.loop_context_stack = []

    def _restore_loop_state(
        self,
        state: tuple[int, list[bool], list[set[str]], list[LoopContext]],
    ) -> None:
        (
            self.loop_depth,
            self.benign_loop_stack,
            self.loop_target_stack,
            self.loop_context_stack,
        ) = state

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def _visit_loop(self, node: ast.AST) -> None:
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self.visit(node.iter)
        benign_loop = is_benign_iteration(node)
        loop_context = classify_loop(node)
        self.add_nested_loop_finding(node)
        self.loop_depth += 1
        self.benign_loop_stack.append(benign_loop)
        self.loop_target_stack.append(loop_target_names(node))
        self.loop_context_stack.append(loop_context)
        self.visit_loop_body(node)
        self.loop_context_stack.pop()
        self.loop_target_stack.pop()
        self.benign_loop_stack.pop()
        self.loop_depth -= 1

    def add_nested_loop_finding(self, node: ast.AST) -> None:
        if not self.loop_depth or any(self.benign_loop_stack):
            return
        if is_child_collection_iteration(node, self.loop_target_stack):
            self.add_nested_traversal_finding(node)
            return
        self.add_nested_scan_finding(node)

    def add_nested_scan_finding(self, node: ast.AST) -> None:
        self.add(
            node,
            "high",
            "medium",
            "nested-loop",
            "Loop nested inside another loop over an apparently independent iterable.",
            "often O(n*m) or O(n^2), depending on collection sizes",
            "Check whether grouping, indexing, batching, sort+two-pointers, "
            "or a single pass can replace the inner scan.",
            "often O(n+m), O(n log n), or one batched I/O step",
            "Verify duplicate handling, ordering, missing values, and input-size assumptions.",
        )

    def add_nested_traversal_finding(self, node: ast.AST) -> None:
        self.add(
            node,
            "medium",
            "low",
            "nested-traversal",
            "Nested loop appears to traverse a child collection of the outer item.",
            "usually O(total child items), not O(n^2), when each child belongs to one parent",
            "Confirm whether the inner iterable is a child collection rather than a repeated full scan.",
            "typically linear in parents plus total children",
            "Check parent-child ownership, duplicate child sharing, and whether the child collection is recomputed.",
        )

    def visit_loop_body(self, node: ast.AST) -> None:
        if isinstance(node, (ast.For, ast.AsyncFor)):
            for child in [*node.body, *node.orelse]:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if (
            self.loop_depth
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
            and not is_likely_set_membership(node)
        ):
            self.add(
                node,
                "medium",
                "low",
                "membership-in-loop",
                "Membership check inside a loop.",
                "can become O(n*m) if the right side is a list or recomputed sequence",
                "Materialise a set or dictionary once when equality, ordering, and mutation semantics allow it.",
                "typically O(n+m)",
                "Check hashability, duplicates, ordering, and whether the collection mutates during iteration.",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        lowered = name.lower()
        full_name = dotted_call_name(node.func).lower()
        if self.loop_depth:
            self._add_loop_call_findings(node, name, lowered, full_name)
        self.generic_visit(node)

    def _add_loop_call_findings(
        self, node: ast.Call, name: str, lowered: str, full_name: str
    ) -> None:
        self.add_loop_transform_findings(node, name)
        self.add_loop_external_finding(node, name, lowered, full_name)

    def add_loop_transform_findings(self, node: ast.Call, name: str) -> None:
        if is_sort_call(name):
            self.add_loop_sort_finding(node)
        if is_scan_call(name):
            self.add_loop_scan_finding(node, name)

    def add_loop_external_finding(
        self, node: ast.Call, name: str, lowered: str, full_name: str
    ) -> None:
        if is_io_call(lowered, full_name):
            self.add_loop_io_finding(node, io_call_category(lowered, full_name))
            return
        evidence = wrapper_evidence_for_call(name, full_name, self.wrappers, self.path, self.root)
        if evidence is not None:
            self.add_wrapper_io_finding(node, name or full_name, evidence)

    def add_loop_sort_finding(self, node: ast.Call) -> None:
        self.add(
            node,
            "high",
            "medium",
            "sort-in-loop",
            "Sort operation inside a loop.",
            "often O(n*m log m) or worse",
            "Sort once, maintain a heap, or use binary insertion/search if intermediate ordering is required.",
            "often O(n log n) or O(n log k)",
            "Check whether intermediate sorted states and comparator side effects are observable.",
        )

    def add_loop_scan_finding(self, node: ast.Call, name: str) -> None:
        self.add(
            node,
            "medium",
            "low",
            "repeated-scan",
            f"{name}() inside a loop.",
            "can repeatedly scan a collection",
            "Precompute an index/grouping or combine passes when semantics permit.",
            "often O(n+m)",
            "Check ordering, laziness, and memory pressure from precomputation.",
        )

    def add_loop_io_finding(self, node: ast.Call, category: str) -> None:
        context = self.current_loop_context()
        if should_skip_loop_io_finding(category, context):
            return
        template = io_template_for_call(context, category)
        self.add(
            node,
            template.severity,
            template.confidence,
            "io-in-loop",
            template.current_pattern,
            template.estimated_complexity,
            template.recommendation,
            template.expected_complexity,
            template.verification,
            loop_classification=context.kind,
            confidence_reason=context.reason,
            calibration=io_calibration(category),
        )

    def add_wrapper_io_finding(
        self, node: ast.Call, name: str, evidence: WrapperEvidence
    ) -> None:
        context = self.current_loop_context()
        template = wrapper_template_for_loop(context)
        self.add(
            node,
            template.severity,
            template.confidence,
            "wrapper-io-in-loop",
            f"Call to likely I/O wrapper `{name}` inside a loop using {evidence.scope} evidence.",
            template.estimated_complexity,
            template.recommendation,
            template.expected_complexity,
            template.verification,
            loop_classification=context.kind,
            confidence_reason=f"{context.reason}; {evidence.scope} wrapper evidence: {evidence.reason}",
            calibration=(
                "Wrapper-aware static scan suggests external work; "
                f"callee confidence {evidence.confidence}; manual validation needed."
            ),
            evidence_note=f"callee evidence {evidence.path}:{evidence.symbol}: {evidence.evidence}",
        )

    def current_loop_context(self) -> LoopContext:
        if self.loop_context_stack:
            return self.loop_context_stack[-1]
        return LoopContext("data loop", "medium", "loop bounds not proven by static scan")


class PythonWrapperCollector(ast.NodeVisitor):
    def __init__(self, path: Path, root: Path, source_lines: Sequence[str]) -> None:
        self.path = path
        self.root = root
        self.source_lines = source_lines
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.wrapper_evidence: dict[str, WrapperEvidence] = {}
        self.calls_by_function: dict[str, set[str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_function(node)

    def visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.calls_by_function.setdefault(node.name, set())
        for child in node.body:
            self.visit(child)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        full_name = dotted_call_name(node.func).lower()
        if self.function_stack:
            self.record_call(self.function_stack[-1], name, full_name, node)
        self.generic_visit(node)

    def record_call(
        self, function_name: str, name: str, full_name: str, node: ast.Call
    ) -> None:
        if name:
            self.calls_by_function.setdefault(function_name, set()).add(name)
        category = io_call_category(name.lower(), full_name)
        if is_io_call(name.lower(), full_name) and should_record_direct_wrapper(
            function_name, category
        ):
            self.wrapper_evidence[function_name] = self.direct_wrapper_evidence(
                function_name, full_name or name, node
            )

    def direct_wrapper_evidence(
        self, function_name: str, callee: str, node: ast.Call
    ) -> WrapperEvidence:
        return WrapperEvidence(
            name=function_name,
            scope="same-file",
            path=relative_path(self.path, self.root),
            symbol=self.current_symbol(function_name),
            confidence="high",
            reason=f"callee calls `{callee}` directly",
            evidence=self.source_line(node),
        )

    def current_symbol(self, function_name: str) -> str:
        parts = [*self.class_stack, function_name]
        return ".".join(parts)

    def source_line(self, node: ast.AST) -> str:
        lineno = getattr(node, "lineno", 0)
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""


def collect_python_io_wrapper_evidence(
    tree: ast.AST, path: Path, root: Path, text: str
) -> dict[str, WrapperEvidence]:
    collector = PythonWrapperCollector(path, root, text.splitlines())
    collector.visit(tree)
    changed = True
    while changed:
        changed = propagate_wrapper_calls(collector.wrapper_evidence, collector.calls_by_function)
    return collector.wrapper_evidence


def collect_python_io_wrappers(tree: ast.AST) -> set[str]:
    return set(legacy_collect_python_io_wrappers(tree))


def collect_repo_python_wrapper_evidence(
    paths: Sequence[Path], root: Path
) -> dict[str, WrapperEvidence]:
    evidence: dict[str, WrapperEvidence] = {}
    for path in paths:
        evidence.update(collect_path_wrapper_evidence(path, root))
    return evidence


def collect_path_wrapper_evidence(path: Path, root: Path) -> dict[str, WrapperEvidence]:
    if path.suffix.lower() != ".py":
        return {}
    text = read_text(path)
    if text is None:
        return {}
    tree = parse_wrapper_tree(text)
    if tree is None:
        return {}
    return collect_python_io_wrapper_evidence(tree, path, root, text)


def parse_wrapper_tree(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def legacy_collect_python_io_wrappers(tree: ast.AST) -> set[str]:
    collector = PythonWrapperCollector(Path("."), Path("."), [])
    collector.visit(tree)
    wrappers = set(collector.wrapper_evidence)
    changed = True
    while changed:
        changed = propagate_legacy_wrapper_calls(wrappers, collector.calls_by_function)
    return wrappers


def propagate_wrapper_calls(
    wrappers: dict[str, WrapperEvidence], calls_by_function: dict[str, set[str]]
) -> bool:
    changed = False
    for function_name, calls in calls_by_function.items():
        if should_promote_wrapper(function_name, calls, wrappers):
            wrappers[function_name] = propagated_wrapper_evidence(function_name, calls, wrappers)
            changed = True
    return changed


def propagated_wrapper_evidence(
    function_name: str, calls: set[str], wrappers: dict[str, WrapperEvidence]
) -> WrapperEvidence:
    callee = min(calls.intersection(wrappers))
    evidence = wrappers[callee]
    return WrapperEvidence(
        name=function_name,
        scope=evidence.scope,
        path=evidence.path,
        symbol=function_name,
        confidence="medium",
        reason=f"callee calls wrapper `{callee}`",
        evidence=evidence.evidence,
    )


def should_promote_wrapper(
    function_name: str, calls: set[str], wrappers: dict[str, WrapperEvidence]
) -> bool:
    if function_name in wrappers:
        return False
    return bool(calls.intersection(wrappers)) and is_wrapper_name_candidate(function_name)


def should_record_direct_wrapper(function_name: str, category: str) -> bool:
    if category == "file":
        return False
    return is_wrapper_name_candidate(function_name)


def propagate_legacy_wrapper_calls(wrappers: set[str], calls_by_function: dict[str, set[str]]) -> bool:
    changed = False
    for function_name, calls in calls_by_function.items():
        if function_name not in wrappers and calls.intersection(wrappers) and is_wrapper_name_candidate(function_name):
            wrappers.add(function_name)
            changed = True
    return changed


def is_wrapper_name_candidate(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in WRAPPER_NAME_TOKENS)


WRAPPER_NAME_TOKENS = (
    "create",
    "delete",
    "download",
    "fetch",
    "get",
    "list",
    "load",
    "read",
    "request",
    "response",
    "run",
    "save",
    "upload",
    "write",
)


def python_complexity_score(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    score = 1
    for child in python_scope_nodes(node):
        score += python_complexity_increment(node, child)
    return score


PYTHON_NESTED_SCOPE_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
)


def python_scope_nodes(root: ast.AST) -> Iterable[ast.AST]:
    """Yield a function's own descendants without nested callable/class bodies."""
    pending = list(reversed(list(ast.iter_child_nodes(root))))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, PYTHON_NESTED_SCOPE_NODES):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def python_complexity_increment(root: ast.AST, child: ast.AST) -> int:
    if child is root:
        return 0
    if is_python_branch(child):
        return 1
    if isinstance(child, ast.BoolOp):
        return max(0, len(child.values) - 1)
    if is_comprehension(child):
        return len(child.generators)
    return 0


def is_python_branch(node: ast.AST) -> bool:
    return isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Match))


def is_comprehension(node: ast.AST) -> bool:
    return isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))


def call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def dotted_call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = dotted_call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def loop_target_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return target_names(node.target)
    return set()


def target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in target_names(item)}
    return set()


def is_child_collection_iteration(
    node: ast.AST, loop_target_stack: Sequence[set[str]]
) -> bool:
    return isinstance(node, (ast.For, ast.AsyncFor)) and iterator_uses_outer_target(
        node.iter, loop_target_stack
    )


def iterator_uses_outer_target(iterator: ast.AST, loop_target_stack: Sequence[set[str]]) -> bool:
    outer_targets = set().union(*loop_target_stack) if loop_target_stack else set()
    return bool(outer_targets and iterator_base_names(iterator).intersection(outer_targets))


def iterator_base_names(iterator: ast.AST) -> set[str]:
    if isinstance(iterator, ast.Attribute):
        return attribute_base_names(iterator)
    if isinstance(iterator, ast.Call):
        return iterator_base_names(iterator.func)
    return set()


def attribute_base_names(node: ast.Attribute) -> set[str]:
    if isinstance(node.value, ast.Name):
        return {node.value.id}
    if isinstance(node.value, ast.Attribute):
        return attribute_base_names(node.value)
    return set()


def is_benign_iteration(node: ast.AST) -> bool:
    if not isinstance(node, (ast.For, ast.AsyncFor)):
        return False
    iterator = node.iter
    return isinstance(iterator, ast.Call) and is_benign_iterator_call(iterator)


def is_benign_iterator_call(iterator: ast.Call) -> bool:
    return call_name(iterator.func) in {"walk", "iter_source_files", "enumerate"}


def classify_loop(node: ast.AST) -> LoopContext:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return classify_for_loop(node)
    if isinstance(node, ast.While):
        return classify_while_loop(node)
    return LoopContext("data loop", "medium", "loop bounds not proven by static scan")


def classify_for_loop(node: ast.For | ast.AsyncFor) -> LoopContext:
    iterator = node.iter
    if is_retry_iterator(iterator):
        return LoopContext("retry loop", "high", "range-based retry loop")
    if is_fixed_size_iterator(iterator):
        return LoopContext("fixed-size loop", "high", "literal or constant-sized iterable")
    if is_streaming_loop(node):
        return LoopContext("streaming loop", "medium", "loop body reads chunks or bytes")
    return LoopContext("data loop", "medium", "loop iterates over runtime data")


def classify_while_loop(node: ast.While) -> LoopContext:
    if is_pagination_loop(node):
        return LoopContext("pagination loop", "medium", "continuation token/url updated in loop body")
    if is_streaming_loop(node):
        return LoopContext("streaming loop", "medium", "loop body reads chunks or bytes")
    if is_retry_while_loop(node):
        return LoopContext("retry loop", "medium", "attempt counter appears to bound the loop")
    return LoopContext("data loop", "medium", "while-loop bound not proven by static scan")


def is_retry_iterator(iterator: ast.AST) -> bool:
    return isinstance(iterator, ast.Call) and call_name(iterator.func) == "range" and any(
        retry_text(arg) for arg in iterator.args
    )


def retry_text(node: ast.AST) -> bool:
    text = ast.unparse(node).lower() if hasattr(ast, "unparse") else ""
    return any(token in text for token in ("retry", "attempt", "max_retries"))


def is_fixed_size_iterator(iterator: ast.AST) -> bool:
    if isinstance(iterator, (ast.Tuple, ast.List, ast.Set)):
        return len(iterator.elts) <= 10
    if isinstance(iterator, ast.Constant) and isinstance(iterator.value, (str, bytes)):
        return True
    return isinstance(iterator, ast.Name) and iterator.id.isupper()


def is_retry_while_loop(node: ast.While) -> bool:
    text = ast.unparse(node.test).lower() if hasattr(ast, "unparse") else ""
    return "retry" in text or "attempt" in text


def is_pagination_loop(node: ast.While) -> bool:
    test = ast.unparse(node.test).lower() if hasattr(ast, "unparse") else ""
    if not any(token in test for token in ("next", "page", "url", "cursor", "token")):
        return False
    return any(mentions_pagination_assignment(child) for child in ast.walk(node))


def mentions_pagination_assignment(node: ast.AST) -> bool:
    if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return False
    text = ast.unparse(node).lower() if hasattr(ast, "unparse") else ""
    return any(token in text for token in ("nextlink", "next_link", "next", "cursor", "page"))


def is_streaming_loop(node: ast.AST) -> bool:
    return has_stream_read_call(node) or has_streaming_text(node)


def has_stream_read_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and call_name(child.func) in {"read", "readinto"}:
            return True
    return False


def has_streaming_text(node: ast.AST) -> bool:
    text = ast.unparse(node).lower() if hasattr(ast, "unparse") else ""
    return any(token in text for token in ("chunk", "bytes", "file_size", "remaining"))


def io_template_for_loop(context: LoopContext) -> HotspotTemplate:
    if context.kind == "retry loop":
        return RETRY_IO_TEMPLATE
    if context.kind == "fixed-size loop":
        return FIXED_IO_TEMPLATE
    if context.kind == "pagination loop":
        return PAGINATION_IO_TEMPLATE
    if context.kind == "streaming loop":
        return STREAMING_IO_TEMPLATE
    return IO_TEMPLATE


def should_skip_loop_io_finding(category: str, context: LoopContext) -> bool:
    return category == "file" and context.kind in {"retry loop", "fixed-size loop"}


def io_template_for_call(context: LoopContext, category: str) -> HotspotTemplate:
    template = io_template_for_loop(context)
    if category == "file" and context.kind == "data loop":
        return HotspotTemplate(
            severity="medium",
            confidence="medium",
            kind=template.kind,
            current_pattern="Filesystem call inside a data loop.",
            estimated_complexity="static scan suggests repeated local filesystem work",
            recommendation="Validate file count and filesystem latency before changing code.",
            expected_complexity="same semantics; possible batching or precomputed existence map if measured",
            verification="Measure representative file counts and confirm symlink/permission behaviour.",
        )
    return template


def io_calibration(category: str) -> str:
    if category == "file":
        return (
            "Static scan found local filesystem work in a loop; this is not "
            "automatically an N+1 database/network bug."
        )
    if category == "db":
        return "Static scan suggests database work in a loop; validate filters, permissions, and cardinality."
    if category == "network":
        return "Static scan suggests network work in a loop; validate request bounds, retries, and rate limits."
    return "Static scan suggests external work in a loop; manual validation needed."


def wrapper_template_for_loop(context: LoopContext) -> HotspotTemplate:
    if context.kind == "retry loop":
        return RETRY_IO_TEMPLATE
    if context.kind == "fixed-size loop":
        return FIXED_IO_TEMPLATE
    if context.kind == "pagination loop":
        return PAGINATION_IO_TEMPLATE
    if context.kind == "streaming loop":
        return STREAMING_IO_TEMPLATE
    return WRAPPER_IO_TEMPLATE


def is_sort_call(name: str) -> bool:
    return name in {"sorted", "sort"}


def is_scan_call(name: str) -> bool:
    return name in {"map", "filter"}


def is_io_call(lowered: str, full_name: str) -> bool:
    if call_root(full_name) in EXTERNAL_IO_ROOTS:
        return True
    if ".db." in full_name:
        return True
    if is_orm_call(lowered, full_name):
        return True
    return lowered in IO_CALL_NAMES or is_file_io(lowered)


def io_call_category(lowered: str, full_name: str) -> str:
    if is_db_io(lowered, full_name):
        return "db"
    if is_network_io(lowered, full_name):
        return "network"
    if is_subprocess_io(lowered, full_name):
        return "subprocess"
    if is_file_io(lowered):
        return "file"
    return "generic"


def is_db_io(lowered: str, full_name: str) -> bool:
    db_names = {"db_set", "get_all", "get_list", "get_doc", "get_value", "sql"}
    return ".db." in full_name or lowered in db_names or is_orm_call(lowered, full_name)


def is_orm_call(lowered: str, full_name: str) -> bool:
    if lowered not in ORM_CALL_NAMES:
        return False
    return (
        ".objects." in full_name
        or ".query." in full_name
        or full_name.startswith(("session.", "db.session."))
    )


def is_network_io(lowered: str, full_name: str) -> bool:
    return call_root(full_name) in {"requests", "httpx", "urllib", "aiohttp"} or lowered in {
        "fetch",
        "request",
    }


def is_subprocess_io(lowered: str, full_name: str) -> bool:
    return call_root(full_name) == "subprocess" or lowered in {"run", "popen"}


def is_file_io(lowered: str) -> bool:
    return lowered in {
        "exists",
        "open",
        "read",
        "read_bytes",
        "read_text",
        "write",
        "write_bytes",
        "write_text",
    }


def call_root(full_name: str) -> str:
    return full_name.split(".", 1)[0]


def is_wrapper_io_call(name: str, full_name: str, wrappers: set[str]) -> bool:
    tail = full_name.rsplit(".", 1)[-1] if full_name else name
    return name in wrappers or tail in wrappers


def wrapper_evidence_for_call(
    name: str,
    full_name: str,
    wrappers: dict[str, WrapperEvidence],
    path: Path,
    root: Path,
) -> WrapperEvidence | None:
    evidence = direct_wrapper_evidence_for_call(name, full_name, wrappers, path, root)
    if evidence is not None:
        return evidence
    tail = full_name.rsplit(".", 1)[-1] if full_name else name
    if is_external_client_wrapper_hint(tail, full_name):
        return name_hint_wrapper_evidence(tail or name, full_name)
    return None


def direct_wrapper_evidence_for_call(
    name: str,
    full_name: str,
    wrappers: dict[str, WrapperEvidence],
    path: Path,
    root: Path,
) -> WrapperEvidence | None:
    for key in wrapper_lookup_keys(name, full_name):
        if key in wrappers:
            return scoped_wrapper_evidence(wrappers[key], path, root)
    return None


def wrapper_lookup_keys(name: str, full_name: str) -> tuple[str, str]:
    tail = full_name.rsplit(".", 1)[-1] if full_name else name
    return name, tail


def scoped_wrapper_evidence(evidence: WrapperEvidence, path: Path, root: Path) -> WrapperEvidence:
    current = relative_path(path, root)
    scope = "same-file" if evidence.path == current else "cross-file"
    return replace(evidence, scope=scope)


def is_external_client_wrapper_hint(tail: str, full_name: str) -> bool:
    if not tail or tail not in WRAPPER_IO_NAME_HINTS or "." not in full_name:
        return False
    root = call_root(full_name)
    return root in EXTERNAL_CLIENT_NAMES or tail in STRONG_EXTERNAL_METHOD_HINTS


def name_hint_wrapper_evidence(name: str, full_name: str) -> WrapperEvidence:
    return WrapperEvidence(
        name=name,
        scope="name-hint",
        path="[external-or-unresolved]",
        symbol=full_name or name,
        confidence="low",
        reason="method name on an external-looking receiver; no callee body was available",
        evidence=f"call `{full_name or name}` matched wrapper naming hints",
    )


def is_likely_set_membership(node: ast.Compare) -> bool:
    return is_mapping_key_check(node) or any(
        is_likely_set_comparator(comparator) for comparator in node.comparators
    )


def is_mapping_key_check(node: ast.Compare) -> bool:
    if not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
        return False
    return any(is_likely_mapping_name(comparator) for comparator in node.comparators)


def is_likely_mapping_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in LIKELY_MAPPING_NAMES or node.id.endswith(("dict", "map", "payload"))
    if isinstance(node, ast.Attribute):
        return node.attr.endswith(("dict", "map", "payload"))
    return False


def is_likely_set_comparator(comparator: ast.AST) -> bool:
    if isinstance(comparator, ast.Name):
        return is_likely_set_name(comparator.id)
    if isinstance(comparator, ast.Attribute):
        return is_likely_set_name(comparator.attr)
    return isinstance(comparator, (ast.Set, ast.Dict))


def is_likely_set_name(name: str) -> bool:
    return (
        name in LIKELY_SET_NAMES
        or name.isupper()
        or name.endswith(
            (
                "_set",
                "_sets",
                "_map",
                "_dict",
                "_lookup",
                "_cache",
                "_paths",
                "_names",
                "_methods",
                "_queues",
                "_wrappers",
                "wrappers",
                "methods",
            )
        )
    )


def scan_python(
    path: Path,
    root: Path,
    text: str,
    repo_wrappers: dict[str, WrapperEvidence] | None = None,
) -> list[Hotspot]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [
            Hotspot(
                path=relative_path(path, root),
                line=exc.lineno or 1,
                severity="info",
                confidence="high",
                kind="parse-error",
                symbol="",
                current_pattern="Python parser failed for this file.",
                estimated_complexity="unknown",
                recommendation="Inspect manually if this file is on a hot path.",
                expected_complexity="unknown",
                verification="Fix parser compatibility or run language-specific tooling.",
            )
        ] + scan_text(path, root, text)
    wrappers = dict(repo_wrappers or {})
    wrappers.update(collect_python_io_wrapper_evidence(tree, path, root, text))
    visitor = PythonHotspotVisitor(path, root, text, wrappers)
    visitor.visit(tree)
    return visitor.findings


def scan_text(path: Path, root: Path, text: str) -> list[Hotspot]:
    lines = text.splitlines()
    context = TextScanContext(
        path,
        root,
        render_candidate_lines(path, lines),
        [],
        [],
        is_brace_delimited(path),
    )
    for number, line in enumerate(lines, start=1):
        scan_text_line(context, number, line)
    return context.findings


def render_candidate_lines(path: Path, lines: Sequence[str]) -> set[int]:
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        return likely_component_lines(lines)
    return set()


def scan_text_line(context: TextScanContext, number: int, line: str) -> None:
    stripped = line.strip()
    if is_ignored_text_line(stripped):
        return
    indent = len(line) - len(line.lstrip(" "))
    context.loop_stack = prune_loop_stack(context.loop_stack, indent, context.brace_depth)
    bind_pending_brace_loop(context, stripped)
    iteration_started = handle_iteration_line(context, number, indent, stripped)
    handle_loop_body_line(context, number, stripped)
    handle_render_line(context, number, stripped)
    if context.brace_delimited:
        context.brace_depth = max(0, context.brace_depth + brace_delta(line))
        context.loop_stack = prune_closed_brace_loops(context.loop_stack, context.brace_depth)
    consume_fallback_loops(context, iteration_started)


def is_ignored_text_line(stripped: str) -> bool:
    return not stripped or stripped.startswith(("//", "#", "*", "/*"))


def prune_loop_stack(
    loop_stack: list[TextLoop], indent: int, brace_depth: int | None = None
) -> list[TextLoop]:
    return [loop for loop in loop_stack if is_text_loop_active(loop, indent, brace_depth)]


def is_text_loop_active(
    loop: TextLoop, indent: int, brace_depth: int | None
) -> bool:
    if loop.brace_depth is not None:
        return brace_depth is None or loop.brace_depth <= brace_depth
    return not loop.fallback_consumed


def prune_closed_brace_loops(
    loop_stack: list[TextLoop], brace_depth: int
) -> list[TextLoop]:
    return [
        loop
        for loop in loop_stack
        if loop.brace_depth is None or loop.brace_depth <= brace_depth
    ]


def is_brace_delimited(path: Path) -> bool:
    return path.suffix.lower() in BRACE_DELIMITED_SUFFIXES


def brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def loop_brace_depth(context: TextScanContext, line: str) -> int | None:
    if not context.brace_delimited or "{" not in line:
        return None
    return context.brace_depth + line.count("{")


def bind_pending_brace_loop(context: TextScanContext, stripped: str) -> None:
    """Bind an Allman-style loop header to its meaningful opening brace."""
    if not context.brace_delimited or not stripped.startswith("{"):
        return
    for index in range(len(context.loop_stack) - 1, -1, -1):
        loop = context.loop_stack[index]
        if not loop.brace_pending:
            continue
        context.loop_stack[index] = replace(
            loop,
            brace_depth=context.brace_depth + stripped.count("{"),
            brace_pending=False,
            fallback_consumed=False,
        )
        return


def consume_fallback_loops(context: TextScanContext, iteration_started: bool) -> None:
    """Keep brace-less detection to one meaningful statement per loop."""
    if iteration_started:
        return
    context.loop_stack = [
        replace(loop, brace_pending=False, fallback_consumed=True)
        if loop.brace_depth is None
        else loop
        for loop in context.loop_stack
    ]


def handle_iteration_line(
    context: TextScanContext, number: int, indent: int, stripped: str
) -> bool:
    if not ITERATION_RE.search(stripped):
        return False
    if is_render_chain_transform(context, number, stripped):
        return False
    if context.loop_stack:
        add_nested_text_loop(context, number, stripped)
    brace_depth = loop_brace_depth(context, stripped)
    context.loop_stack.append(
        TextLoop(
            indent,
            number,
            brace_depth,
            brace_pending=context.brace_delimited and brace_depth is None,
        )
    )
    return True


def handle_loop_body_line(context: TextScanContext, number: int, stripped: str) -> None:
    if not context.loop_stack:
        return
    add_membership_text_hotspot(context, number, stripped)
    add_sort_text_hotspot(context, number, stripped)
    add_io_text_hotspot(context, number, stripped)


def handle_render_line(context: TextScanContext, number: int, stripped: str) -> None:
    if not is_render_chain_transform(context, number, stripped):
        return
    add_render_text_hotspot(context, number)
    add_render_membership_hotspot(context, number, stripped)


def is_render_chain_transform(context: TextScanContext, number: int, stripped: str) -> bool:
    return number in context.render_lines and has_render_transform(stripped)


def has_render_transform(stripped: str) -> bool:
    return any(token in stripped for token in (".filter(", ".map(", ".sort(", ".reduce("))


def add_nested_text_loop(context: TextScanContext, number: int, stripped: str) -> None:
    append_text_hotspot(
        context,
        number,
        "high",
        "low",
        "nested-or-callback-loop",
        "Iteration appears inside another loop or callback.",
        "may be O(n*m) or repeated render work",
        "Inspect whether indexing, grouping, batching, or a single pass removes repeated work.",
        "often O(n+m) when data can be indexed",
        "Validate input sizes, ordering, duplicate handling, and callback side effects.",
        evidence=stripped,
    )


def add_membership_text_hotspot(context: TextScanContext, number: int, stripped: str) -> None:
    if MEMBERSHIP_RE.search(stripped):
        append_text_hotspot(
            context,
            number,
            "medium",
            "low",
            "membership-in-loop",
            "Search or membership operation appears inside iterative code.",
            "may repeatedly scan a collection",
            "Consider Set, Map, dictionary, or grouped lookup when semantics allow.",
            "often O(n+m)",
            "Check equality, ordering, mutation, and duplicate semantics.",
            evidence=stripped,
        )


def add_render_membership_hotspot(context: TextScanContext, number: int, stripped: str) -> None:
    if MEMBERSHIP_RE.search(stripped):
        add_membership_text_hotspot(context, number, stripped)


def add_sort_text_hotspot(context: TextScanContext, number: int, stripped: str) -> None:
    if SORT_RE.search(stripped):
        append_text_hotspot(
            context,
            number,
            "high",
            "low",
            "sort-in-loop",
            "Sort appears inside iterative code.",
            "often repeated O(n log n) work",
            "Move sorting out, use a heap, or change the algorithm around sorted input.",
            "often O(n log n) or O(n log k)",
            "Check comparator dependencies and intermediate ordering requirements.",
            evidence=stripped,
        )


def add_io_text_hotspot(context: TextScanContext, number: int, stripped: str) -> None:
    if IO_RE.search(stripped):
        append_text_hotspot(
            context,
            number,
            "high",
            "low",
            "io-in-loop",
            "I/O or query-like operation appears inside iterative code.",
            "N+1 risk or repeated external latency",
            "Batch, preload, join, cache, or move I/O outside the loop.",
            "one bulk operation plus in-memory join where valid",
            "Preserve auth, filters, pagination, ordering, error handling, and rate limits.",
            evidence=stripped,
        )


def add_render_text_hotspot(context: TextScanContext, number: int) -> None:
    append_text_hotspot(
        context,
        number,
        "medium",
        "low",
        "render-derived-work",
        "Collection transform appears in a likely UI render path.",
        "recomputed work per render",
        "Use selectors, memoisation with complete dependencies, server-side derivation, or virtualisation.",
        "same Big-O per derivation, fewer repeated derivations",
        "Check dependency completeness and mutation behaviour.",
        evidence=f"line {number} in likely render path",
    )


def append_text_hotspot(
    context: TextScanContext,
    line: int,
    severity: str,
    confidence: str,
    kind: str,
    current_pattern: str,
    estimated_complexity: str,
    recommendation: str,
    expected_complexity: str,
    verification: str,
    evidence: str = "",
) -> None:
    context.findings.append(
        text_hotspot(
            context.path,
            context.root,
            line,
            severity,
            confidence,
            kind,
            current_pattern,
            estimated_complexity,
            recommendation,
            expected_complexity,
            verification,
            evidence=evidence,
            confidence_reason="regex scan of non-Python source",
            calibration="Static text scan suggests a risk; use language-specific tooling before changing code.",
        )
    )


def text_hotspot(
    path: Path,
    root: Path,
    line: int,
    severity: str,
    confidence: str,
    kind: str,
    current_pattern: str,
    estimated_complexity: str,
    recommendation: str,
    expected_complexity: str,
    verification: str,
    evidence: str = "",
    confidence_reason: str = "",
    calibration: str = "",
) -> Hotspot:
    return Hotspot(
        path=relative_path(path, root),
        line=line,
        severity=severity,
        confidence=confidence,
        kind=kind,
        symbol="",
        current_pattern=current_pattern,
        estimated_complexity=estimated_complexity,
        recommendation=recommendation,
        expected_complexity=expected_complexity,
        verification=verification,
        evidence=evidence,
        confidence_reason=confidence_reason,
        calibration=calibration,
    )


def likely_component_lines(lines: Sequence[str]) -> set[int]:
    active_until = 0
    brace_balance = 0
    in_component = False
    interesting: set[int] = set()
    for number, line in enumerate(lines, start=1):
        if COMPONENT_RE.search(line):
            in_component, active_until, brace_balance = start_component_window(number)
        if in_component:
            interesting.add(number)
            brace_balance += line.count("{") - line.count("}")
            in_component = keep_component_window(number, active_until, brace_balance, line)
    return interesting


def start_component_window(number: int) -> tuple[bool, int, int]:
    return True, number + 120, 0


def keep_component_window(
    number: int, active_until: int, brace_balance: int, line: str
) -> bool:
    if number > active_until:
        return False
    return not (number > active_until - 110 and brace_balance <= 0 and "}" in line)


def dedupe(findings: Iterable[Hotspot]) -> list[Hotspot]:
    seen: set[tuple[str, int, str, str]] = set()
    result: list[Hotspot] = []
    for finding in findings:
        key = (finding.path, finding.line, finding.kind, finding.symbol)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def sort_key(finding: Hotspot) -> tuple[int, int, str, int]:
    severity_order = {"high": 0, "medium": 1, "info": 2}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    return (
        severity_order.get(finding.severity, 3),
        confidence_order.get(finding.confidence, 3),
        finding.path,
        finding.line,
    )


def is_bounded_loop_finding(item: Hotspot) -> bool:
    """Identify bounded loops that need calibration rather than refactoring."""
    return item.loop_classification in {"retry loop", "fixed-size loop"}




def scan_text_by_language(
    path: Path,
    root: Path,
    text: str,
    repo_wrappers: dict[str, WrapperEvidence] | None = None,
) -> list[Hotspot]:
    if path.suffix.lower() == ".py":
        return scan_python(path, root, text, repo_wrappers)
    return scan_text(path, root, text)
