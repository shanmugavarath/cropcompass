from __future__ import annotations

from typing import Any, AsyncIterator, Protocol


class LLMStreamEvent(dict):
    """Lightweight event shape produced by an LLMClient stream.

    Keys used by the runner:
      - kind: 'text_delta' | 'tool_use' | 'message_end'
      - text: str (when kind == 'text_delta')
      - tool: {'id', 'name', 'input'} (when kind == 'tool_use')
      - stop_reason: str | None (when kind == 'message_end')
    """


class LLMClient(Protocol):
    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AsyncIterator[LLMStreamEvent]: ...

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
    ) -> str: ...
