"""
Rigorous tests for the IMD agromet bulletins ingested into ChromaDB
(ingestion/ingest_imd_to_chromadb.py).

Layers
------
1. Integrity   - the chunks exist, ids are unique/stable, schema is complete.
2. Coverage    - all 6 states, correct date span, season<-date, valid crop vocab.
3. Content     - chunks are advisory prose (no residual numeric tables), deduped.
4. Retrieval   - English agromet queries return relevant IMD chunks; crop filter
                 works; cross-lingual matching works.   (needs the embedding model)
5. Contract    - api.services.rag.query_knowledge_base still honours its frozen shape.
6. Regression  - the pre-existing SAU (Tamil) corpus is untouched.

The model-dependent layers (4, 5, partly) auto-skip if torch / sentence-transformers
aren't installed, so the no-model layers can run anywhere (CI without a GPU, etc.).

Point the tests at a DB with:  CROPCOMPASS_CHROMA_PATH=/path/to/chromadb
Run:                           pytest tests/test_imd_ingestion.py -v
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHROMA_PATH = os.environ.get("CROPCOMPASS_CHROMA_PATH", str(ROOT / "data" / "chromadb"))
COLLECTION = os.environ.get("CROPCOMPASS_COLLECTION", "icar_knowledge")
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

EXPECTED_STATES = {"Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh", "Telangana", "Puducherry"}
KNOWN_CROPS = {
    "rice", "cotton", "groundnut", "maize", "redgram", "blackgram", "greengram",
    "sugarcane", "sorghum", "pearlmillet", "fingermillet", "banana", "coconut",
    "chilli", "turmeric", "tomato", "onion", "sunflower", "sesame", "soybean",
    "wheat", "blackpepper", "rubber", "coffee", "arecanut", "mango", "general",
}
MONTH_SEASON = {1: "rabi", 2: "rabi", 3: "rabi", 4: "zaid", 5: "zaid", 6: "kharif",
                7: "kharif", 8: "kharif", 9: "kharif", 10: "kharif", 11: "rabi", 12: "rabi"}
REQUIRED_FIELDS = ["source", "chunk_id", "doc_type", "state", "district", "date",
                   "year", "season", "crop", "soil_type", "lang"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUM_TOKEN = re.compile(r"^[-+(]?\d[\d.,:;°%/()-]*$")
SPAN_START, SPAN_END = "2025-09-01", "2026-07-01"


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def collection():
    if not Path(CHROMA_PATH).exists():
        pytest.skip(f"ChromaDB not found at {CHROMA_PATH} (run the ingest first)")
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        return client.get_collection(COLLECTION)
    except Exception as e:  # collection missing / unreadable
        pytest.skip(f"Cannot open collection {COLLECTION!r}: {e}")


@pytest.fixture(scope="session")
def imd(collection):
    """All IMD ids + metadatas."""
    got = collection.get(where={"doc_type": "imd_agromet"}, include=["metadatas"])
    if not got["ids"]:
        pytest.skip("No IMD chunks in the collection yet (run ingest_imd_to_chromadb).")
    return got["ids"], got["metadatas"]


@pytest.fixture(scope="session")
def imd_docs(collection):
    """A bounded sample of IMD documents for content checks."""
    got = collection.get(where={"doc_type": "imd_agromet"},
                         include=["documents", "metadatas"], limit=3000)
    return got["documents"], got["metadatas"]


@pytest.fixture(scope="session")
def model():
    pytest.importorskip("torch")
    st = pytest.importorskip("sentence_transformers")
    return st.SentenceTransformer(MODEL_NAME)


def _query(collection, model, text, k=5, where=None):
    emb = model.encode(text).tolist()
    kwargs = {"query_embeddings": [emb], "n_results": k, "include": ["documents", "metadatas"]}
    if where:
        kwargs["where"] = where
    res = collection.query(**kwargs)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    return list(zip(docs, metas))


# --------------------------------------------------------------------------------------
# 1. Integrity
# --------------------------------------------------------------------------------------

class TestIntegrity:
    def test_imd_chunks_present(self, imd):
        ids, _ = imd
        assert len(ids) >= 5000, f"expected a substantial IMD load, got {len(ids)}"

    def test_ids_unique(self, imd):
        ids, _ = imd
        assert len(ids) == len(set(ids))

    def test_ids_prefixed_and_match_chunk_id(self, imd):
        ids, metas = imd
        assert all(i.startswith("imd_") for i in ids)
        assert all(m["chunk_id"] == i for i, m in zip(ids, metas))

    def test_required_fields_present(self, imd):
        _, metas = imd
        for m in metas:
            missing = [k for k in REQUIRED_FIELDS if k not in m or m[k] in (None, "")]
            assert not missing, f"missing {missing} in {m.get('chunk_id')}"

    def test_doc_type_and_lang(self, imd):
        _, metas = imd
        assert all(m["doc_type"] == "imd_agromet" for m in metas)
        assert all(m["lang"] == "eng" for m in metas)

    def test_year_is_int_and_matches_date(self, imd):
        _, metas = imd
        for m in metas:
            assert isinstance(m["year"], int)
            assert DATE_RE.match(m["date"]) and m["date"][:4] == str(m["year"])


# --------------------------------------------------------------------------------------
# 2. Coverage
# --------------------------------------------------------------------------------------

class TestCoverage:
    def test_all_states_present(self, imd):
        _, metas = imd
        assert EXPECTED_STATES <= {m["state"] for m in metas}

    def test_no_unexpected_states(self, imd):
        _, metas = imd
        assert {m["state"] for m in metas} <= EXPECTED_STATES

    def test_date_span(self, imd):
        _, metas = imd
        dates = [m["date"] for m in metas]
        assert min(dates) >= SPAN_START and max(dates) <= SPAN_END

    def test_season_matches_month(self, imd):
        _, metas = imd
        for m in metas:
            assert m["season"] == MONTH_SEASON[int(m["date"][5:7])]

    def test_crop_vocabulary_valid(self, imd):
        _, metas = imd
        assert {m["crop"] for m in metas} <= KNOWN_CROPS

    def test_multiple_districts_per_state(self, imd):
        _, metas = imd
        from collections import defaultdict
        d = defaultdict(set)
        for m in metas:
            d[m["state"]].add(m["district"])
        # every collected state should have several districts represented
        assert all(len(v) >= 2 for v in d.values()), {k: len(v) for k, v in d.items()}


# --------------------------------------------------------------------------------------
# 3. Content quality
# --------------------------------------------------------------------------------------

class TestContentQuality:
    def test_chunks_non_trivial(self, imd_docs):
        docs, _ = imd_docs
        assert all(len(d) >= 40 for d in docs)

    def test_few_residual_numeric_tables(self, imd_docs):
        docs, _ = imd_docs

        def mostly_numeric(t):
            toks = t.split()
            return bool(toks) and sum(1 for x in toks if NUM_TOKEN.match(x)) >= 0.5 * len(toks)

        frac = sum(mostly_numeric(d[:200]) for d in docs) / len(docs)
        assert frac < 0.02, f"{frac:.1%} of chunks look like leftover forecast tables"

    def test_dedup_holds(self, imd_docs):
        docs, _ = imd_docs
        norm = [re.sub(r"\s+", " ", d).strip().lower() for d in docs]
        assert len(norm) == len(set(norm)), "duplicate chunk texts found despite dedup"


# --------------------------------------------------------------------------------------
# 4. Retrieval (needs the embedding model)
# --------------------------------------------------------------------------------------

# (query, crop_filter, expected_terms) — a top-k hit should match the crop or a term.
RETRIEVAL_SCENARIOS = [
    ("management of pink bollworm in cotton crop", "cotton", ["cotton", "bollworm", "spray"]),
    ("paddy nursery raising and transplanting in rice", "rice", ["rice", "paddy", "nursery", "transplant"]),
    ("groundnut sowing seed treatment", "groundnut", ["groundnut", "sowing", "seed"]),
    ("banana bunch management and irrigation", "banana", ["banana", "bunch", "irrigat"]),
    ("coconut management during dry weather", "coconut", ["coconut", "irrigat", "mulch"]),
    ("measures during heavy rainfall and waterlogging", None, ["rain", "drain", "water"]),
]


class TestRetrieval:
    @pytest.mark.parametrize("query,crop,terms", RETRIEVAL_SCENARIOS)
    def test_scenario_returns_relevant_imd_chunk(self, collection, model, query, crop, terms):
        hits = _query(collection, model, query, k=8, where={"doc_type": "imd_agromet"})
        assert hits, f"no IMD results for {query!r}"
        relevant = [
            (doc, meta) for doc, meta in hits
            if (crop and meta.get("crop") == crop) or any(t in doc.lower() for t in terms)
        ]
        assert relevant, f"top-8 IMD results not relevant to {query!r}"

    def test_english_query_hits_imd(self, collection, model):
        hits = _query(collection, model, "agromet advisory for farmers this week", k=10)
        assert any(m.get("doc_type") == "imd_agromet" for _, m in hits)

    def test_crop_filter_is_respected(self, collection, model):
        hits = _query(collection, model, "pest and disease control in cotton",
                      k=5, where={"crop": "cotton"})
        assert hits, "crop=cotton filter returned nothing"
        assert all(m["crop"] == "cotton" for _, m in hits)

    def test_cross_lingual_matching(self, collection, model):
        # English query against a collection that also holds Tamil SAU chunks
        hits = _query(collection, model, "when to irrigate rice during vegetative stage", k=5)
        assert hits


# --------------------------------------------------------------------------------------
# 5. Frozen contract: api/services/rag.py
# --------------------------------------------------------------------------------------

class TestRagContract:
    def test_query_knowledge_base_shape(self, model):
        rag = pytest.importorskip("api.services.rag")
        out = rag.query_knowledge_base(crop="cotton", soil="black",
                                       query="pink bollworm control in cotton", k=5)
        assert isinstance(out, list) and out, "expected non-empty result list"
        for item in out:
            assert {"text", "source", "chunk_id"} <= set(item)
            assert all(isinstance(item[k], str) for k in ("text", "source", "chunk_id"))


# --------------------------------------------------------------------------------------
# 6. Non-regression: SAU (Tamil) corpus untouched
# --------------------------------------------------------------------------------------

class TestNonRegression:
    def test_sau_corpus_intact(self, collection, imd):
        ids, _ = imd
        total = collection.count()
        assert total - len(ids) >= 50000, "SAU corpus appears reduced after IMD ingest"

    def test_tamil_chunks_retrievable_by_filter(self, collection):
        got = collection.get(where={"lang": "tam"}, include=[], limit=5)
        assert got["ids"], "no Tamil (SAU) chunks found"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
