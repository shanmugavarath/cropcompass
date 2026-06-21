from __future__ import annotations

from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ..config import get_settings
from .base import LLMClient, LLMStreamEvent


class AnthropicLLM(LLMClient):
    """Production LLM client. Talks to api.anthropic.com directly."""

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        s = get_settings()
        key = api_key or s.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. For local testing without a key, "
                "set LLM_BACKEND=lm_studio and start LM Studio on port 1234."
            )
        self._client = AsyncAnthropic(api_key=key, base_url=base_url or s.anthropic_base_url)
        self._model = model or s.llm_model

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AsyncIterator[LLMStreamEvent]:
        async for ev in _stream_anthropic(self._client, self._model, system, messages, tools, max_tokens):
            yield ev

    async def complete_json(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""


async def _stream_anthropic(
    client: AsyncAnthropic,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
) -> AsyncIterator[LLMStreamEvent]:
    kwargs: dict[str, Any] = {
        "model": model,
        "system": system,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools

    async with client.messages.stream(**kwargs) as stream:
        current_tool: dict[str, Any] | None = None
        async for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if block is not None and getattr(block, "type", None) == "tool_use":
                    current_tool = {"id": block.id, "name": block.name, "input_buf": ""}
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta is None:
                    continue
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    yield LLMStreamEvent(kind="text_delta", text=delta.text)
                elif dtype == "input_json_delta" and current_tool is not None:
                    current_tool["input_buf"] += delta.partial_json
            elif etype == "content_block_stop":
                if current_tool is not None:
                    import json

                    try:
                        inputs = json.loads(current_tool["input_buf"] or "{}")
                    except json.JSONDecodeError:
                        inputs = {}
                    yield LLMStreamEvent(
                        kind="tool_use",
                        tool={"id": current_tool["id"], "name": current_tool["name"], "input": inputs},
                    )
                    current_tool = None
            elif etype == "message_stop":
                final = await stream.get_final_message()
                yield LLMStreamEvent(
                    kind="message_end",
                    stop_reason=final.stop_reason,
                    content=[b.model_dump() for b in final.content],
                )
