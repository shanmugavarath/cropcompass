"""Verdict correctness: did the verifier reach the labelled verdict?"""

from __future__ import annotations

from ..schema import Expected, Trace

NONE = "NONE"


def verdict_match(trace: Trace, expected: Expected) -> float | None:
    """1.0/0.0 vs the labelled verdict; None when the case has no verdict label
    (e.g. clarify cases) so it's excluded from verdict accuracy."""
    if expected.verdict is None:
        return None
    return 1.0 if trace.final_verdict == expected.verdict else 0.0


def update_confusion(
    confusion: dict[str, dict[str, int]], trace: Trace, expected: Expected
) -> None:
    """Increment a {expected: {predicted: count}} matrix. Unlabelled expected and
    no-verdict predictions both bucket under 'NONE'."""
    e = expected.verdict or NONE
    p = trace.final_verdict or NONE
    confusion.setdefault(e, {})
    confusion[e][p] = confusion[e].get(p, 0) + 1
