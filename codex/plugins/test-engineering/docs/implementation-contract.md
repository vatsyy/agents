# Test Engineering Improvement Contract

Fixed point: `9ca2b2fea79241d2bb132302b2bc7ff569f808ab`

## Architectural verdict

The plugin must expose one deep analysis module through `analyse_repo(repo, coverage_xml=None)`. Inventory, parsing, coverage state, adapter disclosure, evidence calibration, diagnostics, status, limits, and trust gating belong behind that interface. Root commands and skill-local scripts remain compatibility adapters.

## Required behaviour

1. Preserve the four root commands, all skill-local wrapper paths, protected WIP, and existing successful top-level JSON collections.
2. Emit a stable schema version and one status: `complete`, `partial`, `unsupported`, or `error`.
3. Exit `0` for complete analysis, `1` for partial or unsupported analysis, and `2` for input errors.
4. Never render incomplete inventory, parser failure, unsupported code, malformed configuration, or invalid requested coverage as a trustworthy clean verdict.
5. Keep unavailable coverage evidence distinct from concrete zero counts.
6. Report explicit inventory and parsing denominators, exclusions, failures, unsupported files, limits, truncation, diagnostics, adapters, and reproducible commands.
7. Treat function-name mapping, file-level assertions, and line execution as distinct evidence. Preserve legacy labels where compatibility requires them, but mark static name mapping as heuristic and manual-review-required.
8. Reuse deterministic traversal and loaded file text across the canonical analysis path.
9. Claim only implemented Python AST and pattern-based JavaScript/TypeScript capabilities, with pytest, unittest, Jest-style, Vitest, and Frappe adapter clues described at their actual confidence.
10. Keep Markdown and JSON derived from the same canonical outcome.
11. Cover supported, unsupported, empty, mixed, malformed, partial, path-with-spaces, invalid coverage, framework, false-positive, false-negative, and compatibility cases in regression tests and the labelled corpus.

## Stop conditions

Stop without resetting if the baseline fails for unrelated reasons, protected WIP cannot be preserved, or completion requires dependency installation, network access, or edits outside `plugins/test-engineering/`.
