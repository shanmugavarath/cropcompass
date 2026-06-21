"""Shared MCP server helpers - the JSON-RPC 2.0 dispatcher and a small registry.

This is used by every MCP server in agent_service/mcp_servers/*. Keeps the
JSON-RPC envelope handling DRY so server files only describe their tools.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class MCPToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def tool(self, *, name: str, description: str, input_schema: dict[str, Any]) -> Callable[[ToolHandler], ToolHandler]:
        def deco(fn: ToolHandler) -> ToolHandler:
            self._tools[name] = {
                "name": name,
                "description": description,
                "input_schema": input_schema,
                "handler": fn,
            }
            return fn

        return deco

    def descriptors(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in t.items() if k != "handler"} for t in self._tools.values()]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return {"error": f"unknown tool: {name}"}
        try:
            result = await spec["handler"](**(arguments or {}))
            return result if isinstance(result, dict) else {"error": "tool returned non-dict"}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}


def mount_mcp(app: FastAPI, registry: MCPToolRegistry, path: str = "/mcp") -> None:
    """Attach a JSON-RPC 2.0 endpoint to the given FastAPI app."""

    @app.post(path)
    async def _mcp_endpoint(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error(None, -32700, "Parse error")

        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return _error(body.get("id") if isinstance(body, dict) else None, -32600, "Invalid Request")

        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method == "tools/list":
            return _ok(req_id, {"tools": registry.descriptors()})

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not name:
                return _error(req_id, -32602, "missing 'name'")
            result = await registry.call(name, args)
            return _ok(req_id, result)

        if method == "ping":
            return _ok(req_id, {"ok": True})

        return _error(req_id, -32601, f"Method not found: {method}")

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}


def _ok(req_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})
