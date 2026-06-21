# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CropCompass — an agentic farm-advisory backend. A four-phase planner (Gather → Generate
→ Verify → Translate) answers farmer questions, grounded in a Postgres + pgvector
knowledge base reached through MCP tool servers, with token-by-token streaming.

## Commands

```bash
# Full stack (Postgres + 2 MCP servers + agent), Dockerized
./up.sh                       # idempotent bring-up: build, up -d, wait for /health
docker compose up -d          # same, without the health wait
docker compose down           # stop
docker compose down -v        # stop AND drop the DB volume (next up reseeds from dump)
docker compose logs -f agent  # tail agent logs (JSON structured)

# Tests (local, no Docker; needs the package installed in a venv)
pip install -e ".[dev]"       # or: uv pip install --system -e ".[dev]"
pytest -q                     # unit tests; LM Studio integration tests auto-skip
pytest tests/test_verifier.py::test_apply_verdict_reject   # single test
LM_STUDIO_MODEL=<model> pytest -q   # include the live LM Studio integration tests

# Run a service standalone (without Docker), from repo root
uvicorn agent_service.main:app --port 8000
uvicorn mcp_servers.db_server.server:app --port 9101
uvicorn mcp_servers.vector_server.server:app --port 9102

# DB access
docker exec agent-db psql -U cropcompass -d cropcompass -c "\dt"
```

There is no linter configured. `pytest` is configured in `pyproject.toml` with
`pythonpath = ["src", "."]` and `asyncio_mode = "auto"` — async tests need no decorator.

## Git workflow

**Auto-checkpoint at each phase DoD.** When a phase's Definition of Done is *verified
green*, immediately create a commit capturing that phase's work — this is
**pre-authorized for the session**, so commit without asking each time. Each phase
boundary becomes a clean, revertible checkpoint.

The concrete phased work in this repo is the **eval harness rollout** (the five-phase
plan in `EVAL_HARNESS_SPEC.md` → "Phased rollout"). Treat each numbered phase there as a
checkpoint boundary. Work that isn't part of a numbered phase (the agent service itself,
ops fixes, docs) uses ordinary Conventional Commits at each verified-green milestone.

- **Trigger** — the DoD is *verified* (tests pass / smoke run / the check actually
  succeeded), not merely "code written." No green, no commit. For the eval harness,
  "green" means the relevant `pytest tests/test_evals.py` and/or a `python -m evals.cli
  run` succeeded; for the agent service, the relevant `pytest` slice passes (and, when
  the change is runtime behavior, a `docker compose up` / `curl /health` smoke check).
- **One commit per phase** — stage all files belonging to that phase's slice. Mid-phase
  WIP commits are fine for long phases, but the DoD commit is the checkpoint that counts.
- **Message format** — for phased eval-harness work:
  `phase-N(<short-name>): <what + why>`, e.g.
  `phase-3(metrics): deterministic retrieval+grounding metrics; None-skips unlabeled cases`.
  For everything else, Conventional Commits (`feat(...)`, `fix(...)`, `docs(...)`,
  `chore(...)`) — matching this repo's existing history. End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Branch** — commit directly on the active working branch (currently
  `agentic_solution`); this is a solo classroom repo, so branch history is part of the
  deliverable. Branch off only for a genuinely exploratory spike, then merge back.
- **Push** — **never automatic.** Pushing is outward-facing; only when the user
  explicitly asks. Use `gh` for any GitHub/PR operations.
- **Out-of-phase changes** — spec/decision edits made outside a numbered phase (e.g.
  editing `EVAL_HARNESS_SPEC.md` or this file) get their own `docs(...)` checkpoint
  commit rather than riding along with phase code.

## Architecture (the big picture)

Three **independent FastAPI apps** run as separate containers, plus Postgres:

- `agent` (:8000) — the orchestrator. Does NOT hard-code DB access.
- `db-mcp` (:9101) — 7 read-only Postgres tools behind JSON-RPC.
- `vector-mcp` (:9102) — 3 pgvector semantic-search tools behind JSON-RPC.

**Tool discovery is dynamic.** On startup (`main.py` → `discover_and_register`), the
agent calls `tools/list` on each URL in `MCP_SERVER_URLS`, wraps every remote tool as a
`ToolSpec` whose `fn` does an HTTP `tools/call`, and registers it in the shared
`ToolRegistry`. The runner cannot tell remote MCP tools from the one local tool
(`translate_output`) — that indistinguishability is the core design. If `GET /tools`
shows only `translate_output`, MCP discovery failed (servers down / wrong URLs).

**The four-phase flow lives entirely in `agent/runner.py:_run`**, an async generator
yielding `StreamEvent`s (consumed by `/api/chat`, `/sse/chat`, `/ws/chat` — all the same
runner):
- **A. Gather** — three *fixed, non-LLM* tool calls: `get_farmer_profile` (skipped when
  no `farmer_id` → anonymous profile), `fetch_latest_advisory`, `query_knowledge_base`.
- **B. Generate** — planner LLM tool-use loop (up to `max_planner_iterations`, default
  6). Streams `token` events. If the model emits `CLARIFY: <question>` it stops and
  emits a `question` event; the next user message continues the dialogue. The planner
  gets all tools *except* `translate_output`.
- **C. Verify** — `agent/verifier.py` asks the LLM for `{verdict, unsupported_claims,
  supporting_citations}`. `apply_verdict` then: PASS → unchanged; PARTIAL → strips
  unsupported sentences + disclaimer; REJECT (or empty after stripping) → safe KVK
  fallback. This is the anti-hallucination gate every answer passes through.
- **D. Translate** — local `translate_output` tool → IndicTrans2 via HuggingFace
  (no-op for English; needs `HF_API_KEY`).

**Two pluggable abstractions** keep the runner backend-agnostic:
- LLM (`llm/`): `get_default_llm()` picks `anthropic` or `lm_studio` from `LLM_BACKEND`
  (falls back to LM Studio if no `ANTHROPIC_API_KEY`). `LMStudioLLM` transparently
  converts Anthropic ↔ OpenAI message/tool formats AND strips `<think>…</think>` blocks
  mid-stream, so the rest of the code is written once against the Anthropic-style
  `LLMClient` protocol.
- Sessions (`session.py`): `SESSION_BACKEND=memory|postgres`. Postgres persists turns in
  `conversation_turns` (same DB); history is loaded/saved per `session_id` each turn.

**Tools never raise.** `ToolSpec.__call__` and the MCP dispatcher catch everything and
return `{"error": "..."}`. Callers branch on the `"error"` key, never on exceptions.

`ToolSpec` (`tools/base.py`) is the single source of truth for a tool; MCP servers use a
parallel `MCPToolRegistry` + `mount_mcp` (`mcp_server_lib.py`) that wraps handlers in a
JSON-RPC 2.0 envelope at `/mcp`.

## Data & seeding (easy to get wrong)

- The DB dump must live at `db/cropcompass_dump.sql`. docker-compose bind-mounts it (plus
  `vector_server/schema.sql` and `db/conversations.sql`) into
  `/docker-entrypoint-initdb.d/`. **Postgres runs these only on a fresh volume** — if the
  file is missing at first boot Docker creates an empty *directory* in its place and no
  data loads. To reload after fixing: `docker compose down -v` then `up`.
- `knowledge_chunks` starts empty and is **auto-seeded on vector-mcp's first boot**
  (`vector_server/seed.py`) from `crop_water_requirements.notes` and latest
  `imd_advisories`, embedded with sentence-transformers. Seed `chunk_id`s are
  deterministic: `icar:crop:{crop}` and `imd:advisory:{district}:{date}`.

## Gotchas

- **LM Studio from inside Docker uses `host.docker.internal:1234`, not `127.0.0.1`.**
  docker-compose already sets this; the `127.0.0.1` in `.env` is only for non-Docker runs.
- `mcp_servers/Dockerfile` installs **CPU-only torch first** (`--index-url
  .../whl/cpu`) before `sentence-transformers`. Do not remove this — the default Linux
  torch pulls multi-GB CUDA libraries that are useless here and blow up the build.
- `DATABASE_URL` is normalized everywhere (`postgresql+asyncpg://` / `+psycopg2://` →
  `postgresql://`) because asyncpg needs the bare scheme.
- `pyproject.toml` packages **both** `src/agent_service` and `mcp_servers` into the wheel;
  MCP server code imports `agent_service.mcp_server_lib`, so the agent package must be
  installed for the MCP servers to run.

## Adding a tool

In-process: build a `ToolSpec` and `runner.registry.register(it)` after the runner is
created in `main.py`. As an MCP server: use `MCPToolRegistry` + `mount_mcp`, add the
service to docker-compose, and append its URL to `MCP_SERVER_URLS` — the agent
auto-discovers it. See README.md "Adding a tool" for full snippets.

## Reference docs

- `README.md` — quickstart, API examples, LLM backend switching, streaming clients.
- `RUNBOOK.md` — detailed ops: env vars, session backends, deployment.
- `EVAL_HARNESS_SPEC.md` — proposed (not yet built) evaluation harness design.
</content>
