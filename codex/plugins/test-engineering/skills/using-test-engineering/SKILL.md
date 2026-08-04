---
name: "using-test-engineering"
description: "Use as the front door for codebase-aware test engineering work: understanding a feature before test judgement, inventorying existing tests, reviewing coverage gaps, finding redundant or weak tests, designing missing tests, grading function-to-test evidence, and decomposing monolithic test cases."
---

# Using Test Engineering

```yaml
contract:
  plugin: Test Engineering
  role: front_door_router
  purpose: evidence-backed judgement about tests and missing tests
  default_mode: read_first
  never:
    - invent coverage from file names alone
    - generate coverage reports unless the user asks
    - treat heuristic grades as final without source/test inspection
    - edit tests before mapping behaviour, fixtures, and assertions
```

## Dispatch

```yaml
scripts:
  inventory:
    run: bash scripts/test-inventory <repo> --format markdown
    use_when:
      - user asks what tests exist
      - test framework or layout is unknown
      - a coverage judgement needs baseline inventory
  function_map:
    run: bash scripts/function-test-map <repo> --format markdown
    use_when:
      - user asks what tests cover which functions
      - source-to-test traceability matters
  grade_functions:
    run: bash scripts/grade-function-tests <repo> --format markdown
    optional_flags:
      - --coverage-xml <path>
    use_when:
      - user asks for coverage grades
      - weak or missing behavioural assertions need ranking
  monolith_report:
    run: bash scripts/monolith-test-report <repo> --format markdown
    use_when:
      - tests are large, multi-scenario, fixture-heavy, or hard to debug
      - user asks whether tests should be split

machine_readable:
  formats: [json]
  use_when:
    - user requests structured output
    - another script will consume results
```

All four scripts cross the same canonical `analyse_repo` seam. Choose a script for the report emphasis, not for a different inventory or grading authority. Treat exit `0` as complete adapter execution, exit `1` as partial/unsupported evidence, and exit `2` as an input error.

## Specialist Routing

```yaml
skills:
  test-codebase-map:
    use_when: feature structure, entrypoints, callers, side effects, or framework wiring are unclear
  test-suite-inventory:
    use_when: existing tests, fixtures, assertions, or runner clues must be catalogued
  test-coverage-gap-review:
    use_when: behaviour must be compared against existing test evidence
  test-redundancy-review:
    use_when: duplicate, obsolete, weak, or over-broad tests need review
  test-case-design:
    use_when: missing behaviour needs concrete test cases
  function-test-grader:
    use_when: source functions need direct test/assertion grades
  test-monolith-decomposer:
    use_when: a large test needs splitting without losing coverage
  pytest-test-engineering:
    use_when: pytest fixtures, marks, parametrisation, monkeypatching, or assertions dominate
  frappe-test-engineering:
    use_when: Frappe or ERPNext transactions, DocTypes, permissions, hooks, patches, or reports dominate
```

## Evidence Contract

```yaml
required_before_judgement:
  - target behaviour or feature
  - relevant source entrypoints
  - existing test files and assertions
  - runner/framework clues
  - fixture and side-effect boundaries
  - analysis status, diagnostics, and inventory/parsing denominators

escalate_risk_when:
  - destructive operations
  - migrations or schema changes
  - permissions or roles
  - persistence or transactions
  - external IO
  - money, dates, taxes, or rounding
  - scheduler hooks or async jobs
  - public entrypoints

report_fields:
  - `orientation_brief`
  - `trust_verdict`
  - `covered`
  - `missing`
  - `redundant`
  - `low_signal`
  - `placeholder`
  - `improvable`
  - `needs_to_create`
  - `monolith_candidates`
  - `function_grades`
  - `smallest_next_action_plan`
  - command_or_files_inspected
  - confidence
  - covered_behaviour
  - missing_or_weak_behaviour
  - redundant_or_low_value_tests
  - recommended_test_changes
  - verification_gaps
  - status_and_diagnostics
  - adapters_and_limits

empty_sections: If a section has no findings and analysis is complete, say `none found` rather than omitting it. For partial or unsupported analysis, say the repository-wide verdict is unavailable and scope any retained evidence to successfully analysed files.
```

## Workflow

```yaml
steps:
  - classify request as inventory, gap review, redundancy review, case design, grading, or decomposition
  - run the smallest script that establishes baseline evidence
  - inspect representative source and test files before strong claims
  - use specialist skills only for the matching framework or test task
  - keep suggested tests concrete: setup, action, assertions, edge cases
  - report skipped checks and uncertain mappings
  - stop clean-verdict language when status is partial or unsupported
  - when `assessment.repository_verdict_available` is false, report `observed_*` evidence as scoped and do not restate it as a repository grade, taxonomy verdict, or action verdict

language:
  deterministic: use strong wording only with exact source/test/function evidence
  heuristic: Do not overstate heuristic findings; label broad counts and generated grades as triage until manually checked
```
