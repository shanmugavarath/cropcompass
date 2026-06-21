# CropCompass — Integration Plan

**Branches:** `feature/frontend` + `feature/imd-scraper` + `agentic_solution` + `Shanu/RAG` → `main`

---

## Branch Overview

| Branch | Owner | What It Provides |
|---|---|---|
| `feature/imd-scraper` | Data Engineer | FastAPI backend, IMD weather pipeline, PostgreSQL/ChromaDB, `/api/profile`, `/api/forecast`, `/api/rainfall`, chat **stub** |
| `agentic_solution` | Agent Engineer | Agent service (LLM + MCP), WebSocket `/ws/chat`, SSE `/sse/chat`, `POST /api/chat`, MCP servers for DB/vector |
| `feature/frontend` | UI Engineer | React/Vite SPA, farmer onboarding wizard, 9-language support, socket.io-based chat |
| `Shanu/RAG` | RAG Engineer | Dual-collection ChromaDB RAG (`api/services/rag.py`), IndicTrans2 translation service (`api/services/translation.py`), `lingua-py` language detection (`api/services/lang_detect.py`), PDF ingestion pipeline (`ingestion/`) |

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

| File | Conflict Type | Resolution | Status |
|---|---|---|---|
| `docker-compose.yml` | Both branches define it | Merge into one unified compose (see Phase 3) | ✅ Done |
| `Dockerfile` | Both branches define it | Rename to `Dockerfile.api` and `Dockerfile.agent` | ✅ Done |
| `app/routes/chat.py` (stub) vs `src/agent_service/` (full impl) | Functional overlap | Replace stub with proxy/direct wire-up to AgentRunner | ✅ Done |
| `db/schema.sql` vs `db/conversations.sql` | Additive | Load as ordered init scripts | ✅ Done |

---

## Phase 2 — Database Schema Merge ✅

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

### 2.2 Fix `lang_pref` constraint ✅ (SQL only) ⚠️ Pydantic schema not updated

> **Remaining:** `app/schemas/farmer.py` `LangPref` Literal still lists only 6 languages — `ben_Beng`, `kan_Knda`, `mal_Mlym` must be added or the API will return HTTP 422 for those values even though the DB accepts them.

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

## Phase 3 — Docker Compose Unification ✅

Merge both `docker-compose.yml` files into one. Target service layout:

```
db          (pgvector/pgvector:pg15, port 5432)  ← single shared DB
db-mcp      (port 9101)                          ← agentic_solution MCP (Postgres read tools)
chroma      (host 8001 → container 8000)         ← ChromaDB 1.5.9 standalone store
chroma-mcp  (port 9103)                          ← agentic_solution MCP (semantic search)
api         (port 8000)                          ← imd-scraper FastAPI (profile/forecast/rainfall/chat-proxy)
agent       (internal 8001, no host exposure)    ← agentic_solution agent service
```

> **Vector store decision (updated):** `agentic_solution` has fully replaced the pgvector-based
> `vector-mcp` with a two-tier ChromaDB architecture: a standalone `chroma` container (ChromaDB
> 1.5.9, persists `./data/chromadb` on the host) and a thin `chroma-mcp` that embeds queries and
> queries `chroma` over HTTP. `vector-mcp` and `mcp_servers/vector_server/` are **deleted** in that
> branch and must not be restored.
>
> **Port assignments (resolved):** `api` owns host port 8000. `chroma`'s internal port 8000 is
> mapped to host port **8001** for local debugging access (`http://localhost:8001`). The `agent`
> service runs on internal port 8001 and is reachable within Docker via `http://agent:8001`; it
> does not require a separate host-port mapping since only `api` calls it over the Docker network.

Unified `docker-compose.yml` structure:

```yaml
services:
  db:
    image: pgvector/pgvector:pg15
    # init scripts: 01_schema.sql, 02_conversations.sql
    # NOTE: 03_vector.sql (pgvector embeddings table) removed — vector store is now ChromaDB

  db-mcp:
    build: { context: ., dockerfile: mcp_servers/Dockerfile }
    command: uvicorn mcp_servers.db_server.server:app --host 0.0.0.0 --port 9101
    ports: ["9101:9101"]
    depends_on: [db]

  chroma:
    image: chromadb/chroma:1.5.9          # MUST be 1.5.9 — on-disk schema at migration v10
    environment:
      IS_PERSISTENT: "TRUE"
      PERSIST_DIRECTORY: /data
      ANONYMIZED_TELEMETRY: "FALSE"
    volumes:
      - ./data/chromadb:/data             # host-mounted (not a named volume)
    ports: ["8001:8000"]                  # host 8001 → container 8000 (for local debug access)

  chroma-mcp:
    build: { context: ., dockerfile: mcp_servers/chroma_server/Dockerfile }
    command: uvicorn mcp_servers.chroma_server.server:app --host 0.0.0.0 --port 9103
    environment:
      CHROMA_HOST: chroma
      CHROMA_PORT: "8000"
      CHROMA_EMBED_MODEL: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
      CHROMA_PRIMARY_COLLECTION: icar_knowledge_en
      CHROMA_FALLBACK_COLLECTION: icar_knowledge
      HF_HUB_OFFLINE: "1"               # embedder is baked into the image
      TRANSFORMERS_OFFLINE: "1"
    ports: ["9103:9103"]
    depends_on: [chroma]

  api:
    build: { context: ., dockerfile: Dockerfile.api }
    ports: ["8000:8000"]
    environment:
      AGENT_SERVICE_URL: http://agent:8001
    depends_on: [db]

  agent:
    build: { context: ., dockerfile: Dockerfile.agent }
    ports: ["8001:8001"]                  # remapped from 8000 in agentic_solution branch
    command: uvicorn agent_service.main:app --host 0.0.0.0 --port 8001
    environment:
      MCP_SERVER_URLS: http://db-mcp:9101,http://chroma-mcp:9103
    depends_on: [db-mcp, chroma-mcp]
```

> **Data bootstrapping (required before first `docker compose up`):**
> The ChromaDB store at `./data/chromadb` must be populated before starting the stack.
> See §7.6 for ingestion instructions. Without it `chroma-mcp` will start but
> `query_knowledge_base` will return empty results.

---

## Phase 4 — Backend Integration: Wire Agent into IMD API ✅

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

## Phase 5 — Frontend Integration: Fix WebSocket Protocol Mismatch ✅

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

## Phase 6 — Environment & Configuration Alignment ✅ (partial — duplicate MCP_SERVER_URLS entry in .env.example)

### 6.1 Create a root `.env.example`

```dotenv
# ── Shared PostgreSQL ────────────────────────────────────────
DATABASE_URL=postgresql://cropcompass:cropcompass_secret@db:5432/cropcompass
POSTGRES_DB=cropcompass
POSTGRES_USER=cropcompass
POSTGRES_PASSWORD=cropcompass_secret

# ── Agent service ────────────────────────────────────────────
LLM_BACKEND=lm_studio          # or: anthropic
ANTHROPIC_API_KEY=
LM_STUDIO_BASE_URL=http://host.docker.internal:1234
LM_STUDIO_MODEL=qwen/qwen3-coder-30b   # must match exact model id in LM Studio UI
SESSION_BACKEND=postgres        # or: memory
MAX_PLANNER_ITERATIONS=6

# ── MCP servers ───────────────────────────────────────────────
# Docker (set in docker-compose.yml): http://db-mcp:9101,http://chroma-mcp:9103
# Local dev (non-Docker):
MCP_SERVER_URLS=http://localhost:9101,http://localhost:9103
MCP_REQUEST_TIMEOUT_S=15

# ── ChromaDB ─────────────────────────────────────────────────
# HTTP mode (Docker): set CHROMA_HOST + CHROMA_PORT
CHROMA_HOST=chroma
CHROMA_PORT=8000
# Embedded mode (local dev, no Docker): leave CHROMA_HOST empty, set CHROMA_PATH
CHROMA_PATH=data/chromadb
# MUST match the model the store was built with — version pinned to 1.5.9
CHROMA_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
CHROMA_PRIMARY_COLLECTION=icar_knowledge_en
CHROMA_FALLBACK_COLLECTION=icar_knowledge

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

## Phase 7 — Shanu/RAG Integration ✅ (partial — §7.4 and §7.5 still open)

### 7.0 What the branch adds

`Shanu/RAG` introduces three runtime services and a one-time data pipeline:

| Module | Path | Role at runtime |
|---|---|---|
| RAG retriever | `api/services/rag.py` | Original ChromaDB retrieval logic — **superseded** by `mcp_servers/chroma_server/retriever.py` in `agentic_solution` (see §7.3) |
| Translation service | `api/services/translation.py` | Translates farmer queries → English (for retrieval) and agent responses → farmer's language |
| Language detection | `api/services/lang_detect.py` | Detects script/language of incoming message; handles Hinglish code-switching |
| Ingestion pipeline | `ingestion/` | **Run once** (or on new data) to build `data/chromadb/`; not in the request path |

### 7.1 Conflict analysis

| File | Conflict Type | Resolution | Status |
|---|---|---|---|
| `requirements.txt` | imd-scraper and Shanu/RAG both define one; agentic_solution uses `pyproject.toml` | Merge into a single root `requirements.txt` (see §7.2) | ✅ Done (`pyproject.toml` has `chromadb==1.5.9`, `sentence-transformers>=3.0`) |
| `.gitignore` | Minor line change — Shanu/RAG adds `data/chromadb/`, `data/raw/`, `data/*.json` | Accept Shanu/RAG additions; ensure `data/` artifacts are excluded globally | ✅ Done |
| `ingestion/imd_scraper.py` | Both imd-scraper and Shanu/RAG include an IMD scraper | Shanu/RAG's version feeds ChromaDB; imd-scraper's version feeds PostgreSQL — keep **both** under a shared `ingestion/` package (they don't overlap at the function level) | ✅ Done (`ingestion/` has both scrapers) |
| `mcp_servers/vector_server/` | agentic_solution **deletes** this entire directory | Accept deletion — ChromaDB via `chroma-mcp` is the only vector search path | ✅ Done (only `chroma_server/` and `db_server/` remain) |

No conflicts expected in `api/services/` — that directory does not exist in any other branch.

### 7.2 Merge `requirements.txt`

After merging all four branches, produce a single top-level `requirements.txt` that unions all dependencies. Minimum set of additions from `Shanu/RAG`:

```
# RAG / embeddings — ChromaDB MUST be pinned to 1.5.9 (on-disk schema v10)
chromadb==1.5.9
sentence-transformers>=3.0
langchain-text-splitters>=0.2.0

# PDF ingestion
pdfplumber>=0.10.0
pytesseract>=0.3.10
pdf2image>=1.17.0

# IndicTrans2 translation
torch>=2.1.0
transformers>=4.38,<4.46
sentencepiece>=0.1.99
sacremoses>=0.0.53
IndicTransToolkit>=1.0.0

# Language detection
lingua-language-detector>=2.0.0

# Evaluation
rouge-score>=0.1.2
```

> **Version pin:** `chromadb==1.5.9` is non-negotiable. The persisted `data/chromadb` store was
> built with that version (migration v10). Any other version will either panic on migration or
> silently corrupt the store.
>
> **GPU note:** `torch` defaults to a CPU wheel. On the agent container (which runs inference),
> install torch from `https://pytorch.org` with the matching CUDA index URL before
> `pip install -r requirements.txt`.

### 7.3 Wire RAG into the agent service (updated) ✅

**`agentic_solution` already handles this.** The new `chroma-mcp` server (port 9103) exposes
`query_knowledge_base` as an MCP tool — identical signature to what Shanu/RAG's
`api/services/rag.query_knowledge_base()` uses. The agent discovers it automatically at startup
via `MCP_SERVER_URLS=http://db-mcp:9101,http://chroma-mcp:9103`. No additional wiring is needed.

Tools exposed by `chroma-mcp`:
- `query_knowledge_base(query, top_k=5, crop?, soil?)` — dual-collection semantic search
- `fetch_chunk(chunk_id)` — exact chunk lookup by ID
- `list_collections()` — lists available Chroma collections and chunk counts

**Embedding model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim,
multilingual). Maps Tamil (TNAU corpus) and English (ICAR/IMD corpus) into the same vector space
so English queries retrieve Tamil chunks. The model is **baked into the `chroma-mcp` image** and
runs fully offline (`HF_HUB_OFFLINE=1`) — no HuggingFace network access at runtime.

**Collections:**
- `icar_knowledge_en` — all-English collection (IMD + translated SAU). Primary.
- `icar_knowledge` — original collection with untranslated Tamil SAU chunks. Fallback.
Both are queried, results merged by distance score, deduplicated by `chunk_id`.

`api/services/rag.py` from `Shanu/RAG` can be kept as a standalone module but is **not
called at request time** — the agent uses the MCP path instead.

### 7.4 Wire translation into the query/response pipeline ✅ Done

The translation service operates in two directions:

```
Farmer query (any Indic language)
    → lang_detect.detect_with_codeswitching()   # e.g. "tam_Taml"
    → TranslationService(INDIC_EN).translate()  # Tamil → English
    → RAG retrieval via chroma-mcp (English query hits both corpora)
    → AgentRunner produces English recommendation
    → TranslationService(EN_INDIC).translate(tgt_lang=farmer.lang_pref)
    → Farmer sees response in their language
```

`TranslationService` loads ~2 GB of HuggingFace weights on first instantiation. Instantiate
once at agent startup and pass the singleton through; do **not** construct it per-request.

```python
# agent/main.py (startup)
from api.services.translation import TranslationService, DEFAULT_INDIC_EN, DEFAULT_EN_INDIC

indic_to_en = TranslationService(model_name=DEFAULT_INDIC_EN)
en_to_indic  = TranslationService(model_name=DEFAULT_EN_INDIC)
```

### 7.5 Language detection: extend `lang_detect.py` to cover all 9 frontend languages ❌ NOT DONE

`lang_detect.py` currently supports 6 languages (`eng`, `hin`, `tam`, `tel`, `mar`, `pan`).
The frontend added Bengali, Kannada, and Malayalam (Phase 2.2 already fixes the DB constraint).
Extend the detector to match:

```python
# api/services/lang_detect.py
from lingua import Language, LanguageDetectorBuilder

LINGUA_TO_FLORES = {
    Language.HINDI:     "hin_Deva",
    Language.TAMIL:     "tam_Taml",
    Language.TELUGU:    "tel_Telu",
    Language.MARATHI:   "mar_Deva",
    Language.PUNJABI:   "pan_Guru",
    Language.ENGLISH:   "eng_Latn",
    # Add these three:
    Language.BENGALI:   "ben_Beng",
    Language.KANNADA:   "kan_Knda",
    Language.MALAYALAM: "mal_Mlym",
}

_detector = LanguageDetectorBuilder.from_languages(
    *LINGUA_TO_FLORES.keys()
).build()
```

Also extend `TranslationService.SUPPORTED` to include `"ben_Beng"`, `"kan_Knda"`, `"mal_Mlym"`.
IndicTrans2 supports all three out of the box; no model change required.

### 7.6 ChromaDB data bootstrapping ⚠️ PREREQUISITE (must run before `docker compose up`)

The `./data/chromadb` directory (host-mounted into the `chroma` container) must be populated
before the first `docker compose up`. The store is ~800 MB and pinned to ChromaDB **1.5.9**.

**One-time ingestion (run on the host before `docker compose up`):**
```bash
# Install deps (matches chroma-mcp image versions)
pip install "chromadb==1.5.9" "sentence-transformers>=3.0" pdfplumber pytesseract pdf2image

# Run the ingestion pipeline — requires SAU OCR JSON files at data/raw/SAU_ocr_output/
python -m ingestion.ingest_to_chromadb

# Verify both collections exist
python3 -c "
import chromadb
c = chromadb.PersistentClient('data/chromadb')
for col in c.list_collections():
    print(col.name, col.count(), 'chunks')
"
# Expected:
#   icar_knowledge_en  <N> chunks
#   icar_knowledge     <N> chunks
```

After ingestion is done, start the stack:
```bash
docker compose up -d
# chroma container loads the pre-built store from ./data/chromadb
# chroma-mcp warmup log: chroma.ready collections=[...]
```

---

## Phase 10 — Frontend Containerisation

The React/Vite SPA in `ui/` must be built into a static bundle and served via
an Nginx container. The container is part of the unified `docker-compose.yml`
stack and is the only public-facing entry-point for browser clients.

### 10.1 Create `ui/Dockerfile`

Multi-stage build — Node 20 builder → Nginx 1.27 alpine image:

```dockerfile
# ── Stage 1: build the Vite bundle ───────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Install deps (cache this layer)
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci --ignore-scripts

# Inject runtime env vars as Vite compile-time substitutions.
# Set defaults here; override via docker-compose.yml build args.
ARG VITE_API_URL=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8001
ARG VITE_USE_MOCK=false
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL \
    VITE_USE_MOCK=$VITE_USE_MOCK

COPY ui/ .
RUN npm run build
# Output → /app/dist

# ── Stage 2: serve with Nginx ─────────────────────────────────
FROM nginx:1.27-alpine AS runner

# SPA fallback — route all 404s to index.html so React Router works
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
```

### 10.2 Create `ui/nginx.conf`

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback — send all non-file requests to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets aggressively (Vite adds content hashes)
    location ~* \.(js|css|woff2?|svg|png|ico|webp)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # No caching for the HTML entry point itself
    location = /index.html {
        add_header Cache-Control "no-store";
    }
}
```

### 10.3 Add `ui` service to `docker-compose.yml`

```yaml
  # ── React/Vite frontend (port 5173) ──────────────────────────
  ui:
    build:
      context: .
      dockerfile: ui/Dockerfile
      args:
        # Must point to the host-visible addresses so the browser (not Docker)
        # can reach the API and WebSocket:
        VITE_API_URL:  ${VITE_API_URL:-http://localhost:8000}
        VITE_WS_URL:   ${VITE_WS_URL:-ws://localhost:8001}
        VITE_USE_MOCK: ${VITE_USE_MOCK:-false}
    container_name: cropcompass-ui
    restart: unless-stopped
    ports:
      - "5173:80"
    depends_on:
      api:   { condition: service_healthy }
      agent: { condition: service_started }
```

> **Port note:** Nginx inside the container listens on port 80. The host maps it to
> **5173** to preserve the same origin developers are used to from `npm run dev`.
> Change to `80:80` or `443:443` for production behind a real domain.

> **`VITE_*` env vars are baked at build time**, not at runtime. They need to be
> correct when `docker compose build` runs, not when the container starts. If you
> change the API URL you must rebuild the `ui` image (`docker compose build ui`).

### 10.4 Update `docker-compose.yml` volumes section

No named volume is needed for the UI container — all content is baked into the
image. No changes to the `volumes:` block.

### 10.5 Add `VITE_*` vars to `.env.example`

```dotenv
# ── Frontend (Vite build-time substitutions) ─────────────────
# These are baked into the JS bundle at image-build time.
# After changing them you must rebuild: docker compose build ui
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8001
VITE_USE_MOCK=false
```

### 10.6 `.dockerignore` entries to keep the image lean

Ensure these paths are excluded when the Docker build context is sent to the
daemon (they would otherwise be copied by `COPY ui/ .` in stage 1):

```
ui/node_modules
ui/.vite
ui/dist
ui/coverage
```

---

## Phase 8 — Merge Execution Order

```bash
# 1. Create integration branch from main
git checkout -b integration/unified origin/main

# 2. Merge the data backend first (establishes directory structure)
git merge origin/feature/imd-scraper

# 3. Merge the RAG/translation branch (adds api/services/, ingestion/, extends requirements.txt)
git merge origin/Shanu/RAG
#    → manually resolve: requirements.txt (merge dependency lists)
#    → manually resolve: ingestion/imd_scraper.py (keep both; rename if signatures clash)

# 4. Merge the agent service (mostly separate tree under src/, few conflicts)
git merge origin/agentic_solution
#    → manually resolve: docker-compose.yml, Dockerfile

# 5. Merge the frontend (isolated in /ui/, no backend conflicts)
git merge origin/feature/frontend
#    → update ui/.env to point VITE_WS_URL at agent service

# 6. Apply all fixes described in Phases 2–7
# 7. Run full test suite (see Phase 9)
# 8. Open PR: integration/unified → main
```

---

## Phase 9 — Validation Checklist

### 9.1 Service startup

- [ ] All services start without port conflicts
  ```bash
  docker compose up -d
  docker compose ps   # all containers must show "healthy" or "running"
  # Expected services: db (5432), db-mcp (9101), chroma (8001), chroma-mcp (9103), api (8000), agent (internal 8001)
  ```
- [ ] ChromaDB store loaded (check before starting stack)
  ```bash
  # Verify ./data/chromadb exists and has both collections
  python3 -c "
  import chromadb
  c = chromadb.PersistentClient('data/chromadb')
  for col in c.list_collections():
      print(col.name, col.count(), 'chunks')
  "
  # Expected: icar_knowledge_en  <N> chunks
  #           icar_knowledge     <N> chunks
  ```

### 9.2 Health checks

- [ ] IMD API healthy
  ```bash
  curl -sf http://localhost:8000/health
  # Expected: {"status":"ok"}
  ```
- [ ] Agent service healthy
  ```bash
  curl -sf http://localhost:8001/health
  # Expected: {"status":"ok"}
  ```
- [ ] Agent tool discovery
  ```bash
  curl -sf http://localhost:8001/tools
  # Expected: {"tools": [...]} — list must include db_query, query_knowledge_base, translate_output
  # NOTE: query_knowledge_base is now served by chroma-mcp (port 9103), not vector-mcp
  ```

### 9.3 Farmer profile (`/api/profile`)

- [ ] Create farmer profile — returns `farmer_id`
  ```bash
  curl -s -X POST http://localhost:8000/api/profile \
    -H "Content-Type: application/json" \
    -d '{
      "district": "Chennai",
      "state": "Tamil Nadu",
      "name": "Test Farmer",
      "soil_type": "clay",
      "crop_variety": "rice",
      "growth_stage": "sowing",
      "lang_pref": "tam_Taml"
    }' | tee /tmp/farmer.json
  # Expected: JSON with farmer_id (UUID), created_at, is_stale=false
  FARMER_ID=$(cat /tmp/farmer.json | python3 -c "import sys,json; print(json.load(sys.stdin)['farmer_id'])")
  ```
- [ ] Retrieve farmer profile by ID
  ```bash
  curl -sf http://localhost:8000/api/profile/$FARMER_ID
  # Expected: same farmer record; district="Chennai", lang_pref="tam_Taml"
  ```
- [ ] Update farmer profile
  ```bash
  curl -s -X PATCH http://localhost:8000/api/profile/$FARMER_ID \
    -H "Content-Type: application/json" \
    -d '{"growth_stage": "vegetative"}'
  # Expected: updated record with growth_stage="vegetative"
  ```
- [ ] 404 on unknown farmer
  ```bash
  curl -sw "\nHTTP %{http_code}\n" http://localhost:8000/api/profile/00000000-0000-0000-0000-000000000000
  # Expected: HTTP 404
  ```

### 9.4 All 9 `lang_pref` values accepted by DB

- [ ] Each language code must be accepted without a constraint error
  ```bash
  for lang in hin_Deva tam_Taml tel_Telu mar_Deva pan_Guru eng_Latn ben_Beng kan_Knda mal_Mlym; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/profile \
      -H "Content-Type: application/json" \
      -d "{\"district\":\"TestDist\",\"state\":\"TestState\",\"lang_pref\":\"$lang\"}")
    echo "$lang → HTTP $code"
  done
  # Expected: all lines show HTTP 201
  ```

### 9.5 IMD forecast (`/api/forecast`)

- [ ] Fetch forecast for a known district
  ```bash
  curl -sf "http://localhost:8000/api/forecast/Chennai"
  # Expected: JSON with district, bulletin_date, rainfall_prob, advisory_text, is_stale
  ```
- [ ] 404 for unknown district
  ```bash
  curl -sw "\nHTTP %{http_code}\n" "http://localhost:8000/api/forecast/NoSuchDistrict999"
  # Expected: HTTP 404
  ```

### 9.6 Rainfall crop suitability (`/api/rainfall`)

- [ ] Crop suitability for a district + crop
  ```bash
  curl -sf "http://localhost:8000/api/rainfall/Chennai/crop-suitability/rice"
  # Expected: JSON with verdict (SUFFICIENT/MARGINAL/INSUFFICIENT), recommendation, confidence
  ```
- [ ] 404 for unsupported crop
  ```bash
  curl -sw "\nHTTP %{http_code}\n" "http://localhost:8000/api/rainfall/Chennai/crop-suitability/unknowncrop"
  # Expected: HTTP 404, detail lists supported crops
  ```

### 9.7 Chat — HTTP fallback (`POST /api/chat`)

- [ ] Chat via IMD API proxy (requires agent service running)
  ```bash
  curl -s -X POST http://localhost:8000/api/chat \
    -H "Content-Type: application/json" \
    -d "{\"farmer_id\": \"$FARMER_ID\", \"message\": \"When should I irrigate my rice crop?\"}" \
    | python3 -m json.tool
  # Expected: {"session_id": "...", "response": "...", "lang": "eng_Latn", "verdict": "PASS"|"PARTIAL"|"REJECT", "citations": [...]}
  ```
- [ ] Chat directly against agent service
  ```bash
  curl -s -X POST http://localhost:8001/api/chat \
    -H "Content-Type: application/json" \
    -d "{\"farmer_id\": \"$FARMER_ID\", \"message\": \"What is the best fertilizer for clay soil?\"}" \
    | python3 -m json.tool
  # Expected: {"text": "...", "lang": "eng_Latn", "verdict": "PASS"|"PARTIAL"|"REJECT", "citations": {}, "session_id": "..."}
  ```

### 9.8 WebSocket streaming (`/ws/chat`)

- [ ] WebSocket streams `StreamEvent` frames

  **Option A — Python (works everywhere, no extra install):**
  ```bash
  pip install websockets   # once
  python3 - <<'EOF'
  import asyncio, json
  import websockets

  async def test():
      uri = "ws://localhost:8001/ws/chat"
      async with websockets.connect(uri) as ws:
          payload = {"farmer_id": None, "message": "How much water does rice need?", "session_id": None}
          await ws.send(json.dumps(payload))
          while True:
              frame = json.loads(await ws.recv())
              print(frame["type"], "→", str(frame.get("data", ""))[:120])
              if frame["type"] in ("final", "error"):
                  break

  asyncio.run(test())
  EOF
  # Expected: sequence of frames with type in [phase, tool_call, tool_result, token, verdict, final]
  # Last frame must have type="final"
  ```

  **Option B — wscat from PowerShell (Windows Node, not WSL):**
  ```powershell
  # Run in PowerShell (not WSL) — Node/wscat must be installed on Windows
  npx wscat -c "ws://localhost:8001/ws/chat"
  # After the connection prompt, paste:
  # {"farmer_id": null, "message": "How much water does rice need?", "session_id": null}
  ```

  **Option C — websocat single binary (no Node, no Python):**
  ```bash
  # Linux/WSL: download from https://github.com/vi/websocat/releases
  curl -Lo websocat https://github.com/vi/websocat/releases/latest/download/websocat.x86_64-unknown-linux-musl
  chmod +x websocat
  echo '{"farmer_id":null,"message":"How much water does rice need?","session_id":null}' \
    | ./websocat ws://localhost:8001/ws/chat
  ```

### 9.9 SSE streaming (`/sse/chat`)

- [ ] SSE streams events
  ```bash
  curl -sN -X POST http://localhost:8001/sse/chat \
    -H "Content-Type: application/json" \
    -d "{\"farmer_id\": \"$FARMER_ID\", \"message\": \"Explain kharif season planting.\", \"session_id\": null}"
  # Expected: stream of data: {...} lines, ending with type="final"
  ```

### 9.10 Frontend

- [ ] Frontend language selector displays and persists all 9 languages
  ```bash
  cd ui && npm run dev
  # Open http://localhost:5173 — verify all 9 languages appear in the selector
  # Select Tamil, reload page — preference must persist
  ```

### 9.11 Automated test suite

- [ ] E2E tests
  ```bash
  pytest tests/test_e2e.py -v
  ```
- [ ] Latency tests (P95 chat round-trip < threshold)
  ```bash
  pytest tests/test_latency.py -v
  ```
- [ ] Budget / token limit tests
  ```bash
  pytest tests/test_budget.py -v
  ```
- [ ] Session persistence tests
  ```bash
  pytest tests/test_session.py -v
  ```
- [ ] MCP tool discovery tests
  ```bash
  pytest tests/test_mcp.py -v
  ```

### 9.12 RAG pipeline (chroma-mcp)

- [ ] ChromaDB collections accessible via chroma-mcp
  ```bash
  curl -sf http://localhost:9103/mcp/tools/list_collections \
    -H "Content-Type: application/json" -d '{}'
  # Expected: {"collections": [{"name": "icar_knowledge_en", ...}, {"name": "icar_knowledge", ...}]}
  ```
- [ ] `query_knowledge_base` returns chunks via MCP
  ```bash
  curl -s http://localhost:9103/mcp/tools/query_knowledge_base \
    -H "Content-Type: application/json" \
    -d '{"query": "when to irrigate rice", "crop": "rice", "top_k": 3}' \
    | python3 -m json.tool
  # Expected: {"chunks": [{text, similarity, source, ...}, ...]} with >= 1 chunk
  ```
- [ ] RAG retrieval precision ≥ 0.70 on 25-query validation set
  ```bash
  pytest tests/test_rag.py -v
  ```
- [ ] RAG single-query latency < 200 ms
  ```bash
  CROPCOMPASS_LATENCY_MS=200 pytest tests/test_latency.py -v -k rag
  ```
- [ ] Multilingual retrieval — English query retrieves Tamil chunks
  ```bash
  curl -s http://localhost:9103/mcp/tools/query_knowledge_base \
    -H "Content-Type: application/json" \
    -d '{"query": "rice water requirement", "top_k": 5}' \
    | python3 -c "
  import sys,json
  chunks = json.load(sys.stdin).get('chunks', [])
  sources = [c.get('source','') for c in chunks]
  print(f'Retrieved {len(chunks)} chunks')
  print('Sources:', sources)
  "
  # Expected: chunks from both icar_knowledge_en and icar_knowledge collections
  ```

### 9.13 Language detection & translation

- [ ] Language detection returns correct FLORES-200 code for all 9 languages
  ```bash
  pytest tests/test_lang_detect.py -v
  ```
- [ ] Translation round-trip (eng → hin → eng) preserves meaning
  ```bash
  pytest tests/test_translation.py -v
  ```
- [ ] Tamil query routed through translation pipeline end-to-end
  ```bash
  curl -s -X POST http://localhost:8001/api/chat \
    -H "Content-Type: application/json" \
    -d "{\"farmer_id\": \"$FARMER_ID\", \"message\": \"நெல் பயிருக்கு எவ்வளவு தண்ணீர் தேவை?\", \"session_id\": null}" \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('lang:', r['lang']); print(r['text'][:200])"
  # Expected: lang starts with "tam_" and response text is in Tamil script
  ```

---

## Summary of Breaking Issues (must fix before merge)

| # | Issue | Severity | Status | Fix Location |
|---|---|---|---|---|
| 1 | **Socket.io vs raw WebSocket** — incompatible protocols | 🔴 Critical | ✅ Fixed | `ui/src/api/socket.js` replaced with lazy native WebSocket + queue |
| 2 | **Chat stub never wired** — frontend receives stub response only | 🔴 Critical | ✅ Fixed | `app/routes/chat.py` proxies to `AGENT_SERVICE_URL` |
| 3 | **`lang_pref` constraint in DB** — DB rejects 3 new languages | 🟠 High | ✅ Fixed | `01_schema.sql` has all 9 codes |
| 3a | **`lang_pref` Pydantic `Literal`** — API returns 422 for `ben_Beng`/`kan_Knda`/`mal_Mlym` | 🟠 High | ❌ Open | `app/schemas/farmer.py` `LangPref` + §2.2 |
| 4 | **Duplicate `docker-compose.yml`** — port 8000 and 5432 collide | 🟠 High | ✅ Fixed | unified compose with chroma/chroma-mcp/api/agent |
| 5 | **Frontend streaming not handled** — `useChat.js` expects single event | 🟠 High | ✅ Fixed | `useChat.js` handles token/phase/final/error frames |
| 6 | **RAG wiring** — `chroma-mcp` must be in `MCP_SERVER_URLS`; `vector-mcp` removed | 🔴 Critical | ✅ Fixed | `MCP_SERVER_URLS=http://db-mcp:9101,http://chroma-mcp:9103` |
| 7 | **Translation singleton not instantiated at startup** — constructing per-request loads 2 GB twice | 🟠 High | ✅ Fixed | `main.py` startup loads both singletons in thread executor; `builtin.py` uses local service, falls back to HF API |
| 8 | **`lang_detect.py` covers only 6 of 9 languages** — Bengali/Kannada/Malayalam fall back silently to English | 🟡 Medium | ❌ Open | `api/services/lang_detect.py` + §7.5 |
| 9 | **ChromaDB not bootstrapped** — `./data/chromadb` must exist before `docker compose up` | 🔴 Critical | ⚠️ Prerequisite | run `python -m ingestion.ingest_to_chromadb` on host first + §7.6 |
| 10 | **`requirements.txt` conflict** — four branches each define overlapping dependency files | 🟠 High | ✅ Fixed | `pyproject.toml` `[mcp-servers]` pins `chromadb==1.5.9`, `sentence-transformers>=3.0` |
| 11 | **Agent port conflict** — agent `docker-compose.yml` still exposes `ports: ["8000:8000"]` | 🔴 Critical | ✅ Fixed | removed duplicate `ports: ["8000:8000"]`; added `command: uvicorn ... --port 8001` |
| 12 | **`chromadb==1.5.9` must be pinned** — newer versions cannot read on-disk schema v10 | 🔴 Critical | ✅ Fixed | `pyproject.toml` `[mcp-servers]` has `chromadb==1.5.9` |
| 13 | **Embedding model changed** — store built with `paraphrase-multilingual-MiniLM-L12-v2`; any other model produces mismatched vectors | 🔴 Critical | ✅ Fixed | `CHROMA_EMBED_MODEL` set correctly in `chroma-mcp` service |
