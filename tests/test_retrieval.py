"""
tests/test_retrieval.py — language-aware retrieval routing tests.

Fast tests (no models): monkeypatch the ChromaDB layer + inject a fake
translator, and assert the detect -> translate -> hybrid wiring inside
query_knowledge_base is correct.

The embedding model / chromadb client are never loaded because
_query_multi is monkeypatched out before any call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("lingua")
pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services import rag  # noqa: E402


class FakeTranslator:
    """Records calls; returns a deterministic, distinct English string."""

    def __init__(self):
        self.calls = []

    def translate_to_english(self, text, src_lang):
        self.calls.append((text, src_lang))
        return "ENGLISH(" + text + ")"


@pytest.fixture
def capture_queries(monkeypatch):
    captured = {}

    def fake_multi(crop, soil, queries, k=5):
        captured.update(crop=crop, soil=soil, queries=queries, k=k)
        return [{"text": "t", "source": "s", "chunk_id": "c"}]

    monkeypatch.setattr(rag, "_query_multi", fake_multi)
    return captured


@pytest.fixture(autouse=True)
def inject_fake_translator(monkeypatch):
    """Ensure the real IndicTrans2 model is never loaded during fast tests."""
    fake = FakeTranslator()
    monkeypatch.setattr(rag, "_query_translator", fake)
    monkeypatch.setattr(rag, "_get_query_translator", lambda: fake)
    return fake


class TestRouting:
    def test_english_query_is_not_translated(self, capture_queries, inject_fake_translator):
        rag.query_knowledge_base("rice", "clay", "when to irrigate rice", k=5)
        assert inject_fake_translator.calls == []
        assert capture_queries["queries"] == ["when to irrigate rice"]
        assert capture_queries["k"] == 5

    def test_hindi_query_goes_hybrid(self, capture_queries, inject_fake_translator):
        q = "धान की सिंचाई कब करें?"
        rag.query_knowledge_base("rice", "clay", q, k=5)
        assert inject_fake_translator.calls == [(q, "hin_Deva")]
        assert capture_queries["queries"] == [f"ENGLISH({q})", q]

    def test_tamil_query_goes_hybrid(self, capture_queries, inject_fake_translator):
        q = "நெல் பயிருக்கு நீர் எப்போது பாய்ச்ச வேண்டும்?"
        rag.query_knowledge_base("rice", "clay", q)
        assert inject_fake_translator.calls and inject_fake_translator.calls[0][1] == "tam_Taml"
        assert len(capture_queries["queries"]) == 2

    def test_noop_translation_stays_single_query(self, capture_queries, monkeypatch):
        class NoopTranslator:
            def translate_to_english(self, text, src_lang):
                return text

        monkeypatch.setattr(rag, "_get_query_translator", lambda: NoopTranslator())
        q = "धान की सिंचाई कब करें?"
        rag.query_knowledge_base("rice", "clay", q)
        assert capture_queries["queries"] == [q]

    def test_result_shape_passthrough(self, capture_queries):
        out = rag.query_knowledge_base("rice", "clay", "irrigation")
        assert out == [{"text": "t", "source": "s", "chunk_id": "c"}]
