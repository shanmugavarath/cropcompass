# Eval Harness — File-by-File Spec

> Status: **proposed / for review** — no code written yet.
> Scope locked: **In-process target** · **deterministic metrics + LLM-as-judge** · **hand-authored golden dataset (~25–40 cases)**.

This document is the complete blueprint for an evaluation harness for the CropCompass
agentic backend. It measures **agent output quality** (retrieval, grounding, answer
quality, behavior, safety) — not just the mechanical unit correctness already covered
in `tests/`.

---

## Goals

Measure each of the four agent phases plus end-to-end behavior:

| Dimension | What it answers | Phase it targets |
|---|---|---|
| **Retrieval** | Did `query_knowledge_base` surface the right chunks? | A (Gather) |
| **Grounding** | Does the verifier verdict match the labeled verdict? Is the answer faithful to sources? | C (Verify) |
| **Answer quality** | Is the answer relevant / correct / complete vs a reference? | B (Generate, end-to-end) |
| **Behavior** | Did it clarify when it should? Call the right tools? Stay within latency/token budget? | B / D |
| **Safety** | Does it REJECT / fall back when ungrounded? | C |

---

## Directory layout

```
evals/
  __init__.py
  schema.py              # EvalCase, CaseResult, RunReport (pydantic)
  datasets/
    golden.jsonl         # hand-authored labeled cases
    README.md            # how to add/label a case
  targets/
    __init__.py          # EvalTarget protocol
    in_process.py        # imports AgentRunner directly (chosen mode)
  trace.py               # folds runner.stream() events -> structured Trace
  metrics/
    __init__.py
    retrieval.py         # recall@k, precision@k, MRR, hit@k
    grounding.py         # verdict accuracy + confusion matrix
    behavior.py          # clarification match, tool-call match, latency/tokens
    keywords.py          # must_include / must_not_include asserts (deterministic)
    answer.py            # glue to LLM-as-judge: relevance/correctness/completeness/faithfulness
  judge.py               # LLM-as-judge over the existing LLMClient abstraction
  prompts/
    judge_system.md      # judge rubric prompt
  report.py              # aggregate -> JSON + Markdown + console table
  runner.py              # load dataset -> run suite -> RunReport
  cli.py                 # python -m evals.cli run ...
  thresholds.yaml        # regression gates (min recall, min verdict acc, ...)
tests/
  test_evals.py          # unit tests for the metric functions (deterministic)
```

---

## Conventions (apply to all files)

- Python 3.11+, `from __future__ import annotations`, `async`/`await`, `structlog` for
  logging, `pydantic` v2 for models — matching the existing repo style.
- All paths relative to repo root. New top-level package: `evals/`.
- Imports use the installed `agent_service` package (the harness depends on it, not
  vice-versa).

---

## `evals/__init__.py`

**Purpose:** Mark package; export the version and the top-level `run_suite` convenience
function.

**Contents:** `__version__ = "0.1.0"`; re-export `run_suite` from `runner.py` for
programmatic use.

---

## `evals/schema.py`

**Purpose:** Single source of truth for all data shapes (dataset records, traces,
results, report). Pydantic models so JSONL parsing is validated.

**Public API:**

```python
Verdict = Literal["PASS", "PARTIAL", "REJECT"]   # re-use agent_service.schemas.Verdict

class Expected(BaseModel):
    verdict: Verdict | None = None
    relevant_chunk_ids: list[str] = []
    reference_answer: str | None = None
    must_include: list[str] = []
    must_not_include: list[str] = []
    expect_clarification: bool = False
    expected_tools: list[str] = []          # tool names expected to be called

class EvalCase(BaseModel):
    id: str                                  # unique, kebab-case
    farmer_id: str | None = None
    message: str = Field(min_length=1, max_length=500)   # mirror ChatRequest limits
    tags: list[str] = []
    expected: Expected

class RetrievedChunk(BaseModel):
    chunk_id: str
    similarity: float

class Trace(BaseModel):
    """Everything observed from one agent run of one case."""
    case_id: str
    answer_text: str                         # accumulated tokens / final text
    final_verdict: Verdict | None
    citations: dict[str, str] = {}
    tools_called: list[str] = []             # order preserved
    clarified: bool = False                  # a 'question' event fired
    error: str | None = None
    retrieved: list[RetrievedChunk] = []     # from direct KB call (see trace.py)
    latency_s: float = 0.0
    answer_tokens: int = 0
    lang: str | None = None

class JudgeScore(BaseModel):
    relevance: int                           # 1..5
    correctness: int
    completeness: int
    faithfulness: int
    rationale: str = ""

class CaseResult(BaseModel):
    case: EvalCase
    trace: Trace
    metrics: dict[str, float]                # flat metric_name -> value for this case
    judge: JudgeScore | None = None
    passed: bool                             # all hard asserts (keywords/clarify) satisfied

class RunReport(BaseModel):
    dataset: str
    n_cases: int
    aggregates: dict[str, float]             # metric_name -> aggregate value
    confusion: dict[str, dict[str, int]]     # verdict confusion matrix
    per_case: list[CaseResult]
    thresholds: dict[str, float] = {}
    gate_failures: list[str] = []            # metrics below threshold
    started_at: str
    finished_at: str
```

**Notes:** `EvalCase.message` reuses the same `min_length=1, max_length=500` bound as
`ChatRequest` so no case can be valid for eval but rejected by the API.

---

## `evals/datasets/golden.jsonl`

**Purpose:** Hand-authored labeled cases, one JSON object per line conforming to
`EvalCase`.

**Composition (~25–40 cases) by tag:**

| Category | Count | Key labels |
|---|---|---|
| Grounded happy-path | ~10 | `verdict: PASS`, `relevant_chunk_ids`, `reference_answer`, `must_include` |
| Ambiguous → clarify | ~5 | `expect_clarification: true`, `verdict: null` |
| Out-of-scope / unanswerable | ~5 | `verdict: REJECT`, `must_include: ["KVK"]` |
| Adversarial / safety | ~5 | `must_not_include: ["guaranteed","100%"]` |
| Multilingual | ~3 | `farmer_id` of a farmer with non-English `lang_pref` |
| Anonymous (no farmer_id) | ~3 | `farmer_id: null`, crop/district named in `message` |

**Ground-truth sourcing:** `relevant_chunk_ids` use the deterministic seed IDs —
`icar:crop:{crop}` and `imd:advisory:{district}:{date}` from
`mcp_servers/vector_server/seed.py`. The labeling step (documented in the README below)
requires querying the live DB to confirm each ID exists before committing it.

---

## `evals/datasets/README.md`

**Purpose:** Labeling guide so cases stay valid.

**Contents:** the `EvalCase` field reference; how to discover valid `chunk_id`s
(`SELECT chunk_id FROM knowledge_chunks` or the `list_collections` / `fetch_chunk` MCP
tools); how to pick a `farmer_id` from the `farmers` table (note: only **1 row**
currently in the DB — flag that more farmer rows or anonymous cases are needed for the
multilingual / known-farmer categories); rules (every PASS case must have ≥1
`relevant_chunk_id` and a `reference_answer`).

---

## `evals/targets/__init__.py`

**Purpose:** Define the target abstraction so metrics never depend on *how* a case was
executed.

**Public API:**

```python
class EvalTarget(Protocol):
    async def run(self, case: EvalCase) -> Trace: ...
    async def aclose(self) -> None: ...
```

---

## `evals/targets/in_process.py`

**Purpose:** Execute a case by driving `AgentRunner` directly in-process (the chosen
mode). This is the most important integration file.

**Public API:**

```python
class InProcessTarget(EvalTarget):
    def __init__(self, runner: AgentRunner | None = None,
                 settings: Settings | None = None) -> None: ...
    @classmethod
    async def create(cls) -> "InProcessTarget": ...   # builds + registers MCP tools
    async def run(self, case: EvalCase) -> Trace: ...
    async def aclose(self) -> None: ...
```

**Behavior:**

- `create()`:
  1. `registry = build_builtin_registry()` (from `agent_service.tools.builtin`).
  2. `clients = await discover_and_register(registry, settings.mcp_urls, timeout=settings.mcp_request_timeout_s)`
     — same call `main.py` makes at startup. Requires db-mcp / vector-mcp reachable
     (default `MCP_SERVER_URLS=http://localhost:9101,...` for local; documented).
  3. `runner = AgentRunner(registry=registry, session_store=InMemorySessionStore())`
     — **in-memory sessions** so eval cases don't pollute the Postgres
     `conversation_turns` table and each case is isolated.
  4. Stash `clients` for `aclose()`.
- `run(case)`:
  1. Record `t0` (monotonic).
  2. Use a **fresh `session_id` per case** (pass `None` → runner generates one) so
     there's no cross-case history bleed.
  3. `async for ev in runner.stream(case.farmer_id, case.message, None):` accumulate
     into a `Trace` via `trace.py` helpers — sum `token` deltas into `answer_text`,
     capture `tool_call` names into `tools_called`, set `clarified=True` on `question`,
     capture `verdict` + `citations` on `verdict`, capture final text/lang on `final`,
     capture `error`.
  4. After the stream, set `latency_s`, `answer_tokens` (via
     `agent_service.budget.count_tokens`).
  5. **Retrieval ground truth:** call `query_knowledge_base` *directly* through the
     registry to get untruncated chunk IDs (see `trace.py` rationale) and populate
     `trace.retrieved`.
- `aclose()`: `await c.aclose()` for each MCP client (mirrors `main.py` shutdown).

**Edge cases:** if `discover_and_register` registers zero tools (servers down),
`create()` raises a clear error telling the user to bring the stack up. If a case errors
mid-stream, `trace.error` is set and the case still produces a `CaseResult` (never
crashes the suite).

---

## `evals/trace.py`

**Purpose:** Pure functions to fold a `StreamEvent` sequence into a `Trace`, and to fetch
retrieval ground truth. Kept separate from the target so it's unit-testable with
synthetic events.

**Public API:**

```python
class TraceAccumulator:
    def __init__(self, case_id: str) -> None: ...
    def consume(self, ev: StreamEvent) -> None: ...     # one event
    def finish(self, latency_s: float) -> Trace: ...

async def fetch_retrieved_chunks(
    registry: ToolRegistry, message: str, crop: str | None, top_k: int = 5
) -> list[RetrievedChunk]: ...
```

**Behavior / rationale:**

- `consume` maps `StreamEvent.type` → `Trace` fields.
- `fetch_retrieved_chunks` exists because `runner.py:_preview` **truncates `tool_result`
  to 240 chars**, so chunk IDs aren't recoverable from the stream. It calls the
  registered `query_knowledge_base` tool directly. **Important fidelity note:** the
  runner (`runner.py:139`) calls KB with `crop=profile.crop_variety` and `top_k=5` and
  the **default `collection="icar"`** — this helper must replicate those exact args so
  the retrieval metric reflects what the agent actually retrieves. For anonymous cases
  `crop=""`.
- `count_tokens` reused from `agent_service.budget`.

---

## `evals/metrics/retrieval.py`

**Purpose:** Deterministic retrieval metrics.

**Public API:**

```python
def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float
def precision_at_k(retrieved_ids, relevant_ids, k) -> float
def hit_at_k(retrieved_ids, relevant_ids, k) -> float       # 1.0 if any relevant in top-k
def mrr(retrieved_ids, relevant_ids) -> float               # reciprocal rank of first hit
def retrieval_metrics(trace: Trace, expected: Expected, k: int = 5) -> dict[str, float]
```

**Behavior:** `retrieval_metrics` returns `{}` when `expected.relevant_chunk_ids` is
empty (case isn't a retrieval case → excluded from that aggregate, not counted as 0).
Order taken from `trace.retrieved` (already similarity-ranked by pgvector).

---

## `evals/metrics/grounding.py`

**Purpose:** Verdict correctness.

**Public API:**

```python
def verdict_match(trace: Trace, expected: Expected) -> float | None   # 1.0/0.0, None if no label
def update_confusion(confusion: dict, trace: Trace, expected: Expected) -> None
```

**Behavior:** compares `trace.final_verdict` to `expected.verdict`. `None` when the case
has no labeled verdict (e.g. clarify cases) so it's excluded from accuracy.
`update_confusion` increments a 3×3 `{expected: {predicted: count}}` matrix;
clarify / no-verdict rows bucket under a `"NONE"` key.

---

## `evals/metrics/keywords.py`

**Purpose:** Cheap deterministic content asserts — the safety net.

**Public API:**

```python
def must_include_score(text: str, terms: list[str]) -> float        # fraction present
def must_not_include_violations(text: str, terms: list[str]) -> list[str]
def keyword_pass(trace: Trace, expected: Expected) -> bool          # hard pass/fail
```

**Behavior:** case-insensitive substring matching on `trace.answer_text`. `keyword_pass`
is `False` if any `must_not_include` term appears or any `must_include` term is missing —
this feeds `CaseResult.passed`.

---

## `evals/metrics/behavior.py`

**Purpose:** Clarification, tool-call, and performance metrics.

**Public API:**

```python
def clarification_match(trace: Trace, expected: Expected) -> float   # 1.0 if clarified == expect_clarification
def tool_call_jaccard(trace: Trace, expected: Expected) -> float | None
def behavior_metrics(trace: Trace, expected: Expected) -> dict[str, float]   # + latency_s, answer_tokens
```

**Behavior:** `tool_call_jaccard` returns `None` when `expected_tools` empty.
Latency / tokens passed through for aggregation (p50/p95 computed at report time).

---

## `evals/judge.py`

**Purpose:** LLM-as-judge wrapper over the **existing** `LLMClient` (defaults to LM
Studio — local, zero-cost, the same backend the app uses).

**Public API:**

```python
class Judge:
    def __init__(self, llm: LLMClient | None = None) -> None: ...   # get_default_llm() if None
    async def score(self, case: EvalCase, trace: Trace) -> JudgeScore: ...
```

**Behavior:**

- Builds a rubric prompt: rates **relevance** & **correctness** & **completeness**
  against `expected.reference_answer`, and **faithfulness** against `trace.retrieved` /
  answer (hallucination check). Asks for strict JSON.
- Calls `llm.complete_json(system=JUDGE_SYSTEM, user=..., max_tokens=1024)` and parses
  via the same `_safe_json` tolerance pattern used in
  `agent_service/agent/verifier.py` (handles models that wrap JSON in prose; LM Studio
  client already strips `<think>`).
- On parse failure → returns a `JudgeScore` of all-zeros with
  `rationale="judge parse failure"` (never crashes the suite).
- Judge **system prompt** stored as `evals/prompts/judge_system.md` (mirrors how
  `agent_service/prompts.py` loads `.md` files) — keeps prompt out of code.

**Skipped when:** `expected.reference_answer is None` (e.g. clarify / reject cases) →
`judge=None` on the result.

---

## `evals/prompts/judge_system.md`

**Purpose:** The judge rubric prompt (separate file, like the existing
`prompts/planner_system.md`). Defines the 1–5 scale per dimension and demands JSON-only
output.

---

## `evals/metrics/answer.py`

**Purpose:** Glue between `Judge` and aggregation.

**Public API:**

```python
async def answer_metrics(judge: Judge, case: EvalCase, trace: Trace,
                         repeats: int = 1) -> tuple[JudgeScore | None, dict[str, float]]
```

**Behavior:** runs the judge `repeats` times (default 1), averages the four dimensions,
returns the mean `JudgeScore` plus a metrics dict (`judge_relevance_mean`, …, and
`*_std` when `repeats>1`). Handles non-determinism.

---

## `evals/runner.py`

**Purpose:** Orchestrate a full suite: load dataset → run each case through the target →
compute all metrics → assemble `RunReport`.

**Public API:**

```python
def load_dataset(path: str | Path) -> list[EvalCase]
async def run_suite(
    cases: list[EvalCase],
    target: EvalTarget,
    judge: Judge | None = None,
    tags: list[str] | None = None,
    k: int = 5,
    repeats: int = 1,
) -> RunReport
```

**Behavior:**

- `load_dataset`: parse JSONL → validated `EvalCase` list; raises with line number on a
  bad record.
- `run_suite`: optional tag filter; for each case `trace = await target.run(case)`, then
  run the deterministic metric modules + (if `judge` given and `reference_answer`
  present) `answer_metrics`. Build `CaseResult` (with
  `passed = keyword_pass and clarification ok`). Aggregate: mean of each metric across
  cases where it's defined (skip `None`s), p50/p95 latency, mean tokens, confusion
  matrix, judge means. Stamp `started_at` / `finished_at`.
- Cases run **sequentially** by default (LM Studio is single-instance; concurrency would
  thrash it). A `concurrency` knob can be added later.

---

## `evals/report.py`

**Purpose:** Render a `RunReport` to disk + console.

**Public API:**

```python
def write_json(report: RunReport, out_dir: Path) -> Path        # results.json
def write_markdown(report: RunReport, out_dir: Path) -> Path    # report.md
def print_summary(report: RunReport) -> None                    # console table
def evaluate_gates(report: RunReport, thresholds: dict[str, float]) -> list[str]
```

**Behavior:** `report.md` includes the aggregate table grouped by metric, the verdict
confusion matrix, and a per-case pass/fail list. `evaluate_gates` returns the list of
metrics below threshold (stored in `report.gate_failures`). Output dir is
`results/<timestamp>/` (timestamp passed in from CLI).

---

## `evals/thresholds.yaml`

**Purpose:** Regression gates for CI.

**Contents (initial values, tunable):**

```yaml
recall_at_5: 0.70
verdict_accuracy: 0.80
clarification_match: 0.80
judge_correctness_mean: 3.5
judge_faithfulness_mean: 4.0
keyword_pass_rate: 1.00
```

---

## `evals/cli.py`

**Purpose:** Entry point. `python -m evals.cli run ...`.

**Public API:** `argparse`-based `main()` with a `run` subcommand.

**Flags:** `--dataset`, `--tags`, `--k 5`, `--repeats 1`, `--judge/--no-judge`,
`--judge-backend {lm_studio,anthropic}`, `--out results/`,
`--fail-under evals/thresholds.yaml`.

**Behavior:**

1. `asyncio.run` an async main: `target = await InProcessTarget.create()`;
   `judge = Judge()` unless `--no-judge`.
2. `report = await run_suite(...)`.
3. `write_json` + `write_markdown` + `print_summary`.
4. If `--fail-under` given, load YAML, `evaluate_gates`, **exit code 1** if any gate
   fails (CI integration). Always `await target.aclose()` in `finally`.

**pyproject:** add `[project.optional-dependencies] evals = ["pyyaml>=6"]` (everything
else — httpx, pydantic, structlog — is already a dep). Optionally add
`[project.scripts] agent-evals = "evals.cli:main"`.

---

## `tests/test_evals.py`

**Purpose:** Deterministic unit tests for the metric math — **no DB, no LLM, no
network** (runs in normal `pytest`).

**Coverage:**

- `retrieval`: known retrieved / relevant lists → asserts recall / precision / MRR / hit
  values.
- `grounding`: verdict match + confusion matrix updates.
- `keywords`: include / exclude logic incl. case-insensitivity.
- `behavior`: clarification + Jaccard + `None`-when-unlabeled.
- `trace.TraceAccumulator`: feed a synthetic `StreamEvent` sequence
  (phase → tokens → tool_call → verdict → final) and assert the resulting `Trace`.
- `judge`: monkeypatch a fake `LLMClient` returning canned JSON → assert `JudgeScore`
  parsing + parse-failure fallback.
- `runner.run_suite`: a stub `EvalTarget` returning fixed traces → assert aggregates /
  gate logic. (Proves the whole pipeline without external services.)

---

## `RUNBOOK.md` (append a section)

**Purpose:** Document operation.

**Contents:** prerequisites (`docker compose up -d`, confirm `knowledge_chunks` seeded
via `list_collections`), the `python -m evals.cli run ...` invocation, how to read
`results/`, how to add a case (links to `datasets/README.md`), and the CI gate usage.

---

## Dependency / integration summary

What the harness touches in `agent_service`:

| Used | From |
|---|---|
| `AgentRunner`, `.stream()` | `agent_service.agent.runner` |
| `build_builtin_registry`, `ToolRegistry` | `agent_service.tools.*` |
| `discover_and_register` | `agent_service.tools.mcp_client` |
| `InMemorySessionStore` | `agent_service.session` |
| `get_settings`, `Settings` | `agent_service.config` |
| `get_default_llm`, `LLMClient` | `agent_service.llm` |
| `count_tokens` | `agent_service.budget` |
| `StreamEvent`, `Verdict` | `agent_service.schemas` |

**No changes to `agent_service` are required** — the only friction point (truncated
`tool_result` previews) is sidestepped by the direct `query_knowledge_base` call in
`trace.py`. If you'd later prefer the harness to read retrieval straight from the
stream, that would need a small `trace=True` flag on the runner; flagged as optional,
not in this spec.

---

## Phased rollout

1. **Schema + dataset** — `schema.py` + `datasets/golden.jsonl` (seed cases) +
   `datasets/README.md`.
2. **Targets + trace** — `targets/in_process.py` + `trace.py` (with the direct
   `query_knowledge_base` call for retrieval, **no runner changes**).
3. **Deterministic metrics** — `metrics/{retrieval,grounding,behavior,keywords}.py` +
   `report.py` + `cli.py` → **working harness, no LLM yet**.
4. **LLM-as-judge** — `judge.py` + `prompts/judge_system.md` + `metrics/answer.py`.
5. **Gates + tests + docs** — `thresholds.yaml`, `tests/test_evals.py`, RUNBOOK
   section.

Each phase is independently runnable; phase 3 already gives a working harness.

---

## Summary

**18 files** total: 12 Python modules, 1 JSONL dataset, 2 docs, 1 prompt, 1 YAML, plus
`pyproject.toml` / `RUNBOOK.md` edits.
</content>
</invoke>
