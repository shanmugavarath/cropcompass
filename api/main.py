from __future__ import annotations

import logging
import os

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.runner import AgentRunner
from .config import get_settings
from .schemas import AgentResponse, ChatRequest
from .session import InMemorySessionStore, PostgresSessionStore
from .tools.mcp_client import MCPClient, discover_and_register
from .transports.sse import make_router as make_sse_router
from .transports.websocket import make_router as make_ws_router


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )


async def _build_session_store() -> InMemorySessionStore | PostgresSessionStore:
    backend = os.getenv("SESSION_BACKEND", "memory")
    if backend == "postgres":
        import asyncpg

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass",
        ).replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
        store = PostgresSessionStore(pool)
        await store.ensure_schema()
        return store
    return InMemorySessionStore()


def create_app(runner: AgentRunner | None = None) -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(title="Agent Service", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if runner is None:
        session_store = InMemorySessionStore()
        runner = AgentRunner(session_store=session_store)
    app.state.runner = runner
    app.state.mcp_clients: list[MCPClient] = []

    @app.on_event("startup")
    async def _startup() -> None:
        # Upgrade session store to Postgres if configured
        if os.getenv("SESSION_BACKEND") == "postgres":
            store = await _build_session_store()
            runner._sessions = store

        # Discover MCP tools
        urls = settings.mcp_urls
        if urls:
            clients = await discover_and_register(
                runner.registry, urls, timeout=settings.mcp_request_timeout_s
            )
            app.state.mcp_clients = clients

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        for c in app.state.mcp_clients:
            try:
                await c.aclose()
            except Exception:
                pass

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tools")
    async def list_tools() -> dict[str, list[dict]]:
        return {"tools": runner.registry.anthropic_spec()}

    @app.post("/api/chat", response_model=AgentResponse)
    async def chat(req: ChatRequest) -> AgentResponse:
        return await runner.run(req.farmer_id, req.message, req.session_id)

    @app.delete("/api/session/{session_id}")
    async def clear_session(session_id: str) -> dict[str, str]:
        store = runner._sessions
        if hasattr(store, "clear"):
            result = store.clear(session_id)
            if hasattr(result, "__await__"):
                await result
        return {"cleared": session_id}

    app.include_router(make_ws_router(runner))
    app.include_router(make_sse_router(runner))

    return app


app = create_app()


def run() -> None:
    s = get_settings()
    uvicorn.run(
        "agent_service.main:app",
        host=s.service_host,
        port=s.service_port,
        log_level=s.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    run()
