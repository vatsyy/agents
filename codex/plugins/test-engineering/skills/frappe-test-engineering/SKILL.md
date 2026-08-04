---
name: frappe-test-engineering
description: "Use for Frappe and ERPNext test engineering: DocType controllers, whitelisted methods, reports, hooks, patches, permissions, fixtures, transactions, bench run-tests, and integration-safe test design."
---

# Frappe Test Engineering

Use this only when the repo is a Frappe app or the target feature depends on Frappe/ERPNext behaviour.

## Workflow

1. Detect app structure through `hooks.py`, module directories, DocType JSON/controllers, reports, patches, fixtures, and `pyproject.toml`.
2. Map the feature through controllers, whitelisted methods, reports, scheduled jobs, hooks, client scripts, and permission checks.
3. Separate pure Python behaviour from Frappe integration behaviour.
4. Prefer existing Frappe test patterns in the app before introducing new fixtures.
5. Treat database writes, naming series, background jobs, permissions, and transactions as first-class test concerns.
6. Do not run `bench --site ... run-tests` unless the user provides or approves the site context.

## Test Design Checks

- DocType tests assert saved document state, validation errors, permissions, and side effects.
- Report tests assert filters, columns, totals, ordering, and permission-sensitive rows.
- Whitelisted method tests assert allowed inputs, rejected inputs, permissions, and response shape.
- Patch tests are idempotent and safe for partially migrated data.
- Integration tests clean up or isolate data according to the repo's existing pattern.
