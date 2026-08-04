---
name: test-coverage-gap-review
description: "Use when comparing feature or function behaviour against existing tests to classify what is covered, missing, partial, weak, unasserted, or needing new test cases."
compatibility: Requires the containing Test Engineering Codex plugin package; wrapper scripts dispatch to plugin-level scripts.
---

# Test Coverage Gap Review

Review behaviour coverage from code evidence and test evidence together.

## Quick Start

```bash
bash scripts/function-test-map <repo> --format markdown
bash scripts/grade-function-tests <repo> --format markdown
```

Add `--coverage-xml <path>` only when the coverage artefact already exists.

## Workflow

1. Start from `$test-codebase-map` when the feature surface is not already clear.
2. Use existing tests, assertions, fixtures, parametrisation, and coverage artefacts as evidence.
3. Separate line execution from behavioural coverage. Executed code without meaningful assertions is partial at best.
4. Classify gaps by behaviour: happy path, boundaries, validation, permissions, errors, idempotency, ordering, persistence, concurrency, and integration seams.
5. Mark confidence as high only when both code path and assertion intent are clear.
6. Prefer behaviour-oriented findings over function-name-only claims. Static name matches are routing clues, not proof.
7. Keep coverage states `not-requested`, `missing`, `malformed`, `empty`, and `loaded` distinct; unavailable evidence is not zero execution.
8. Stop clean-verdict language when inventory or parsing is partial, unsupported, truncated, or failed.

## Output

Use this shape:

- `covered`: specific behaviours with file/test evidence
- `partial`: exercised but weakly asserted behaviours
- `missing`: behaviours or functions with no credible test evidence
- `improvable`: existing tests needing stronger assertions, clearer setup, or better separation
- `needs_to_create`: test cases to add next, with purpose and expected assertions
- `coverage_caveats`: missing coverage file, stale index, dynamic dispatch, generated code, or framework-specific uncertainty
