"""
POST /api/chat — HTTP proxy to the agent service.
Forwards requests to AGENT_SERVICE_URL/api/chat and returns the response.
WebSocket and SSE endpoints are served directly by the agent at port 8001
(/ws/chat and /sse/chat); clients should connect to those directly.
"""
import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/chat", tags=["chat"])

_AGENT_URL = os.getenv("AGENT_SERVICE_URL", "http://agent:8001")


class ChatRequest(BaseModel):
    farmer_id:  uuid.UUID
    message:    str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response:   str
    lang:       str
    verdict:    str | None = None
    citations:  list[str] = []


@router.post("", response_model=ChatResponse)
async def chat_handler(body: ChatRequest):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_AGENT_URL}/api/chat",
            json=body.model_dump(mode="json"),
            timeout=60.0,
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    data = r.json()
    return ChatResponse(
        session_id=data["session_id"],
        response=data["text"],
        lang=data.get("lang", "eng_Latn"),
        verdict=data.get("verdict"),
        citations=list(data.get("citations", {}).keys()),
    )
