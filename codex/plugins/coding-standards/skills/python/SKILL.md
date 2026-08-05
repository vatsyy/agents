---
name: python
description: Apply project-aware Python standards when implementing, reviewing, refactoring, or optimising Python code.
---

# Python coding standards

Use this skill only when Python code is in scope. It supplements governing instructions, task scope, repository policy, and general testing or review guidance.

## Authority and rule strength

For review-only requests, inspect and report without editing. For implementation requests, edit only authorised, in-scope artefacts.

Rule precedence is:

1. **MUST** — governing instructions, active project configuration, supported runtime, declared contracts, correctness, security, resource safety, and truthful verification.
2. **SHOULD** — Python conventions and engineering defaults where the project has not decided otherwise.
3. **JUDGEMENT** — architecture, abstraction, test depth, typing coverage, concurrency, and performance choices based on context.

A **SHOULD** may be waived when active project or task context justifies it. A **MUST** may be displaced only by a higher-precedence instruction or an explicit in-scope contract change.

## Resolve before work

1. Identify whether the request is review-only or implementation.
2. Inspect instructions and effective configuration needed for the changed paths. Expand into contributing, deployment, packaging, framework, or public-contract documentation only when relevant.
3. Resolve configuration separately for every changed subtree using the project’s actual command, working directory, explicit arguments, nested files, and `extend` relationships. Do not assume root configuration applies or that nested Ruff configurations merge automatically.
4. Resolve Python support:
   - For libraries, treat `requires-python` as the packaging contract. Use CI as evidence of tested versions; classifiers and documentation corroborate it.
   - For applications, treat active deployment/runtime definitions and CI environments as credible consumers.
   - Preserve every credible active consumer unless the task explicitly changes support.
   - If a material conflict cannot be satisfied safely, report it and request direction.
   - Treat Ruff `target-version` as tooling/parser configuration, not the sole support contract.
5. Identify changed contracts, framework registration, side effects, dependencies, and relevant tests.
6. Make the smallest coherent change.

## MUST preserve

- Existing behaviour, public/API/data contracts, and resource ownership unless an in-scope change requires otherwise.
- Only the resolved, declared Python support range. Do not add speculative version shims, polyfills, or fallback branches. Required compatibility code for a declared multi-version library is not speculative.
- Correctness, security, and resource safety.
- Causal and observable failure information unless an active abstraction or security contract explicitly requires translation or suppression.
- Never catch `BaseException` except in explicit termination machinery; preserve cancellation and process-termination semantics.
- Do not weaken configured quality gates or conceal their outcomes.

## SHOULD follow

- PEP 8 layout, naming, imports, and whitespace; PEP 20’s explicit/simple/readable bias; PEP 257 docstrings where documentation is expected.
- The current typing specification and project type policy. Annotate new or changed public boundaries and complex internals when useful; do not require blanket annotations. Avoid indiscriminate `Any` and `type: ignore`, allowing documented boundary cases.
- PEP 585/604 and newer syntax only when the resolved target supports it.
- Descriptive names, straightforward control flow, and comments that explain why.
- Cohesive units split by responsibility, dependency, change reason, and testability—not arbitrary line count.
- Existing project dependencies and patterns. Add a dependency only with clear need and compatibility/security review.
- Explicit imports. Avoid incidental wildcard imports, while permitting controlled public re-exports with `__all__`.
- No accidental import-time work; preserve deliberate framework registration and import-time wiring.
- Context managers and explicit resource ownership.
- Specific exception handling for local recovery. Catch `Exception` broadly only at a documented containment boundary—for example, a process, job, request, worker, plugin callback, or batch-item boundary—whose contract requires translation, isolation, cleanup, or recording. Use the project’s established observability mechanism and produce a defined outcome.
- Boundary validation for external input.
- No speculative abstractions, god modules/classes, circular imports, duplicated business logic, or accidental deep nesting.

## JUDGEMENT: resilience and performance

Retries, timeouts, degradation, and worker isolation are domain behaviour. Use them only when the project or explicit in-scope task contract requires them, with bounded limits and observable failure.

For routine changes, avoid evident regressions without mandatory benchmarking. For performance work:

- choose the algorithm and data structure first;
- establish a baseline and compare before/after on the same representative workload;
- verify semantic equivalence;
- report environment, metric, and measurement uncertainty;
- do not add caching, concurrency, JITs, or alternative interpreters solely for speculative speed.

## Verification and hand-off

Run configured checks relevant to the changed paths and contract, expanding from focused checks according to risk. Do not require absent tools or a whole-project suite for every edit.

For new or changed tests, control time, randomness, network, and environment; use bounded polling when eventual consistency is real.

Apply automatic fixes only within authorised files and inspect the diff. Narrow, documented suppressions are acceptable for genuine false positives, but never weaken quality gates merely to pass.

Always report checks run, skipped, or failed. Report target resolution, changed contracts, unresolved findings, and performance, compatibility, or resilience decisions only when material.

## Conditional references

Load only when relevant:

- `references/project-resolution.md`
- `references/typing-and-api.md`
- `references/performance-and-concurrency.md`
- `references/verification-matrix.md`
- `references/pep-map.md`
