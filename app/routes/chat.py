"""
POST /api/chat — stub for Member 3 (Agent Engineer) to implement.
Accepts a farmer message, returns a placeholder response.
The AgentRunner (WS2) will replace the body of chat_handler.
"""
import uuid
from pydantic import BaseModel
from fastapi import APIRouter

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    farmer_id: uuid.UUID
    message:   str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id:  str
    response:    str
    lang:        str
    verdict:     str | None = None
    citations:   list[str] = []


@router.post("", response_model=ChatResponse)
async def chat_handler(body: ChatRequest):
    # Stub — AgentRunner (WS2) will replace this body
    return ChatResponse(
        session_id=body.session_id or str(uuid.uuid4()),
        response="[stub] Agent not yet connected.",
        lang="eng_Latn",
        verdict=None,
        citations=[],
    )
