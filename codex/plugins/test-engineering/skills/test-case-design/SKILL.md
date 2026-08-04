---
name: test-case-design
description: "Use when creating a precise test plan or concrete test cases for missing feature behaviour, including fixtures, setup, action, assertions, edge cases, and framework-specific implementation notes."
---

# Test Case Design

Design tests only after understanding code and existing coverage.

## Workflow

1. Start from a codebase map and gap review when available.
2. For each missing behaviour, define purpose, setup, action, assertion, and failure signal.
3. Prefer small tests with one reason to fail.
4. Use parametrisation for boundary matrices only when it improves clarity.
5. Keep unit, integration, and end-to-end coverage distinct.
6. Do not write files unless the user explicitly asks to implement the tests.

## Test Case Shape

For each proposed test, include:

- name
- target behaviour
- scope: unit, integration, regression, permission, error, boundary, or workflow
- setup and fixtures
- action
- assertions
- mocks or external dependencies
- why this test is not redundant with existing coverage

## Quality Bar

Good tests fail for the behaviour they name. Avoid broad smoke checks, fixture-heavy ceremony without assertions, snapshots without reviewed meaning, and tests that depend on execution order.
