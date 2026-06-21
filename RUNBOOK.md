# CropCompass Agent Service — Runbook

> **What is this?**
> A production-ready agentic backend for CropCompass. 4-phase planner
> (Gather → Generate → Verify → Translate), two MCP servers (Postgres reads +
> pgvector semantic search), token-by-token streaming. Dockerized. No mocks.

---

## Table of Contents

1. [Architecture at a Glance](#1-architecture-at-a-glance)
2. [Prerequisites](#2-prerequisites)
3. [Environment Setup](#3-environment-setup)
4. [Running with Docker (Recommended)](#4-running-with-docker-recommended)
5. [Running Locally (No Docker)](#5-running-locally-no-docker)
6. [Verify the Stack is Alive](#6-verify-the-stack-is-alive)
7. [Calling the API](#7-calling-the-api)
8. [Streaming (SSE & WebSocket)](#8-streaming-sse--websocket)
9. [Session Management](#9-session-management)
10. [Switching LLM Backends](#10-switching-llm-backends)
11. [Loading Knowledge into the Vector MCP](#11-loading-knowledge-into-the-vector-mcp)
12. [Adding a Tool](#12-adding-a-tool)
13. [Adding an MCP Server](#13-adding-an-mcp-server)
14. [Running Tests](#14-running-tests)
15. [Deploying](#15-deploying)
16. [Logs & Debugging](#16-logs--debugging)
17. [Reset / Wipe](#17-reset--wipe)
18. [Quick-Reference Cheat Sheet](#18-quick-reference-cheat-sheet)

---

## 1. Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│                      agent (port 8000)                  │
│   FastAPI · AgentRunner · 4-phase planner · streaming   │
└────────────────┬───────────────────┬────────────────────┘
                 │ JSON-RPC 2.0      │ JSON-RPC 2.0
        ┌────────▼────────┐  ┌───────▼───────────┐
        │  db-mcp (9101)  │  │ vector-mcp (9102) │
        │  7 read tools   │  │  semantic search  │
        │  on Postgres    │  │  via pgvector     │
        └────────┬────────┘  └───────┬───────────┘
                 └──────────┬────────┘
                    ┌───────▼──────┐
                    │  db (5432)   │
                    │ Postgres 15  │
                    │ + pgvector   │
                    └──────────────┘
```

| Service      | Port | Responsibility |
|-------------|------|----------------|
| `db`         | 5432 | Postgres 15 + pgvector. Auto-loads `cropcompass_dump.sql` on first boot. |
| `db-mcp`     | 9101 | MCP server — 7 read-only tools against the cropcompass DB. |
| `vector-mcp` | 9102 | MCP server — semantic search. Auto-seeds `knowledge_chunks` on first boot. |
| `agent`      | 8000 | The agent. Auto-discovers tools from both MCP servers on startup. |

---

## 2. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Docker Desktop | ≥ 24 | `docker --version` |
| Docker Compose | ≥ 2.20 | `docker compose version` |
| Python (local dev only) | ≥ 3.11 | `python3 --version` |
| uv (local dev only) | latest | `uv --version` |

---

## 3. Environment Setup

```bash
cd /Users/r0c0hjm/learning/corpcomall/agent_service
cp .env.example .env
```

Open `.env` and choose a backend — **you only need one**:

```bash
# Option A — Production (Anthropic Claude, paid API key required)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxx

# Option B — Local testing (LM Studio, FREE, no key, no internet)
# See Section 10 for setup instructions.
LLM_BACKEND=lm_studio
LM_STUDIO_BASE_URL=http://localhost:1234
LM_STUDIO_MODEL=lmstudio-community/Llama-3.1-8B-Instruct-GGUF
```

> **Auto-detection:** if `ANTHROPIC_API_KEY` is not set, the agent automatically
> falls back to LM Studio.

All available env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BACKEND` | `anthropic` | `anthropic` \| `lm_studio` |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic` backend |
| `LM_STUDIO_BASE_URL` | `http://localhost:1234` | LM Studio server URL |
| `LM_STUDIO_MODEL` | `local-model` | Model identifier (copy from LM Studio UI) |
| `MCP_SERVER_URLS` | — | Comma-separated MCP base URLs (auto-set in Docker) |
| `SESSION_BACKEND` | `memory` | `memory` or `postgres` |
| `DATABASE_URL` | — | Postgres connection string |
| `ALLOWED_ORIGINS` | `*` | CORS origins |
| `MAX_PLANNER_ITERATIONS` | `6` | Max agent loop turns |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## 4. Running with Docker (Recommended)

### One command to rule them all

```bash
cd agent_service
./up.sh
```

`up.sh` will:
1. Create `.env` from `.env.example` if it doesn't exist
2. Build all images
3. Start all 4 services in dependency order: `db` → `db-mcp` → `vector-mcp` → `agent`
4. Wait until `GET /health` returns 200
5. Print all the URLs

**First boot takes 3–5 minutes** — Postgres loads the SQL dump, and the vector MCP
downloads `sentence-transformers/all-MiniLM-L6-v2` and embeds ~200 chunks.

### Or use docker compose directly

```bash
# Build + start in foreground (see all logs)
docker compose up --build

# Build + start in background
docker compose up --build -d

# Rebuild just one service
docker compose build agent
docker compose up -d agent
```

---

## 5. Running Locally (No Docker)

```bash
# Set up venv
cd agent_service
uv venv && source .venv/bin/activate
uv pip install -e ".[mcp-servers,dev]"

# Start Postgres from Docker only
docker compose up db -d

# Terminal 1 — DB MCP
DATABASE_URL=postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass \
  uvicorn mcp_servers.db_server.server:app --port 9101 --reload

# Terminal 2 — Vector MCP
DATABASE_URL=postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass \
  uvicorn mcp_servers.vector_server.server:app --port 9102 --reload

# Terminal 3 — Agent
MCP_SERVER_URLS=http://localhost:9101,http://localhost:9102 \
SESSION_BACKEND=postgres \
DATABASE_URL=postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass \
ANTHROPIC_API_KEY=sk-ant-... \
  uvicorn agent_service.main:app --port 8000 --reload
```

> **Tip:** `--reload` restarts on every file save. Great for dev, never for prod.

---

## 6. Verify the Stack is Alive

```bash
# 1. Agent health
curl http://localhost:8000/health
# → {"status": "ok"}

# 2. What tools does the agent have? (should list 11 tools)
curl http://localhost:8000/tools | python3 -m json.tool | grep '"name"'
# → "translate_output", "get_farmer_profile", "fetch_latest_advisory",
#   "fetch_seasonal_outlook", "fetch_historical_rainfall",
#   "get_crop_water_requirement", "list_districts", "fetch_district_summary",
#   "query_knowledge_base", "fetch_chunk", "list_collections"

# 3. Grab a real farmer_id from the seeded DB
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT farmer_id, name, district, crop_variety FROM farmers LIMIT 5;"

# 4. Check vector DB has data
curl -s -X POST http://localhost:9102/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_collections","arguments":{}}}' \
  | python3 -m json.tool
```

---

## 7. Calling the API

### POST `/api/chat` — one-shot REST

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{
    "farmer_id": "<uuid-from-step-3-above>",
    "message": "When should I sow soybean?",
    "session_id": "my-session-1"
  }' | python3 -m json.tool
```

**Response shape:**

```json
{
  "text": "Sow your soybean JS-335 between 15 June and 15 July...",
  "lang": "hin_Deva",
  "verdict": "PASS",
  "citations": { "Sow now": "icar:crop:soybean" },
  "session_id": "my-session-1"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Translated answer in farmer's language |
| `lang` | string | BCP-47 language code |
| `verdict` | `"PASS"` \| `"FAIL"` | Verifier output |
| `citations` | object | Source references used by the agent |
| `session_id` | string | Echo of the session used |

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness — `{"status":"ok"}` |
| `/tools` | GET | All registered tools (Anthropic spec) |
| `/api/chat` | POST | One-shot REST chat |
| `/api/session/{id}` | DELETE | Clear conversation history |
| `/ws/chat` | WS | Token-streaming WebSocket |
| `/sse/chat` | GET | Token-streaming SSE |

---

## 8. Streaming (SSE & WebSocket)

### Server-Sent Events — `/sse/chat`

```bash
curl -N --get http://localhost:8000/sse/chat \
  --data-urlencode 'farmer_id=<uuid>' \
  --data-urlencode 'message=When should I sow soybean?' \
  --data-urlencode 'session_id=stream-session-1'
```

**JavaScript client:**

```js
const es = new EventSource(
  `/sse/chat?farmer_id=${id}&message=${encodeURIComponent(msg)}&session_id=s1`
);
es.addEventListener("token", (e) => appendToken(JSON.parse(e.data).data.delta));
es.addEventListener("final", (e) => { es.close(); render(JSON.parse(e.data).data); });
es.addEventListener("error", (e) => console.error(JSON.parse(e.data).data));
```

### WebSocket — `/ws/chat`

```js
const ws = new WebSocket(`ws://localhost:8000/ws/chat`);
ws.onopen = () => ws.send(JSON.stringify({
  farmer_id: id, message: msg, session_id: "s1"
}));
ws.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  if (evt.type === "token")    appendToken(evt.data.delta);
  if (evt.type === "final")    render(evt.data);
  if (evt.type === "question") showFollowUpBubble(evt.data.text); // agent asks for clarification
};
```

**Event types (both transports):**

| Event | When |
|-------|------|
| `phase` | Agent enters a new planner phase |
| `tool_call` | Agent is calling a tool |
| `tool_result` | Tool returned a result |
| `token` | One streamed text token |
| `verdict` | Verifier result (`PASS`/`FAIL`) |
| `question` | Agent is asking the farmer a clarifying question |
| `final` | Full response ready; stream ends |
| `error` | Something went wrong |

---

## 9. Session Management

The agent stores conversation history so follow-up questions just work.

```bash
# Memory backend (default locally) — lost on restart
SESSION_BACKEND=memory

# Postgres backend (default in Docker) — survives restarts
SESSION_BACKEND=postgres
DATABASE_URL=postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass
```

Send multiple messages with the **same `session_id`** — the agent remembers prior turns.
Inspect history:
```bash
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT role, LEFT(content, 60) FROM conversation_turns WHERE session_id='s1' ORDER BY id;"
```

---
## 10. Switching LLM Backends

The agent supports two backends. Switching is **env vars only** — no code changes,
no rebuild required. Just edit `.env` and restart the agent.

---

### Option A — Anthropic (production)

**Step 1 — Get an API key**

Go to https://console.anthropic.com -> API Keys -> Create Key.  
Copy the key (starts with `sk-ant-...`).

**Step 2 — Update `.env`**

```env
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx

# Optional: override model (default is claude-sonnet-4-5)
# ANTHROPIC_MODEL=claude-opus-4-5

# LM Studio lines can stay in the file -- they are ignored when backend=anthropic
```

**Step 3 — Restart the agent**

```bash
docker compose restart agent
```

**Step 4 -- Confirm**

```bash
docker compose logs agent 2>&1 | grep ANALYZE
# [ANALYZE] Using Anthropic backend
```

---

### Option B -- LM Studio (local dev, free, no API key)

**Step 1 -- Install and configure LM Studio (one-time)**

1. Download [LM Studio](https://lmstudio.ai) (free, Mac/Win/Linux)
2. Load a model with **tool/function calling** support:
   - `qwen/qwen3-coder-30b` (tested, works well)
   - `Qwen2.5-7B-Instruct`
   - `Llama-3.1-8B-Instruct`
   - `Mistral-Nemo-Instruct-2407`
3. Go to **Server -> Start Server** -- leave the port at **1234**
4. Copy the model identifier from the LM Studio UI

**Step 2 -- Verify LM Studio is serving**

```bash
curl http://localhost:1234/v1/models | python3 -m json.tool
# Should list your loaded model
```

**Step 3 -- Update `.env`**

```env
LLM_BACKEND=lm_studio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=qwen/qwen3-coder-30b    # paste the name shown in LM Studio
```

**Step 4 -- Restart the agent**

```bash
docker compose restart agent
```

**Step 5 -- Confirm**

```bash
docker compose logs agent 2>&1 | grep ANALYZE
# [ANALYZE] Using LM Studio backend  url=http://host.docker.internal:1234  model=qwen/qwen3-coder-30b
```

> **Docker networking note:** Inside the agent container, LM Studio is reachable
> at `http://host.docker.internal:1234`, not `127.0.0.1`. The `docker-compose.yml`
> already overrides the URL to `host.docker.internal` for the agent service, so
> your `.env` value of `127.0.0.1` is only used for local (non-Docker) runs.

**Run LM Studio integration tests**

```bash
LM_STUDIO_MODEL=qwen/qwen3-coder-30b pytest tests/test_lm_studio.py -v
```

---

### Quick comparison

| Setting | LM Studio | Anthropic |
|---|---|---|
| `LLM_BACKEND` | `lm_studio` | `anthropic` |
| API key needed | No | Yes -- `ANTHROPIC_API_KEY=sk-ant-...` |
| LM Studio must be running | Yes | No |
| Cost | Free | Pay per token |
| Quality | Depends on loaded model | Best (Claude Sonnet / Opus) |
| Model override | `LM_STUDIO_MODEL=<name>` | `ANTHROPIC_MODEL=claude-opus-4-5` |
| Auto-fallback (no key set) | Falls back to `lm_studio` | N/A |

---

### Note on thinking models (Qwen3, DeepSeek-R1, etc.)

Reasoning models emit `<think>...</think>` blocks before their actual answer.
The LM Studio client handles this automatically:
- **Streaming:** thinking-block tokens are suppressed before they reach the draft
- **JSON completion (verifier):** `_strip_thinking()` removes blocks before parsing
- **`response_format: json_object`** is sent with every `complete_json` call to
  force valid JSON output; gracefully falls back if the server rejects it

---

## 11. Loading Knowledge into the Vector MCP

The vector MCP auto-seeds on first boot from crop notes + IMD advisories in the dump.
To load more:

### Option A — Plain text

```bash
docker exec agent-vector-mcp python -m mcp_servers.vector_server.loader \
  --text "Soybean JS-335 sowing window is 15 June to 15 July for Vidarbha. Seed rate: 75 kg/ha." \
  --collection icar \
  --source "manual-soybean-note"
```

### Option B — PDF or text files

```bash
# Single file
docker exec agent-vector-mcp python -m mcp_servers.vector_server.loader \
  --file /path/to/handbook.pdf --collection icar

# Whole folder (add --replace to overwrite existing chunks)
docker exec agent-vector-mcp python -m mcp_servers.vector_server.loader \
  --dir /data/icar_docs --collection icar --replace
```

Mount a local folder in `docker-compose.yml`:

```yaml
vector-mcp:
  volumes:
    - /your/local/pdfs:/data/icar_docs:ro
```

### Check what's loaded

```bash
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT collection, COUNT(*), MIN(created_at) FROM knowledge_chunks GROUP BY collection;"
```

### Force re-seed

```bash
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "TRUNCATE knowledge_chunks;"
docker restart agent-vector-mcp
```

---

## 12. Adding a Tool

### In-process tool (pure Python, no new server)

```python
# src/agent_service/extras.py
from agent_service.tools.base import ToolSpec

async def list_mandi_prices(commodity: str, district: str) -> dict:
    # async, returns dict, never raises
    return {"min": 4200, "max": 4650, "modal": 4480}

MANDI = ToolSpec(
    name="list_mandi_prices",
    description="Today's APMC mandi prices for a commodity in a district.",
    input_schema={
        "type": "object",
        "properties": {
            "commodity": {"type": "string"},
            "district":  {"type": "string"},
        },
        "required": ["commodity", "district"],
    },
    fn=list_mandi_prices,
)
```

Register it in `src/agent_service/main.py` right after `runner = AgentRunner(...)`:

```python
from .extras import MANDI
runner.registry.register(MANDI)
```

Restart the agent — the tool is live immediately.

---

## 13. Adding an MCP Server

```python
# mcp_servers/my_server/server.py
from fastapi import FastAPI
from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp

reg = MCPToolRegistry()

@reg.tool(
    name="get_widget",
    description="Fetch a widget by ID.",
    input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
)
async def _get_widget(id: str) -> dict:
    return {"id": id, "name": "My Widget"}

app = FastAPI()
mount_mcp(app, reg)
```

Add to `docker-compose.yml`:

```yaml
my-mcp:
  build: { context: ., dockerfile: mcp_servers/Dockerfile }
  command: uvicorn mcp_servers.my_server.server:app --host 0.0.0.0 --port 9200
  ports: ["9200:9200"]
  depends_on:
    db: { condition: service_healthy }
```

Extend `MCP_SERVER_URLS` in the `agent` service env:

```yaml
MCP_SERVER_URLS: http://db-mcp:9101,http://vector-mcp:9102,http://my-mcp:9200
```

Run `./up.sh` — the agent auto-discovers every tool the new server exposes. Done.

> **Third-party MCP server?** Just append its URL to `MCP_SERVER_URLS`. No code changes.

---

## 14. Running Tests

No Docker, no API keys needed:

```bash
cd agent_service && source .venv/bin/activate
pytest -q
# 25 passed, 4 skipped (skipped = optional extras: langchain-core, google-adk)

pytest tests/test_tools.py -v   # specific file
```

---

## 15. Deploying

| Target | How |
|--------|-----|
| **Any VM** | `scp` repo + `.env`, run `./up.sh` |

**Liveness probes:** `GET /health` on all three services (agent, db-mcp, vector-mcp).

**MCP sanity check:**
```bash
curl http://localhost:8000/tools | jq '.tools | length'
# Should be 11. If it's 1, MCP_SERVER_URLS is wrong or MCPs aren't reachable
# (check agent logs for mcp.discover.failed)
```

---

## 16. Logs & Debugging

```bash
# All services
docker compose logs -f

# Just the agent
docker compose logs -f agent

# Just the vector MCP (seeding logs here on first boot)
docker compose logs -f vector-mcp

# Just the DB MCP
docker compose logs -f db-mcp

# Increase verbosity (edit .env or pass inline)
LOG_LEVEL=DEBUG docker compose up agent
```

Structured JSON logs (structlog). Pipe through `jq` for readability:

```bash
docker compose logs -f agent | jq -r '"\(.timestamp) [\(.level)] \(.event)"'
```

---

## 17. Reset / Wipe

```bash
# Stop all services, keep the DB volume (data survives)
docker compose down

# Stop all services AND wipe the DB (next boot reloads from the dump)
docker compose down -v

# Restart just the agent (e.g. after a code change + rebuild)
docker compose build agent && docker compose up -d agent

# Re-seed vector knowledge only (no full wipe)
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "TRUNCATE knowledge_chunks;"
docker restart agent-vector-mcp
```

---

## 18. Quick-Reference Cheat Sheet

```bash
# Lifecycle
./up.sh                                      # start everything
docker compose up --build                    # start (foreground logs)
docker compose down                          # stop, keep data
docker compose down -v                       # stop + wipe DB
docker compose restart agent                 # restart agent only
docker compose logs -f [agent|vector-mcp]    # tail logs

# Health & tools
curl http://localhost:8000/health
curl http://localhost:8000/tools | jq '.tools[].name'

# Get a farmer ID
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT farmer_id, name FROM farmers LIMIT 5;"

# Chat
curl -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"farmer_id":"<id>","message":"When to sow soybean?","session_id":"s1"}'

# Stream
curl -N --get http://localhost:8000/sse/chat \
  --data-urlencode 'farmer_id=<id>' --data-urlencode 'message=...' --data-urlencode 'session_id=s1'

# Session & tests
curl -X DELETE http://localhost:8000/api/session/s1
pytest -q   # inside .venv

# Load knowledge
docker exec agent-vector-mcp python -m mcp_servers.vector_server.loader \
  --text "..." --collection icar
```
