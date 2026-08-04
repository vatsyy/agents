---
name: test-monolith-decomposer
description: "Use when large, multi-assertion, multi-branch, fixture-heavy, or scenario-packed test cases need to be split into smaller focused tests without losing behavioural coverage."
compatibility: Requires the containing Test Engineering Codex plugin package; wrapper scripts dispatch to plugin-level scripts.
---

# Test Monolith Decomposer

Break broad tests into focused behaviours while preserving safety.

## Quick Start

```bash
bash scripts/monolith-test-report <repo> --format markdown
```

## Workflow

1. Identify monolithic candidates by line count, assertion count, branch count, fixture count, parametrisation breadth, and mixed behaviours.
2. Read each candidate before recommending a split. Metrics are clues, not proof.
3. Extract independent behaviours into separately named tests.
4. Keep shared setup only when it improves readability and failure diagnosis.
5. Preserve regression intent. If a broad test protects an integration workflow, replace it with focused tests plus one intentional workflow test.
6. Do not edit test files unless the user explicitly asks for implementation.

## Output

For each candidate, report:

- current test name and file
- behaviours packed into the test
- proposed new test names
- setup that should remain shared
- assertions to move into each new test
- coverage or regression risk to preserve
