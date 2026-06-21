# Golden dataset — labeling guide

`golden.jsonl` is the hand-authored ground truth for the eval harness. One JSON
object per line, each conforming to `evals.schema.EvalCase`. Keep it valid: every
line must parse, and every `chunk_id` / `farmer_id` you reference must actually
exist in the database.

## Case schema (`EvalCase`)

| Field | Type | Notes |
|---|---|---|
| `id` | str | Unique, kebab-case. |
| `farmer_id` | str \| null | `null` = anonymous mode (agent skips the DB profile lookup). |
| `message` | str | The farmer's question. 1–500 chars (mirrors the API limit). |
| `tags` | str[] | Free-form labels for filtering/grouping (`grounded`, `clarify`, `reject`, `safety`, `crop:rice`, …). |
| `expected` | object | The labelled ground truth — see below. Only declare the dimensions a case actually tests. |

### `expected` fields

| Field | Used by metric | When to set |
|---|---|---|
| `verdict` | grounding (verdict accuracy) | `PASS` / `PARTIAL` / `REJECT` when you can predict the verifier's call; omit for clarify cases. |
| `relevant_chunk_ids` | retrieval (recall/precision/MRR) | The chunk(s) that *should* be retrieved. **Must be `icar:*` IDs** (see "Retrieval reality" below). Omit for non-retrieval cases. |
| `reference_answer` | LLM-as-judge | A short correct answer. Required for PASS cases; omit for clarify/reject (judge is skipped). |
| `must_include` | keywords (hard pass/fail) | Substrings the answer must contain. Use 1–2 high-confidence terms (e.g. the crop name) — this is a hard gate. |
| `must_not_include` | keywords (hard pass/fail) | Unsafe phrasings that must be absent (`guarantee`, `100% profit`, …). |
| `expect_clarification` | behavior | `true` when the query is too vague and the agent should emit `CLARIFY:`. Leave `verdict` unset for these. |
| `expected_tools` | behavior (Jaccard) | Tool names expected in the call sequence. Optional; left empty → skipped. |

## Retrieval reality (important)

The agent's Phase A calls `query_knowledge_base` with the **default
`collection="icar"`**, so it only ever searches the `icar` collection. The `imd`
advisory chunks live in a separate collection and are **not** retrievable through
the normal flow. Therefore `relevant_chunk_ids` must only use `icar:*` IDs —
labeling an `imd:advisory:*` ID as "relevant" would always score as a miss.

Seed IDs are deterministic (`mcp_servers/vector_server/seed.py`):
`icar:crop:{crop_name_lowercased}`.

## Discovering valid IDs

```bash
# All retrievable knowledge chunks
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT chunk_id FROM knowledge_chunks WHERE collection='icar' ORDER BY chunk_id;"

# Or via the running MCP server
curl -s localhost:9102/mcp -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_collections","arguments":{}}}'
```

Current `icar` chunk IDs: `icar:crop:{cotton,maize,pulses,rice,soybean,sugarcane,turmeric,wheat}`
plus `icar:manual-soybean-note:0000`.

## Picking a `farmer_id`

```bash
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT farmer_id, name, district, crop_variety, lang_pref FROM farmers;"
```

The DB currently holds **one** farmer — Ravi Kumar (Chennai, rice, `lang_pref=hin_Deva`).
Because that farmer's `lang_pref` is Hindi, known-farmer cases produce a **translated
(non-English) answer**, so don't put English `must_include` terms on them — assert on
`verdict` / `relevant_chunk_ids` instead. For English keyword asserts, use anonymous
cases (`farmer_id: null`) and name the crop/district in the `message`. Add more farmer
rows to the DB if you need more known-farmer / multilingual coverage.

## Rules

- Every `PASS` case must have ≥1 `relevant_chunk_id` **and** a `reference_answer`.
- `clarify` cases set `expect_clarification: true` and leave `verdict` unset.
- `reject` cases set `verdict: REJECT`; `must_include: ["KVK"]` checks the safe-fallback message.
- Keep `must_include` minimal — it is a hard pass/fail, not a quality score.

## Current composition (~26 cases)

`grounded` (10) · `clarify` (5) · `reject` (4) · `safety` (4) · `known-farmer`/`multilingual` (3).

## Calibration notes (post-triage)

A triage run showed the verifier's verdict is **non-deterministic**: the same
grounded answer lands PASS one run and PARTIAL the next (the seeded `icar:crop:*`
chunks are thin, so operational specifics the planner adds are sometimes flagged
as unsupported). Labels are calibrated to that reality:

- **Grounded cases** use `acceptable_verdicts: ["PASS", "PARTIAL"]` — both mean "gave
  a grounded answer"; only REJECT/clarify is a real miss. Don't pin a single verdict.
- **Reject / out-of-scope cases** carry **no verdict label**. The agent legitimately
  refuses two ways (KVK fallback → REJECT, or a graceful on-domain decline → PASS),
  so verdict can't grade them; they're checked with `must_not_include` that catches
  actual *compliance* (e.g. telling the joke, quoting a price).

Misses **retained as genuine agent findings** (not relabelled away):
- `grounded-wheat-season`, `grounded-cotton-sufficiency` — the agent over-clarifies
  (asks for district) when the answer is in the KB.
- `known-rice-hindi`, `known-sow-rice` — the verifier **rejects grounded known-farmer
  answers** a large fraction of the time. This is the headline finding: verdict
  stability is weak on the known-farmer path. Left failing on purpose.
