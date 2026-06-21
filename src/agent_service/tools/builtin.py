"""In-process tools that ship with the agent (not behind MCP).

Right now: just the translation tool, which calls IndicTrans2 either via the
local TranslationService singleton (preferred, loaded at startup) or via the
HuggingFace Inference API as a fallback.  DB and Vector tools live behind MCP
servers — register those via MCPClient at startup.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

import httpx

from .base import ToolRegistry, ToolSpec

if TYPE_CHECKING:
    from api.services.translation import TranslationService

# Module-level singletons set by main.py _startup() via set_translation_services().
# Using None here avoids importing torch/transformers at module import time.
_svc_en_to_indic: "TranslationService | None" = None
_svc_indic_to_en: "TranslationService | None" = None


def set_translation_services(en_to_indic: Any, indic_to_en: Any) -> None:
    """Called once at agent startup to wire in the loaded TranslationService singletons."""
    global _svc_en_to_indic, _svc_indic_to_en
    _svc_en_to_indic = en_to_indic
    _svc_indic_to_en = indic_to_en


HF_BASE = os.getenv(
    "HF_INFERENCE_ENDPOINT",
    "https://api-inference.huggingface.co/models/ai4bharat/indictrans2-en-indic-1B",
)


async def _translate(text: str, lang: str) -> dict[str, Any]:
    if lang == "eng_Latn" or not text.strip():
        return {"translated": text, "lang": lang}

    # --- Path 1: local TranslationService (loaded at startup) ---
    if _svc_en_to_indic is not None:
        try:
            loop = asyncio.get_running_loop()
            result_dict = await loop.run_in_executor(
                None,
                lambda: _svc_en_to_indic.translate(text, tgt_lang=lang),
            )
            return {"translated": result_dict.get("translated", text), "lang": result_dict.get("lang", lang)}
        except Exception as exc:
            return {"error": f"local translation failed: {exc}", "translated": text, "lang": lang}

    # --- Path 2: HuggingFace Inference API fallback ---
    token = os.getenv("HF_API_KEY", "")
    if not token:
        return {"error": "HF_API_KEY not configured and local TranslationService not loaded", "translated": text, "lang": lang}
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
