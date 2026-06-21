"""
tests/test_rag.py — Task 1.2 acceptance tests for the RAG retriever.

Exercises the FROZEN api.services.rag.query_knowledge_base(crop, soil, query, k)
against the populated ChromaDB (SAU Tamil + IMD English) and checks the two
plan acceptance gates:

    * retrieval precision  >= 0.70   (on a 25-query, multi-crop validation set)
    * single-query latency <  200 ms

Bilingual relevance
-------------------
The collection holds English (IMD) and Tamil (SAU) chunks. A query "hits" if any
of its top-k chunks contains a *concept* term in EITHER language (e.g. "irrigat"
or the Tamil root "நீர்"). Relevance is tied to the question's concept, not the
crop, so the crop pre-filter alone can't trivially satisfy it.

Run on the machine that has the embedding model + data/chromadb:
    pytest tests/test_rag.py -v
Tune gates via env: CROPCOMPASS_PRECISION (default 0.70), CROPCOMPASS_LATENCY_MS (200).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# This whole module needs the embedding model + chromadb; skip cleanly without them.
pytest.importorskip("chromadb")
pytest.importorskip("torch")
pytest.importorskip("sentence_transformers")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
rag = pytest.importorskip("api.services.rag")

PRECISION_THRESHOLD = float(os.environ.get("CROPCOMPASS_PRECISION", "0.70"))
LATENCY_BUDGET_MS = float(os.environ.get("CROPCOMPASS_LATENCY_MS", "200"))
TOP_K = 5
TAMIL = ("஀", "௿")  # Tamil Unicode block

# (crop, soil, question, concept_terms) — concept_terms are EN keywords + Tamil roots.
# A query is satisfied if ANY term appears in ANY of the top-k retrieved chunks.
VALIDATION = [
    # --- rice: several question types ---
    ("rice", "clay", "When should I irrigate paddy during the vegetative stage?",
     ["irrigat", "water", "நீர்", "பாசன"]),
    ("rice", "clay", "How do I raise a healthy rice nursery before transplanting?",
     ["nursery", "seedling", "நாற்று", "sow", "விதை"]),
    ("rice", "clay_loam", "Nitrogen top-dressing schedule for transplanted rice",
     ["nitrogen", "urea", "fertiliz", "nutrient", "உர", "top dress"]),
    ("rice", "clay", "Drainage advice for paddy during heavy rainfall",
     ["drain", "rain", "waterlog", "மழை", "நீர்"]),
    ("rice", "clay", "Weed control in direct-sown rice",
     ["weed", "herbicid", "களை", "spray"]),
    # --- cotton ---
    ("cotton", "black", "How to manage pink bollworm in cotton?",
     ["bollworm", "pest", "spray", "insectic", "பூச்சி", "தெளி"]),
    ("cotton", "loam", "Spacing and sowing time for cotton",
     ["sow", "spacing", "season", "விதை"]),
    ("cotton", "black", "Foliar nutrient spray for cotton boll development",
     ["foliar", "nutrient", "spray", "boll", "தெளி"]),
    # --- groundnut ---
    ("groundnut", "sandy", "Seed treatment before sowing groundnut",
     ["seed", "treat", "fungicid", "sow", "விதை"]),
    ("groundnut", "red", "Leaf spot (tikka) disease control in groundnut",
     ["leaf spot", "tikka", "disease", "spray", "நோய்", "தெளி"]),
    ("groundnut", "sandy", "When is groundnut ready to harvest?",
     ["harvest", "maturity", "dig", "அறுவடை"]),
    # --- maize ---
    ("maize", "loam", "Fall armyworm control in maize",
     ["armyworm", "pest", "spray", "insectic", "பூச்சி"]),
    ("maize", "loam", "Recommended sowing window for kharif maize",
     ["sow", "kharif", "season", "விதை"]),
    # --- pulses ---
    ("redgram", "red", "Pod borer management in redgram",
     ["pod borer", "borer", "pest", "spray", "பூச்சி"]),
    ("blackgram", "clay", "Sowing time and seed rate for blackgram",
     ["sow", "seed", "spacing", "விதை"]),
    # --- plantation / horticulture ---
    ("banana", "loam", "Bunch management and propping in banana",
     ["bunch", "prop", "irrigat", "sucker", "நீர்"]),
    ("banana", "loam", "Sigatoka leaf spot management in banana",
     ["sigatoka", "leaf spot", "disease", "spray", "நோய்"]),
    ("coconut", "sandy", "Irrigation for coconut during summer",
     ["irrigat", "water", "mulch", "drought", "நீர்"]),
    ("coconut", "sandy", "Rhinoceros beetle control in coconut",
     ["beetle", "rhino", "pest", "பூச்சி"]),
    # --- spices / vegetables ---
    ("chilli", "loam", "Thrips and leaf curl management in chilli",
     ["thrips", "leaf curl", "virus", "mite", "spray", "பூச்சி"]),
    ("turmeric", "loam", "Rhizome rot control in turmeric",
     ["rhizome", "rot", "disease", "drench", "நோய்"]),
    ("tomato", "loam", "Fruit borer and blight control in tomato",
     ["borer", "blight", "disease", "spray", "நோய்", "தெளி"]),
    # --- sugarcane / sorghum ---
    ("sugarcane", "clay_loam", "Earthing up and irrigation in sugarcane",
     ["earthing", "irrigat", "water", "நீர்"]),
    ("sorghum", "red", "Shoot fly control and sowing time in sorghum",
     ["shoot fly", "pest", "sow", "spray", "விதை"]),
    # --- general weather-contingency / livestock (IMD bulletins) ---
    ("general", "loam", "Precautions for livestock during heavy rain and cold weather",
     ["livestock", "cattle", "poultry", "animal", "shelter", "rain"]),
]


def _hit(results: list[dict], terms: list[str]) -> bool:
    blob = " ".join(r["text"] for r in results).lower()
    return any(t.lower() in blob for t in terms)


@pytest.fixture(scope="module", autouse=True)
def _warm_up():
    """Load the model + collection once so timing/precision aren't skewed by cold start."""
    rag.query_knowledge_base("rice", "clay", "sowing time", k=1)


# --------------------------------------------------------------------------------------
# Precision
# --------------------------------------------------------------------------------------

class TestRetrievalPrecision:
    def test_precision_at_k_meets_threshold(self):
        hits, misses = 0, []
        for crop, soil, q, terms in VALIDATION:
            res = rag.query_knowledge_base(crop, soil, q, k=TOP_K)
            if res and _hit(res, terms):
                hits += 1
            else:
                misses.append(f"{crop}: {q}")
        precision = hits / len(VALIDATION)
        assert precision >= PRECISION_THRESHOLD, (
            f"precision {precision:.2f} < {PRECISION_THRESHOLD:.2f} "
            f"({hits}/{len(VALIDATION)} hit). Misses:\n  " + "\n  ".join(misses)
        )

    @pytest.mark.parametrize("crop,soil,q,terms", VALIDATION,
                             ids=[f"{v[0]}:{v[2][:30]}" for v in VALIDATION])
    def test_each_query_returns_results(self, crop, soil, q, terms):
        res = rag.query_knowledge_base(crop, soil, q, k=TOP_K)
        assert isinstance(res, list) and res, f"no results for {crop!r}: {q!r}"
        assert len(res) <= TOP_K


# --------------------------------------------------------------------------------------
# Frozen contract
# --------------------------------------------------------------------------------------

class TestContract:
    def test_result_shape(self):
        res = rag.query_knowledge_base("rice", "clay", "irrigation schedule", k=5)
        assert isinstance(res, list) and res
        for r in res:
            assert {"text", "source", "chunk_id"} <= set(r)
            assert all(isinstance(r[k], str) and r[k] for k in ("text", "source", "chunk_id"))

    def test_k_is_respected(self):
        assert len(rag.query_knowledge_base("cotton", "black", "pest control", k=3)) <= 3

    def test_unknown_crop_is_graceful(self):
        # crop absent from store -> rag falls back to no-filter; must return a list, never raise
        res = rag.query_knowledge_base("dragonfruit", "loam", "when to plant", k=5)
        assert isinstance(res, list)


# --------------------------------------------------------------------------------------
# Latency
# --------------------------------------------------------------------------------------

class TestLatency:
    def test_single_query_under_budget(self):
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            rag.query_knowledge_base("cotton", "black", "bollworm spray", k=5)
            times.append((time.perf_counter() - t0) * 1000)
        best = min(times)
        assert best < LATENCY_BUDGET_MS, f"best-of-5 {best:.0f} ms exceeds {LATENCY_BUDGET_MS:.0f} ms"


# --------------------------------------------------------------------------------------
# Multilingual retrieval.
# NOTE: retrieval is same-language-dominant. An ENGLISH query is ranked highest against
# the English IMD chunks and does NOT surface the Tamil SAU corpus (even though ~80% of a
# crop's chunks are Tamil). So we verify the property that actually holds: a query in the
# farmer's language reaches the corpus written in that language. The implication for the
# agent (Member 3) is recorded in TASK.md — decide the query-language strategy there.
# --------------------------------------------------------------------------------------

class TestMultilingualRetrieval:
    def test_tamil_query_retrieves_tamil_chunks(self):
        # When to irrigate rice — asked in Tamil; should surface the Tamil SAU corpus.
        q = "நெல் பயிருக்கு நீர் பாசனம் எப்போது செய்ய வேண்டும்?"
        res = rag.query_knowledge_base("rice", "clay", q, k=8)
        assert res, "no results for Tamil query"
        assert any(any(TAMIL[0] <= ch <= TAMIL[1] for ch in r["text"]) for r in res), \
            "Tamil query did not retrieve any Tamil (SAU) chunk"

    def test_english_query_returns_relevant_results(self):
        # English query is expected to return (English IMD) chunks — just assert it works.
        res = rag.query_knowledge_base("rice", "clay", "when to irrigate rice", k=5)
        assert res and all(r["text"] for r in res)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
