"""MCP client over HTTP+JSON-RPC 2.0.

Connects to one or more MCP servers, calls `tools/list` for discovery, and
exposes each remote tool as a local Tool (`MCPRemoteTool`) that can be
registered in the `ToolRegistry`. The agent runner cannot tell remote tools
apart from local ones - that's the whole point.

Wire format follows the MCP spec:
  Request:  {"jsonrpc": "2.0", "id": <int>, "method": "tools/list", "params": {}}
  Response: {"jsonrpc": "2.0", "id": <int>, "result": {"tools": [...]}}
            or {"jsonrpc": "2.0", "id": <int>, "error": {"code": ..., "message": ...}}
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx
import structlog

from .base import ToolSpec

log = structlog.get_logger(__name__)


class MCPClient:
    """One client per MCP server. Cheap to instantiate; reuses an httpx client."""

    def __init__(self, base_url: str, timeout: float = 15.0, headers: dict[str, str] | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = headers or {}
        self._id_seq = itertools.count(1)
        self._http = httpx.AsyncClient(timeout=timeout, headers=self._headers)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._call("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._call("tools/call", {"name": name, "arguments": arguments})

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._id_seq), "method": method, "params": params}
        r = await self._http.post(f"{self._base_url}/mcp", json=payload)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            return {"error": f"{body['error'].get('code')}: {body['error'].get('message')}"}
        return body.get("result", {})

    async def remote_tools(self) -> list[ToolSpec]:
        """Discover every tool the server exposes and wrap each as a ToolSpec."""
        discovered = await self.list_tools()
        return [self._wrap(t) for t in discovered]

    def _wrap(self, descriptor: dict[str, Any]) -> ToolSpec:
        name = descriptor["name"]
        description = descriptor.get("description", "")
        input_schema = descriptor.get("input_schema") or descriptor.get("inputSchema") or {"type": "object"}

        async def _invoke(**kwargs: Any) -> dict[str, Any]:
            return await self.call_tool(name, kwargs)

        return ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            fn=_invoke,
            tags=["mcp", f"server:{self._base_url}"],
        )


async def discover_and_register(registry: Any, server_urls: list[str], timeout: float = 15.0) -> list[MCPClient]:
    """Connect to each MCP server, list tools, register every one of them.

    Returns the list of opened clients so the caller can close them on shutdown.
    """
    clients: list[MCPClient] = []
    for url in server_urls:
        client = MCPClient(base_url=url, timeout=timeout)
        try:
            tools = await client.remote_tools()
        except Exception as exc:
            log.warning("mcp.discover.failed", url=url, error=str(exc))
            await client.aclose()
            continue
        for t in tools:
            if t.name in registry.names():
                log.warning("mcp.tool.duplicate", name=t.name, url=url)
                continue
            registry.register(t)
            log.info("mcp.tool.registered", name=t.name, url=url)
        clients.append(client)
    return clients
