"""Smoke test against a running LM Studio instance.

Skipped automatically if LM Studio is not reachable on the configured URL.
No API key needed — that's the whole point.

Run with:
    LM_STUDIO_MODEL=<model-id> pytest tests/test_lm_studio.py -v

LM Studio must be running with:
    - Server enabled (default port 1234)
    - At least one model loaded
    - The loaded model preferably supports tool/function calling
"""

from __future__ import annotations

import os

import httpx
import pytest

LM_STUDIO_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234")
_MODEL_SET = os.getenv("LM_STUDIO_MODEL", "local-model") != "local-model"


def _lm_studio_reachable() -> bool:
    try:
        r = httpx.get(f"{LM_STUDIO_URL}/v1/models", timeout=2.0)
        return r.status_code < 500
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_MODEL_SET and _lm_studio_reachable()),
    reason=(
        "Set LM_STUDIO_MODEL=<your-model-id> and start LM Studio on port 1234 "
        "to run these integration tests."
    ),
)


async def test_lm_studio_streams_text():
    from agent_service.llm.lm_studio_client import LMStudioLLM

    llm = LMStudioLLM()
    chunks: list[str] = []
    saw_end = False
    async for ev in llm.stream(
        system="You are a terse assistant. Reply with exactly two words: Hello World",
        messages=[{"role": "user", "content": "Say hello."}],
        tools=[],
        max_tokens=16,
    ):
        if ev.get("kind") == "text_delta":
            chunks.append(ev["text"])
        elif ev.get("kind") == "message_end":
            saw_end = True
    assert saw_end, "stream never emitted message_end"
    assert "".join(chunks).strip(), "stream produced no text"


async def test_lm_studio_complete_json():
    from agent_service.llm.lm_studio_client import LMStudioLLM

    llm = LMStudioLLM()
    out = await llm.complete_json(
        system='Respond ONLY with valid JSON: {"ok": true}',
        user="go",
        max_tokens=32,
    )
    assert out.strip(), "complete_json returned empty string"
