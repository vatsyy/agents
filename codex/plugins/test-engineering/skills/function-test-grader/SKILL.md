---
name: function-test-grader
description: "Use when assigning function-to-test coverage grades by mapping source functions to direct tests, assertions, coverage XML evidence, and missing or weak behavioural cases."
compatibility: Requires the containing Test Engineering Codex plugin package; wrapper scripts dispatch to plugin-level scripts.
---

# Function Test Grader

Grade functions against test evidence.

## Quick Start

```bash
bash scripts/grade-function-tests <repo> --format markdown
```

Add `--coverage-xml <path>` when available.

## Rubric

- `A`: direct tests, meaningful assertions, and coverage evidence or clear behaviour coverage.
- `B`: direct tests and assertions, with minor missing boundaries.
- `C`: indirect or partial evidence; behaviour is exercised but assertions are incomplete.
- `D`: weak evidence such as execution-only coverage, smoke tests, or assertion-light tests.
- `E`: no credible test evidence found.

## Workflow

1. Run `grade-function-tests` for a reproducible static first-pass mapping.
2. Manually inspect high-risk functions, public entrypoints, and low grades before final judgement.
3. Treat name matching as a hint. A call-shaped static reference and assertions elsewhere in the same file are still not proof of assertion intent.
4. Use coverage XML as execution evidence, not as proof of behavioural coverage.
5. For each `D` or `E`, propose concrete test cases through `$test-case-design`.
6. Preserve confidence labels and evidence types. Do not upgrade a name-only/static match into a coverage claim.
7. If status is `partial` or `unsupported`, report the diagnostics before discussing grades and do not issue a clean verdict.
8. In incomplete outcomes, use `observed_grade` only as evidence from successfully analysed files; the repository grade remains `unavailable`.

## Output

Return a table with function, file, grade, evidence, missing behaviour, and recommended next test.
