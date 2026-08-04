"""Canonical serialization for complexity analysis outcomes."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from analysis_contract import (
    DEFAULT_EXCLUDES,
    PLUGIN_VERSION,
    SCHEMA_VERSION,
    AnalysisOutcome,
    MeasuredMetric,
)

OutputFormat = Literal["markdown", "json"]
OutputProjection = Literal["full", "summary"]


class OutputError(ValueError):
    """A requested output destination or format could not be honoured."""


def render(
    outcome: AnalysisOutcome,
    output_format: OutputFormat,
    *,
    projection: OutputProjection = "full",
    output_file: Path | None = None,
) -> str:
    document = build_document(
        outcome,
        output_format,
        projection=projection,
        output_file=output_file,
    )
    if output_format == "json":
        return json.dumps(document, indent=2, sort_keys=False) + "\n"
    if output_format == "markdown":
        return render_markdown(document)
    raise ValueError(f"Unsupported output format: {output_format}")


def build_document(
    outcome: AnalysisOutcome,
    output_format: OutputFormat,
    *,
    projection: OutputProjection = "full",
    output_file: Path | None = None,
) -> dict[str, object]:
    if projection not in {"full", "summary"}:
        raise ValueError(f"Unsupported output projection: {projection}")
    request = outcome.request
    all_metrics = [metric_to_dict(item) for item in outcome.metrics]
    metrics = all_metrics if projection == "full" else []
    all_findings = [asdict(item) for item in outcome.findings]
    all_top_files = [asdict(item) for item in outcome.top_files]
    all_top_functions = [metric_to_dict(item) for item in outcome.top_functions]
    all_inspection_targets = [asdict(item) for item in outcome.inspection_queue]
    findings = all_findings[: request.max_findings]
    top_files = all_top_files[: request.max_top]
    top_functions = all_top_functions[: request.max_top]
    inspection_queue = all_inspection_targets[: request.max_top]
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "status": outcome.status,
        "request": {
            "target": outcome.target,
            "target_kind": outcome.target_kind,
            "mode": request.mode,
            "required_lanes": sorted(request.required_lanes),
            "requested_excludes": sorted(request.excludes),
            "effective_excludes": sorted(DEFAULT_EXCLUDES | request.excludes),
            "max_findings": request.max_findings,
            "max_top": request.max_top,
            "repo_context": str(request.repo_context.expanduser().resolve())
            if request.repo_context
            else None,
            "coverage_xml": str(request.coverage_xml.expanduser().resolve())
            if request.coverage_xml
            else None,
            "context_limit": request.context_limit,
            "output_format": output_format,
            "reproducible_command": reproducible_command(
                outcome,
                output_format,
                projection=projection,
                output_file=output_file,
            ),
        },
        "coverage": asdict(outcome.coverage),
        "adapters": [asdict(item) for item in outcome.adapters],
        "verdict": outcome.verdict,
        "decision_fields": outcome.decision_fields,
        "metrics": metrics,
        "findings": findings,
        "top_files": top_files,
        "top_functions": top_functions,
        "inspection_queue": inspection_queue,
        "diagnostics": [asdict(item) for item in outcome.diagnostics],
        "repo_context": asdict(outcome.repo_context),
        "timings": asdict(outcome.timings),
        "counts": {
            "metrics": count_metadata(len(all_metrics), len(metrics)),
            "findings": count_metadata(len(all_findings), len(findings)),
            "top_files": count_metadata(len(all_top_files), len(top_files)),
            "top_functions": count_metadata(len(all_top_functions), len(top_functions)),
            "inspection_queue": count_metadata(
                len(all_inspection_targets), len(inspection_queue)
            ),
        },
    }
    if projection == "summary":
        document["projection"] = {
            "name": "summary",
            "raw_metrics": {
                "included": False,
                "total": len(all_metrics),
                "returned": 0,
                "full_output_file": (
                    str(output_file.expanduser().resolve()) if output_file else None
                ),
            },
        }
    return document


def metric_to_dict(item: MeasuredMetric) -> dict[str, object]:
    return {"path": item.path, **asdict(item.metric)}


def canonical_analysis_payload(outcome: AnalysisOutcome) -> dict[str, object]:
    """Project the stable analysis fields retained by legacy commands."""
    return {
        "status": outcome.status,
        "coverage": asdict(outcome.coverage),
        "adapters": [asdict(item) for item in outcome.adapters],
        "diagnostics": [asdict(item) for item in outcome.diagnostics],
        "verdict": outcome.verdict,
    }


def reproducible_command(
    outcome: AnalysisOutcome,
    output_format: OutputFormat,
    *,
    projection: OutputProjection = "full",
    output_file: Path | None = None,
) -> str:
    request = outcome.request
    command = [
        "analyse-complexity",
        outcome.target,
        "--mode",
        request.mode,
        "--format",
        output_format,
        "--max-findings",
        str(request.max_findings),
        "--max-top",
        str(request.max_top),
    ]
    for exclude in sorted(request.excludes):
        command.extend(("--exclude", exclude))
    if request.repo_context is not None:
        command.extend(
            ("--repo-context", str(request.repo_context.expanduser().resolve()))
        )
    if request.coverage_xml is not None:
        command.extend(
            ("--coverage-xml", str(request.coverage_xml.expanduser().resolve()))
        )
    if projection == "summary":
        command.append("--summary")
    if output_file is not None:
        command.extend(("--output-file", str(output_file.expanduser().resolve())))
    return shlex.join(command)


def resolve_output_file(output_file: Path | str) -> Path:
    """Resolve a user-supplied output path without creating its parent."""
    return Path(output_file).expanduser().resolve()


def validate_compact_output_options(
    output_format: str,
    *,
    summary: bool = False,
    output_file: Path | str | None = None,
) -> None:
    """Reject compact controls that would otherwise change a delimited contract."""
    if output_format not in {"csv", "tsv"} or (not summary and output_file is None):
        return
    controls = []
    if summary:
        controls.append("--summary")
    if output_file is not None:
        controls.append("--output-file")
    joined = " and ".join(controls)
    raise OutputError(
        f"{joined} require Markdown or JSON; {output_format.upper()} output "
        "cannot be used with compact controls"
    )


def write_text_file(output_file: Path | str, text: str) -> Path:
    """Write output evidence and translate filesystem errors into CLI-safe errors."""
    path = resolve_output_file(output_file)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise OutputError(f"Could not write output file {path}: {error}") from error
    return path


def render_with_output(
    outcome: AnalysisOutcome,
    output_format: OutputFormat,
    *,
    summary: bool = False,
    output_file: Path | str | None = None,
) -> str:
    """Render full evidence to disk and return an agent-safe projection when requested."""
    if output_file is not None:
        path = write_text_file(
            output_file,
            render(
                outcome,
                output_format,
                output_file=resolve_output_file(output_file),
            ),
        )
        return render(
            outcome,
            output_format,
            projection="summary",
            output_file=path,
        )
    return render(
        outcome,
        output_format,
        projection="summary" if summary else "full",
    )


def count_metadata(total: int, returned: int) -> dict[str, object]:
    return {"total": total, "returned": returned, "truncated": returned < total}


def render_markdown(document: dict[str, object]) -> str:
    status = str(document["status"])
    request = require_dict(document["request"])
    coverage = document["coverage"]
    assert isinstance(coverage, dict)
    verdict = document["verdict"]
    overall = verdict.get("overall") if isinstance(verdict, dict) else "unavailable"
    counts = require_dict(document["counts"])
    findings = require_list(document["findings"])
    top_files = require_list(document["top_files"])
    top_functions = require_list(document["top_functions"])
    inspection_queue = require_list(document["inspection_queue"])
    diagnostics = require_list(document["diagnostics"])
    projection = document.get("projection")
    lines = [
        "## Scope",
        f"- Target: `{request['target']}`",
        f"- Mode: {request['mode']}",
        f"- Status: {status}",
        f"- Analysed files: {coverage.get('analysed_files', 0)}/{coverage.get('eligible_files', 0)} eligible",
        f"- Unsupported files: {coverage.get('unsupported_files', 0)}",
        f"- Failed files: {coverage.get('failed_files', 0)}",
        "",
    ]
    if projection is not None:
        output = require_dict(projection)
        raw_metrics = require_dict(output["raw_metrics"])
        full_output_file = raw_metrics.get("full_output_file")
        lines.extend(
            [
                "## Output",
                f"- Projection: `{output['name']}`",
                (
                    "- Raw metrics: omitted from this response; "
                    f"{raw_metrics['total']} rows remain available"
                ),
                (
                    f"- Full evidence: `{full_output_file}`"
                    if full_output_file
                    else "- Full evidence: rerun without `--summary`"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Verdict",
            f"- Overall: {overall}",
            "",
            "## Top Files",
            render_count_summary(counts, "top_files", "Top files"),
            *render_top_files(top_files),
            "",
            "## Top Functions",
            render_count_summary(counts, "top_functions", "Top functions"),
            *render_top_functions(top_functions),
            "",
            "## Findings",
            render_count_summary(counts, "findings", "Findings"),
            *render_findings(findings),
            "",
            "## Inspection Queue",
            render_count_summary(counts, "inspection_queue", "Inspection targets"),
            *render_inspection_queue(inspection_queue),
            "",
            "## Diagnostics",
            *render_diagnostics(diagnostics),
            "",
            "## Reproduce",
            f"`{request['reproducible_command']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def require_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Expected mapping in canonical analysis document")
    return value


def require_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Expected list in canonical analysis document")
    return value


def render_count_summary(
    counts: dict[str, object], key: str, label: str
) -> str:
    item = require_dict(counts[key])
    truncated = str(bool(item["truncated"])).lower()
    return (
        f"- {label} returned: {item['returned']}/{item['total']}; "
        f"truncated: {truncated}"
    )


def render_top_files(rows: list[object]) -> list[str]:
    if not rows:
        return ["- None"]
    lines = [
        "| File | Why selected | Worst risk | Functions | Hotspots |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for value in rows:
        row = require_dict(value)
        lines.append(
            "| "
            + " | ".join(
                escape_markdown(str(item))
                for item in (
                    row["path"],
                    row["reason"],
                    row["worst_risk"],
                    row["function_count"],
                    row["hotspot_count"],
                )
            )
            + " |"
        )
    return lines


def render_top_functions(rows: list[object]) -> list[str]:
    if not rows:
        return ["- None"]
    lines = [
        "| Function | Location | Risk | Cyclomatic | Cognitive |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for value in rows:
        row = require_dict(value)
        lines.append(
            "| "
            + " | ".join(
                escape_markdown(str(item))
                for item in (
                    row["name"],
                    f"{row['path']}:{row['start']}",
                    row["risk"],
                    row["cyclomatic"],
                    row.get("cognitive") or "",
                )
            )
            + " |"
        )
    return lines


def render_findings(rows: list[object]) -> list[str]:
    if not rows:
        return ["- None"]
    lines = [
        "| Location | Kind | Severity | Confidence | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for value in rows:
        row = require_dict(value)
        lines.append(
            "| "
            + " | ".join(
                escape_markdown(str(item))
                for item in (
                    f"{row['path']}:{row['line']}",
                    row["kind"],
                    row["severity"],
                    row["confidence"],
                    row["evidence"],
                )
            )
            + " |"
        )
    return lines


def render_inspection_queue(rows: list[object]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- `{require_dict(value)['path']}:{require_dict(value)['line']}` "
        f"{require_dict(value)['name']} — {require_dict(value)['reason']}"
        for value in rows
    ]


def render_diagnostics(rows: list[object]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {require_dict(value)['stage']}: "
        f"{require_dict(value).get('path') or '[adapter]'} — {require_dict(value)['reason']}"
        for value in rows
    ]


def escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
