---
name: "analyse-complexity"
description: "Use when you need read-only static complexity analysis, hotspot ranking, or source-based performance-risk review across repositories, directories, or source files."
---

# Analyse Complexity

Run bounded static analysis without editing code. The command supplies evidence;
inspect the highest-ranked source locations before making strong claims.

## Canonical command

```sh
bash scripts/analyse-complexity TARGET --mode standard --format markdown --summary
```

Use `--summary` for repository or directory scans so chat receives bounded
agent-safe evidence; it marks raw metrics as omitted and retains their count.
Use `--output-file PATH` to save the full schema-v1 evidence while returning the
same compact projection. Omit both controls only when the caller needs raw
metrics in the response. `quick` is heuristic-only; `standard` adds metrics.
JSON is the canonical machine format, and compatibility wrappers accept the
same output controls; wrapper files retain their legacy shape while stdout uses
the canonical summary envelope. CSV/TSV compatibility output remains raw;
`--summary` and `--output-file` require Markdown or JSON.

## Trust contract

- `complete` / exit `0`: every applicable requested lane completed.
- `partial` / exit `3`: useful evidence exists, but required coverage failed or
  unsupported source is mixed into the scope.
- `unsupported` / exit `4`: no eligible source file was analysed.
- Invalid invocation or target / exit `2`: report the input error from stderr.
- Never turn zero analysed files, missing adapters, or read failures into a clean
  or low-risk verdict.
- Optional Git, `rg`, and coverage enrichment gaps are diagnostics, not failures
  of otherwise complete static analysis.

## Workflow

1. Resolve the user-named scope exactly; do not widen a file request.
2. Run the canonical command from this skill directory.
3. Check status, coverage, adapters, diagnostics, and truncation metadata.
4. Inspect source for the top files, functions, and heuristic findings.
5. Separate deterministic facts from heuristic leads and manual judgement.
6. Report only findings that survive source inspection, plus verification gaps.

The scripts emit full evidence when requested. Normal chat should distil it to
`Scope`, `Findings`, `Evidence`, and `Next Action`; preserve the formal report
headings only when the user requests a formal audit.

## References

- Use the [optimisation playbook](references/optimisation-playbook.md) after a
  finding is validated and the user wants refactor choices.
- Use the [formal report template](references/report-template.md) when the user
  explicitly requests a full report.

Completion means the requested scope was analysed, coverage status was stated,
ranked source was inspected, confidence was calibrated, and no code was edited.
