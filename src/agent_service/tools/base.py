"""Framework-agnostic tool specification.

A ToolSpec is the canonical, single-source-of-truth definition of a tool.
Adapters in adapters/ convert it to the shape each LLM framework expects:
  - Anthropic tool-use blocks
  - LangChain BaseTool / StructuredTool
  - Google ADK FunctionTool

Tools NEVER raise. They return a dict; errors are {"error": "..."}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

ToolFn = Callable[..., Awaitable[dict[str, Any]]]


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def __call__(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass
class ToolSpec:
    """The portable description of a tool. Hand this to any framework adapter."""

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn
    tags: list[str] = field(default_factory=list)

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        try:
            result = await self.fn(**kwargs)
            if not isinstance(result, dict):
                return {"error": f"tool {self.name} returned non-dict: {type(result).__name__}"}
            return result
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def anthropic_spec(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    async def dispatch(self, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        return await tool(**inputs)
