"""In-process target: drive AgentRunner directly and capture a Trace per case.

Mirrors the agent's own startup wiring (`agent_service.main`): build the builtin
registry, discover + register MCP tools, then run cases through `runner.stream()`.
Uses an in-memory session store so eval runs never touch the Postgres
`conversation_turns` table and each case is isolated (fresh session_id).

Requires the db-mcp and vector-mcp servers to be reachable via MCP_SERVER_URLS
(e.g. http://localhost:9101,http://localhost:9102 for a local run).
"""

from __future__ import annotations

import time

from agent_service.agent.runner import AgentRunner
from agent_service.config import Settings, get_settings
from agent_service.schemas import StreamEvent
from agent_service.session import InMemorySessionStore
from agent_service.tools.builtin import build_builtin_registry
from agent_service.tools.mcp_client import MCPClient, discover_and_register

from ..schema import EvalCase, Trace
from ..trace import TraceAccumulator, fetch_retrieved_chunks

TOOL_GET_PROFILE = "get_farmer_profile"
TOOL_QUERY_KB = "query_knowledge_base"


class InProcessTarget:
    def __init__(
        self, runner: AgentRunner, clients: list[MCPClient], settings: Settings
    ) -> None:
        self._runner = runner
        self._clients = clients
        self._settings = settings

    @classmethod
    async def create(cls, settings: Settings | None = None) -> "InProcessTarget":
        settings = settings or get_settings()
        registry = build_builtin_registry()
        clients = await discover_and_register(
            registry, settings.mcp_urls, timeout=settings.mcp_request_timeout_s
        )
        # The KB tool is essential for retrieval metrics; its absence means MCP
        # discovery failed (servers down or MCP_SERVER_URLS unset/wrong).
        if registry.get(TOOL_QUERY_KB) is None:
            for c in clients:
                await c.aclose()
            raise RuntimeError(
                "MCP tools not discovered. Bring the stack up and set MCP_SERVER_URLS "
                "(e.g. http://localhost:9101,http://localhost:9102). "
                f"Configured: {settings.mcp_urls or '[]'}"
            )
        runner = AgentRunner(registry=registry, session_store=InMemorySessionStore())
        return cls(runner, clients, settings)

    async def run(self, case: EvalCase) -> Trace:
        acc = TraceAccumulator(case.id)
        t0 = time.monotonic()
        # runner.stream() catches its own exceptions and emits an 'error' event,
        # but guard anyway so one bad case never aborts the suite.
        try:
            async for ev in self._runner.stream(case.farmer_id, case.message, None):
                acc.consume(ev)
        except Exception as exc:  # pragma: no cover - defensive
            acc.consume(
                StreamEvent.make("error", case.id, message=f"{type(exc).__name__}: {exc}")
            )
        trace = acc.finish(time.monotonic() - t0)

        # Retrieval ground truth: replicate the runner's KB call with the right crop.
        crop = await self._resolve_crop(case)
        trace.retrieved = await fetch_retrieved_chunks(self._runner.registry, case.message, crop)
        return trace

    async def _resolve_crop(self, case: EvalCase) -> str:
        """The runner passes crop=profile.crop_variety to the KB (empty for anon)."""
        if not case.farmer_id:
            return ""
        tool = self._runner.registry.get(TOOL_GET_PROFILE)
        if tool is None:
            return ""
        profile = await tool(farmer_id=case.farmer_id)
        if not isinstance(profile, dict) or "error" in profile:
            return ""
        return profile.get("crop_variety", "") or ""

    async def aclose(self) -> None:
        for c in self._clients:
            try:
                await c.aclose()
            except Exception:  # pragma: no cover - best effort
                pass
