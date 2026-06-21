"""Deterministic unit tests for the eval harness — no DB, no LLM, no network.

Metric math, trace folding, judge parsing (fake LLM), and suite aggregation /
gate logic (stub target). Runs under the repo's normal `pytest` (asyncio_mode=auto).
"""

from __future__ import annotations

from agent_service.schemas import StreamEvent

from evals.judge import Judge, _parse_score
from evals.metrics.answer import answer_metrics
from evals.metrics.behavior import behavior_metrics, clarification_match, tool_call_jaccard
from evals.metrics.grounding import update_confusion, verdict_match
from evals.metrics.keywords import keyword_pass, must_include_score, must_not_include_violations
from evals.metrics.retrieval import hit_at_k, mrr, precision_at_k, recall_at_k, retrieval_metrics
from evals.report import evaluate_gates, write_json, write_markdown
from evals.runner import run_suite
from evals.schema import EvalCase, Expected, RetrievedChunk, Trace
from evals.trace import TraceAccumulator


# ── retrieval ────────────────────────────────────────────────────────────────

def test_recall_precision_hit():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = ["c", "z"]
    assert recall_at_k(retrieved, relevant, 5) == 0.5      # 1 of 2 relevant found
    assert precision_at_k(retrieved, relevant, 5) == 0.2   # 1 of 5 slots
    assert hit_at_k(retrieved, relevant, 5) == 1.0
    assert hit_at_k(retrieved, relevant, 2) == 0.0         # c is at rank 3


def test_mrr_rank():
    assert mrr(["x", "y", "rel"], ["rel"]) == 1 / 3
    assert mrr(["rel", "y"], ["rel"]) == 1.0
    assert mrr(["x", "y"], ["rel"]) == 0.0


def test_retrieval_metrics_skips_unlabeled():
    trace = Trace(case_id="t", retrieved=[RetrievedChunk(chunk_id="a", similarity=0.5)])
    assert retrieval_metrics(trace, Expected()) == {}      # no relevant_chunk_ids
    m = retrieval_metrics(trace, Expected(relevant_chunk_ids=["a"]), k=5)
    assert m["recall_at_5"] == 1.0 and m["mrr"] == 1.0


# ── grounding ────────────────────────────────────────────────────────────────

def test_verdict_match_and_none():
    assert verdict_match(Trace(case_id="t", final_verdict="PASS"), Expected(verdict="PASS")) == 1.0
    assert verdict_match(Trace(case_id="t", final_verdict="REJECT"), Expected(verdict="PASS")) == 0.0
    assert verdict_match(Trace(case_id="t", final_verdict="PASS"), Expected()) is None


def test_verdict_acceptable_set():
    e = Expected(verdict="PASS", acceptable_verdicts=["PASS", "PARTIAL"])
    assert verdict_match(Trace(case_id="t", final_verdict="PARTIAL"), e) == 1.0  # tolerated
    assert verdict_match(Trace(case_id="t", final_verdict="REJECT"), e) == 0.0
    assert verdict_match(Trace(case_id="t", final_verdict="PASS"), e) == 1.0


def test_confusion_buckets_none():
    conf: dict = {}
    update_confusion(conf, Trace(case_id="1", final_verdict="PASS"), Expected(verdict="PASS"))
    update_confusion(conf, Trace(case_id="2", final_verdict=None), Expected())  # clarify
    update_confusion(conf, Trace(case_id="3", final_verdict="PARTIAL"), Expected())
    assert conf["PASS"] == {"PASS": 1}
    assert conf["NONE"] == {"NONE": 1, "PARTIAL": 1}


# ── keywords ─────────────────────────────────────────────────────────────────

def test_keywords_case_insensitive():
    assert must_include_score("Rice needs 1500 MM", ["rice", "mm"]) == 1.0
    assert must_include_score("Rice only", ["rice", "wheat"]) == 0.5
    assert must_include_score("anything", []) == 1.0
    assert must_not_include_violations("We GUARANTEE yields", ["guarantee"]) == ["guarantee"]


def test_keyword_pass_gate():
    t = Trace(case_id="t", answer_text="Rice needs water. Consult your KVK.")
    assert keyword_pass(t, Expected(must_include=["kvk"])) is True
    assert keyword_pass(t, Expected(must_include=["wheat"])) is False
    bad = Trace(case_id="t", answer_text="I guarantee double yields")
    assert keyword_pass(bad, Expected(must_not_include=["guarantee"])) is False


# ── behavior ─────────────────────────────────────────────────────────────────

def test_clarification_and_jaccard():
    assert clarification_match(Trace(case_id="t", clarified=True), Expected(expect_clarification=True)) == 1.0
    assert clarification_match(Trace(case_id="t", clarified=False), Expected(expect_clarification=True)) == 0.0
    t = Trace(case_id="t", tools_called=["a", "b", "c"])
    assert tool_call_jaccard(t, Expected()) is None                       # unlabeled -> skipped
    assert tool_call_jaccard(t, Expected(expected_tools=["a", "b"])) == 2 / 3


def test_behavior_metrics_shape():
    t = Trace(case_id="t", clarified=False, latency_s=1.5, answer_tokens=10)
    m = behavior_metrics(t, Expected())
    assert m["clarification_match"] == 1.0 and m["latency_s"] == 1.5 and m["answer_tokens"] == 10.0
    assert "tool_call_jaccard" not in m


# ── trace folding ────────────────────────────────────────────────────────────

def test_trace_accumulator_prefers_final():
    acc = TraceAccumulator("c")
    for e in [
        StreamEvent.make("tool_call", "s", name="query_knowledge_base"),
        StreamEvent.make("token", "s", delta="draft text"),
        StreamEvent.make("verdict", "s", verdict="PASS", citations={"x": "icar:crop:rice"}),
        StreamEvent.make("final", "s", text="final answer", lang="hin_Deva", verdict="PASS", citations={"x": "icar:crop:rice"}),
    ]:
        acc.consume(e)
    t = acc.finish(2.0)
    assert t.tools_called == ["query_knowledge_base"]
    assert t.answer_text == "final answer"        # final beats accumulated tokens
    assert t.final_verdict == "PASS" and t.lang == "hin_Deva"
    assert t.latency_s == 2.0 and t.answer_tokens > 0


def test_trace_accumulator_clarify_and_error():
    acc = TraceAccumulator("c")
    acc.consume(StreamEvent.make("question", "s", text="Which crop?"))
    t = acc.finish(0.3)
    assert t.clarified and t.answer_text == "Which crop?" and t.final_verdict is None

    acc2 = TraceAccumulator("c")
    acc2.consume(StreamEvent.make("error", "s", message="boom"))
    assert acc2.finish(0.1).error == "boom"


# ── judge (fake LLM) ─────────────────────────────────────────────────────────

class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._r = list(responses)
        self._i = 0

    async def complete_json(self, **_kwargs) -> str:  # matches LLMClient.complete_json
        r = self._r[self._i % len(self._r)]
        self._i += 1
        return r


def test_parse_score_fallback_and_clamp():
    s = _parse_score("no json at all")
    assert (s.relevance, s.correctness, s.completeness, s.faithfulness) == (0, 0, 0, 0)
    assert s.rationale == "judge parse failure"
    c = _parse_score('{"relevance":9,"correctness":-1,"completeness":"x","faithfulness":3.6}')
    assert (c.relevance, c.correctness, c.completeness, c.faithfulness) == (5, 0, 0, 4)


async def test_answer_metrics_average_and_std():
    case = EvalCase(id="j", message="q", expected=Expected(reference_answer="ref"))
    trace = Trace(case_id="j", answer_text="a")
    judge = Judge(_FakeLLM([
        '{"relevance":4,"correctness":4,"completeness":4,"faithfulness":4,"rationale":"a"}',
        '{"relevance":2,"correctness":2,"completeness":2,"faithfulness":2,"rationale":"b"}',
    ]))
    agg, m = await answer_metrics(judge, case, trace, repeats=2)
    assert m["judge_relevance_mean"] == 3.0
    assert abs(m["judge_relevance_std"] - 1.0) < 1e-9
    assert agg.relevance == 3


# ── suite + gates (stub target) ──────────────────────────────────────────────

class _StubTarget:
    def __init__(self, traces: dict[str, Trace]) -> None:
        self._t = traces

    async def run(self, case: EvalCase) -> Trace:
        return self._t[case.id]

    async def aclose(self) -> None:
        pass


async def test_run_suite_aggregates_and_gates(tmp_path):
    cases = [
        EvalCase(id="g", message="rice?", tags=["grounded"],
                 expected=Expected(verdict="PASS", relevant_chunk_ids=["r"], must_include=["rice"], reference_answer="x")),
        EvalCase(id="s", message="guarantee?", tags=["safety"],
                 expected=Expected(must_not_include=["guarantee"])),
    ]
    traces = {
        "g": Trace(case_id="g", answer_text="Rice needs water", final_verdict="PASS",
                   retrieved=[RetrievedChunk(chunk_id="r", similarity=0.9)], latency_s=1.0, answer_tokens=3),
        "s": Trace(case_id="s", answer_text="I guarantee yields", final_verdict="PARTIAL",
                   retrieved=[RetrievedChunk(chunk_id="r", similarity=0.5)], latency_s=2.0, answer_tokens=3),
    }
    rep = await run_suite(cases, _StubTarget(traces), dataset="unit")
    assert rep.n_cases == 2
    assert rep.aggregates["recall_at_5"] == 1.0           # 'r' relevant; only 'g' labeled, 's' has no relevant id... both have? s has none
    assert rep.aggregates["verdict_accuracy"] == 1.0      # only g labeled, correct
    assert rep.aggregates["keyword_pass_rate"] == 0.5     # s violates must_not_include

    gates = evaluate_gates(rep, {"recall_at_5": 0.7, "keyword_pass_rate": 1.0, "judge_correctness_mean": 3.5})
    assert gates == ["keyword_pass_rate 0.500 < 1.0"]     # judge_* skipped (not computed)

    assert write_json(rep, tmp_path).exists()
    assert write_markdown(rep, tmp_path).exists()
