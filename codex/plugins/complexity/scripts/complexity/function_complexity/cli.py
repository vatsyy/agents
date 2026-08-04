from __future__ import annotations

import argparse
import contextlib
import io
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from analysis_output import (
    OutputError,
    render,
    validate_compact_output_options,
    write_text_file,
)

from .lizard_adapter import analyse_with_lizard
from .output import markdown_report, sort_metrics, write_delimited
from .python_ast import analyse_python


def analyse_file(path: Path):
    if path.suffix == ".py":
        return analyse_python(path)
    return analyse_with_lizard(path)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report per-function complexity metrics for one source file."
    )
    parser.add_argument("file", help="Source file to analyse")
    parser.add_argument(
        "--format",
        choices=("markdown", "json", "csv", "tsv"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--sort",
        choices=("source", "complexity"),
        default="source",
        help="Sort rows by source order or descending complexity",
    )
    parser.add_argument(
        "--view",
        choices=("core", "full", "review"),
        default="core",
        help="Column set to print",
    )
    parser.add_argument(
        "--repo-context",
        help="Optional repository root for repo references, Git churn, and coverage enrichment",
    )
    parser.add_argument(
        "--coverage-xml",
        help="Optional coverage.xml path; defaults to <repo-context>/coverage.xml when present",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Emit a compact canonical projection instead of raw per-function metrics "
            "(requires Markdown or JSON; CSV/TSV are rejected)"
        ),
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        help=(
            "Write full legacy evidence to PATH and emit the compact projection on stdout "
            "(requires Markdown or JSON; CSV/TSV are rejected)"
        ),
    )
    return parser.parse_args(argv)


def emit_metrics(
    metrics,
    output_format: str,
    view: str,
    *,
    path: Path,
    repo_context: Path | None,
    command: str,
) -> None:
    print(
        render_metrics(
            metrics,
            output_format,
            view,
            path=path,
            repo_context=repo_context,
            command=command,
        ),
        end="",
    )


def render_metrics(
    metrics,
    output_format: str,
    view: str,
    *,
    path: Path,
    repo_context: Path | None,
    command: str,
) -> str:
    if output_format == "json":
        return json.dumps([asdict(item) for item in metrics], indent=2) + "\n"
    if output_format == "csv":
        return render_delimited(metrics, ",", view)
    if output_format == "tsv":
        return render_delimited(metrics, "\t", view)
    return (
        markdown_report(
            metrics,
            view,
            source_path=path,
            repo_context=repo_context,
            command=command,
        )
        + "\n"
    )


def render_delimited(metrics, delimiter: str, view: str) -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        write_delimited(metrics, delimiter, view)
    return output.getvalue()


def repo_context_path(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    return None


def coverage_xml_path(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    return None


def command_text(path: Path, args: argparse.Namespace) -> str:
    command = [
        "measure-complexity",
        str(path),
        "--format",
        args.format,
        "--view",
        args.view,
        "--sort",
        args.sort,
    ]
    if args.summary:
        command.append("--summary")
    if args.output_file:
        command.extend(("--output-file", str(args.output_file)))
    return shlex.join(command)


def effective_repo_context(
    path: Path, repo_context: Path | None, coverage_xml: Path | None
) -> Path | None:
    if repo_context is not None:
        return repo_context
    return path.parent if coverage_xml is not None else None


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
    path = Path(args.file).expanduser().resolve()
    from analysis import analyse
    from analysis_contract import (
        AnalysisInputError,
        AnalysisRequest,
        exit_code_for_status,
        status_message,
    )

    repo_context = repo_context_path(args.repo_context)
    coverage_xml = coverage_xml_path(args.coverage_xml)
    context_root = effective_repo_context(path, repo_context, coverage_xml)
    try:
        outcome = analyse(
            AnalysisRequest.for_compatibility(
                path,
                "metrics",
                repo_context=context_root,
                coverage_xml=coverage_xml,
            )
        )
    except AnalysisInputError as error:
        print(str(error), file=sys.stderr)
        return 2
    explicit_compact_output = args.summary or args.output_file
    if outcome.status == "unsupported" and not explicit_compact_output:
        print(status_message(outcome.status), file=sys.stderr)
        return exit_code_for_status(outcome.status)
    metrics = [item.metric for item in outcome.metrics]
    if outcome.status == "complete" or metrics or explicit_compact_output:
        full_text = render_metrics(
            sort_metrics(metrics, args.sort),
            args.format,
            args.view,
            path=path,
            repo_context=context_root,
            command=command_text(path, args),
        )
        try:
            output_path = (
                write_text_file(args.output_file, full_text) if args.output_file else None
            )
        except OutputError as error:
            print(str(error), file=sys.stderr)
            return 2
        if explicit_compact_output:
            sys.stdout.write(
                render(
                    outcome,
                    args.format,
                    projection="summary",
                    output_file=output_path,
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
