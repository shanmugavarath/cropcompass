import json

import pytest

from agent_service.tools.base import ToolRegistry, ToolSpec
from agent_service.tools.builtin import build_builtin_registry


async def _echo(**kwargs):
    return {"echo": kwargs}


def _spec(name="echo"):
    return ToolSpec(
        name=name,
        description="echo back",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        fn=_echo,
    )


async def test_spec_returns_dict_and_never_raises():
    async def boom(**_):
        raise RuntimeError("kaboom")

    t = ToolSpec(name="boom", description="x", input_schema={"type": "object"}, fn=boom)
    out = await t(x="y")
    assert "error" in out and "kaboom" in out["error"]


async def test_spec_rejects_non_dict_returns():
    async def bad(**_):
        return [1, 2, 3]

    t = ToolSpec(name="bad", description="x", input_schema={"type": "object"}, fn=bad)
    out = await t()
    assert out == {"error": "tool bad returned non-dict: list"}


async def test_registry_dispatch_round_trip():
    reg = ToolRegistry()
    reg.register(_spec())
    out = await reg.dispatch("echo", {"x": "hi"})
    assert out == {"echo": {"x": "hi"}}


def test_registry_rejects_duplicate_registration():
    reg = ToolRegistry()
    reg.register(_spec())
    with pytest.raises(ValueError):
        reg.register(_spec())


async def test_unknown_tool_returns_error():
    reg = ToolRegistry()
    out = await reg.dispatch("nope", {})
    assert "unknown tool" in out["error"]


def test_builtin_registry_exposes_translate():
    reg = build_builtin_registry()
    assert "translate_output" in reg.names()


def test_anthropic_spec_shape():
    reg = ToolRegistry()
    reg.register(_spec())
    spec = reg.anthropic_spec()
    assert spec == [
        {
            "name": "echo",
            "description": "echo back",
            "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        }
    ]


async def test_translate_passthrough_english(monkeypatch):
    """The translate tool short-circuits for eng_Latn even without HF_API_KEY."""
    reg = build_builtin_registry()
    out = await reg.dispatch("translate_output", {"text": "Sow now.", "lang": "eng_Latn"})
    assert out == {"translated": "Sow now.", "lang": "eng_Latn"}


def test_anthropic_spec_dropped_on_unregister():
    reg = ToolRegistry()
    reg.register(_spec())
    reg.unregister("echo")
    assert reg.names() == []
    assert reg.anthropic_spec() == []


def test_specs_are_json_serializable():
    reg = ToolRegistry()
    reg.register(_spec())
    json.dumps(reg.anthropic_spec())
