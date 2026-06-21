from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import structlog

from ..budget import CONTEXT_BUDGET, truncate_to_budget
from ..config import get_settings
from ..llm import get_default_llm
from ..llm.base import LLMClient
from ..prompts import PLANNER_SYSTEM
from ..schemas import AgentResponse, StreamEvent, new_session_id
from ..session import InMemorySessionStore, Turn, format_history_for_context
from ..tools.base import ToolRegistry
from ..tools.builtin import build_builtin_registry
from .verifier import apply_verdict, verify_recommendation

log = structlog.get_logger(__name__)

TOOL_GET_PROFILE    = "get_farmer_profile"
TOOL_FETCH_ADVISORY = "fetch_latest_advisory"
TOOL_QUERY_KB       = "query_knowledge_base"
TOOL_TRANSLATE      = "translate_output"

CLARIFY_PREFIX = "CLARIFY:"

# Used when no farmer_id is supplied — skips the DB profile lookup entirely.
_ANON_PROFILE: dict[str, Any] = {
    "farmer_id": "anonymous",
    "name": "Anonymous",
    "district": "",
    "crop_variety": "",
    "lang_pref": "eng_Latn",
}


class AgentRunner:
    """Orchestrates the four-phase agent flow and streams events.

    Phases:
      A. Gather   - profile + advisory + KB tools
      B. Generate - planner LLM with tool-use loop; emits tokens
                    If planner replies "CLARIFY: <question>" → emits 'question'
                    event and stops. Next user message continues the conversation.
      C. Verify   - grounding check; PASS / PARTIAL / REJECT
      D. Translate- to farmer's lang_pref
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        llm: LLMClient | None = None,
        session_store: Any | None = None,
    ) -> None:
        self._registry = registry or build_builtin_registry()
        self._llm = llm or get_default_llm()
        self._settings = get_settings()
        self._sessions = session_store or InMemorySessionStore()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream(
        self, farmer_id: str | None, user_message: str, session_id: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        sid = session_id or new_session_id()
        try:
            async for event in self._run(farmer_id, user_message, sid):
                yield event
        except Exception as exc:
            log.exception("agent.run.failed", session_id=sid)
            yield StreamEvent.make("error", sid, message=f"{type(exc).__name__}: {exc}")

    async def run(
        self, farmer_id: str | None, user_message: str, session_id: str | None = None
    ) -> AgentResponse:
        final: AgentResponse | None = None
        last_error: str | None = None
        async for event in self.stream(farmer_id, user_message, session_id):
            if event.type == "final":
                final = AgentResponse(**event.data)
            elif event.type == "error":
                last_error = event.data.get("message", "unknown error")
            elif event.type == "question":
                # Planner needs clarification — return the question as the response text.
                final = AgentResponse(
                    text=event.data.get("text", "Could you provide more details?"),
                    lang="eng_Latn",
                    verdict="PARTIAL",
                    citations={},
                    session_id=event.session_id,
                )
        if final is None:
            raise RuntimeError(last_error or "agent produced no final response")
        return final

    # ------------------------------------------------------------------
    # Core flow
    # ------------------------------------------------------------------

    async def _run(
        self, farmer_id: str | None, user_message: str, sid: str
    ) -> AsyncIterator[StreamEvent]:
        # Load conversation history BEFORE anything else
        history: list[Turn] = await self._load_history(sid)

        # Persist this user turn immediately
        await self._save_turn(sid, "user", user_message, farmer_id)

        # Phase A – Gather
        yield StreamEvent.make("phase", sid, phase="gather")

        if farmer_id:
            profile = await self._call_tool(TOOL_GET_PROFILE, {"farmer_id": farmer_id}, sid)
            async for ev in self._yield_tool_events(TOOL_GET_PROFILE, profile, sid):
                yield ev
            if "error" in profile:
                yield StreamEvent.make("error", sid, message=f"profile lookup failed: {profile['error']}")
                return
        else:
            # No farmer_id — use anonymous profile; user can mention crop/district in their message.
            profile = _ANON_PROFILE.copy()

        district   = profile.get("district", "")
        crop       = profile.get("crop_variety", "")
        lang_pref  = profile.get("lang_pref", "eng_Latn")

        forecast = await self._call_tool(TOOL_FETCH_ADVISORY, {"district": district}, sid)
        async for ev in self._yield_tool_events(TOOL_FETCH_ADVISORY, forecast, sid):
            yield ev

        kb = await self._call_tool(TOOL_QUERY_KB, {"query": user_message, "crop": crop, "top_k": 5}, sid)
        async for ev in self._yield_tool_events(TOOL_QUERY_KB, kb, sid):
            yield ev
        chunks = kb.get("chunks", []) if isinstance(kb, dict) else []

        # Phase B ─ Generate
        yield StreamEvent.make("phase", sid, phase="generate")
        context = self._assemble_context(profile, forecast, chunks, user_message, history)
        draft = ""
        async for ev in self._generate(context, sid):
            if ev.type == "token":
                draft += ev.data.get("delta", "")
            elif ev.type == "question":
                # Planner asked a clarifying question — save it and stop.
                q_text = ev.data.get("text", "")
                await self._save_turn(sid, "assistant", q_text, farmer_id)
                yield ev
                return
            yield ev

        # Phase C ─ Verify
        yield StreamEvent.make("phase", sid, phase="verify")
        # Strip any XML context blocks Qwen echoes back before verifying.
        clean_draft = re.sub(r"<(?:farmer_profile|forecast|knowledge|question|conversation_history)>.*?</(?:farmer_profile|forecast|knowledge|question|conversation_history)>", "", draft, flags=re.DOTALL).strip()
        verdict_payload = await verify_recommendation(self._llm, clean_draft, chunks, forecast)
        final_text, verdict, citations = apply_verdict(clean_draft, verdict_payload)
        yield StreamEvent.make("verdict", sid, verdict=verdict, citations=citations)

        # Phase D ─ Translate
        yield StreamEvent.make("phase", sid, phase="translate")
        translated = await self._call_tool(
            TOOL_TRANSLATE, {"text": final_text, "lang": lang_pref}, sid
        )
        async for ev in self._yield_tool_events(TOOL_TRANSLATE, translated, sid):
            yield ev
        out_text = translated.get("translated", final_text) if isinstance(translated, dict) else final_text

        response = AgentResponse(
            text=out_text,
            lang=lang_pref,
            verdict=verdict,
            citations=citations,
            session_id=sid,
        )
        # Persist the assistant's final answer
        await self._save_turn(sid, "assistant", out_text, farmer_id)
        yield StreamEvent(type="final", session_id=sid, data=response.model_dump())

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _assemble_context(
        self,
        profile: dict[str, Any],
        forecast: dict[str, Any],
        chunks: list[dict[str, Any]],
        user_query: str,
        history: list[Turn],
    ) -> dict[str, str]:
        profile_txt  = json.dumps(profile,  ensure_ascii=False, default=str)
        forecast_txt = json.dumps(forecast, ensure_ascii=False, default=str)
        chunks_txt   = "\n\n".join(
            f"[{c.get('chunk_id', '?')}] {c.get('text', '')}" for c in chunks
        )
        history_txt  = format_history_for_context(history, CONTEXT_BUDGET["conversation_history"])
        return {
            "system_prompt":        truncate_to_budget(PLANNER_SYSTEM,  CONTEXT_BUDGET["system_prompt"]),
            "farmer_profile":       truncate_to_budget(profile_txt,     CONTEXT_BUDGET["farmer_profile"]),
            "imd_forecast":         truncate_to_budget(forecast_txt,    CONTEXT_BUDGET["imd_forecast"]),
            "icar_chunks":          truncate_to_budget(chunks_txt,      CONTEXT_BUDGET["icar_chunks"]),
            "user_query":           truncate_to_budget(user_query,      CONTEXT_BUDGET["user_query"]),
            "conversation_history": history_txt,
        }

    # ------------------------------------------------------------------
    # LLM generation loop (streams token events; may yield a question event)
    # ------------------------------------------------------------------

    async def _generate(self, context: dict[str, str], sid: str) -> AsyncIterator[StreamEvent]:
        history_block = context.get("conversation_history", "")
        history_section = (
            f"<conversation_history>\n{history_block}\n</conversation_history>\n\n"
            if history_block.strip() else ""
        )
        user_content = (
            f"<farmer_profile>\n{context['farmer_profile']}\n</farmer_profile>\n\n"
            f"<forecast>\n{context['imd_forecast']}\n</forecast>\n\n"
            f"<knowledge>\n{context['icar_chunks']}\n</knowledge>\n\n"
            f"{history_section}"
            f"<question>\n{context['user_query']}\n</question>"
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        planner_tools = [t for t in self._registry.anthropic_spec() if t["name"] != TOOL_TRANSLATE]

        for _ in range(self._settings.max_planner_iterations):
            tool_uses: list[dict[str, Any]] = []
            assistant_blocks: list[dict[str, Any]] = []
            text_accum = ""

            async for ev in self._llm.stream(
                system=context["system_prompt"],
                messages=messages,
                tools=planner_tools,
                max_tokens=1024,
            ):
                kind = ev.get("kind")
                if kind == "text_delta":
                    delta = ev.get("text", "")
                    text_accum += delta
                    yield StreamEvent.make("token", sid, delta=delta)
                elif kind == "tool_use":
                    tool_uses.append(ev["tool"])
                elif kind == "message_end":
                    assistant_blocks = ev.get("content", []) or []

            # Detect CLARIFY: before processing tool calls.
            # Strip echoed XML context tags that some models prepend to their output,
            # then look for CLARIFY: anywhere in the remaining text.
            stripped = re.sub(r"<[^>]+>.*?</[^>]+>", "", text_accum, flags=re.DOTALL).strip()
            clarify_idx = stripped.upper().find(CLARIFY_PREFIX)
            if clarify_idx != -1:
                question_text = stripped[clarify_idx + len(CLARIFY_PREFIX):].strip()
                yield StreamEvent.make("question", sid, text=question_text)
                return

            if assistant_blocks:
                messages.append({"role": "assistant", "content": assistant_blocks})
            elif text_accum or tool_uses:
                rebuilt: list[dict[str, Any]] = []
                if text_accum:
                    rebuilt.append({"type": "text", "text": text_accum})
                for t in tool_uses:
                    rebuilt.append(
                        {"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["input"]}
                    )
                messages.append({"role": "assistant", "content": rebuilt})

            if not tool_uses:
                return

            tool_results: list[dict[str, Any]] = []
            for use in tool_uses:
                result = await self._call_tool(use["name"], use["input"], sid)
                async for ev in self._yield_tool_events(use["name"], result, sid):
                    yield ev
                tool_results.append(
                    {
                        "type":        "tool_result",
                        "tool_use_id": use["id"],
                        "content":     json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        yield StreamEvent.make("error", sid, message="planner exceeded max iterations without final answer")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _call_tool(self, name: str, inputs: dict[str, Any], sid: str) -> dict[str, Any]:
        tool = self._registry.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        log.info("tool.call", name=name, session_id=sid)
        return await tool(**inputs)

    async def _yield_tool_events(
        self, name: str, result: dict[str, Any], sid: str
    ) -> AsyncIterator[StreamEvent]:
        ok = isinstance(result, dict) and "error" not in result
        yield StreamEvent.make("tool_call", sid, name=name)
        yield StreamEvent.make("tool_result", sid, name=name, ok=ok, preview=_preview(result))

    async def _load_history(self, sid: str) -> list[Turn]:
        store = self._sessions
        if hasattr(store, "load"):
            result = store.load(sid)
            if hasattr(result, "__await__"):
                return await result
            return result
        return []

    async def _save_turn(self, sid: str, role: str, content: str, farmer_id: str | None = None) -> None:
        store = self._sessions
        if not hasattr(store, "append"):
            return
        try:
            result = store.append(sid, role, content)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            log.warning("session.save_failed", error=str(exc))


def _preview(result: Any, limit: int = 240) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "..."
