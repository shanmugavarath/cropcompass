"""ChromaDB retriever — the engine behind the chroma MCP server.

Ported from cropcompass/api/services/rag.py so the MCP layer stays thin and the
retrieval behaviour (multilingual embeddings + dual-collection merge) lives in
exactly one place.

Embedding model: paraphrase-multilingual-MiniLM-L12-v2
  Maps both Tamil (TNAU corpus) and English (ICAR/IMD corpus) into the same
  384-dim vector space, so English queries retrieve Tamil chunks.

Dual-collection strategy:
  icar_knowledge_en  — all-English collection (IMD + translated SAU). Best for
                       English queries since retrieval is same-language-dominant.
  icar_knowledge     — original collection (IMD eng + SAU tam). Covers the
                       untranslated Tamil SAU chunks the _en collection lacks.
  Both are queried, merged by distance, deduplicated by chunk_id.

Everything heavy (model + chroma client) is lazy-loaded once and reused.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

# Two connection modes:
#   1. HTTP  (production / Docker)  - talk to a standalone `chroma` container.
#        Set CHROMA_HOST (+ optional CHROMA_PORT, default 8000).
#   2. Embedded (local dev)        - open the persisted store directly.
#        Leave CHROMA_HOST unset; falls back to CHROMA_PATH.
_CHROMA_HOST = os.getenv("CHROMA_HOST", "").strip()
_CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

# Repo-root/data/chromadb by default; override with CHROMA_PATH (embedded mode).
_DEFAULT_CHROMA_PATH = Path(__file__).resolve().parents[2] / "data" / "chromadb"
_CHROMA_PATH = os.getenv("CHROMA_PATH", str(_DEFAULT_CHROMA_PATH))

_EMBED_MODEL_NAME = os.getenv(
    "CHROMA_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
_PRIMARY_COLLECTION = os.getenv("CHROMA_PRIMARY_COLLECTION", "icar_knowledge_en")
_FALLBACK_COLLECTION = os.getenv("CHROMA_FALLBACK_COLLECTION", "icar_knowledge")

_model = None
_client = None
_col_primary = None
_col_fallback = None


def _resources():
    """Lazy-init the embedding model + chroma collections (once).

    Transactional: globals are only assigned after *all* steps succeed, so a
    transient failure (e.g. the chroma container not ready yet) leaves the module
    un-initialized and the next call retries cleanly instead of caching a
    half-built state.
    """
    global _model, _client, _col_primary, _col_fallback
    if _col_primary is not None:
        return _model, _client, _col_primary, _col_fallback

    from sentence_transformers import SentenceTransformer
    import chromadb

    model = _model or SentenceTransformer(_EMBED_MODEL_NAME)
    if _CHROMA_HOST:
        # Standalone chroma container (the `db`-style service).
        client = chromadb.HttpClient(host=_CHROMA_HOST, port=_CHROMA_PORT)
    else:
        # Embedded store, opened straight off disk (local dev only).
        client = chromadb.PersistentClient(path=_CHROMA_PATH)
    col_primary = client.get_or_create_collection(
        name=_PRIMARY_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        # We pass our own query_embeddings, so Chroma needs NO embedding function.
        # Leaving this unset makes Chroma download its default ONNX model and spin
        # up onnxruntime on startup — which hangs the server. None avoids all that.
        embedding_function=None,
    )
    col_fallback = client.get_or_create_collection(
        name=_FALLBACK_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )

    # Commit to globals only once everything above succeeded.
    _model, _client, _col_primary, _col_fallback = model, client, col_primary, col_fallback
    return _model, _client, _col_primary, _col_fallback


def _query_collection(collection, embedding, crop, k):
    """Try a crop-filtered query first; fall back to unfiltered on zero hits."""
    if crop:
        results = collection.query(
            query_embeddings=[embedding],
            n_results=k,
            where={"crop": crop},
        )
        if results["documents"] and results["documents"][0]:
            return results
    return collection.query(query_embeddings=[embedding], n_results=k)


def _merge_results(results_list, k):
    """Merge multi-collection results, dedupe by chunk_id, keep top-k by distance."""
    seen: set = set()
    candidates: list[tuple[float, str, dict]] = []
    for results in results_list:
        if not results["documents"]:
            continue
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            cid = meta.get("chunk_id", id(doc))
            if cid in seen:
                continue
            seen.add(cid)
            candidates.append((dist, doc, meta))
    candidates.sort(key=lambda x: x[0])
    return candidates[:k]


def _search(query: str, crop: str | None, k: int) -> list[dict[str, Any]]:
    model, _client, col_primary, col_fallback = _resources()
    embedding = model.encode(query).tolist()

    r_primary = _query_collection(col_primary, embedding, crop, k)
    r_fallback = _query_collection(col_fallback, embedding, crop, k)
    merged = _merge_results([r_primary, r_fallback], k)

    return [
        {
            "chunk_id": meta.get("chunk_id", ""),
            "text": doc,
            "source": meta.get("source", ""),
            # cosine distance -> similarity in [0, 1]
            "similarity": round(1.0 - float(dist), 4),
            "metadata": dict(meta),
        }
        for dist, doc, meta in merged
    ]


async def query_knowledge_base(
    query: str,
    crop: str | None = None,
    soil: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Async wrapper — runs the blocking chroma/embedding work off the event loop."""
    # `soil` is accepted for signature parity with the legacy rag.py contract but
    # is not used as a DB filter (kept implicit in the query text upstream).
    chunks = await asyncio.to_thread(_search, query, crop, top_k)
    return {"query": query, "crop": crop, "chunks": chunks}


def _fetch(chunk_id: str) -> dict[str, Any]:
    _model, _client, col_primary, col_fallback = _resources()
    for col in (col_primary, col_fallback):
        got = col.get(where={"chunk_id": chunk_id}, limit=1)
        if got["documents"]:
            meta = (got["metadatas"][0] or {}) if got["metadatas"] else {}
            return {
                "chunk_id": chunk_id,
                "text": got["documents"][0],
                "source": meta.get("source", ""),
                "metadata": dict(meta),
                "collection": col.name,
            }
    return {"error": f"chunk not found: {chunk_id}"}


async def fetch_chunk(chunk_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_fetch, chunk_id)


def _collections() -> dict[str, Any]:
    _model, client, _p, _f = _resources()
    out = []
    for col in client.list_collections():
        try:
            count = col.count()
        except Exception:
            count = -1
        out.append({"name": col.name, "chunks": count})
    return {"collections": out}


async def list_collections() -> dict[str, Any]:
    return await asyncio.to_thread(_collections)
