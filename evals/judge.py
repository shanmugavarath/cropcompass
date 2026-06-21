"""LLM-as-judge over the existing LLMClient (defaults to LM Studio / Anthropic,
whichever the app is configured for).

Reuses agent_service's LLM abstraction and the verifier's tolerant JSON parsing.
Never raises: a parse failure yields an all-zero score so one bad judgement can't
abort a suite.

agent_service.llm is imported lazily so this module stays importable (for offline
metric tests) without the agent runtime installed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .schema import EvalCase, JudgeScore, Trace

if TYPE_CHECKING:
    from agent_service.llm.base import LLMClient

_JUDGE_SYSTEM = (Path(__file__).resolve().parent / "prompts" / "judge_system.md").read_text(
    encoding="utf-8"
).strip()

_MAX_CHUNK_CHARS = 600
_DIMS = ("relevance", "correctness", "completeness", "faithfulness")


class Judge:
    def __init__(self, llm: "LLMClient | None" = None) -> None:
        if llm is None:
            from agent_service.llm import get_default_llm

            llm = get_default_llm()
        self._llm = llm

    async def score(self, case: EvalCase, trace: Trace) -> JudgeScore:
        sources = "\n\n".join(
            f"[{c.chunk_id}] {c.text[:_MAX_CHUNK_CHARS]}" for c in trace.retrieved if c.text
        ) or "(no sources retrieved)"
        user = (
            f"Farmer question:\n{case.message}\n\n"
            f"Reference answer:\n{case.expected.reference_answer or '(none provided)'}\n\n"
            f"Agent answer:\n{trace.answer_text or '(empty)'}\n\n"
            f"Retrieved sources:\n{sources}"
        )
        raw = await self._llm.complete_json(system=_JUDGE_SYSTEM, user=user, max_tokens=1024)
        return _parse_score(raw)


def _safe_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _clamp(value: Any) -> int:
    try:
        return max(0, min(5, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _parse_score(raw: str) -> JudgeScore:
    data = _safe_json(raw)
    if not data:
        return JudgeScore(
            relevance=0, correctness=0, completeness=0, faithfulness=0,
            rationale="judge parse failure",
        )
    return JudgeScore(
        relevance=_clamp(data.get("relevance")),
        correctness=_clamp(data.get("correctness")),
        completeness=_clamp(data.get("completeness")),
        faithfulness=_clamp(data.get("faithfulness")),
        rationale=str(data.get("rationale", ""))[:500],
    )
