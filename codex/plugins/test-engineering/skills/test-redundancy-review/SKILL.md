---
name: test-redundancy-review
description: "Use when reviewing existing tests for duplicate intent, obsolete coverage, over-broad smoke tests, excessive fixture reuse, weak assertions, or low-value tests that should be merged, rewritten, or retired."
---

# Test Redundancy Review

Find redundancy without deleting useful safety nets.

## Workflow

1. Inventory tests first with `$test-suite-inventory` or `test-inventory <repo>`.
2. Group tests by intent, behaviour, target function, fixture setup, and assertion shape.
3. Treat repeated setup as a refactor candidate only when it obscures intent or creates brittle coupling.
4. Treat duplicate names as a clue, not proof. Confirm by reading assertions and exercised code.
5. Do not remove tests during review. Recommend merge, split, rewrite, or retire with risk noted.

## Redundancy Signals

- same behaviour asserted in multiple places without a different boundary or integration layer
- smoke tests that call a path but assert only truthiness or no exception
- stale tests for removed feature flags, old routes, or obsolete fixtures
- monolithic tests hiding several independent behaviours
- repeated fixture setup that makes failure cause unclear

## Output

Report redundant candidates with:

- test file and test name
- overlapping tests or behaviours
- why it is redundant or weak
- recommended action: keep, merge, split, rewrite, or retire
- risk if changed
