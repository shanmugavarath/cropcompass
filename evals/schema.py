"""Single source of truth for every eval data shape.

Pydantic v2 models so dataset JSONL is validated on load and traces/results are
serialisable to JSON. Mirrors agent_service.schemas.Verdict; kept dependency-free
(only pydantic) so the metric unit tests can import this with no agent_service
runtime, DB, or network.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Mirror of agent_service.schemas.Verdict — duplicated (not imported) to keep this
# module importable without pulling the agent package into the test path.
Verdict = Literal["PASS", "PARTIAL", "REJECT"]


class Expected(BaseModel):
    """The labelled ground truth for one case. Every field is optional so a case
    only declares the dimensions it actually exercises."""

    verdict: Verdict | None = None
    # Optional set of acceptable verdicts; when set, verdict_match passes if the
    # observed verdict is any of these. Needed because the verifier is
    # non-deterministic (a grounded answer may land PASS or PARTIAL run to run).
    acceptable_verdicts: list[Verdict] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    reference_answer: str | None = None
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    expect_clarification: bool = False
    expected_tools: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str                                       # unique, kebab-case
    farmer_id: str | None = None                  # None => anonymous mode
    message: str = Field(min_length=1, max_length=500)   # mirrors ChatRequest bounds
    tags: list[str] = Field(default_factory=list)
    expected: Expected = Field(default_factory=Expected)


class RetrievedChunk(BaseModel):
    chunk_id: str
    similarity: float
    text: str = ""   # chunk content; populated for the judge's faithfulness check


class Trace(BaseModel):
    """Everything observed from one agent run of one case."""

    case_id: str
    answer_text: str = ""
    final_verdict: Verdict | None = None
    citations: dict[str, str] = Field(default_factory=dict)
    tools_called: list[str] = Field(default_factory=list)   # order preserved
    clarified: bool = False                                 # a 'question' event fired
    error: str | None = None
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    latency_s: float = 0.0
    answer_tokens: int = 0
    lang: str | None = None


class JudgeScore(BaseModel):
    relevance: int        # 1..5
    correctness: int      # 1..5
    completeness: int     # 1..5
    faithfulness: int     # 1..5
    rationale: str = ""


class CaseResult(BaseModel):
    case: EvalCase
    trace: Trace
    metrics: dict[str, float] = Field(default_factory=dict)
    judge: JudgeScore | None = None
    passed: bool = False   # all hard asserts (keywords + clarification) satisfied


class RunReport(BaseModel):
    dataset: str
    n_cases: int
    aggregates: dict[str, float] = Field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
    per_case: list[CaseResult] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    gate_failures: list[str] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
