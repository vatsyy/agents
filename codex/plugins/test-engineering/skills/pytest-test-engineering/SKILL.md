---
name: pytest-test-engineering
description: "Use for Python pytest-specific test engineering: fixtures, parametrisation, marks, monkeypatching, tmp_path, assertion quality, test discovery, coverage XML, and splitting pytest tests."
---

# Pytest Test Engineering

Use this only when the repo uses pytest or Python tests following pytest conventions.

## Workflow

1. Detect pytest through `pyproject.toml`, `pytest.ini`, `tox.ini`, `conftest.py`, `test_*.py`, or `*_test.py`.
2. Prefer reading `conftest.py` and feature-local fixtures before designing tests.
3. Keep fixture scope small. Do not move setup into a fixture if it hides the behaviour under test.
4. Use `pytest.mark.parametrize` for compact boundary matrices with the same arrange/action/assert shape.
5. Use `monkeypatch`, `tmp_path`, and fakes deliberately; avoid mocks that simply restate implementation internals.
6. Do not run or write pytest tests unless the user asks. When running, use the repo's existing command and RTK for noisy output.

## Review Checks

- tests have meaningful assertions, not only "does not raise"
- parametrised cases have readable IDs when failures would be ambiguous
- fixtures do not leak state across tests
- exceptions and warnings are asserted with the expected message or type
- file, DB, network, and time dependencies are isolated
- broad tests can be decomposed without losing one workflow-level regression test
