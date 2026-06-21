"""In-process tools that ship with the agent (not behind MCP).

Right now: just the translation tool, which calls IndicTrans2 via the HF
Inference API. DB and Vector tools live behind MCP servers - register those
via MCPClient at startup.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .base import ToolRegistry, ToolSpec

HF_BASE = os.getenv(
    "HF_INFERENCE_ENDPOINT",
    "https://api-inference.huggingface.co/models/ai4bharat/indictrans2-en-indic-1B",
)


async def _translate(text: str, lang: str) -> dict[str, Any]:
    if lang == "eng_Latn" or not text.strip():
        return {"translated": text, "lang": lang}
    token = os.getenv("HF_API_KEY", "")
    if not token:
        return {"error": "HF_API_KEY not configured", "translated": text, "lang": lang}
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"inputs": text, "parameters": {"src_lang": "eng_Latn", "tgt_lang": lang}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(HF_BASE, headers=headers, json=payload)
        if r.status_code >= 400:
            return {"error": f"HF status {r.status_code}: {r.text[:200]}"}
        data = r.json()
    translated = data[0]["translation_text"] if isinstance(data, list) and data else text
    return {"translated": translated, "lang": lang}


TRANSLATE_OUTPUT = ToolSpec(
    name="translate_output",
    description="Translate English advisory text into the farmer's preferred Indic language using IndicTrans2.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "lang": {"type": "string", "description": "FLORES-200 code, e.g. hin_Deva."},
        },
        "required": ["text", "lang"],
    },
    fn=_translate,
    tags=["builtin", "translation"],
)


def build_builtin_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(TRANSLATE_OUTPUT)
    return reg
