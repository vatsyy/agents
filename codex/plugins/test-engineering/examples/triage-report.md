# Example Triage Report

This is the intended shape of a senior-review first pass. It is not a coverage oracle.

- Analysis status: **complete**
- Schema version: 1.0

## Report Basis

- Inventory: 17 analysed / 17 supported candidates / 64 discovered files.
- Parsing: 17 succeeded / 17 attempted; 0 failed.
- Coverage evidence: not-requested (unavailable lines indexed).
- Diagnostics: none.
- Adapters: python-ast@1, javascript-static@1, coverage-xml@1.

## Orientation Brief

- 12 source files and 5 test files inspected.
- 42 test cases found across pytest/python.
- No coverage XML requested.

Runner clues: Python project configuration found.; Framework hint: pytest/python.

## Trust Verdict

Static triage suggests medium trust for narrow unit behaviour and low refactor readiness. No coverage XML was requested; seven public or risky behaviours look probably untested, two tests are assertion-light, one test is mock-heavy, and one test is a monolith candidate. Manual inspection is required.

Evidence basis:

- Can I trust the tests around this code? partial (medium confidence, heuristic).
- What behaviour is unprotected? 7 public behaviour candidates look probably untested; 3 private functions are only not directly mapped. (medium confidence, heuristic).
- What tests are implementation-shaped or over-mocked? 1 tests look mock-heavy by static scan. (medium confidence, heuristic).

## Covered

- `normalise_payload` in `src/payload.py:14` grade B (medium confidence, deterministic): direct test reference with observable assertion evidence.

## Missing

- `upload_file` in `src/client.py:82` grade E (high confidence, deterministic): no direct test reference, no assertion evidence, and no coverage XML evidence.

## Redundant

- `test_upload_smoke` and `test_upload_happy_path` appear to assert the same success-path intent (medium confidence, heuristic). Confirm by reading both before deleting or merging.

## Improvable

- `test_retry_client` in `tests/test_client.py:72` checks the retry method was called, but does not assert the observable result after retries (medium confidence, heuristic).

## Needs To Create

- `test_upload_file_persists_progress_after_partial_chunk` for `upload_file` in `src/client.py:82`: setup a two-chunk upload, force a partial response, and assert persisted progress plus final metadata.

## Monolith Candidates

- `test_backup_workflow` in `tests/test_tasks.py:120` has many assertions and mixed setup/action/result phases (medium confidence, heuristic). Split by independently named behaviour while preserving workflow regression intent.

## Function Grades

- Grade counts: B=12, D=4, E=7.
- Highest-risk low-confidence functions: `upload_file`, `load_upload_state`, `cleanup_old_backups`.

## Smallest Next Action Plan

| Action | Target | Evidence | Recommendation |
| --- | --- | --- | --- |
| add-test | `upload_file` in `src/client.py:82` | none confidence, heuristic | Create a focused test with setup, action, and observable assertions. |
| strengthen-assertion | `test_upload_smoke` in `tests/test_client.py:44` | high confidence, heuristic | No direct assertion found in this test case. |
| split-test | `test_backup_workflow` in `tests/test_tasks.py:120` | medium confidence, heuristic | Split by independently named behaviour while preserving workflow regression intent. |

The useful next step is to read those exact tests and functions, then add the smallest missing test oracle before refactoring.
