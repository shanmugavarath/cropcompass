"""Cheap deterministic content asserts — the hard pass/fail safety net.

Case-insensitive substring matching on the delivered answer text.
"""

from __future__ import annotations

from ..schema import Expected, Trace


def must_include_score(text: str, terms: list[str]) -> float:
    """Fraction of required terms present (1.0 when no terms are required)."""
    if not terms:
        return 1.0
    low = (text or "").lower()
    hits = sum(1 for t in terms if t.lower() in low)
    return hits / len(terms)


def must_not_include_violations(text: str, terms: list[str]) -> list[str]:
    low = (text or "").lower()
    return [t for t in terms if t.lower() in low]


def keyword_pass(trace: Trace, expected: Expected) -> bool:
    """Hard gate: False if any forbidden term appears or any required term is missing."""
    text = trace.answer_text or ""
    if must_not_include_violations(text, expected.must_not_include):
        return False
    low = text.lower()
    return all(t.lower() in low for t in expected.must_include)
