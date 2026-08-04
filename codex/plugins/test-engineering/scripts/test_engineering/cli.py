#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from test_engineering.analysis import analyse_repo  # noqa: E402
from test_engineering.analysis_contract import command_context, exit_code_for  # noqa: E402
from test_engineering.output import render  # noqa: E402


COMMANDS = {
    "test-inventory",
    "function-test-map",
    "grade-function-tests",
    "monolith-test-report",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only test engineering evidence reports."
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("repo", help="Repository or directory to analyse.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--coverage-xml",
        help="Optional existing coverage.py XML report. The command never generates coverage.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        repo = Path(args.repo)
        coverage_xml = Path(args.coverage_xml) if args.coverage_xml else None
        report = analyse_repo(repo, coverage_xml)
    except Exception as exc:
        if args.format == "json":
            print(render_error_json(str(exc)))
        else:
            print(f"test-engineering: {exc}", file=sys.stderr)
        return 2
    report = command_context(report, args.command, repo, coverage_xml)
    print(render(report, args.command, args.format), end="")
    return exit_code_for(report)


def render_error_json(message: str) -> str:
    import json

    return json.dumps(
        {
            "schema_version": "1.0",
            "status": "error",
            "diagnostics": [{"severity": "error", "code": "input-error", "message": message}],
        },
        sort_keys=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
