"""Clarification, tool-call, and performance metrics."""

from __future__ import annotations

from ..schema import Expected, Trace


def clarification_match(trace: Trace, expected: Expected) -> float:
    """1.0 when the agent clarified iff the case expected a clarification."""
    return 1.0 if trace.clarified == expected.expect_clarification else 0.0


def tool_call_jaccard(trace: Trace, expected: Expected) -> float | None:
    """Jaccard overlap of called vs expected tools; None when no tools are labelled."""
    if not expected.expected_tools:
        return None
    called = set(trace.tools_called)
    want = set(expected.expected_tools)
    if not called and not want:
        return 1.0
    return len(called & want) / len(called | want)


def behavior_metrics(trace: Trace, expected: Expected) -> dict[str, float]:
    m: dict[str, float] = {
        "clarification_match": clarification_match(trace, expected),
        "latency_s": trace.latency_s,
        "answer_tokens": float(trace.answer_tokens),
    }
    j = tool_call_jaccard(trace, expected)
    if j is not None:
        m["tool_call_jaccard"] = j
    return m
