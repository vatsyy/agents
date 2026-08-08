# Frappe repository audit

Run this task from `/Users/vatsal/frappev16/v16/apps/onedrive_backup_v16`.

> Use `$python` to perform a read-only audit of all production Python in this
> repository. Read applicable project instructions and resolve the effective
> Python and lint configuration before auditing. Do not edit files, invoke
> Beads or other task tracking, create task records, or run a whole-project test
> suite. Inspect source in bounded groups
> and return at most eight actionable findings. For every finding, give its
> severity (`MUST`, `SHOULD`, or `JUDGEMENT`), path, line, evidence, and a
> proportionate remedy. Report the resolved support/tooling targets, relevant
> framework contracts, checks run/skipped, and whether files were changed.

The task deliberately does not identify the framework. Discover it from the
repository and apply only the framework constraints supported by the project’s
own code, configuration, or documentation.
