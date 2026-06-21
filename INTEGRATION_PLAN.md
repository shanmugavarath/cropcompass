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

## Phase 7 — Shanu/RAG Integration

### 7.0 What the branch adds

`Shanu/RAG` introduces three runtime services and a one-time data pipeline:

| Module | Path | Role at runtime |
|---|---|---|
| RAG retriever | `api/services/rag.py` | Called by the agent's MCP tool to fetch crop-advisory chunks from ChromaDB |
| Translation service | `api/services/translation.py` | Translates farmer queries → English (for retrieval) and agent responses → farmer's language |
| Language detection | `api/services/lang_detect.py` | Detects script/language of incoming message; handles Hinglish code-switching |
| Ingestion pipeline | `ingestion/` | **Run once** (or on new data) to build `data/chromadb/`; not in the request path |

### 7.1 Conflict analysis

| File | Conflict Type | Resolution |
|---|---|---|
| `requirements.txt` | imd-scraper and Shanu/RAG both define one; agentic_solution has its own | Merge into a single root `requirements.txt` (see §7.2) |
| `.gitignore` | Minor line change — Shanu/RAG adds `data/chromadb/`, `data/raw/`, `data/*.json` | Accept Shanu/RAG additions; ensure `data/` artifacts are excluded globally |
| `ingestion/imd_scraper.py` | Both imd-scraper and Shanu/RAG include an IMD scraper | Shanu/RAG's version feeds ChromaDB; imd-scraper's version feeds PostgreSQL — keep **both** under a shared `ingestion/` package (they don't overlap at the function level) |

No conflicts expected in `api/services/` — that directory does not exist in any other branch.

### 7.2 Merge `requirements.txt`

After merging all four branches, produce a single top-level `requirements.txt` that unions all dependencies. Minimum set of additions from `Shanu/RAG`:

```
# RAG / embeddings
chromadb>=0.5.0
sentence-transformers>=2.7.0
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

> **GPU note:** `torch` defaults to a CPU wheel. On the agent container (which runs inference),
> install torch from `https://pytorch.org` with the matching CUDA index URL before
> `pip install -r requirements.txt`.

### 7.3 Wire RAG into the agent service

`api/services/rag.query_knowledge_base()` has a **frozen signature** that Member 3's MCP tool
definitions depend on. Do not rename or reorder its parameters.

In `agentic_solution`, the vector MCP server (`mcp_servers/vector_server/`) currently embeds
its own retrieval logic against pgvector. After merging, the agent can call
`query_knowledge_base()` directly (Option A) or continue using the vector MCP (Option B):

**Option A — direct Python import (recommended):** Mount `api/services/rag.py` into the agent
container and call it from `AgentRunner`. Requires the `data/chromadb/` volume to be mounted
in the agent container.

```python
# Inside AgentRunner.run() or a new MCP tool handler:
from api.services.rag import query_knowledge_base

chunks = query_knowledge_base(
    crop=farmer.crop,
    soil=farmer.soil_type,
    query=translated_query,   # English (after translation step below)
    k=5,
)
context = "\n\n".join(c["text"] for c in chunks)
```

**Option B — keep vector MCP:** Leave the pgvector-based MCP in place for session history /
structured data, and call `query_knowledge_base()` only for unstructured agronomic knowledge.
Both can coexist — they use different stores (ChromaDB vs pgvector).

### 7.4 Wire translation into the query/response pipeline

The translation service operates in two directions:

```
Farmer query (any Indic language)
    → lang_detect.detect_with_codeswitching()   # e.g. "tam_Taml"
    → TranslationService(INDIC_EN).translate()  # Tamil → English
    → RAG retrieval (English query hits both corpora)
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

### 7.5 Language detection: extend `lang_detect.py` to cover all 9 frontend languages

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

### 7.6 Mount ChromaDB volume in Docker Compose

Add a named volume for the ChromaDB store and mount it into the agent container
(and optionally an ingestion service for one-time data loading):

```yaml
# docker-compose.yml additions

services:
  agent:
    # ... existing definition ...
    volumes:
      - chromadb_data:/app/data/chromadb
    environment:
      # existing envs +
      INDIC_EN_MODEL: ai4bharat/indictrans2-indic-en-1B
      EN_INDIC_MODEL: ai4bharat/indictrans2-en-indic-1B

  ingest:                          # run once: docker compose run --rm ingest
    build: { context: ., dockerfile: Dockerfile.agent }
    command: python -m ingestion.ingest_to_chromadb
    volumes:
      - chromadb_data:/app/data/chromadb
      - ./data/raw:/app/data/raw:ro
    depends_on: []                 # no DB dependency — ChromaDB is file-based

volumes:
  chromadb_data:
```

> **Data bootstrapping:** Before the first `docker compose up`, run the ingestion pipeline on
> the host (or via `docker compose run --rm ingest`) to populate `data/chromadb/`. The volume
> is then shared between the `ingest` and `agent` containers. The `data/raw/` SAU OCR JSON
> files must be present on the host at `data/raw/SAU_ocr_output/`.

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
  # Expected: {"tools": [...]} — list must include db_query, vector_search, translate_output
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

### 9.12 RAG pipeline

- [ ] RAG retrieval precision ≥ 0.70 on 25-query validation set
  ```bash
  pytest tests/test_rag.py -v
  ```
- [ ] RAG single-query latency < 200 ms
  ```bash
  CROPCOMPASS_LATENCY_MS=200 pytest tests/test_latency.py -v -k rag
  ```
- [ ] `query_knowledge_base` returns ≥ 1 chunk
  ```python
  # python3 -c
  from api.services.rag import query_knowledge_base
  chunks = query_knowledge_base("rice", "clay", "when to irrigate", k=5)
  assert len(chunks) >= 1, f"Expected chunks, got {chunks}"
  print(f"OK — {len(chunks)} chunks returned")
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

| # | Issue | Severity | Fix Location |
|---|---|---|---|
| 1 | **Socket.io vs raw WebSocket** — incompatible protocols | 🔴 Critical | `ui/src/api/socket.js`, `ui/src/hooks/useChat.js` |
| 2 | **Chat stub never wired** — frontend receives stub response only | 🔴 Critical | `app/routes/chat.py` |
| 3 | **`lang_pref` constraint** — DB rejects 3 new languages | 🟠 High | `db/schema.sql` |
| 4 | **Duplicate `docker-compose.yml`** — port 8000 and 5432 collide | 🟠 High | merge into unified compose |
| 5 | **Frontend streaming not handled** — `useChat.js` expects single event | 🟠 High | `ui/src/hooks/useChat.js` |
| 6 | **RAG not wired into agent** — `query_knowledge_base()` is never called at request time | 🔴 Critical | `agentic_solution` AgentRunner + §7.3 |
| 7 | **Translation singleton not instantiated at startup** — constructing per-request loads 2 GB twice | 🟠 High | agent `main.py` startup + §7.4 |
| 8 | **`lang_detect.py` covers only 6 of 9 languages** — Bengali/Kannada/Malayalam fall back silently to English | 🟡 Medium | `api/services/lang_detect.py` + §7.5 |
| 9 | **ChromaDB volume not mounted** — agent container has no access to `data/chromadb/` | 🔴 Critical | `docker-compose.yml` + §7.6 |
| 10 | **`requirements.txt` conflict** — four branches each define overlapping dependency files | 🟠 High | merge into single root `requirements.txt` + §7.2 |
