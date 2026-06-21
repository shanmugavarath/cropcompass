from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..agent.runner import AgentRunner
from ..schemas import ChatRequest

router = APIRouter()


def make_router(runner: AgentRunner) -> APIRouter:
    @router.post("/sse/chat")
    async def chat_sse(req: ChatRequest) -> EventSourceResponse:
        async def gen() -> AsyncIterator[dict]:
            try:
                async for event in runner.stream(req.farmer_id, req.message, req.session_id):
                    yield {
                        "event": event.type,
                        "data": json.dumps(event.model_dump(), ensure_ascii=False),
                    }
            except Exception as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": f"{type(exc).__name__}: {exc}"}),
                }

        return EventSourceResponse(gen())

    @router.get("/sse/chat")
    async def chat_sse_get(farmer_id: str, message: str, session_id: str | None = None) -> EventSourceResponse:
        try:
            req = ChatRequest(farmer_id=farmer_id, message=message, session_id=session_id)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return await chat_sse(req)

    return router
