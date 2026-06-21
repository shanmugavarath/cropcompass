"""Fold a StreamEvent sequence into a structured Trace, and fetch retrieval
ground truth.

Kept free of any target so it's unit-testable with synthetic events (no network).

Why `fetch_retrieved_chunks` exists: the runner truncates `tool_result` previews
to 240 chars (`runner.py:_preview`), so retrieved chunk IDs aren't recoverable
from the event stream. We instead call `query_knowledge_base` directly, replicating
exactly how the runner invokes it (`runner.py` Phase A): query = the user message,
`crop` = the farmer's crop_variety (empty for anonymous), `top_k` = 5, and the
default `collection="icar"`. That makes the retrieval metric reflect what the agent
actually retrieves.
"""

from __future__ import annotations

from typing import Any

from agent_service.budget import count_tokens
from agent_service.schemas import StreamEvent
from agent_service.tools.base import ToolRegistry

from .schema import RetrievedChunk, Trace

TOOL_QUERY_KB = "query_knowledge_base"


class TraceAccumulator:
    """Consumes StreamEvents one at a time and produces a Trace on finish()."""

    def __init__(self, case_id: str) -> None:
        self._trace = Trace(case_id=case_id)
        self._token_parts: list[str] = []

    def consume(self, ev: StreamEvent) -> None:
        kind = ev.type
        data: dict[str, Any] = ev.data or {}

        if kind == "token":
            self._token_parts.append(data.get("delta", ""))
        elif kind == "tool_call":
            name = data.get("name", "")
            if name:
                self._trace.tools_called.append(name)
        elif kind == "question":
            # Planner asked for clarification — the question IS the response, and
            # there is no 'final' event after this.
            self._trace.clarified = True
            self._trace.answer_text = data.get("text", self._trace.answer_text)
        elif kind == "verdict":
            self._trace.final_verdict = data.get("verdict", self._trace.final_verdict)
            self._trace.citations = data.get("citations") or self._trace.citations
        elif kind == "final":
            # The delivered (verified + translated) answer — prefer this over the draft.
            self._trace.answer_text = data.get("text", self._trace.answer_text)
            self._trace.final_verdict = data.get("verdict", self._trace.final_verdict)
            self._trace.citations = data.get("citations") or self._trace.citations
            self._trace.lang = data.get("lang", self._trace.lang)
        elif kind == "error":
            self._trace.error = data.get("message", "unknown error")

    def finish(self, latency_s: float) -> Trace:
        # Fall back to the accumulated draft only if no final/question text arrived.
        if not self._trace.answer_text and self._token_parts:
            self._trace.answer_text = "".join(self._token_parts)
        self._trace.latency_s = latency_s
        self._trace.answer_tokens = count_tokens(self._trace.answer_text)
        return self._trace


async def fetch_retrieved_chunks(
    registry: ToolRegistry, message: str, crop: str | None, top_k: int = 5
) -> list[RetrievedChunk]:
    """Replicate the runner's Phase-A KB call to capture untruncated chunk IDs."""
    tool = registry.get(TOOL_QUERY_KB)
    if tool is None:
        return []
    result = await tool(query=message, crop=crop or "", top_k=top_k)
    if not isinstance(result, dict) or "error" in result:
        return []
    out: list[RetrievedChunk] = []
    for c in result.get("chunks", []):
        cid = c.get("chunk_id")
        if cid is None:
            continue
        out.append(RetrievedChunk(chunk_id=cid, similarity=float(c.get("similarity", 0.0))))
    return out
