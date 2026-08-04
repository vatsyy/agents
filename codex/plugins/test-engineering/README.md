# Test Engineering

Test Engineering is a read-only Codex plugin for codebase-aware test review. It helps an agent understand a project, inventory tests, map function-to-test evidence, identify weak or missing coverage, find redundant or monolithic tests, and design the next tests to create.

The intended use is senior-engineer triage: get a fast, evidence-backed first pass before reviewing, refactoring, or improving a test suite.

The core is framework-neutral. Framework-specific behaviour belongs in narrow adapters and should not dominate the public report.

## What It Does

- Walks a repository deterministically and separates supported source files from test files.
- Inventories Python, JavaScript, and TypeScript test files.
- Recognises pytest, unittest, Jest, Vitest, and adapter-scoped framework patterns.
- Maps source functions to static call references, name-only clues, file-scoped assertion evidence, and optional coverage XML.
- Grades function-to-test confidence with explicit evidence labels.
- Extracts static assertion signals such as error paths, boundaries, state changes, persistence, permission/security checks, and external calls.
- Produces an orientation brief, trust report, and action plan.
- Reports covered, missing, redundant, improvable, needs-to-create, monolith candidates, and assertion-light areas.
- Reports inventory and parsing denominators, exclusions, unsupported code, diagnostics, adapter versions, limits, and render truncation.

## What It Does Not Prove

- It does not prove behavioural coverage from names alone.
- It does not generate coverage XML or run tests unless an agent is separately asked to do so.
- It does not rewrite, delete, or create tests by default.
- It does not treat a low function grade as proof that the exact helper needs a direct unit test.
- It does not replace manual review of assertions, fixtures, mocks, and framework wiring.

## Commands

```bash
scripts/test-inventory <repo> --format markdown
scripts/function-test-map <repo> --format markdown
scripts/grade-function-tests <repo> --format markdown
scripts/monolith-test-report <repo> --format markdown
```

Use JSON for machine-readable output:

```bash
scripts/grade-function-tests <repo> --format json
```

JSON and Markdown are projections of the same versioned outcome. JSON retains the legacy report collections and adds `schema_version`, `status`, `diagnostics`, `inventory`, `parsing`, `coverage`, `adapters`, `limits`, `truncation`, `command`, and `reproduction`.

For `partial` and `unsupported` runs, `assessment.repository_verdict_available` is false. Function grades, taxonomy, actions, trust fields, and empty sections are then unavailable as repository-wide verdicts. Evidence from successfully analysed files remains under explicitly scoped fields such as `observed_grade`, `observed_*_counts`, and `assessment_status: scoped-evidence-only`.

Statuses and exits:

- `complete` exits `0`: every in-scope supported file was analysed by its declared adapter.
- `partial` exits `1`: some evidence was skipped or failed, including malformed Python/config/coverage, missing or empty requested coverage, unreadable files or directories, supported oversize files, traversal limits, or mixed unsupported code.
- `unsupported` exits `1`: the scope has no analysable supported source or test files.
- input `error` exits `2`; JSON callers receive a small machine-readable error outcome.

`complete` describes execution of the declared static adapters, not proof that the test suite is behaviourally complete.

Use an existing coverage artefact when available:

```bash
scripts/function-test-map <repo> --coverage-xml coverage.xml --format markdown
```

## Recommended Codex Prompt

```text
Use $using-test-engineering for a read-only senior-engineer-grade test review of this repository. Include exact evidence, confidence labels, explicit empty sections, and a smallest-useful-next-action plan.
```

## Evidence Labels

- `direct test reference`: retained for compatibility when the static scan finds a call-shaped reference in a test file with assertions; it is still heuristic and requires inspection.
- `coverage XML evidence`: an existing coverage XML file shows line execution.
- `indirect behavioural evidence`: coverage exists without a direct static test reference.
- `name/static heuristic`: the function name appears without a call-shaped reference; it does not raise the function grade.
- `no evidence`: no static test or coverage evidence was found.

Major findings also include `confidence`, `evidence_type`, `mapping_method`, `assertion_scope`, and `manual_review_required`. File-level assertions do not prove that a matching function call owns those assertions.

## Claim Calibration

Reports should be read as calibrated triage, not proof:

- Deterministic facts cover inventory, parser completion, extracted syntax, and supplied coverage line data. Function-to-test mappings and behavioural interpretations remain heuristic.
- Heuristic findings are review leads and include representative examples where counts are large, such as mock-heavy tests.
- Missing coverage around migrations, destructive data changes, permissions, persistence, external calls, date/money logic, scheduler hooks, and public entrypoints is prioritised above low-risk private-helper noise.
- Private helpers, constants, adapter hooks, and lifecycle methods should not be treated as direct-test mandates unless they own independent risk.
- Placeholder and low-signal tests are reported separately from redundant tests; redundancy means duplicate or overlapping intent.

## Report Sections

Full-repository agent reviews should always include these sections, even when a section has no findings:

- `Orientation Brief`: source/test layout, framework hints, runner clues, fixture/helper shape, coverage XML availability, and high-signal test files.
- `Trust Verdict`: whether the suite is trustworthy for mocked unit behaviour, behavioural coverage, and refactor readiness.
- `Covered`: behaviour or functions with credible test evidence.
- `Missing`: behaviour or functions with no meaningful test evidence.
- `Redundant`: duplicate, overlapping, obsolete, or low-signal tests.
- `Improvable`: tests that exist but need sharper assertions, fixtures, boundaries, parametrisation, or separation.
- `Needs To Create`: concrete new test cases with purpose, setup, action, and assertions.
- `Monolith Candidates`: large, multi-branch, multi-assertion, or scenario-packed tests worth splitting.
- `Function Grades`: grade summary plus highest-risk low-confidence functions for large repos.
- `Smallest Next Action Plan`: the smallest useful next tests, assertion improvements, mock reviews, or test splits.

Deterministic script output also includes `Trust Verdict`, `Trust Report`, and `Action Plan` sections. `Trust Report` surfaces grade counts, risk counts, and the highest-risk `E`/`D` functions so an agent can cite the script evidence without rereading the whole grade table.

## Interpreting Grades

Grades are confidence signals, not verdicts on code quality.

- `A` and `B`: credible test evidence exists; review boundary cases for critical paths.
- `C` and `D`: some evidence exists, but assertions, boundaries, or confidence need review.
- `E`: no credible deterministic evidence was found.

For private or internal helpers, prefer testing the public behaviour they protect. Add direct helper tests only when the helper owns tricky parsing, branching, state handling, or boundary logic.

## Known Limitations

- JavaScript and TypeScript function extraction is lightweight and pattern-based.
- Dynamic dispatch, generated tests, custom runners, and snapshot-heavy suites need manual inspection.
- Coverage XML is execution evidence, not proof of assertion quality.
- Only successfully loaded, non-empty coverage XML is described as execution evidence; missing, malformed, unreadable, and empty artefacts remain unavailable.
- Redundancy and monolith findings are heuristics and should be confirmed by reading the tests.
- JavaScript/TypeScript support is pattern-based rather than a full parser; Jest-style globals and Vitest are recognised, not executed.
- Python uses the standard-library AST. Pytest, unittest, and Frappe test bases are classified from static structure and clues; framework runtime wiring is not executed.
- Traversal stops after 50,000 discovered files, skips symlink targets and ignored directories, and skips supported files larger than 2,000,000 bytes. The outcome records each applicable denominator or exclusion.

## Canonical Analysis Seam

[`analyse_repo()`](scripts/test_engineering/analysis.py) is the single interface for inventory, parsing, grading, taxonomy, status, diagnostics, trust gating, and adapter disclosure. The four commands and skill-local scripts are compatibility adapters that select report presentation; they are not separate analysis authorities.

Internally, one typed analysis run carries inventory, loaded text, cached Python ASTs, parser outcomes, coverage state, and adapter runtime state into one typed assessment outcome. Serialization happens only when `analyse_repo()` returns the compatibility dictionary. Python source extraction, test extraction, and call mapping reuse the same AST. Adapter capability metadata is declared beside its concrete source/test dispatch and emitted with attempted, analysed, failed, and runtime-state counts.

## Repo-Local Configuration

Optional `.test-engineering.json` files can suppress known generated or irrelevant paths:

```json
{
  "ignore_path_contains": ["vendor/"],
  "generated_path_contains": ["generated/"]
}
```

Keep configuration narrow. It should document local review intent, not hide real test debt.
