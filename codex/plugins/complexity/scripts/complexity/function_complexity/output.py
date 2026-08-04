from __future__ import annotations

import csv
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path

from .models import FunctionMetric


def sort_metrics(metrics: list[FunctionMetric], mode: str) -> list[FunctionMetric]:
    if mode == "complexity":
        return sorted(
            metrics,
            key=lambda item: (
                -max(item.cyclomatic, item.cognitive or 0),
                item.maintainability_index or 100,
                item.start,
                item.name,
            ),
        )
    return sorted(metrics, key=lambda item: (item.start, item.name))


def table_fields(view: str) -> list[str]:
    if view == "core":
        return [
            "name",
            "kind",
            "start",
            "end",
            "loc",
            "sloc",
            "params",
            "cyclomatic",
            "cognitive",
            "max_nesting",
            "time_complexity_hint",
            "space_complexity_hint",
            "maintainability_index",
            "coverage_percent",
            "risk",
            "review_flags",
        ]
    if view == "review":
        return [
            "name",
            "start",
            "direct_recursion",
            "indirect_recursion",
            "max_loop_depth",
            "fan_out",
            "internal_fan_in",
            "internal_fan_out",
            "repo_references",
            "git_commits",
            "git_churn_lines",
            "coverage_percent",
            "db_calls",
            "network_calls",
            "file_calls",
            "subprocess_calls",
            "io_calls_in_loops",
            "n_plus_one_risk",
            "awaits",
            "task_calls",
            "lock_calls",
            "raises",
            "global_writes",
            "mutations",
            "allocation_ops",
            "evidence",
            "review_flags",
        ]
    return list(FunctionMetric.__dataclass_fields__)


def format_header(field: str) -> str:
    return field.replace("_", " ").title().replace("Db", "DB").replace("Io", "I/O")


def format_optional(value: bool | float | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def markdown_table(metrics: Sequence[FunctionMetric], view: str) -> str:
    fields = table_fields(view)
    headers = [format_header(field) for field in fields]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for item in metrics:
        row = asdict(item)
        values = [format_optional(row[field]) for field in fields]
        lines.append("| " + " | ".join(escape_markdown(value) for value in values) + " |")
    return "\n".join(lines)


def markdown_report(
    metrics: Sequence[FunctionMetric],
    view: str,
    *,
    source_path: Path | None = None,
    repo_context: Path | None = None,
    command: str = "",
) -> str:
    return "\n".join(
        [
            "## Orientation Brief",
            metric_orientation(metrics, source_path, repo_context, command),
            "## Complexity Verdict",
            metric_verdict(metrics),
            "## Deterministic Metrics",
            markdown_table(metrics, view),
            "## Heuristic Hotspots",
            metric_hotspots(metrics),
            "## Overstated Findings",
            metric_overstated(metrics),
            "## Understated Risks",
            metric_understated(metrics),
            "## False Positive Candidates",
            metric_false_positive_candidates(metrics),
            "## Missing Signals",
            metric_missing_signals(),
            "## Evidence and Confidence",
            metric_evidence(metrics),
            "## Smallest Next Action Plan",
            metric_next_actions(metrics),
        ]
    )


def metric_orientation(
    metrics: Sequence[FunctionMetric],
    source_path: Path | None,
    repo_context: Path | None,
    command: str,
) -> str:
    suffix = source_path.suffix if source_path else ""
    return (
        f"- File: `{source_path}`\n"
        f"- Language: `{suffix or 'unknown'}`\n"
        f"- Functions measured: {len(metrics)}\n"
        f"- Repo context: `{repo_context}`\n"
        f"- Command: `{command}`"
    )


def metric_verdict(metrics: Sequence[FunctionMetric]) -> str:
    if not metrics:
        return "- Maintainability risk: unknown\n- Runtime risk: unknown\n- Refactor priority: no functions measured"
    worst = worst_metric(metrics)
    runtime_count = sum(1 for item in metrics if runtime_flags(item))
    return (
        f"- Maintainability risk: worst bucket `{worst.risk}` at `{worst.name}`\n"
        f"- Runtime risk: {runtime_count} functions carry heuristic runtime flags\n"
        f"- Refactor priority: {metric_refactor_priority(worst, runtime_count)}"
    )


def metric_refactor_priority(worst: FunctionMetric, runtime_count: int) -> str:
    if worst.risk == "A" and runtime_count == 0:
        return "no metric-driven refactor candidate"
    return "start with non-A functions that also have I/O, allocation, fan-out, or churn signals"


def worst_metric(metrics: Sequence[FunctionMetric]) -> FunctionMetric:
    order = {"E": 0, "D": 1, "C": 2, "B": 3, "A": 4}
    return min(metrics, key=lambda item: (order.get(item.risk, 9), -item.cyclomatic))


def runtime_flags(metric: FunctionMetric) -> list[str]:
    flags = split_flags(metric.review_flags)
    return [
        flag
        for flag in flags
        if any(token in flag for token in ("I/O", "DB", "network", "file", "N+1", "allocation", "recursion"))
    ]


def split_flags(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def metric_hotspots(metrics: Sequence[FunctionMetric]) -> str:
    rows = metric_hotspot_rows(metrics)
    if not rows:
        return "- none"
    return metric_hotspot_table(rows)


def metric_hotspot_rows(metrics: Sequence[FunctionMetric]) -> list[FunctionMetric]:
    return [item for item in metrics if runtime_flags(item) or item.risk not in {"A", ""}]


def metric_hotspot_table(rows: Sequence[FunctionMetric]) -> str:
    lines = [
        "| Function | Risk | Flags | Evidence | Calibration |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in rows[:15]:
        lines.append(
            "| "
            + " | ".join(
                escape_markdown(value)
                for value in (
                    item.name,
                    item.risk,
                    item.review_flags,
                    item.evidence,
                    item.calibration,
                )
            )
            + " |"
        )
    return "\n".join(lines)


def metric_overstated(metrics: Sequence[FunctionMetric]) -> str:
    candidates = metric_overstated_candidates(metrics)
    if not candidates:
        return "- none identified from deterministic metrics alone"
    return render_metric_name_lines(
        candidates,
        "I/O-in-loop may be bounded or streaming; inspect evidence before treating as N+1",
    )


def metric_overstated_candidates(metrics: Sequence[FunctionMetric]) -> list[FunctionMetric]:
    return [
        item
        for item in metrics
        if "I/O in loop" in item.review_flags and item.max_loop_depth == 1 and item.cyclomatic <= 5
    ]


def metric_understated(metrics: Sequence[FunctionMetric]) -> str:
    wrappers = metric_understated_candidates(metrics)
    if not wrappers:
        return "- wrapper-aware and cross-file runtime risks may require `scan-hotspots` plus manual call tracing"
    return "\n".join(understated_line(item) for item in wrappers[:8])


def metric_understated_candidates(metrics: Sequence[FunctionMetric]) -> list[FunctionMetric]:
    return [item for item in metrics if item.fan_out and item.fan_out >= 10 and not runtime_flags(item)]


def understated_line(item: FunctionMetric) -> str:
    return f"- `{item.name}` has fan_out={item.fan_out}; callee runtime costs may be hidden"


def metric_false_positive_candidates(metrics: Sequence[FunctionMetric]) -> str:
    candidates = recursion_false_positive_candidates(metrics)
    if not candidates:
        return "- none from current metric rules"
    return render_metric_name_lines(candidates, "recursion flag needs suppression review")


def recursion_false_positive_candidates(metrics: Sequence[FunctionMetric]) -> list[FunctionMetric]:
    return [item for item in metrics if item.direct_recursion and item.name.endswith(".__init__")]


def render_metric_name_lines(metrics: Sequence[FunctionMetric], message: str) -> str:
    return "\n".join(f"- `{item.name}`: {message}" for item in metrics[:8])


def metric_missing_signals() -> str:
    return (
        "- cannot prove input sizes, hot-path frequency, wrapper side effects, or cache behaviour from one file\n"
        "- non-Python metrics depend on lizard availability and parser support\n"
        "- Big-O and space hints are syntax-derived review prompts"
    )


def metric_evidence(metrics: Sequence[FunctionMetric]) -> str:
    lines = [
        (
            "- deterministic high confidence: LOC/SLOC, branches, loops, cyclomatic, "
            "cognitive, and risk bucket are computed from the parsed source"
        )
    ]
    heuristic_rows = [item for item in metrics if item.review_flags]
    lines.extend(
        f"- heuristic medium confidence: `{item.name}` flags `{item.review_flags}`; "
        f"evidence `{item.evidence or 'no representative line captured'}`"
        for item in heuristic_rows[:10]
    )
    return "\n".join(lines)


def metric_next_actions(metrics: Sequence[FunctionMetric]) -> str:
    non_a = [item for item in metrics if item.risk not in {"A", ""}]
    if not non_a:
        return "- no metric-driven refactor candidate; inspect runtime symptoms before changing code"
    top = worst_metric(non_a)
    return (
        f"- inspect `{top.name}` first and pin behaviour with tests before refactoring\n"
        "- validate runtime claims with input-size assumptions or measurements\n"
        "- keep changes small: split branch/side-effect blocks only when tests preserve behaviour"
    )


def escape_markdown(value: str) -> str:
    return value.replace("|", "\\|")


def write_delimited(metrics: Iterable[FunctionMetric], delimiter: str, view: str) -> None:
    fields = table_fields(view)
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, delimiter=delimiter)
    writer.writeheader()
    for item in metrics:
        writer.writerow({field: asdict(item)[field] for field in fields})
