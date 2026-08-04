# Complexity Triage Report Template

Use this formal shape when the user explicitly requests a full repo-wide scan,
file review, or optimisation audit. Normal chat should distil the evidence to
Scope, Findings, Evidence, and Next Action. Add `Manual Judgement` only when
source inspection adds interpretation beyond the command output.

## Orientation Brief

- Scope analysed:
- Files/functions scanned:
- Files skipped:
- Language counts:
- Commands run:
- Plugin/script version:
- Timing summary:

## Complexity Verdict

- Maintainability risk:
- Runtime risk:
- Refactor priority:

## Deterministic Metrics

Repeatable facts only: cyclomatic, cognitive, LOC/SLOC, nesting, fan-in/out,
risk bucket, maintainability index, file counts, language counts, risk counts,
non-A rows, metric failures, and top files/functions.

## Heuristic Hotspots

Potential performance or maintainability leads. Use calibrated language:
"static scan suggests", "candidate", "manual validation needed".

## Manual Judgement

Source-inspection conclusions that explain which tool findings are material,
bounded, downgraded, or worth acting on first. Include only when manual source
inspection was performed.

## Overstated Findings

Warnings that may be low risk because they are bounded retry loops, fixed-size
loops, set/dict membership, streaming loops, pagination loops, or guarded
recursion.

## Understated Risks

Risks the scanner may miss or under-rank: wrapper calls, framework/database APIs,
pagination, chunked uploads, cleanup loops, retry amplification, hidden external
latency, and cross-file side effects.

## False Positive Candidates

Findings needing suppression, downgraded wording, or stronger evidence.

## Missing Signals

What static analysis cannot prove: input sizes, hot-path frequency, cache
invalidation, permissions, retry safety, page bounds, and production data shape.

## Evidence and Confidence

Label each material claim as deterministic, heuristic, or manual judgement, with
high/medium/low confidence and representative evidence lines.

## Smallest Next Action Plan

Order the smallest useful improvements or repo actions by engineering value.
