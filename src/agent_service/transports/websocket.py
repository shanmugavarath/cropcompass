from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..agent.runner import AgentRunner
from ..schemas import ChatRequest

router = APIRouter()


def make_router(runner: AgentRunner) -> APIRouter:
    @router.websocket("/ws/chat")
    async def chat_ws(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    payload = json.loads(raw)
                    req = ChatRequest.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as exc:
                    await ws.send_json(
                        {"type": "error", "data": {"message": f"bad request: {exc}"}}
                    )
                    continue

                async for event in runner.stream(req.farmer_id, req.message, req.session_id):
                    await ws.send_json(event.model_dump())
        except WebSocketDisconnect:
            return

    return router
