"""Tests for the MCP JSON-RPC server library + the MCPClient.

Spins up a tiny in-process MCP server (FastAPI test client) and round-trips
both tools/list and tools/call. No mocks - this is the real wire format.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp
from agent_service.tools.base import ToolRegistry
from agent_service.tools.mcp_client import MCPClient


def _build_app() -> FastAPI:
    reg = MCPToolRegistry()

    @reg.tool(
        name="add",
        description="Add two integers.",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    )
    async def _add(a: int, b: int) -> dict[str, Any]:
        return {"sum": a + b}

    @reg.tool(
        name="boom",
        description="Always errors.",
        input_schema={"type": "object"},
    )
    async def _boom() -> dict[str, Any]:
        raise RuntimeError("test failure")

    app = FastAPI()
    mount_mcp(app, reg)
    return app


def test_tools_list_via_test_client():
    client = TestClient(_build_app())
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    names = [t["name"] for t in body["result"]["tools"]]
    assert names == ["add", "boom"]


def test_tools_call_via_test_client():
    client = TestClient(_build_app())
    r = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 2, "b": 3}},
        },
    )
    body = r.json()
    assert body["result"] == {"sum": 5}


def test_handler_exceptions_become_error_dict():
    client = TestClient(_build_app())
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "boom", "arguments": {}}},
    )
    body = r.json()
    assert "error" in body["result"]
    assert "RuntimeError" in body["result"]["error"]


def test_unknown_method_returns_jsonrpc_error():
    client = TestClient(_build_app())
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "frobnicate", "params": {}})
    body = r.json()
    assert body["error"]["code"] == -32601


async def test_mcp_client_against_real_http_server():
    """End-to-end: real httpx client -> in-process FastAPI MCP server -> back.

    Uses httpx.ASGITransport to talk to the ASGI app without binding a port.
    """
    app = _build_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        client = MCPClient(base_url="http://test")
        client._http = http  # inject ASGI-bound client
        tools = await client.list_tools()
        assert {t["name"] for t in tools} == {"add", "boom"}

        result = await client.call_tool("add", {"a": 10, "b": 7})
        assert result == {"sum": 17}

        # Auto-wrap as ToolSpec and register in our framework-agnostic registry
        reg = ToolRegistry()
        for spec in await client.remote_tools():
            reg.register(spec)
        assert set(reg.names()) == {"add", "boom"}
        out = await reg.dispatch("add", {"a": 1, "b": 1})
        assert out == {"sum": 2}
