from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from analysis_contract import (
    AdapterState,
    ContextSignalSummary,
    Diagnostic,
    RepoContextSummary,
)

from .graph import join_flags, split_flags
from .models import FunctionMetric

REFERENCE_SEARCH_BUDGET = 10
GIT_SEARCH_BUDGET = 10
CONTEXT_TIME_BUDGET_SECONDS = 10.0
COMMAND_TIMEOUT_SECONDS = 2.0


def enrich_ranked_metrics(
    metrics: Sequence[tuple[Path, FunctionMetric]],
    *,
    repo_context: Path,
    coverage_xml: Path | None,
    requested_top_k: int,
    adapters: ContextAdapters | None = None,
) -> tuple[RepoContextSummary, list[Diagnostic], list[AdapterState]]:
    """Enrich one ranked, bounded sample and report exactly what ran."""
    run = ContextRun(
        metrics,
        repo_context=repo_context,
        coverage_xml=coverage_xml,
        requested_top_k=requested_top_k,
        adapters=adapters,
    )
    run.enrich()
    return run.result()


@dataclass
class SignalCounter:
    attempted: int = 0
    completed: int = 0
    with_value: int = 0

    def summary(self, identifier: str, available: bool) -> ContextSignalSummary:
        return ContextSignalSummary(
            identifier,
            available,
            self.attempted,
            self.completed,
            self.with_value,
        )


class ReferenceSignal(Protocol):
    identifier: str
    available: bool
    version: str | None

    def search(
        self, repo: Path, function_name: str, deadline: float
    ) -> tuple[str | None, str | None]: ...


class GitSignal(Protocol):
    identifier: str
    available: bool
    version: str | None

    def churn(
        self, repo: Path, path: Path, start: int, end: int, deadline: float
    ) -> tuple[tuple[int, int] | None, str | None]: ...


class CoverageSignal(Protocol):
    identifier: str
    state: str
    reason: str
    version: str | None

    def percent(
        self, repo: Path, path: Path, start: int, end: int | None
    ) -> float | None: ...


@dataclass(frozen=True)
class ContextAdapters:
    """Concrete signal adapters used by one bounded enrichment run."""

    reference: ReferenceSignal
    git: GitSignal
    coverage: CoverageSignal


class RgReferenceAdapter:
    identifier = "repo-context-rg"

    def __init__(self, deadline: float) -> None:
        self.binary = shutil.which("rg")
        self.version = command_version(self.binary, deadline)

    @property
    def available(self) -> bool:
        return self.binary is not None

    def search(
        self, repo: Path, function_name: str, deadline: float
    ) -> tuple[str | None, str | None]:
        if not self.available:
            return None, "rg is unavailable"
        return run_rg_context(repo, function_name, deadline)


class GitHistoryAdapter:
    identifier = "repo-context-git"

    def __init__(self, deadline: float) -> None:
        self.binary = shutil.which("git")
        self.version = command_version(self.binary, deadline)

    @property
    def available(self) -> bool:
        return self.binary is not None

    def churn(
        self, repo: Path, path: Path, start: int, end: int, deadline: float
    ) -> tuple[tuple[int, int] | None, str | None]:
        if not self.available:
            return None, "git is unavailable"
        return run_git_context(repo, path, start, end, deadline)


class CoverageXmlAdapter:
    identifier = "coverage-xml"

    def __init__(self, path: Path, repo: Path) -> None:
        self.coverage, self.state, self.reason, self.version = load_coverage_snapshot(
            path, repo
        )

    def percent(
        self, repo: Path, path: Path, start: int, end: int | None
    ) -> float | None:
        if self.state != "complete":
            return None
        return coverage_percent_for(self.coverage, repo, path, start, end)


def default_context_adapters(
    repo: Path, coverage_path: Path, deadline: float
) -> ContextAdapters:
    return ContextAdapters(
        reference=RgReferenceAdapter(deadline),
        git=GitHistoryAdapter(deadline),
        coverage=CoverageXmlAdapter(coverage_path, repo),
    )


class ContextRun:
    def __init__(
        self,
        metrics: Sequence[tuple[Path, FunctionMetric]],
        *,
        repo_context: Path,
        coverage_xml: Path | None,
        requested_top_k: int,
        adapters: ContextAdapters | None,
    ) -> None:
        self.metrics = metrics
        self.requested_top_k = requested_top_k
        self.selected = list(metrics[:requested_top_k])
        self.repo = repo_context.expanduser().resolve()
        self.deadline = time.monotonic() + CONTEXT_TIME_BUDGET_SECONDS
        self.coverage_path = (coverage_xml or self.repo / "coverage.xml").expanduser()
        self.adapters = adapters or default_context_adapters(
            self.repo, self.coverage_path, self.deadline
        )
        self.diagnostics: list[Diagnostic] = []
        self.references = SignalCounter()
        self.git_searches = SignalCounter()
        self.coverage_counts = SignalCounter()
        self.reference_cache: dict[str, tuple[str | None, str | None]] = {}
        self.reference_searches = 0
        self.reference_skipped = 0
        self.git_skipped = 0
        self.reference_problem = False
        self.git_problem = False
        self.enriched_metric_ids: set[int] = set()
        self.record_unavailable_signals()

    def record_unavailable_signals(self) -> None:
        if not self.selected:
            return
        if not self.adapters.reference.available:
            self.diagnostics.append(
                Diagnostic(
                    None,
                    "repo-context-rg",
                    "rg is unavailable; reference enrichment skipped",
                )
            )
        if not self.adapters.git.available:
            self.diagnostics.append(
                Diagnostic(
                    None,
                    "repo-context-git",
                    "git is unavailable; churn enrichment skipped",
                )
            )
        if self.adapters.coverage.state != "complete":
            self.diagnostics.append(
                Diagnostic(
                    str(self.coverage_path),
                    "coverage-xml",
                    self.adapters.coverage.reason,
                )
            )

    def enrich(self) -> None:
        for path, metric in self.selected:
            self.enrich_references(path, metric)
            self.enrich_git(path, metric)
            self.enrich_coverage(path, metric)
            metric.review_flags = context_review_flags(metric)
        self.record_budget_exhaustion()

    def enrich_references(self, path: Path, metric: FunctionMetric) -> None:
        if not self.adapters.reference.available:
            return
        simple_name = metric.name.split(".")[-1]
        cached = self.reference_cache.get(simple_name)
        if cached is None:
            if self.reference_searches >= REFERENCE_SEARCH_BUDGET:
                self.reference_problem = True
                self.reference_skipped += 1
                return
            self.reference_searches += 1
            cached = self.adapters.reference.search(
                self.repo, simple_name, self.deadline
            )
            self.reference_cache[simple_name] = cached
        self.references.attempted += 1
        output, reason = cached
        if output is None:
            self.reference_problem = True
            if reason:
                self.diagnostics.append(
                    Diagnostic(str(path), "repo-context-rg", f"{metric.name}: {reason}")
                )
            return
        self.references.completed += 1
        metric.repo_references = count_external_hits(output, path)
        self.references.with_value += 1
        self.enriched_metric_ids.add(id(metric))

    def enrich_git(self, path: Path, metric: FunctionMetric) -> None:
        if not self.adapters.git.available or metric.end is None:
            return
        if self.git_searches.attempted >= GIT_SEARCH_BUDGET:
            self.git_problem = True
            self.git_skipped += 1
            return
        self.git_searches.attempted += 1
        churn, reason = self.adapters.git.churn(
            self.repo, path, metric.start, metric.end, self.deadline
        )
        if churn is None:
            self.git_problem = True
            if reason:
                self.diagnostics.append(
                    Diagnostic(str(path), "repo-context-git", f"{metric.name}: {reason}")
                )
            return
        self.git_searches.completed += 1
        metric.git_commits, metric.git_churn_lines = churn
        self.git_searches.with_value += 1
        self.enriched_metric_ids.add(id(metric))

    def enrich_coverage(self, path: Path, metric: FunctionMetric) -> None:
        if self.adapters.coverage.state != "complete" or metric.end is None:
            return
        self.coverage_counts.attempted += 1
        metric.coverage_percent = self.adapters.coverage.percent(
            self.repo, path, metric.start, metric.end
        )
        self.coverage_counts.completed += 1
        if metric.coverage_percent is not None:
            self.coverage_counts.with_value += 1
            self.enriched_metric_ids.add(id(metric))

    def record_budget_exhaustion(self) -> None:
        if self.reference_skipped:
            self.diagnostics.append(
                Diagnostic(
                    None,
                    "repo-context-rg",
                    f"reference-search budget exhausted; skipped {self.reference_skipped} selected functions",
                )
            )
        if self.git_skipped:
            self.diagnostics.append(
                Diagnostic(
                    None,
                    "repo-context-git",
                    f"git-history budget exhausted; skipped {self.git_skipped} selected functions",
                )
            )

    def result(
        self,
    ) -> tuple[RepoContextSummary, list[Diagnostic], list[AdapterState]]:
        signals = (
            self.references.summary(
                self.adapters.reference.identifier,
                self.adapters.reference.available,
            ),
            self.git_searches.summary(
                self.adapters.git.identifier,
                self.adapters.git.available,
            ),
            self.coverage_counts.summary(
                self.adapters.coverage.identifier,
                self.adapters.coverage.state == "complete",
            ),
        )
        summary = RepoContextSummary(
            root=str(self.repo),
            eligible_functions=len(self.metrics),
            requested_top_k=self.requested_top_k,
            selected_functions=len(self.selected),
            enriched_functions=len(self.enriched_metric_ids),
            sampled=len(self.selected) < len(self.metrics),
            signals=signals,
        )
        adapters = [
            context_adapter_state(
                "repo-context-rg",
                self.selected,
                self.adapters.reference.available,
                self.reference_problem,
                self.adapters.reference.version,
            ),
            context_adapter_state(
                "repo-context-git",
                self.selected,
                self.adapters.git.available,
                self.git_problem,
                self.adapters.git.version,
            ),
            coverage_adapter_state(
                self.selected,
                self.adapters.coverage.state,
                self.adapters.coverage.version,
            ),
        ]
        return summary, self.diagnostics, adapters


def context_adapter_state(
    identifier: str,
    selected: Sequence[tuple[Path, FunctionMetric]],
    available: bool,
    partial: bool,
    version: str | None,
) -> AdapterState:
    if not selected:
        return AdapterState(identifier, "not-applicable", version=version)
    if not available:
        return AdapterState(identifier, "unavailable", version=version)
    return AdapterState(
        identifier, "partial" if partial else "complete", version=version
    )


def coverage_adapter_state(
    selected: Sequence[tuple[Path, FunctionMetric]],
    state: str,
    version: str | None,
) -> AdapterState:
    if not selected:
        return AdapterState("coverage-xml", "not-applicable", version=version)
    if state == "missing":
        return AdapterState("coverage-xml", "unavailable", version=version)
    if state == "invalid":
        return AdapterState("coverage-xml", "failed", version=version)
    return AdapterState("coverage-xml", "complete", version=version)


def load_coverage_snapshot(
    path: Path, repo: Path
) -> tuple[dict[str, dict[int, int]], str, str, str | None]:
    if not path.is_file():
        return {}, "missing", "coverage XML not found", None
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as error:
        return {}, "invalid", f"coverage XML could not be parsed: {error}", None
    coverage: dict[str, dict[int, int]] = {}
    try:
        for class_node in root.findall(".//class"):
            add_class_coverage(coverage, class_node, repo)
    except (OverflowError, ValueError) as error:
        return (
            {},
            "invalid",
            f"coverage XML contains invalid line data: {error}",
            None,
        )
    version = root.get("version") or "Cobertura-compatible XML"
    return coverage, "complete", "", version


def command_version(binary: str | None, deadline: float) -> str | None:
    if binary is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"],
            check=False,
            text=True,
            capture_output=True,
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if proc.returncode != 0:
        return None
    return next((line.strip() for line in proc.stdout.splitlines() if line.strip()), None)


def run_rg_context(
    repo: Path, function_name: str, deadline: float
) -> tuple[str | None, str | None]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, "context time budget exhausted"
    try:
        proc = subprocess.run(
            ["rg", "-n", reference_pattern(function_name), str(repo)],
            check=False,
            text=True,
            capture_output=True,
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        )
    except subprocess.TimeoutExpired:
        return None, "reference search timed out"
    except UnicodeError as error:
        return None, f"reference search output could not be decoded: {error}"
    except OSError as error:
        return None, f"reference search could not start: {error}"
    if proc.returncode not in {0, 1}:
        return None, proc.stderr.strip() or f"rg exited {proc.returncode}"
    return proc.stdout, None


def run_git_context(
    repo: Path, path: Path, start: int, end: int, deadline: float
) -> tuple[tuple[int, int] | None, str | None]:
    rel = relative_repo_path(repo, path)
    if rel is None:
        return None, "source is outside repository context"
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, "context time budget exhausted"
    try:
        proc = subprocess.run(
            git_log_command(repo, rel, start, end),
            check=False,
            text=True,
            capture_output=True,
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        )
    except subprocess.TimeoutExpired:
        return None, "Git history query timed out"
    except UnicodeError as error:
        return None, f"Git history output could not be decoded: {error}"
    except OSError as error:
        return None, f"Git history query could not start: {error}"
    if proc.returncode != 0:
        return None, proc.stderr.strip() or f"git exited {proc.returncode}"
    return parse_git_log(proc.stdout), None


def context_review_flags(metric: FunctionMetric) -> str:
    flags = split_flags(metric.review_flags)
    append_reference_flag(flags, metric.repo_references)
    append_churn_flag(flags, metric.git_churn_lines)
    append_coverage_flag(flags, metric.coverage_percent)
    return join_flags(flags)


def append_reference_flag(flags: list[str], references: int | None) -> None:
    if references is not None and references >= 10:
        flags.append("widely referenced")


def append_churn_flag(flags: list[str], churn: int | None) -> None:
    if churn is not None and churn >= 50:
        flags.append("high churn")


def append_coverage_flag(flags: list[str], coverage_percent: float | None) -> None:
    if coverage_percent is not None and coverage_percent < 60:
        flags.append("low coverage")


def reference_pattern(function_name: str) -> str:
    simple_name = function_name.split(".")[-1]
    return rf"\b{re.escape(simple_name)}\s*\("


def count_external_hits(output: str, path: Path) -> int:
    current = str(path.resolve())
    count = 0
    for line in output.splitlines():
        count += external_hit(line, current)
    return count


def external_hit(line: str, current: str) -> int:
    hit_path = line.split(":", 1)[0]
    return int(Path(hit_path).resolve() != Path(current))


def relative_repo_path(repo: Path, path: Path) -> Path | None:
    try:
        return path.resolve().relative_to(repo)
    except ValueError:
        return None


def git_log_command(repo: Path, rel: Path, start: int, end: int) -> list[str]:
    return [
        "git",
        "-C",
        str(repo),
        "log",
        f"-L{start},{end}:{rel.as_posix()}",
        "--format=commit:%H",
    ]


def parse_git_log(output: str) -> tuple[int, int]:
    commits = 0
    churn = 0
    for line in output.splitlines():
        commits += int(line.startswith("commit:"))
        churn += git_churn_line_count(line)
    return commits, churn


def git_churn_line_count(line: str) -> int:
    return int(line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


def add_class_coverage(
    coverage: dict[str, dict[int, int]], class_node: ElementTree.Element, repo: Path
) -> None:
    filename = class_node.get("filename")
    if not filename:
        return
    line_hits = coverage_line_hits(class_node)
    for candidate in coverage_candidates(repo, filename):
        coverage[candidate] = line_hits


def coverage_candidates(repo: Path, filename: str) -> set[str]:
    return {filename, str((repo / filename).resolve())}


def coverage_line_hits(class_node: ElementTree.Element) -> dict[int, int]:
    line_hits: dict[int, int] = {}
    line_nodes = class_node.findall("./lines/line")
    for line_node in line_nodes:
        add_line_hit(line_hits, line_node)
    return line_hits


def add_line_hit(line_hits: dict[int, int], line_node: ElementTree.Element) -> None:
    number = line_node.get("number")
    hits = line_node.get("hits")
    if number and hits:
        line_hits[int(number)] = int(float(hits))


def coverage_percent_for(
    coverage: dict[str, dict[int, int]],
    repo: Path,
    path: Path,
    start: int,
    end: int | None,
) -> float | None:
    if end is None or not coverage:
        return None
    line_hits = matching_line_hits(coverage, repo, path)
    if not line_hits:
        return None
    relevant = relevant_line_hits(line_hits, start, end)
    if not relevant:
        return None
    return covered_percent(relevant)


def matching_line_hits(
    coverage: dict[str, dict[int, int]], repo: Path, path: Path
) -> dict[int, int] | None:
    return next((coverage[key] for key in coverage_keys(repo, path) if key in coverage), None)


def coverage_keys(repo: Path, path: Path) -> list[str]:
    keys = [str(path.resolve())]
    try:
        keys.append(path.resolve().relative_to(repo).as_posix())
    except ValueError:
        pass
    return keys


def relevant_line_hits(line_hits: dict[int, int], start: int, end: int) -> list[int]:
    return [line_hits[number] for number in range(start, end + 1) if number in line_hits]


def covered_percent(relevant: list[int]) -> float:
    covered = sum(1 for hits in relevant if hits > 0)
    return round(covered * 100 / len(relevant), 2)
