from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Verdict = Literal["PASS", "PARTIAL", "REJECT"]


class ChatRequest(BaseModel):
    farmer_id: str | None = None
    message: str = Field(min_length=1, max_length=500)
    session_id: str | None = None


class AgentResponse(BaseModel):
    text: str
    lang: str
    verdict: Verdict
    citations: dict[str, str] = Field(default_factory=dict)
    session_id: str


class StreamEvent(BaseModel):
    """Single frame emitted over WS or SSE."""

    type: Literal[
        "phase", "tool_call", "tool_result", "token",
        "verdict", "final", "question", "error",
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str

    @classmethod
    def make(cls, kind: str, session_id: str, **data: Any) -> "StreamEvent":
        return cls(type=kind, session_id=session_id, data=data)


def new_session_id() -> str:
    return uuid4().hex
