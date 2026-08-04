from __future__ import annotations

from .constants import (
    BOUNDARY_ASSERTION_TERMS,
    ERROR_ASSERTION_TERMS,
    EXTERNAL_ASSERTION_TERMS,
    MOCK_TERMS,
    PERMISSION_ASSERTION_TERMS,
    PERSISTENCE_ASSERTION_TERMS,
    STATE_ASSERTION_TERMS,
)


def assertion_kinds(samples: list[str], body_text: str) -> list[str]:
    text = combined_text(samples, body_text)
    labels: list[str] = []
    add_label(labels, "error-path", contains_any(text, ERROR_ASSERTION_TERMS))
    add_label(labels, "boundary", contains_any(text, BOUNDARY_ASSERTION_TERMS))
    add_label(labels, "state-change", contains_any(text, STATE_ASSERTION_TERMS))
    add_label(labels, "persistence", contains_any(text, PERSISTENCE_ASSERTION_TERMS))
    add_label(labels, "permission/security", contains_any(text, PERMISSION_ASSERTION_TERMS))
    add_label(labels, "external-call", contains_any(text, EXTERNAL_ASSERTION_TERMS))
    add_label(labels, "observable assertion", bool(samples))
    return labels


def combined_text(samples: list[str], body_text: str) -> str:
    return " ".join([body_text, *samples]).lower()


def add_label(labels: list[str], label: str, condition: bool) -> None:
    if condition:
        labels.append(label)


def contains_any(text: str, terms: set[str]) -> bool:
    return any(term.lower() in text for term in terms)


def mock_count(text: str) -> int:
    return sum(text.count(term.lower()) for term in lower_terms(MOCK_TERMS))


def lower_terms(terms: set[str]) -> set[str]:
    return {term.lower() for term in terms}


def test_confidence(assertions: int, mocks: int) -> str:
    if assertions == 0:
        return "low"
    if mocks >= 4:
        return "medium"
    return "high"


def risk_notes(assertions: int, mocks: int, branches: int) -> list[str]:
    notes: list[str] = []
    add_label(notes, "assertion-light", assertions == 0)
    add_label(notes, "over-mocked", mocks >= 4)
    add_label(notes, "branch-heavy", branches >= 6)
    return notes
