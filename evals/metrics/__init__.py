"""Metric functions. All deterministic (no LLM) except answer.py (Phase 4)."""

from __future__ import annotations

from .behavior import behavior_metrics, clarification_match, tool_call_jaccard
from .grounding import update_confusion, verdict_match
from .keywords import keyword_pass, must_include_score, must_not_include_violations
from .retrieval import hit_at_k, mrr, precision_at_k, recall_at_k, retrieval_metrics

__all__ = [
    "behavior_metrics",
    "clarification_match",
    "tool_call_jaccard",
    "update_confusion",
    "verdict_match",
    "keyword_pass",
    "must_include_score",
    "must_not_include_violations",
    "hit_at_k",
    "mrr",
    "precision_at_k",
    "recall_at_k",
    "retrieval_metrics",
]
