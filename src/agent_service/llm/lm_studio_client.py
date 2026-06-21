"""LM Studio LLM client — for local testing without any API key.

LM Studio exposes an OpenAI-compatible REST API at http://localhost:1234/v1
by default. Any model loaded in LM Studio that supports tool/function calling
(e.g. Llama-3.1, Qwen-2.5, Mistral-Nemo) works here.

This client converts bidirectionally between Anthropic's message/tool format
(used throughout the runner) and OpenAI's format (used by LM Studio), so the
rest of the codebase needs zero changes.

Usage:
    LLM_BACKEND=lm_studio
    LM_STUDIO_BASE_URL=http://localhost:1234   # default
    LM_STUDIO_MODEL=<model-identifier>         # copy from LM Studio UI
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import httpx

from ..config import get_settings
from .base import LLMClient, LLMStreamEvent

# Matches <think>...</think> blocks that Qwen3 and other reasoning models
# emit before their actual answer. We strip these so downstream code never
# sees them.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LMStudioLLM(LLMClient):
    """OpenAI-compatible client that talks to a local LM Studio instance."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        s = get_settings()
        self._base_url = (base_url or s.lm_studio_base_url).rstrip("/")
        self._model = model or s.lm_studio_model
        print(f"[ANALYZE] Using LM Studio backend  url={self._base_url}  model={self._model}")

    # ------------------------------------------------------------------
    # LLMClient protocol
    # ------------------------------------------------------------------

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AsyncIterator[LLMStreamEvent]:
        oai_messages = _to_openai_messages(system, messages)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = _to_openai_tools(tools)
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for ev in _parse_openai_stream(resp):
                    yield ev

    async def complete_json(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        """Non-streaming JSON completion.

        Tries with response_format=json_object first (forces valid JSON output).
        Falls back to plain completion if the server rejects that parameter,
        so this works across all LM Studio versions and model types.
        """
        base_payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Attempt 1: with JSON mode enforced
            try:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json={**base_payload, "response_format": {"type": "json_object"}},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                # Server rejected response_format (e.g. older LM Studio or unsupported model)
                # Attempt 2: plain request, rely on prompt + _strip_thinking
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=base_payload,
                )
                resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"].get("content", "")
        return _strip_thinking(raw)


# ------------------------------------------------------------------
# OpenAI streaming parser
# ------------------------------------------------------------------

async def _parse_openai_stream(
    resp: httpx.Response,
) -> AsyncIterator[LLMStreamEvent]:
    """Parse an OpenAI SSE stream and emit LLMStreamEvents.

    Thinking blocks (<think>...</think>) emitted by reasoning models like
    Qwen3 are silently dropped — they never reach the runner or the verifier.
    """
    tool_buffers: dict[int, dict[str, Any]] = {}
    text_buffer = ""
    content_blocks: list[dict[str, Any]] = []

    # State machine for stripping <think>...</think> mid-stream.
    # We buffer partial text so tags split across chunks are handled correctly.
    in_think = False
    tag_buf = ""          # holds a partial tag being assembled

    async for raw_line in resp.aiter_lines():
        line = raw_line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break

        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue

        choices = chunk.get("choices")
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta", {})

        # ── text token (with think-block filtering) ──────────────────
        text_piece = delta.get("content") or ""
        if text_piece:
            # Append to tag_buf so we can detect split tags
            tag_buf += text_piece
            emit = ""

            while tag_buf:
                if in_think:
                    end = tag_buf.lower().find("</think>")
                    if end == -1:
                        # Still inside think block, no close tag yet
                        # Keep 8 chars buffered in case </think> is split
                        if len(tag_buf) > 8:
                            tag_buf = tag_buf[-8:]
                        break
                    else:
                        tag_buf = tag_buf[end + len("</think>"):]
                        in_think = False
                else:
                    start = tag_buf.lower().find("<think>")
                    if start == -1:
                        emit += tag_buf
                        tag_buf = ""
                    else:
                        emit += tag_buf[:start]
                        tag_buf = tag_buf[start + len("<think>"):]
                        in_think = True

            if emit:
                text_buffer += emit
                yield LLMStreamEvent(kind="text_delta", text=emit)

        # ── tool call accumulation ──────────────────────────────────
        for tc in delta.get("tool_calls") or []:
            idx: int = tc["index"]
            if idx not in tool_buffers:
                fn = tc.get("function") or {}
                tool_buffers[idx] = {
                    "id": tc.get("id") or f"call_{idx}",
                    "name": fn.get("name") or f"tool_{idx}",
                    "args_buf": "",
                }
            args_chunk = (tc.get("function") or {}).get("arguments") or ""
            tool_buffers[idx]["args_buf"] += args_chunk

        # -- finish -------------------------------------------------------
        finish = choice.get("finish_reason")
        # Accept any non-null finish_reason; "stop" and "tool_calls" are standard
        # but some models/versions emit others (e.g. "eos", "end").
        if not finish:
            continue

        if text_buffer:
            content_blocks.append({"type": "text", "text": text_buffer})

        for idx, tb in sorted(tool_buffers.items()):
            try:
                inputs = json.loads(tb["args_buf"] or "{}")
            except json.JSONDecodeError:
                inputs = {}
            yield LLMStreamEvent(
                kind="tool_use",
                tool={"id": tb["id"], "name": tb["name"], "input": inputs},
            )
            content_blocks.append(
                {"type": "tool_use", "id": tb["id"], "name": tb["name"], "input": inputs}
            )

        yield LLMStreamEvent(
            kind="message_end",
            stop_reason=finish,
            content=content_blocks,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from a model response.

    Reasoning models (Qwen3, DeepSeek-R1, etc.) emit a thinking block before
    the actual answer. For complete_json calls this would break JSON parsing.
    """
    return _THINK_RE.sub("", text).strip()


# ------------------------------------------------------------------
# Format converters: Anthropic ↔ OpenAI
# ------------------------------------------------------------------

def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool spec → OpenAI function definition."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_openai_messages(
    system: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages (as used by the runner) to OpenAI format.

    Handles:
    - Plain string user messages
    - Anthropic tool_result user blocks  → OpenAI 'tool' role messages
    - Anthropic assistant content blocks → OpenAI 'assistant' message + tool_calls
    """
    oai: list[dict[str, Any]] = []
    if system:
        oai.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            oai.extend(_convert_user(content))
        elif role == "assistant":
            oai.append(_convert_assistant(content))

    return oai


def _convert_user(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"role": "user", "content": content}]

    if not isinstance(content, list):
        return [{"role": "user", "content": str(content)}]

    # Anthropic tool_result blocks → OpenAI 'tool' role messages
    tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
    if tool_results:
        return [
            {
                "role": "tool",
                "tool_call_id": tr["tool_use_id"],
                "content": tr.get("content", ""),
            }
            for tr in tool_results
        ]

    # Other list content (e.g. text blocks) — join as plain text
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return [{"role": "user", "content": " ".join(parts)}]


def _convert_assistant(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "assistant", "content": content}

    if not isinstance(content, list):
        return {"role": "assistant", "content": str(content)}

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
            )

    msg: dict[str, Any] = {"role": "assistant", "content": " ".join(text_parts) or None}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg
