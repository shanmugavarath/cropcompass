"""Verdict correctness: did the verifier reach the labelled verdict?"""

from __future__ import annotations

from ..schema import Expected, Trace

NONE = "NONE"


def verdict_match(trace: Trace, expected: Expected) -> float | None:
    """1.0/0.0 vs the acceptable verdict set; None when the case has no verdict
    label (e.g. clarify/reject cases) so it's excluded from verdict accuracy.
    `acceptable_verdicts` (if set) widens the match to tolerate verifier variance."""
    accept = expected.acceptable_verdicts or ([expected.verdict] if expected.verdict else [])
    if not accept:
        return None
    return 1.0 if trace.final_verdict in accept else 0.0


def update_confusion(
    confusion: dict[str, dict[str, int]], trace: Trace, expected: Expected
) -> None:
    """Increment a {expected: {predicted: count}} matrix. Unlabelled expected and
    no-verdict predictions both bucket under 'NONE'."""
    e = expected.verdict or (expected.acceptable_verdicts[0] if expected.acceptable_verdicts else NONE)
    p = trace.final_verdict or NONE
    confusion.setdefault(e, {})
    confusion[e][p] = confusion[e].get(p, 0) + 1
