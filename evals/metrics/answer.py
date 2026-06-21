"""Glue between the LLM judge and aggregation.

Runs the judge `repeats` times (default 1), averages the four dimensions, and
returns the mean JudgeScore plus a flat metrics dict (judge_<dim>_mean, and
judge_<dim>_std when repeats > 1) for the harness to aggregate.
"""

from __future__ import annotations

from statistics import mean, pstdev
from typing import TYPE_CHECKING

from ..schema import EvalCase, JudgeScore, Trace

if TYPE_CHECKING:
    from ..judge import Judge

_DIMS = ("relevance", "correctness", "completeness", "faithfulness")


async def answer_metrics(
    judge: "Judge", case: EvalCase, trace: Trace, repeats: int = 1
) -> tuple[JudgeScore | None, dict[str, float]]:
    repeats = max(1, repeats)
    scores: list[JudgeScore] = [await judge.score(case, trace) for _ in range(repeats)]

    means = {d: mean([getattr(s, d) for s in scores]) for d in _DIMS}
    agg = JudgeScore(
        relevance=round(means["relevance"]),
        correctness=round(means["correctness"]),
        completeness=round(means["completeness"]),
        faithfulness=round(means["faithfulness"]),
        rationale=scores[0].rationale,
    )

    metrics: dict[str, float] = {f"judge_{d}_mean": means[d] for d in _DIMS}
    if repeats > 1:
        for d in _DIMS:
            metrics[f"judge_{d}_std"] = pstdev([getattr(s, d) for s in scores])
    return agg, metrics
