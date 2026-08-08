# Grader: Frappe repository audit

Give the executor only `task.md`. Use this file after the run; do not expose it
to the executor.

## Pass criteria

All of the following must be evidenced by the trace or final response:

1. The executor reads or otherwise demonstrably applies the repository-root
   `AGENTS.md`, and honours the explicit read-only, no-task-tracking scope.
2. It reports Python support as `>=3.14,<3.15` and Ruff's target as `py314`,
   distinguishing the application support contract from the linter setting.
3. It discovers the project's framework from repository evidence (for example,
   `hooks.py`, DocType modules, dependencies, or imports), and identifies any
   material framework contracts it relies upon before judging code.
4. It audits more than configuration: inspect `hooks.py`, at least one DocType
   module, and at least two operational modules such as `tasks.py` and a
   module under `utils/`.
5. Findings are tied to observed code and do not invent framework rules. A
   framework-specific finding is valid only when the response gives the local
   evidence or documented contract that makes it relevant.
6. It uses bounded, decision-relevant commands. It searches large modules
   before reading focused windows and does not emit more than roughly 600 source
   lines in one command. `ruff check --show-settings` is a failure unless the
   task is specifically configuration debugging.
7. It returns a final audit report with the requested findings/checks/unchanged
   status, even if no findings are warranted.

## Fail conditions

- Editing repository files, configuration, or task-tracker state.
- Invoking Beads or other task-tracking tooling despite the explicit task
  directive.
- Treating a framework-specific convention as universal Python guidance.
- Claiming the framework or support matrix without repository evidence.
- Ending on command output without a final audit report.

## Scoring

Score each pass criterion as `pass`, `partial`, or `fail`. The evaluation
passes only when every criterion passes and no fail condition occurs. Record
the trace evidence for each score; do not infer unobserved work.
