"""Session store — keeps conversation history per session_id.

Default: in-memory (lost on restart). Swap to Postgres by setting
SESSION_BACKEND=postgres in env — the same cropcompass DB, no extra service.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    role: str                       # "user" | "assistant"
    content: str
    ts: float = field(default_factory=time.time)


class InMemorySessionStore:
    """Simple dict-backed store. Fine for single-process deployments."""

    def __init__(self, max_turns: int = 20) -> None:
        self._store: dict[str, list[Turn]] = defaultdict(list)
        self._max_turns = max_turns

    def load(self, session_id: str) -> list[Turn]:
        return list(self._store[session_id])

    def append(self, session_id: str, role: str, content: str) -> None:
        turns = self._store[session_id]
        turns.append(Turn(role=role, content=content))
        # Keep only last N turns to bound memory
        if len(turns) > self._max_turns:
            self._store[session_id] = turns[-self._max_turns:]

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)


class PostgresSessionStore:
    """Persists turns in the cropcompass DB. Survives restarts."""

    DDL = """
    CREATE TABLE IF NOT EXISTS conversation_turns (
        id          BIGSERIAL       PRIMARY KEY,
        session_id  VARCHAR(64)     NOT NULL,
        farmer_id   VARCHAR(64),
        role        VARCHAR(10)     NOT NULL,
        content     TEXT            NOT NULL,
        created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns (session_id, id);
    """

    def __init__(self, pool: Any, max_turns: int = 20) -> None:
        self._pool = pool
        self._max_turns = max_turns

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(self.DDL)

    async def load(self, session_id: str) -> list[Turn]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, EXTRACT(EPOCH FROM created_at) AS ts
                  FROM conversation_turns
                 WHERE session_id = $1
                 ORDER BY id DESC
                 LIMIT $2
                """,
                session_id,
                self._max_turns,
            )
        # rows are newest-first; reverse for chronological order
        return [Turn(role=r["role"], content=r["content"], ts=float(r["ts"])) for r in reversed(rows)]

    async def append(self, session_id: str, role: str, content: str, farmer_id: str | None = None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversation_turns (session_id, farmer_id, role, content) VALUES ($1, $2, $3, $4)",
                session_id,
                farmer_id,
                role,
                content,
            )

    async def clear(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM conversation_turns WHERE session_id = $1", session_id)


def format_history_for_context(turns: list[Turn], budget_tokens: int = 500) -> str:
    """Serialise turns into a compact dialogue block, newest-first truncation."""
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns:
        prefix = "Farmer" if t.role == "user" else "Agent"
        lines.append(f"{prefix}: {t.content}")
    # Join all, then truncate to budget from the START (drop oldest first)
    full = "\n".join(lines)
    from .budget import truncate_to_budget
    # Truncation from the right loses newest turns; truncate from left instead
    words = full.split()
    from .budget import count_tokens, CONTEXT_BUDGET
    while words and count_tokens(" ".join(words)) > budget_tokens:
        words = words[20:]   # drop ~20 oldest words at a time
    return " ".join(words)
