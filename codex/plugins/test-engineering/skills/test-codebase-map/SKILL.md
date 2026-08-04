---
name: test-codebase-map
description: "Use when test work must first understand the codebase, feature structure, public entrypoints, callers, callees, side effects, data flow, or framework wiring before judging or designing tests."
---

# Test Codebase Map

Map the feature before evaluating its tests.

## Workflow

1. Resolve the target feature, module, function family, report, command, API, component, or workflow.
2. Use Codanna when healthy for semantic search, exact symbols, callers, callees, implementations, and impact.
3. Read only narrowed files after structural search. Use `rg` for decorators, routes, hook names, fixtures, config keys, generated names, and framework strings.
4. List the behavioural surface to test: public entrypoints, branches, validation paths, permissions, persistence, external calls, failure modes, and user-visible outputs.
5. Hand off to `$test-suite-inventory`, `$test-coverage-gap-review`, or `$function-test-grader` only after the feature surface is clear.

## Output

Return a compact map:

- target and files inspected
- public entrypoints and important internal functions
- direct callers and callees where available
- data stores, side effects, external services, and framework hooks
- behaviours that must have tests
- uncertainty, stale-index caveats, or manual fallbacks used
