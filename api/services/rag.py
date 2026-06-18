"""
RAG service — wraps ChromaDB retrieval for the planning agent.

The only public function is query_knowledge_base(). Its signature is frozen
and must not change — Member 3's MCP tool definitions depend on it.

Embedding model: paraphrase-multilingual-MiniLM-L12-v2
  Maps both Tamil (TNAU corpus) and English (future ICAR corpus) into the
  same 384-dim vector space, so English queries retrieve Tamil chunks.

Dual-collection strategy:
  icar_knowledge_en  — all-English collection (IMD + translated SAU). Best for
                       English queries since retrieval is same-language-dominant.
  icar_knowledge     — original collection (IMD eng + SAU tam). Covers the
                       untranslated Tamil SAU chunks that icar_knowledge_en lacks.
  Both are queried, results merged by distance, deduplicated by chunk_id.

Crop filter behaviour:
  Tries exact crop match first (where={"crop": crop}).
  Falls back to no filter if 0 results — this happens when:
    - The requested crop isn't in the loaded books yet (pilot phase)
    - The relevant chunks were tagged "general" (multi-crop pages)
"""

from pathlib import Path

from sentence_transformers import SentenceTransformer
import chromadb

_EMBED_MODEL_NAME  = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_CHROMA_PATH       = Path(__file__).parent.parent.parent / "data" / "chromadb"
_PRIMARY_COLLECTION = "icar_knowledge_en"
_FALLBACK_COLLECTION = "icar_knowledge"

_model: SentenceTransformer | None = None
_col_primary = None
_col_fallback = None


def _resources():
    global _model, _col_primary, _col_fallback
    if _model is None:
        _model = SentenceTransformer(_EMBED_MODEL_NAME)
        client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        _col_primary = client.get_or_create_collection(
            name=_PRIMARY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        _col_fallback = client.get_or_create_collection(
            name=_FALLBACK_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _model, _col_primary, _col_fallback


def _query_collection(collection, embedding, crop, k):
    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where={"crop": crop},
    )
    if not results["documents"][0]:
        results = collection.query(
            query_embeddings=[embedding],
            n_results=k,
        )
    return results


def _merge_results(results_list, k):
    """Merge results from multiple collections, deduplicate by chunk_id, return top-k by distance."""
    seen = set()
    candidates = []
    for results in results_list:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        for doc, meta, dist in zip(docs, metas, dists):
            cid = meta.get("chunk_id", id(doc))
            if cid in seen:
                continue
            seen.add(cid)
            candidates.append((dist, doc, meta))
    candidates.sort(key=lambda x: x[0])
    return candidates[:k]


def query_knowledge_base(crop: str, soil: str, query: str, k: int = 5) -> list[dict]:
    """
    Returns top-k source chunks relevant to the query.

    Each returned dict has:
        text      — the raw chunk text (Tamil or English depending on source)
        source    — original PDF filename
        chunk_id  — stable identifier for citation tracking

    Args:
        crop  — crop name matching PLAN.md values (e.g. "rice", "cotton")
        soil  — soil type (passed through to query text; not used as DB filter)
        query — natural-language question from the farmer (any language)
        k     — number of chunks to return
    """
    model, col_primary, col_fallback = _resources()

    embedding = model.encode(query).tolist()

    r_primary = _query_collection(col_primary, embedding, crop, k)
    r_fallback = _query_collection(col_fallback, embedding, crop, k)

    merged = _merge_results([r_primary, r_fallback], k)

    return [
        {
            "text":     doc,
            "source":   meta["source"],
            "chunk_id": meta["chunk_id"],
        }
        for _, doc, meta in merged
    ]
