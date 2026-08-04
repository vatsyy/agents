---
name: test-suite-inventory
description: "Use when inspecting existing tests to understand what test files, test cases, fixtures, assertions, frameworks, and behavioural intent already exist before deciding coverage or new test work."
compatibility: Requires the containing Test Engineering Codex plugin package; wrapper scripts dispatch to plugin-level scripts.
---

# Test Suite Inventory

Inventory tests before judging gaps.

## Quick Start

```bash
bash scripts/test-inventory <repo> --format markdown
```

Use JSON only when another script or report needs machine-readable output.

## Workflow

1. Run `test-inventory` for a repo or directory scope.
2. Read the highest-signal test files directly: feature-specific tests, fixture-heavy files, and any oversized or assertion-light files.
3. Group tests by behaviour, not just by filename.
4. Identify framework clues: pytest fixtures and marks, unittest classes, JS/TS test runners, adapter-specific base classes, factory helpers, snapshot tests, and integration boundaries.
5. Do not label a behaviour covered unless the test has an assertion or observable verification tied to that behaviour.
6. Report discovered, supported-candidate, analysed, failed, excluded, unsupported, and truncated counts. A partial inventory is not a clean inventory.

## Output

Report:

- test framework and layout detected
- test files and test case counts
- fixture and helper usage
- behaviours currently exercised
- assertion-light or smoke-only areas
- files that need manual reading before coverage conclusions
- analysis status, adapter limits, skipped files, and parse diagnostics
