# Complexity Plugin

Read-only complexity and performance-risk analysis for Codex. The plugin combines
heuristic hotspot detection, deterministic function metrics, coverage accounting,
ranking, bounded repository context, and reproducible Markdown or JSON output.

## Runtime and command

Python 3.10+ is required. All shell entry points share `scripts/complexity-python`;
set `COMPLEXITY_PYTHON` to select a specific interpreter.

```sh
scripts/analyse-complexity TARGET --mode standard --format markdown --summary
scripts/analyse-complexity TARGET --mode quick --format json --summary
```

- `quick` requests heuristic scanning only.
- `standard` requests heuristics and deterministic metrics wherever the relevant
  adapter supports the source language. It is the default.
- `--max-findings` limits rendered findings; `--max-top` independently limits top
  files, top functions, and the inspection queue. Coverage and totals are never
  truncated.
- Use `--summary` for repository or directory scans to omit raw per-function
  rows explicitly while retaining counts and ranked evidence. `--output-file PATH`
  writes the full evidence and returns that compact projection on stdout. Both
  controls are available on the compatibility wrappers; their output files
  retain the legacy shape while stdout uses the canonical summary envelope.
  CSV/TSV compatibility output remains raw and byte-compatible; those formats
  reject `--summary` and `--output-file` because compact controls require
  Markdown or JSON.
- `--repo-context PATH` optionally adds bounded heuristic call-site, Git-churn,
  and coverage evidence. Optional failures remain diagnostics.
- `--coverage-xml PATH` supplies a coverage snapshot. When repository context is
  omitted, the target directory (or a file target's parent) is used as its scope.

## Status and exit codes

| Exit | Status | Meaning |
| ---: | --- | --- |
| 0 | `complete` | Every applicable requested lane completed for nonzero analysed scope. |
| 1 | internal failure | An unexpected implementation failure occurred. |
| 2 | input error | Invocation or named target is invalid or unreadable. |
| 3 | `partial` | Useful evidence exists but required coverage is incomplete. |
| 4 | `unsupported` | No eligible source file was analysed. |

Only `complete` with at least one analysed source file can receive a clean verdict.
`partial` is inconclusive and `unsupported` has no verdict.

## Capability matrix

| Source class | Heuristics | Metrics |
| --- | --- | --- |
| Python | bundled text/AST scanner | bundled Python AST adapter |
| C/C++, Java, JavaScript/TypeScript, Go, Ruby, PHP, C#, Swift | text scanner | Lizard 1.23 adapter |
| Rust, Kotlin, Scala, Lua, Erlang, Fortran, Objective-C, Solidity, Zig, TTCN, PL/SQL and other manifest suffixes | not applicable | Lizard 1.23 adapter |
| Shell (`.sh`, `.bash`, `.zsh`, `.fish`) | unsupported | unsupported |
| Documentation and assets | not applicable | not applicable |

Applicability is lane-specific: standard Rust can be complete through metrics,
while quick Rust is unsupported because no heuristic adapter applies.

## Canonical output

JSON without output controls remains the schema-v1 full object with
`schema_version: 1`, `plugin_version`, `status`,
normalized `request`, full `coverage`, six stable `adapters`, `verdict`,
`decision_fields`, raw `metrics`, limited `findings`, `top_files`, `top_functions`,
`inspection_queue`, `diagnostics`, truthful `repo_context` denominators, `counts`,
and stage `timings`. `--summary` adds an explicit `projection` marker and returns
zero raw rows; `--output-file` preserves the full object at the requested path.
Markdown is rendered from the same authoritative projection.

The legacy `complexity-triage`, `scan-hotspots`, and `measure-complexity` commands
remain compatibility adapters. Their successful JSON row shapes are unchanged;
new consumers should use `analyse-complexity`.

## Verification

```sh
python3 -m unittest -v plugins.complexity.tests.test_complexity_plugin
```

The skill remains read-only: command output is evidence, and strong performance or
refactor claims still require inspection of the ranked source.
