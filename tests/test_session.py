"""Tests for session store and conversation history injection.

All tests use InMemorySessionStore — no DB required.
"""

from __future__ import annotations

from agent_service.session import InMemorySessionStore, Turn, format_history_for_context


def test_store_load_empty():
    store = InMemorySessionStore()
    assert store.load("new-session") == []


def test_store_append_and_load():
    store = InMemorySessionStore()
    store.append("s1", "user", "hello")
    store.append("s1", "assistant", "hi there")
    turns = store.load("s1")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"


def test_store_max_turns_truncates_oldest():
    store = InMemorySessionStore(max_turns=3)
    for i in range(5):
        store.append("s1", "user", f"msg {i}")
    turns = store.load("s1")
    assert len(turns) == 3
    assert turns[0].content == "msg 2"   # oldest 2 dropped


def test_store_clear():
    store = InMemorySessionStore()
    store.append("s1", "user", "hello")
    store.clear("s1")
    assert store.load("s1") == []


def test_format_history_empty():
    assert format_history_for_context([]) == ""


def test_format_history_renders_correctly():
    turns = [
        Turn(role="user", content="When should I sow?"),
        Turn(role="assistant", content="Sow after 70mm rain."),
    ]
    out = format_history_for_context(turns)
    assert "Farmer: When should I sow?" in out
    assert "Agent: Sow after 70mm rain." in out


def test_format_history_truncates_to_budget():
    long_content = "word " * 500
    turns = [Turn(role="user", content=long_content)] * 10
    out = format_history_for_context(turns, budget_tokens=50)
    from agent_service.budget import count_tokens
    assert count_tokens(out) <= 60    # small slack for rounding
