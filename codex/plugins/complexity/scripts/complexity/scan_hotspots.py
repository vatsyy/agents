"""Legacy heuristic reporting and CLI compatibility adapter."""

from __future__ import annotations

import argparse
import csv
import io
import json
import shlex
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path

from analysis_contract import non_negative_int
from analysis_output import (
    OutputError,
    render,
    validate_compact_output_options,
    write_text_file,
)
from heuristic_scanner import (
    Hotspot,
    ScanReport,
    ScanStats,
    WrapperEvidence,
    collect_repo_python_wrapper_evidence,
    dedupe,
    is_bounded_loop_finding,
    iter_source_files,
    read_text,
    relative_path,
    scan_text_by_language,
    sort_key,
)


def render_markdown(findings: Sequence[Hotspot]) -> str:
    if not findings:
        return "No obvious complexity hotspots found by heuristic scanning.\n"
    lines = [
        (
            "| Severity | Confidence | Kind | Location | Symbol | Current Pattern | "
            "Estimated Complexity | Recommendation | Expected Complexity | Verification |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for finding in findings:
        location = f"{finding.path}:{finding.line}"
        lines.append(
            "| "
            + " | ".join(
                escape_cell(value)
                for value in (
                    finding.severity,
                    finding.confidence,
                    finding.kind,
                    location,
                    finding.symbol,
                    finding.current_pattern,
                    finding.estimated_complexity,
                    finding.recommendation,
                    finding.expected_complexity,
                    finding.verification,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_markdown_report(report: ScanReport) -> str:
    findings = report.findings
    return "\n".join(
        [
            "## Orientation Brief",
            render_orientation(report),
            "## Complexity Verdict",
            render_scan_verdict(findings),
            "## Deterministic Metrics",
            render_scan_metrics(report),
            "## Heuristic Hotspots",
            render_hotspot_table(findings),
            "## Overstated Findings",
            render_overstated(findings),
            "## Understated Risks",
            render_understated(findings),
            "## False Positive Candidates",
            render_false_positive_candidates(findings),
            "## Missing Signals",
            render_missing_signals(),
            "## Evidence and Confidence",
            render_evidence(findings),
            "## Smallest Next Action Plan",
            render_next_actions(findings),
        ]
    ) + "\n"


def render_orientation(report: ScanReport) -> str:
    stats = report.stats
    languages = ", ".join(
        f"{suffix or '[none]'}:{count}" for suffix, count in sorted(stats.language_counts.items())
    )
    skipped = f"{stats.files_skipped}"
    return (
        f"- Scope: `{stats.root}`\n"
        f"- Plugin version: `{stats.plugin_version}`\n"
        f"- Files scanned: {stats.files_scanned}\n"
        f"- Files skipped: {skipped}\n"
        f"- Language counts: {languages or 'none'}\n"
        f"- Command: `{report.command}`"
    )


def render_scan_verdict(findings: Sequence[Hotspot]) -> str:
    if not findings:
        return clean_scan_verdict()
    return populated_scan_verdict(findings)


def clean_scan_verdict() -> str:
    return (
        "- Maintainability risk: low from this scanner\n"
        "- Runtime risk: no obvious heuristic hotspot\n"
        "- Refactor priority: none from static scan alone"
    )


def populated_scan_verdict(findings: Sequence[Hotspot]) -> str:
    return (
        f"- Maintainability risk: {maintainability_verdict(findings)}\n"
        f"- Runtime risk: {runtime_risk_text(findings)}\n"
        f"- Refactor priority: {scan_refactor_priority(findings)}"
    )


def maintainability_verdict(findings: Sequence[Hotspot]) -> str:
    return maintainability_from_severities(high_function_complexity_severities(findings))


def high_function_complexity_severities(findings: Sequence[Hotspot]) -> set[str]:
    return {item.severity for item in findings if item.kind == "high-function-complexity"}


def maintainability_from_severities(severities: set[str]) -> str:
    if "high" in severities:
        return "high"
    if severities:
        return "medium"
    return "low-to-medium"


def runtime_risk_text(findings: Sequence[Hotspot]) -> str:
    return (
        f"static scan found {len(findings)} leads, including "
        f"{count_severity(findings, 'high')} high-severity and "
        f"{count_kind(findings, 'wrapper-io-in-loop')} wrapper-aware leads"
    )


def scan_refactor_priority(findings: Sequence[Hotspot]) -> str:
    bounded_count = sum(1 for item in findings if is_bounded_loop_finding(item))
    return (
        "inspect high-confidence data-loop findings first; "
        f"treat {bounded_count} bounded-loop findings as calibration checks"
    )


def count_severity(findings: Sequence[Hotspot], severity: str) -> int:
    return sum(1 for item in findings if item.severity == severity)


def count_kind(findings: Sequence[Hotspot], kind: str) -> int:
    return sum(1 for item in findings if item.kind == kind)


def render_scan_metrics(report: ScanReport) -> str:
    counts = kind_counts(report.findings)
    rendered_counts = ", ".join(f"{kind}:{count}" for kind, count in sorted(counts.items()))
    return (
        f"- Deterministic scope facts: files_scanned={report.stats.files_scanned}, "
        f"files_skipped={report.stats.files_skipped}\n"
        f"- Heuristic finding counts: {rendered_counts or 'none'}\n"
        "- exact per-function cyclomatic/cognitive metrics require `measure-complexity`."
    )


def kind_counts(findings: Sequence[Hotspot]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in findings:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def render_hotspot_table(findings: Sequence[Hotspot]) -> str:
    if not findings:
        return "- none"
    rows = [
        "| Severity | Confidence | Kind | Location | Loop | Evidence | Calibration |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in findings[:20]:
        rows.append(
            "| "
            + " | ".join(
                escape_cell(value)
                for value in (
                    item.severity,
                    item.confidence,
                    item.kind,
                    f"{item.path}:{item.line}",
                    item.loop_classification,
                    item.evidence,
                    item.calibration or item.estimated_complexity,
                )
            )
            + " |"
        )
    return "\n".join(rows)


def render_overstated(findings: Sequence[Hotspot]) -> str:
    candidates = overstated_candidates(findings)
    if not candidates:
        return "- none identified by calibration rules"
    return render_hotspot_lines(candidates, "{kind}: {current_pattern}")


def overstated_candidates(findings: Sequence[Hotspot]) -> list[Hotspot]:
    return [item for item in findings if is_bounded_loop_finding(item) or item.confidence == "low"]


def render_hotspot_lines(findings: Sequence[Hotspot], template: str) -> str:
    return "\n".join(render_hotspot_line(item, template) for item in findings[:8])


def render_hotspot_line(item: Hotspot, template: str) -> str:
    body = template.format(kind=item.kind, current_pattern=item.current_pattern)
    return f"- `{item.path}:{item.line}` {body}"


def render_understated(findings: Sequence[Hotspot]) -> str:
    wrappers = [item for item in findings if item.kind == "wrapper-io-in-loop"]
    if wrappers:
        return "\n".join(
            f"- `{item.path}:{item.line}` wrapper call may hide external latency: {item.evidence}"
            for item in wrappers[:8]
        )
    return (
        "- wrapper and cross-file external-call risks may still be missed; run "
        "targeted inspection on high-risk entrypoints"
    )


def render_false_positive_candidates(findings: Sequence[Hotspot]) -> str:
    candidates = [item for item in findings if item.confidence == "low"]
    if not candidates:
        return "- none from current confidence rules"
    return "\n".join(
        f"- `{item.path}:{item.line}` {item.kind}: needs manual validation before changing code"
        for item in candidates[:8]
    )


def render_missing_signals() -> str:
    return (
        "- cannot prove input cardinality, hot-path frequency, cache invalidation, permissions, or retry safety\n"
        "- cross-file wrapper propagation is heuristic; use manual call tracing for material claims\n"
        "- Big-O and space claims are review prompts, not proven performance facts"
    )


def render_evidence(findings: Sequence[Hotspot]) -> str:
    if not findings:
        return (
            "- deterministic: file/language counts are direct filesystem facts\n"
            "- heuristic: no hotspot claim emitted"
        )
    lines = ["- deterministic: file/language counts are direct filesystem facts"]
    lines.extend(
        f"- {item.claim_type} ({item.confidence}): `{item.path}:{item.line}` "
        f"{item.kind}; {item.confidence_reason or 'static pattern match'}"
        for item in findings[:10]
    )
    return "\n".join(lines)


def render_next_actions(findings: Sequence[Hotspot]) -> str:
    if not findings:
        return "- no immediate plugin-reported refactor; measure known hot files if runtime symptoms exist"
    top = findings[0]
    return (
        f"- inspect `{top.path}:{top.line}` first and validate input bounds before proposing changes\n"
        "- run `measure-complexity` on files with high-function-complexity findings\n"
        "- benchmark or test only after a specific behaviour-preserving change is selected"
    )


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_csv(findings: Sequence[Hotspot]) -> None:
    sys.stdout.write(render_csv(findings))


def render_csv(findings: Sequence[Hotspot]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(Hotspot.__dataclass_fields__.keys()))
    writer.writeheader()
    for finding in findings:
        writer.writerow(asdict(finding))
    return output.getvalue()


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a repository for likely complexity hotspots.")
    parser.add_argument("root", nargs="?", default=".", help="Repository or directory to scan.")
    parser.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown")
    parser.add_argument("--exclude", action="append", default=[], help="Additional directory name to exclude.")
    parser.add_argument("--max-findings", type=non_negative_int, default=80)
    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Emit a compact canonical projection instead of raw findings "
            "(requires Markdown or JSON; CSV is rejected)"
        ),
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        help=(
            "Write full legacy evidence to PATH and emit the compact projection on stdout "
            "(requires Markdown or JSON; CSV is rejected)"
        ),
    )
    return parser.parse_args(argv)

def scan_source_file(
    path: Path,
    root: Path,
    stats: ScanStats | None = None,
    repo_wrappers: dict[str, WrapperEvidence] | None = None,
) -> list[Hotspot]:
    text = read_text(path)
    if text is None:
        record_skipped_file(stats, path, root)
        return []
    record_scanned_file(stats, path)
    return scan_text_by_language(path, root, text, repo_wrappers)


def record_skipped_file(stats: ScanStats | None, path: Path, root: Path) -> None:
    if stats is None:
        return
    stats.files_skipped += 1
    stats.skipped_paths.append(relative_path(path, root))


def record_scanned_file(stats: ScanStats | None, path: Path) -> None:
    if stats is None:
        return
    stats.files_scanned += 1
    suffix = path.suffix or "[none]"
    stats.language_counts[suffix] = stats.language_counts.get(suffix, 0) + 1




def collect_findings(root: Path, excludes: set[str]) -> list[Hotspot]:
    findings: list[Hotspot] = []
    paths = list(iter_source_files(root, excludes))
    repo_wrappers = collect_repo_python_wrapper_evidence(paths, root)
    for path in paths:
        findings.extend(scan_source_file(path, root, repo_wrappers=repo_wrappers))
    return findings


def collect_report(root: Path, excludes: set[str], command: str) -> ScanReport:
    stats = ScanStats(root=str(root))
    findings: list[Hotspot] = []
    paths = list(iter_source_files(root, excludes))
    repo_wrappers = collect_repo_python_wrapper_evidence(paths, root)
    for path in paths:
        findings.extend(scan_source_file(path, root, stats, repo_wrappers))
    return ScanReport(stats=stats, findings=findings, command=command)


def limit_findings(findings: Iterable[Hotspot], max_findings: int) -> list[Hotspot]:
    return sorted(dedupe(findings), key=sort_key)[:max_findings]


def emit_findings(findings: Sequence[Hotspot], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps([asdict(finding) for finding in findings], indent=2))
    elif output_format == "csv":
        write_csv(findings)
    else:
        print(render_markdown(findings), end="")


def rendered_findings(findings: Sequence[Hotspot], output_format: str) -> str:
    if output_format == "json":
        return json.dumps([asdict(finding) for finding in findings], indent=2) + "\n"
    if output_format == "csv":
        return render_csv(findings)
    return render_markdown(findings)


def emit_report(report: ScanReport, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps([asdict(finding) for finding in report.findings], indent=2))
    elif output_format == "csv":
        write_csv(report.findings)
    else:
        print(render_markdown_report(report), end="")


def command_text(root: Path, args: argparse.Namespace) -> str:
    command = [
        "scan-hotspots",
        str(root),
        "--format",
        args.format,
        "--max-findings",
        str(args.max_findings),
    ]
    if args.summary:
        command.append("--summary")
    if args.output_file:
        command.extend(("--output-file", str(args.output_file)))
    return shlex.join(command)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        validate_compact_output_options(
            args.format,
            summary=args.summary,
            output_file=args.output_file,
        )
    except OutputError as error:
        print(str(error), file=sys.stderr)
        return 2
    root = Path(args.root).expanduser().resolve()
    from analysis import analyse
    from analysis_contract import (
        AnalysisInputError,
        AnalysisRequest,
        exit_code_for_status,
        status_message,
    )

    try:
        outcome = analyse(
            AnalysisRequest.for_compatibility(
                root,
                "heuristic",
                excludes=frozenset(args.exclude),
            )
        )
    except AnalysisInputError as error:
        print(str(error), file=sys.stderr)
        return 2
    findings = limit_findings(outcome.findings, args.max_findings)
    if outcome.status == "complete" or findings or args.summary or args.output_file:
        full_text = rendered_findings(findings, args.format)
        try:
            path = write_text_file(args.output_file, full_text) if args.output_file else None
        except OutputError as error:
            print(str(error), file=sys.stderr)
            return 2
        if args.summary or path is not None:
            sys.stdout.write(
                render(
                    outcome,
                    args.format,
                    projection="summary",
                    output_file=path,
                )
            )
        else:
            sys.stdout.write(full_text)
    message = status_message(outcome.status)
    if message:
        print(message, file=sys.stderr)
    return exit_code_for_status(outcome.status)


if __name__ == "__main__":
    raise SystemExit(main())
