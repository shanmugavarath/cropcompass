from __future__ import annotations

import asyncio
import logging
import os

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent.runner import AgentRunner
from .config import get_settings
from .schemas import AgentResponse, ChatRequest
from .session import InMemorySessionStore, PostgresSessionStore
from .tools.builtin import set_translation_services
from .tools.mcp_client import MCPClient, discover_and_register
from .transports.sse import make_router as make_sse_router
from .transports.websocket import make_router as make_ws_router

log = structlog.get_logger(__name__)


class EvaluateRequest(BaseModel):
    """Payload for POST /api/evaluate — evaluate one live chat answer."""

    message: str = Field(min_length=1, max_length=500)   # the farmer's question
    answer: str                                          # the agent's answer text
    farmer_id: str | None = None                         # for retrieval-crop parity
    verdict: str | None = None                           # verifier verdict from the chat
    citations: dict[str, str] = Field(default_factory=dict)


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

        # Load IndicTrans2 translation singletons off the event-loop thread.
        # Each model is ~2 GB; loading blocks for 30-60 s on first start.
        # We skip this when SKIP_TRANSLATION=1 (unit tests / lightweight dev mode).
        if os.getenv("SKIP_TRANSLATION", "0") != "1":
            try:
                from api.services.translation import (
                    TranslationService,
                    DEFAULT_INDIC_EN,
                    DEFAULT_EN_INDIC,
                )
                log.info("translation.loading", msg="Loading IndicTrans2 models (this may take ~60s)…")
                loop = asyncio.get_running_loop()
                en_to_indic, indic_to_en = await asyncio.gather(
                    loop.run_in_executor(None, lambda: TranslationService(model_name=DEFAULT_EN_INDIC)),
                    loop.run_in_executor(None, lambda: TranslationService(model_name=DEFAULT_INDIC_EN)),
                )
                set_translation_services(en_to_indic=en_to_indic, indic_to_en=indic_to_en)
                app.state.en_to_indic = en_to_indic
                app.state.indic_to_en = indic_to_en
                log.info("translation.ready", msg="IndicTrans2 models loaded.")
            except Exception as exc:
                log.warning("translation.load_failed", error=str(exc),
                            msg="IndicTrans2 not loaded — translation will fall back to HF API.")

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

    @app.post("/api/evaluate")
    async def evaluate(req: EvaluateRequest) -> dict:
        """Run the eval harness's LLM-as-judge on a live chat answer.

        Genuinely reuses evals/ (Judge + judge_system.md prompt + the same
        retrieval call the runner makes). Relevance and faithfulness are
        meaningful live; correctness/completeness are returned but flagged
        reference_available=false (no golden reference exists for a live query).
        """
        try:
            from evals.judge import Judge
            from evals.schema import EvalCase, Expected, Trace
            from evals.trace import fetch_retrieved_chunks
        except Exception as exc:  # harness not bundled
            return {"error": f"eval harness unavailable: {exc}"}

        # Resolve crop the same way the runner does, so retrieval matches the answer.
        crop = ""
        if req.farmer_id:
            profile_tool = runner.registry.get("get_farmer_profile")
            if profile_tool is not None:
                profile = await profile_tool(farmer_id=req.farmer_id)
                if isinstance(profile, dict) and "error" not in profile:
                    crop = profile.get("crop_variety", "") or ""

        retrieved = await fetch_retrieved_chunks(runner.registry, req.message, crop, top_k=5)
        case = EvalCase(id="live", message=req.message, expected=Expected())
        trace = Trace(
            case_id="live", answer_text=req.answer, retrieved=retrieved, final_verdict=req.verdict
        )
        score = await Judge(llm=runner._llm).score(case, trace)
        return {
            "judge": score.model_dump(),
            "reference_available": False,
            "retrieval": {
                "count": len(retrieved),
                "chunks": [
                    {"chunk_id": c.chunk_id, "similarity": round(c.similarity, 3), "text": c.text[:240]}
                    for c in retrieved
                ],
            },
            "grounding": {"verdict": req.verdict, "citations": req.citations},
        }

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
