"""Orchestrate a suite: load dataset -> run each case -> compute metrics -> RunReport."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .metrics import (
    behavior_metrics,
    clarification_match,
    keyword_pass,
    must_include_score,
    retrieval_metrics,
    update_confusion,
    verdict_match,
)
from .schema import CaseResult, EvalCase, RunReport
from .targets import EvalTarget


def load_dataset(path: str | Path) -> list[EvalCase]:
    p = Path(path)
    cases: list[EvalCase] = []
    with p.open(encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(EvalCase.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - re-raise with location
                raise ValueError(f"{p}:{n}: {exc}") from exc
    return cases


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[i]


async def run_suite(
    cases: list[EvalCase],
    target: EvalTarget,
    judge=None,
    tags: list[str] | None = None,
    k: int = 5,
    repeats: int = 1,
    dataset: str = "golden",
) -> RunReport:
    if tags:
        wanted = set(tags)
        cases = [c for c in cases if wanted & set(c.tags)]

    started = _now()
    results: list[CaseResult] = []
    confusion: dict[str, dict[str, int]] = {}

    for case in cases:
        trace = await target.run(case)
        metrics: dict[str, float] = {}
        metrics.update(retrieval_metrics(trace, case.expected, k))
        metrics.update(behavior_metrics(trace, case.expected))

        vm = verdict_match(trace, case.expected)
        if vm is not None:
            metrics["verdict_match"] = vm
        metrics["must_include_score"] = must_include_score(
            trace.answer_text, case.expected.must_include
        )
        update_confusion(confusion, trace, case.expected)

        kp = keyword_pass(trace, case.expected)
        metrics["keyword_pass"] = 1.0 if kp else 0.0
        passed = kp and clarification_match(trace, case.expected) == 1.0

        judge_score = None
        if judge is not None and case.expected.reference_answer:
            from .metrics.answer import answer_metrics  # Phase 4

            judge_score, jm = await answer_metrics(judge, case, trace, repeats=repeats)
            metrics.update(jm)

        results.append(
            CaseResult(case=case, trace=trace, metrics=metrics, judge=judge_score, passed=passed)
        )

    report = RunReport(
        dataset=dataset,
        n_cases=len(results),
        aggregates=_aggregate(results),
        confusion=confusion,
        per_case=results,
        started_at=started,
        finished_at=_now(),
    )
    return report


def _aggregate(results: list[CaseResult]) -> dict[str, float]:
    agg: dict[str, float] = {}
    keys: set[str] = set()
    for r in results:
        keys |= set(r.metrics)

    for key in keys:
        vals = [r.metrics[key] for r in results if key in r.metrics]
        if not vals:
            continue
        if key == "latency_s":
            agg["latency_mean_s"] = _mean(vals)
            agg["latency_p50_s"] = _pct(vals, 0.5)
            agg["latency_p95_s"] = _pct(vals, 0.95)
        elif key == "answer_tokens":
            agg["answer_tokens_mean"] = _mean(vals)
        elif key == "verdict_match":
            agg["verdict_accuracy"] = _mean(vals)
        elif key == "keyword_pass":
            agg["keyword_pass_rate"] = _mean(vals)
        else:
            agg[key] = _mean(vals)

    agg["pass_rate"] = _mean([1.0 if r.passed else 0.0 for r in results])
    agg["n_cases"] = float(len(results))
    return agg
