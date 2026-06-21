from __future__ import annotations

import json
import re
from typing import Any

from ..llm.base import LLMClient
from ..prompts import PARTIAL_DISCLAIMER, SAFE_FALLBACK_MESSAGE, VERIFIER_SYSTEM
from ..schemas import Verdict


async def verify_recommendation(
    llm: LLMClient,
    recommendation: str,
    source_chunks: list[dict[str, Any]],
    forecast: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Nothing to verify against — knowledge base is empty.
    # Give a PARTIAL pass so the farmer still gets a useful answer
    # rather than the generic KVK fallback.
    if not source_chunks and not forecast:
        return {"verdict": "PARTIAL", "unsupported_claims": [], "supporting_citations": {}}

    chunks_text = "\n\n".join(
        f"[{c.get('chunk_id', 'unknown')}] {c.get('text', '')}" for c in source_chunks
    )
    forecast_text = (
        f"\n\n[forecast] {json.dumps(forecast, ensure_ascii=False)}" if forecast else ""
    )
    raw = await llm.complete_json(
        system=VERIFIER_SYSTEM,
        user=f"Recommendation:\n{recommendation}\n\nSources:\n{chunks_text}{forecast_text}",
        max_tokens=1024,
    )
    return _safe_json(raw)


def _safe_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {"verdict": "REJECT", "unsupported_claims": [], "supporting_citations": {}}


def apply_verdict(
    recommendation: str, verdict_payload: dict[str, Any]
) -> tuple[str, Verdict, dict[str, str]]:
    verdict: Verdict = verdict_payload.get("verdict", "REJECT")
    citations: dict[str, str] = verdict_payload.get("supporting_citations", {}) or {}
    unsupported: list[str] = verdict_payload.get("unsupported_claims", []) or []

    if verdict == "REJECT":
        return SAFE_FALLBACK_MESSAGE, "REJECT", {}
    if verdict == "PARTIAL":
        stripped = strip_unsupported(recommendation, unsupported)
        if not stripped.strip():
            return SAFE_FALLBACK_MESSAGE, "REJECT", {}
        return stripped + PARTIAL_DISCLAIMER, "PARTIAL", citations
    return recommendation, "PASS", citations


def strip_unsupported(text: str, unsupported_claims: list[str]) -> str:
    if not unsupported_claims:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [
        s for s in sentences if not any(_normalise(claim) in _normalise(s) for claim in unsupported_claims)
    ]
    return " ".join(cleaned).strip()


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())
