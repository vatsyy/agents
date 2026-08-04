"""Canonical command adapter for bounded complexity analysis."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from analysis import analyse
from analysis_contract import (
    AnalysisInputError,
    AnalysisRequest,
    exit_code_for_status,
    non_negative_int,
)
from analysis_output import OutputError, render_with_output


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run calibrated complexity analysis through the canonical outcome contract."
    )
    parser.add_argument("target", help="Source file or directory to analyse")
    parser.add_argument("--mode", choices=("quick", "standard"), default="standard")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--max-findings", type=non_negative_int, default=80)
    parser.add_argument("--max-top", type=non_negative_int, default=8)
    parser.add_argument("--repo-context")
    parser.add_argument("--coverage-xml")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit a compact agent-safe projection without raw per-function metrics",
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        help="Write full evidence to PATH and emit the compact projection on stdout",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    request = AnalysisRequest(
        target=Path(args.target),
        mode=args.mode,
        excludes=frozenset(args.exclude),
        max_findings=args.max_findings,
        max_top=args.max_top,
        repo_context=Path(args.repo_context) if args.repo_context else None,
        coverage_xml=Path(args.coverage_xml) if args.coverage_xml else None,
    )
    try:
        outcome = analyse(request)
    except AnalysisInputError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        rendered = render_with_output(
            outcome,
            args.format,
            summary=args.summary,
            output_file=args.output_file,
        )
    except OutputError as error:
        print(str(error), file=sys.stderr)
        return 2
    sys.stdout.write(rendered)
    return exit_code_for_status(outcome.status)


if __name__ == "__main__":
    raise SystemExit(main())
