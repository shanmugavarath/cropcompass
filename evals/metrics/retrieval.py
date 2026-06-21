"""Deterministic retrieval metrics over the chunk IDs the agent retrieved."""

from __future__ import annotations

from ..schema import Expected, Trace


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    rel = set(relevant_ids)
    top = set(retrieved_ids[:k])
    return len(rel & top) / len(rel)


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    rel = set(relevant_ids)
    top = retrieved_ids[:k]
    return sum(1 for x in top if x in rel) / k


def hit_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    rel = set(relevant_ids)
    return 1.0 if any(x in rel for x in retrieved_ids[:k]) else 0.0


def mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    rel = set(relevant_ids)
    for rank, cid in enumerate(retrieved_ids, start=1):
        if cid in rel:
            return 1.0 / rank
    return 0.0


def retrieval_metrics(trace: Trace, expected: Expected, k: int = 5) -> dict[str, float]:
    """Empty dict when the case has no retrieval label, so it's excluded from the
    retrieval aggregate rather than counted as a zero."""
    if not expected.relevant_chunk_ids:
        return {}
    ids = [c.chunk_id for c in trace.retrieved]
    rel = expected.relevant_chunk_ids
    return {
        f"recall_at_{k}": recall_at_k(ids, rel, k),
        f"precision_at_{k}": precision_at_k(ids, rel, k),
        f"hit_at_{k}": hit_at_k(ids, rel, k),
        "mrr": mrr(ids, rel),
    }
