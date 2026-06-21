# agent-service

CropCompass agent in a box. 4-phase planner (Gather → Generate → Verify → Translate),
two MCP servers (Postgres reads + ChromaDB knowledge search), token-by-token streaming.
No mocks. Dockerized. Deploy in one command.

---

## Architecture

```
POST /api/chat  or  GET /sse/chat
        │
   AgentRunner._run()
        │
   Phase A ── Gather ──────────────────────────────────────┐
   │   get_farmer_profile       (db-mcp  → Postgres :5432) │
   │   fetch_latest_advisory    (db-mcp  → Postgres :5432) │
   │   query_knowledge_base     (chroma-mcp → chroma :8000) │
        │
   Phase B ── Generate ─────────────────────────────────────┐
   │   LM Studio (Qwen / any model) streaming               │
   │   Tool-use loop up to max_planner_iterations           │
        │
   Phase C ── Verify ───────────────────────────────────────┐
   │   Grounding check: PASS / PARTIAL / REJECT             │
   │   PARTIAL when knowledge base is empty (no sources)    │
        │
   Phase D ── Translate ────────────────────────────────────┐
       translate_output (built-in; skips if lang=eng_Latn)
        │
   AgentResponse { text, lang, verdict, citations, session_id }
```

| Service      | Port | What it does |
|--------------|------|--------------|
| `db`         | 5432 | Postgres 15 + pgvector. `cropcompass_dump.sql` auto-loads on first boot. |
| `db-mcp`     | 9101 | MCP server — 7 read-only tools against the cropcompass DB. |
| `chroma`     | 8001 | Standalone ChromaDB **1.5.9** vector store (persists `./data/chromadb`; container port 8000). |
| `chroma-mcp` | 9103 | MCP server — multilingual semantic search; embedder **baked into the image** (runs offline), queries `chroma` over HTTP. |
| `agent`      | 8001 | The agent. Auto-discovers all MCP tools on startup. |
| `ui`         | 5173 | React/Vite SPA (Nginx). Language selector, onboarding wizard, streaming chat in 9 Indic languages. |

---

## Quickstart

### 1. Configure LM Studio (one-time)

1. Download [LM Studio](https://lmstudio.ai) and load a model  
   (tested with `qwen/qwen3-coder-30b`, any tool-capable model works)
2. Go to **Server → Start Server** — leave the port at **1234**
3. In `.env`, set:

```env
LLM_BACKEND=lm_studio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=qwen/qwen3-coder-30b   # match the model name shown in LM Studio
```

### 2. Start everything

```bash
cd cropcompass
cp .env.example .env   # edit LM_STUDIO_MODEL, VITE_API_URL, VITE_WS_URL
docker compose up --build -d
```


### 3. Verify it's alive

```bash
curl http://localhost:8000/health        # → {"status":"ok"}  (IMD API)
curl http://localhost:8001/health        # → {"status":"ok"}  (agent)
curl http://localhost:8001/tools | python3 -m json.tool  # → list of all MCP tools
curl -sf http://localhost:5173/ | head -3  # → HTML — UI is serving
```

Open **http://localhost:5173** in a browser to see the CropCompass SPA.

---

## Sending a question

### With a farmer ID (full profile from DB)

Get a real farmer ID first:
```bash
docker exec agent-db psql -U cropcompass -d cropcompass \
  -c "SELECT farmer_id, name, district, crop_variety FROM farmers LIMIT 5;"
```

Then ask:
```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{
    "farmer_id": "<uuid-from-above>",
    "message": "When should I sow rice and how much water does it need?",
    "session_id": "my-session-1"
  }' | python3 -m json.tool
```

### Without a farmer ID (anonymous mode)

`farmer_id` is optional. When omitted, the agent skips the DB profile lookup
and uses an anonymous profile (English, no district/crop context). The user
can mention their crop and region in the message itself.

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{
    "message": "I grow soybean in Nagpur. When should I sow and how much water does it need?",
    "session_id": "anon-1"
  }' | python3 -m json.tool
```

### Follow-up question (conversation memory)

Reuse the same `session_id` — the agent remembers the full conversation:

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{
    "farmer_id": "<uuid>",
    "message": "What fertiliser should I use?",
    "session_id": "my-session-1"
  }' | python3 -m json.tool
```

### Response shape

```json
{
  "text":       "Sow rice in June–July (kharif season)…",
  "lang":       "eng_Latn",
  "verdict":    "PASS | PARTIAL | REJECT",
  "citations":  { "sentence": "chunk_id" },
  "session_id": "my-session-1"
}
```

| Verdict   | Meaning |
|-----------|---------|
| `PASS`    | Every claim is grounded in a source chunk |
| `PARTIAL` | Some claims supported; unsupported ones stripped. Also used when knowledge base is empty (nothing to contradict). |
| `REJECT`  | No claims supported → safe KVK fallback message returned |

---

## Streaming (watch the agent think)

**SSE (Server-Sent Events) — best for debugging:**
```bash
curl -N --get http://localhost:8000/sse/chat \
  --data-urlencode 'farmer_id=<uuid>' \
  --data-urlencode 'message=When should I sow rice?' \
  --data-urlencode 'session_id=stream-1'
```

You'll see events in real time: `phase` → `tool_call` → `tool_result` → `token` → `verdict` → `final`.

**WebSocket:** `/ws/chat` (same params as query string)

**JavaScript client:**
```js
const es = new EventSource(`/sse/chat?farmer_id=${id}&message=${encodeURIComponent(msg)}`);
es.addEventListener("token",  e => append(JSON.parse(e.data).data.delta));
es.addEventListener("final",  e => { es.close(); render(JSON.parse(e.data).data); });
es.addEventListener("error",  e => console.error(JSON.parse(e.data).data.message));
```

---

## LLM Backends

| `LLM_BACKEND` | When to use | Required env var |
|---------------|-------------|------------------|
| `lm_studio` | Local dev / testing — free, no API key | `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL` |
| `anthropic`  | Production — best quality | `ANTHROPIC_API_KEY` |

### Switch LM Studio → Anthropic

1. Get an API key at https://console.anthropic.com → **API Keys → Create Key**
2. Edit `.env`:
   ```env
   LLM_BACKEND=anthropic
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
   # LM Studio lines can stay — they're ignored when backend=anthropic
   ```
3. Restart the agent (no rebuild needed):
   ```bash
   docker compose restart agent
   ```
4. Confirm the switch:
   ```bash
   docker compose logs agent 2>&1 | grep ANALYZE
   # [ANALYZE] Using Anthropic backend
   ```

### Switch Anthropic → LM Studio

1. Load a model in LM Studio and start its server (port 1234)
2. Edit `.env`:
   ```env
   LLM_BACKEND=lm_studio
   LM_STUDIO_BASE_URL=http://127.0.0.1:1234
   LM_STUDIO_MODEL=qwen/qwen3-coder-30b   # match the model name in LM Studio
   ```
3. Restart the agent:
   ```bash
   docker compose restart agent
   ```
4. Confirm:
   ```bash
   docker compose logs agent 2>&1 | grep ANALYZE
   # [ANALYZE] Using LM Studio backend  url=http://host.docker.internal:1234  model=...
   ```

> **Inside Docker, LM Studio URL must be `host.docker.internal`** not `127.0.0.1`.
> The `.env` value of `127.0.0.1` is only used for local (non-Docker) runs.
> `dockerse.yml` already overrides this to `host.docker.internal` for you.

| Setting | LM Studio | Anthropic |
|---|---|---|
| `LLM_BACKEND` | `lm_studio` | `anthropic` |
| API key needed |  |  `ANTHROPIC_API_KEY` |
| LM Studio running |  |  |
| Cost | Free | Pay per token |
| Model override | `LM_STUDIO_MODEL=...` | `ANTHROPIC_MODEL=claude-sonnet-4-5` |

> **Thinking models (Qwen3, DeepSeek-R1 etc.):** The client automatically strips
> `<think>…</think>` blocks from streamed tokens and JSON responses so they
> never pollute the draft or confuse the verifier.

---

## Adding a tool

### In-process (pure Python, no new server)

```python
# src/agent_service/extras.py
from agent_service.tools.base import ToolSpec

async def list_mandi_prices(commodity: str, district: str) -> dict:
    return {"min": 4200, "max": 4650, "modal": 4480}

MANDI = ToolSpec(
    name="list_mandi_prices",
    description="Today's APMC mandi prices.",
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

Register in `src/agent_service/main.py` after `runner = AgentRunner()`:
```python
from .extras import MANDI
runner.registry.register(MANDI)
```

### MCP server (separate deployable process)

```python
# mcp_servers/my_server/server.py
from fastapi import FastAPI
from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp

reg = MCPToolRegistry()

@reg.tool(
    name="get_widget", description="Fetch a widget by id.",
    input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
)
async def _get_widget(id: str) -> dict:
    return {"id": id}

app = FastAPI()
mount_mcp(app, reg)
```

Add to `docker-compose.yml` and extend `MCP_SERVER_URLS` in the agent env.
The agent auto-discovers every tool on startup via `tools/list`.

---

## Tests

```bash
# Local (no Docker needed)
source .venv/bin/activate
pytest -q          # 31 unit tests pass, 2 integration tests skip (need live LM Studio)

# Run integration tests too
LM_STUDIO_MODEL=qwen/qwen3-coder-30b pytest -q
```

---

## Frontend (UI Container)

The React/Vite SPA is containerised as a two-stage Docker build and served by
Nginx on host port **5173**.

### Required files (create if absent)

**`ui/nginx.conf`** — SPA routing + cache headers:
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
    location ~* \.(js|css|woff2?|svg|png|ico|webp)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location = /index.html { add_header Cache-Control "no-store"; }
}
```

**`ui/Dockerfile`** — two-stage build:
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci --ignore-scripts
ARG VITE_API_URL=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8001
ARG VITE_USE_MOCK=false
ENV VITE_API_URL=$VITE_API_URL VITE_WS_URL=$VITE_WS_URL VITE_USE_MOCK=$VITE_USE_MOCK
COPY ui/ .
RUN npm run build

FROM nginx:1.27-alpine AS runner
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

### `.env` variables for the UI build

```dotenv
# Baked into the JS bundle at build time — change requires docker compose build ui
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8001
VITE_USE_MOCK=false
```

### Build & run

```bash
# Rebuild after source changes or VITE_* var changes
docker compose build ui
docker compose up -d ui

# Check it's serving
curl -sf http://localhost:5173/
# Open in browser
start http://localhost:5173   # Windows
open  http://localhost:5173   # macOS
```

### Local dev (hot-reload, no container)

```bash
cd ui
VITE_API_URL=http://localhost:8000 VITE_WS_URL=ws://localhost:8001 npm run dev
# Opens http://localhost:5173 with hot-reload
```

> **Note:** `VITE_*` vars are compiled into the bundle by Vite at **build time**.
> They are not read from the environment at container runtime. After editing them
> in `.env` you must rebuild the image with `docker compose build ui`.

---

## Deploying to production

| Target | How |
|--------|-----|
| **Any VM** | Copy repo + `.env.production`, run `docker compose up -d` |

Health / readiness: `GET /health` on agent + every MCP server.  
Tool discovery sanity check: `GET /tools` — should list all MCP-exposed tools. If only `translate_output` shows, `MCP_SERVER_URLS` is wrong or the MCP servers aren't reachable.

---

## Reset everything

```bash
docker compose down -v   # drops DB volume; next `up` reseeds from the dump
```

---

## Full runbook

See [`RUNBOOK.md`](./RUNBOOK.md) for detailed ops: local dev setup, session backends,
environment variables, log reading, and deployment options.
