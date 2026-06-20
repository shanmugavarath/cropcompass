# CropCompass — Integration Plan

**Branches:** `feature/frontend` + `feature/imd-scraper` + `agentic_solution` → `main`

---

## Branch Overview

| Branch | Owner | What It Provides |
|---|---|---|
| `feature/imd-scraper` | Data Engineer | FastAPI backend, IMD weather pipeline, PostgreSQL/ChromaDB, `/api/profile`, `/api/forecast`, `/api/rainfall`, chat **stub** |
| `agentic_solution` | Agent Engineer | Agent service (LLM + MCP), WebSocket `/ws/chat`, SSE `/sse/chat`, `POST /api/chat`, MCP servers for DB/vector |
| `feature/frontend` | UI Engineer | React/Vite SPA, farmer onboarding wizard, 9-language support, socket.io-based chat |

---

## Phase 1 — Pre-Integration Audit (no code changes)

### 1.1 Enumerate conflicts before touching any branch

```bash
git checkout -b integration/unified origin/main

git merge --no-commit --no-ff origin/feature/imd-scraper
git merge --abort

git merge --no-commit --no-ff origin/agentic_solution
git merge --abort
```

### 1.2 Known conflicts

| File | Conflict Type | Resolution |
|---|---|---|
| `docker-compose.yml` | Both branches define it | Merge into one unified compose (see Phase 3) |
| `Dockerfile` | Both branches define it | Rename to `Dockerfile.api` and `Dockerfile.agent` |
| `app/routes/chat.py` (stub) vs `src/agent_service/` (full impl) | Functional overlap | Replace stub with proxy/direct wire-up to AgentRunner |
| `db/schema.sql` vs `db/conversations.sql` | Additive | Load as ordered init scripts |

---

## Phase 2 — Database Schema Merge

### 2.1 Unify DB init scripts (load in this order)

1. `db/schema.sql` — farmers, imd_advisories, historical_rainfall, seasonal_outlook *(imd-scraper)*
2. `db/conversations.sql` — session/conversation tables *(agentic_solution)*
3. `mcp_servers/vector_server/schema.sql` — pgvector embeddings table *(agentic_solution)*

Map these to numbered `docker-entrypoint-initdb.d/` files so Postgres loads them in order:
```
01_schema.sql        ← db/schema.sql
02_conversations.sql ← db/conversations.sql
03_vector.sql        ← mcp_servers/vector_server/schema.sql
```

### 2.2 Fix `lang_pref` constraint

The imd-scraper schema constrains `lang_pref` to 6 languages, but the frontend added Bengali, Kannada, and Malayalam. Update the constraint in `db/schema.sql`:

```sql
-- Before
CONSTRAINT chk_lang_pref CHECK (
    lang_pref IN ('hin_Deva','tam_Taml','tel_Telu','mar_Deva','pan_Guru','eng_Latn')
)

-- After
CONSTRAINT chk_lang_pref CHECK (
    lang_pref IN (
        'hin_Deva','tam_Taml','tel_Telu','mar_Deva',
        'pan_Guru','eng_Latn',
        'ben_Beng','kan_Knda','mal_Mlym'
    )
)
```

---

## Phase 3 — Docker Compose Unification

Merge both `docker-compose.yml` files into one. Target service layout:

```
db          (pgvector/pgvector:pg15, port 5432)  ← single shared DB
db-mcp      (port 9101)                          ← agentic_solution MCP
vector-mcp  (port 9102)                          ← agentic_solution MCP
api         (port 8000)                          ← imd-scraper FastAPI (profile/forecast/rainfall/chat-proxy)
agent       (port 8001)                          ← agentic_solution agent service
```

> **Decision on vector store:** Drop the ChromaDB service (`vectordb`) from imd-scraper and use the
> pgvector-based `vector-mcp` from agentic_solution exclusively. Both PostgreSQL images already
> include pgvector, so no extra container is needed.

Unified `docker-compose.yml` structure:

```yaml
services:
  db:
    image: pgvector/pgvector:pg15
    # init scripts: 01_schema.sql, 02_conversations.sql, 03_vector.sql

  db-mcp:
    build: { context: ., dockerfile: mcp_servers/Dockerfile }
    ports: ["9101:9101"]
    depends_on: [db]

  vector-mcp:
    build: { context: ., dockerfile: mcp_servers/Dockerfile }
    ports: ["9102:9102"]
    depends_on: [db]

  api:
    build: { context: ., dockerfile: Dockerfile.api }
    ports: ["8000:8000"]
    environment:
      AGENT_SERVICE_URL: http://agent:8001
    depends_on: [db]

  agent:
    build: { context: ., dockerfile: Dockerfile.agent }
    ports: ["8001:8001"]
    environment:
      MCP_SERVER_URLS: http://db-mcp:9101,http://vector-mcp:9102
    depends_on: [db-mcp, vector-mcp]
```

---

## Phase 4 — Backend Integration: Wire Agent into IMD API

The imd-scraper chat route (`app/routes/chat.py`) is an explicit stub with the comment:
> *"AgentRunner (WS2) will replace the body of chat_handler"*

### 4.1 Option A — Microservice proxy (recommended for separation of concerns)

Replace the stub's body with an HTTP proxy to the agent service:

```python
# app/routes/chat.py
import os, httpx
from fastapi import APIRouter, HTTPException

AGENT_URL = os.getenv("AGENT_SERVICE_URL", "http://agent:8001")

@router.post("", response_model=ChatResponse)
async def chat_handler(body: ChatRequest):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{AGENT_URL}/api/chat", json=body.model_dump(mode="json"), timeout=60)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return ChatResponse(**r.json())
```

Also expose the agent's WebSocket and SSE endpoints by proxying or documenting the direct `agent:8001` URL.

### 4.2 Option B — Monolith (single process)

Import `AgentRunner` directly into `app/main.py` and register the agent's routers on the same FastAPI app. Suitable if running as a single container is preferred.

---

## Phase 5 — Frontend Integration: Fix WebSocket Protocol Mismatch

> ⚠️ **This is the most critical fix.** The frontend uses `socket.io-client` but the agent service
> exposes a **raw WebSocket** at `/ws/chat`. Socket.io and raw WebSocket are not wire-compatible.

### 5.1 Replace `ui/src/api/socket.js`

```js
// Before — socket.io (incompatible with agent service)
import { io } from 'socket.io-client'
_socket = io(import.meta.env.VITE_API_URL, { transports: ['websocket'] })
_socket.emit('chat', payload)
_socket.on('response', handler)

// After — native WebSocket (matches /ws/chat)
const WS_URL = import.meta.env.VITE_WS_URL  // e.g. ws://localhost:8001
_socket = new WebSocket(`${WS_URL}/ws/chat`)
_socket.send(JSON.stringify(payload))
_socket.onmessage = (evt) => { /* handle StreamEvent */ }
```

Remove `socket.io-client` from `ui/package.json` (no replacement needed — WebSocket is built-in).

### 5.2 Update `ui/src/hooks/useChat.js` to handle streaming

The agent service streams a sequence of `StreamEvent` frames, not a single `response` event.
`StreamEvent.type` values: `phase`, `tool_call`, `tool_result`, `token`, `verdict`, `final`, `error`.

Required changes to `useChat.js`:
- Buffer consecutive `token` events into a growing in-progress message bubble
- Show `phase` / `tool_call` events as status indicators (e.g. "🔍 Checking forecast…")
- Finalize the assistant message on `final` or `verdict` event
- Map `error` type to a user-visible error bubble
- Keep `pending = true` from first message until a `final`/`verdict`/`error` frame arrives

---

## Phase 6 — Environment & Configuration Alignment

### 6.1 Create a root `.env.example`

```dotenv
# ── Shared PostgreSQL ────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://cropcompass:cropcompass_secret@db:5432/cropcompass
POSTGRES_DB=cropcompass
POSTGRES_USER=cropcompass
POSTGRES_PASSWORD=cropcompass_secret

# ── Agent service ────────────────────────────────────────────
LLM_BACKEND=lm_studio          # or: anthropic
ANTHROPIC_API_KEY=
LM_STUDIO_BASE_URL=http://host.docker.internal:1234
LM_STUDIO_MODEL=local-model
SESSION_BACKEND=postgres        # or: memory

# ── IMD API service ──────────────────────────────────────────
AGENT_SERVICE_URL=http://agent:8001
LOG_LEVEL=INFO

# ── Frontend (Vite) ──────────────────────────────────────────
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8001
VITE_USE_MOCK=false
```

### 6.2 CORS

Both services currently use `allow_origins=["*"]`. Tighten to explicit frontend origin
(`http://localhost:5173` for dev, production domain for prod) before final merge.

---

## Phase 7 — Merge Execution Order

```bash
# 1. Create integration branch from main
git checkout -b integration/unified origin/main

# 2. Merge the data backend first (establishes directory structure)
git merge origin/feature/imd-scraper

# 3. Merge the agent service (mostly separate tree under src/, few conflicts)
git merge origin/agentic_solution
#    → manually resolve: docker-compose.yml, Dockerfile

# 4. Merge the frontend (isolated in /ui/, no backend conflicts)
git merge origin/feature/frontend
#    → update ui/.env to point VITE_WS_URL at agent service

# 5. Apply all fixes described in Phases 2–6
# 6. Run full test suite (see Phase 8)
# 7. Open PR: integration/unified → main
```

---

## Phase 8 — Validation Checklist

- [ ] `docker-compose up` starts all services without port conflicts
- [ ] `GET http://localhost:8000/health` → `{"status":"ok"}`
- [ ] `GET http://localhost:8001/health` → `{"status":"ok"}`
- [ ] Farmer onboarding `POST /api/profile` saves record to DB and returns `farmer_id`
- [ ] `GET /api/profile/{farmer_id}` returns farmer data
- [ ] `GET /api/forecast/{district}` returns IMD advisory
- [ ] WebSocket `/ws/chat` streams `StreamEvent` tokens to the frontend chat window
- [ ] `POST /api/chat` (HTTP fallback) returns `AgentResponse`
- [ ] All 9 language preferences accepted by the DB (`lang_pref` constraint)
- [ ] Frontend language selector displays and persists all 9 languages
- [ ] Frontend E2E tests pass: `pytest tests/test_e2e.py`
- [ ] Frontend latency tests pass: `pytest tests/test_latency.py`

---

## Summary of Breaking Issues (must fix before merge)

| # | Issue | Severity | Fix Location |
|---|---|---|---|
| 1 | **Socket.io vs raw WebSocket** — incompatible protocols | 🔴 Critical | `ui/src/api/socket.js`, `ui/src/hooks/useChat.js` |
| 2 | **Chat stub never wired** — frontend receives stub response only | 🔴 Critical | `app/routes/chat.py` |
| 3 | **`lang_pref` constraint** — DB rejects 3 new languages | 🟠 High | `db/schema.sql` |
| 4 | **Duplicate `docker-compose.yml`** — port 8000 and 5432 collide | 🟠 High | merge into unified compose |
| 5 | **Frontend streaming not handled** — `useChat.js` expects single event | 🟠 High | `ui/src/hooks/useChat.js` |
