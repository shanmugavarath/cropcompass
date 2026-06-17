# CropCompass — Member 1 (Data Engineer) SPEC

**Role:** Data Engineer  
**Work Streams:** WS1 (Tasks 1.1, 1.3, 1.4) + WS6 (Tasks 6.1, 6.2)  
**Sprint:** 4 weeks · June 2026  
**Stack:** FastAPI · SQLAlchemy 2.x async · PostgreSQL 15 + pgvector · APScheduler · structlog

---

## Table of Contents

1. [Project Context](#1-project-context)
2. [Task 6.1 — System Architecture & API Design](#2-task-61--system-architecture--api-design)
3. [Task 6.2 — Model Hosting & Compute Setup](#3-task-62--model-hosting--compute-setup)
4. [Task 1.1 — IMD GKMS Advisory Ingestion Pipeline](#4-task-11--imd-gkms-advisory-ingestion-pipeline)
5. [Task 1.3 — Farmer Profile & Context Schema](#5-task-13--farmer-profile--context-schema)
6. [Task 1.4 — Data Refresh & Staleness Handling](#6-task-14--data-refresh--staleness-handling)
7. [Do's and Don'ts](#7-dos-and-donts)
8. [Acceptance Criteria Summary](#8-acceptance-criteria-summary)
9. [Environment Setup](#9-environment-setup)
10. [Testing Checklist](#10-testing-checklist)

---

## 1. Project Context

CropCompass is a **multilingual agentic advisory system** for Indian farmers. Farmers type queries in any of 6 Indic languages; the system fetches IMD weather forecasts, retrieves ICAR agronomic knowledge, and responds via a Claude-powered agent with translated recommendations.

### System Architecture (overview)

```
Farmer (browser)
  → Web Chat UI (React/Vite)        [Member 4 — WS4]
    → FastAPI + Socket.IO           [Member 1 — WS6]
      → AgentRunner                 [Member 3 — WS2]
        → MCP Tools: get_farmer_profile / fetch_forecast / query_knowledge_base
        → Planner (claude-sonnet-4-6) → Verifier → IndicTrans2 (translate)
      ← AgentResponse
    ← WebSocket response
  ← Indic text + citations
```

Member 1 owns **the entire data foundation** — the database layer, ingestion pipelines, farmer CRUD, and infrastructure that every other member depends on.

### Key Constraints

| Constraint | Value |
|------------|-------|
| IndicTrans2 latency target | < 2s per call |
| LLM (claude-sonnet-4-6) latency target | < 8s per response |
| Full pipeline latency target | < 15s end-to-end |
| IMD districts supported | 37 (across 11 states) |
| IMD advisory freshness | 48 hours max |
| Farmer profile freshness | 90 days max |
| Supported languages | hin_Deva, tam_Taml, tel_Telu, mar_Deva, pan_Guru, eng_Latn |

---

## 2. Task 6.1 — System Architecture & API Design

### What it is

Define how all 5 members' components connect. Document the architecture diagram and produce FastAPI route stubs that other members can code against.

### Files Owned

| File | Purpose | Status |
|------|---------|--------|
| `architecture.md` | Mermaid component + sequence diagrams | DONE |
| `app/main.py` | FastAPI app entry point + lifespan | DONE |
| `app/routes/profile.py` | POST/GET/PATCH /api/profile | DONE |
| `app/routes/forecast.py` | GET /api/forecast/{district} | DONE |
| `app/routes/chat.py` | POST /api/chat stub for Member 3 | DONE |
| `openapi.yaml` | Machine-readable API spec | **PENDING** |

### Detailed Steps

#### Step 1 — Architecture Diagram (`architecture.md`)

1. Draw a `graph TD` Mermaid diagram with labelled subgraphs for each Work Stream (UI, API, AgentLoop, DataLayer, MLLayer, Infra).
2. Add a `sequenceDiagram` for the end-to-end request/response flow (Farmer → UI → API → Agent → LLM → DB → RAG → Trans → UI → Farmer).
3. Add a `graph LR` for the Docker deployment topology (api:8000, db:5432, vectordb:8001).
4. Document latency targets inline: IndicTrans2 < 2s, LLM < 8s, pipeline < 15s.

#### Step 2 — FastAPI Routes

Route stubs must be created **before** other members start coding so they have a contract to code against.

**POST /api/profile** (`app/routes/profile.py`)
```
body: FarmerCreate  →  201 Created  →  FarmerResponse
```
- Persist to `farmers` table via SQLAlchemy async session.
- Return the full farmer object (including UUID).

**GET /api/profile/{farmer_id}** (`app/routes/profile.py`)
```
path: UUID  →  200 OK  →  FarmerResponse
                404 Not Found (if no row)
```

**PATCH /api/profile/{farmer_id}** (`app/routes/profile.py`)
```
body: FarmerUpdate (all optional)  →  200 OK  →  FarmerResponse
```
- Only update fields that are present in the request body (`model_dump(exclude_unset=True)`).
- Always update `updated_at` to `datetime.now(timezone.utc)`.

**GET /api/forecast/{district}** (`app/routes/forecast.py`)
```
path: district name (case-insensitive)  →  200 OK  →  ForecastResponse
                                           404 Not Found (no data for district)
```
- Query `imd_advisories` with `WHERE LOWER(district) = LOWER(:district)`.
- Return the most recent record ordered by `bulletin_date DESC, fetched_at DESC`.
- Include `is_stale` flag in response so consumers know data freshness.

**POST /api/chat** (`app/routes/chat.py`)
```
body: {farmer_id, message, session_id?}  →  200 OK  →  {message, session_id}
```
- This is a **stub** for Member 3 (Agent Engineer) to implement.
- Return a `{"message": "stub", "session_id": uuid}` placeholder.
- Do not add business logic here.

#### Step 3 — FastAPI App Entry Point (`app/main.py`)

1. Use `@asynccontextmanager` lifespan to start/stop APScheduler:
   ```python
   scheduler = build_scheduler()
   scheduler.start()
   yield
   scheduler.shutdown(wait=False)
   ```
2. Add `CORSMiddleware` with `allow_origins=["*"]` (development mode — restrict in production).
3. Register all three routers: `profile`, `forecast`, `chat`.
4. Add `GET /health` endpoint returning `{"status": "ok"}`.

#### Step 4 — OpenAPI Spec (`openapi.yaml`) — **PENDING**

1. Generate base spec from the running FastAPI app:
   ```bash
   curl http://localhost:8000/openapi.json | python3 -m json.tool > openapi.json
   python3 -c "import json, yaml, sys; yaml.dump(json.load(open('openapi.json')), open('openapi.yaml','w'), default_flow_style=False)"
   ```
2. Validate with redocly:
   ```bash
   npx @redocly/cli lint openapi.yaml
   ```
3. Manually add `examples` for each request/response body.
4. Fix any lint warnings before marking done.

### Acceptance Criteria — Task 6.1

- [ ] `architecture.md` renders without errors in GitHub markdown preview.
- [ ] All 5 routes exist and return correct status codes (test with curl — see §10).
- [ ] `GET /health` returns `{"status": "ok"}`.
- [ ] APScheduler starts when uvicorn starts (confirm in logs: `scheduler_started`).
- [ ] `openapi.yaml` passes `redocly lint` with zero errors.

---

## 3. Task 6.2 — Model Hosting & Compute Setup

### What it is

Set up the infrastructure that every other member's code runs on — Docker services, environment variables, and external API connectivity.

### Files Owned

| File | Purpose | Status |
|------|---------|--------|
| `.env.example` | Env var template with all required keys | DONE |
| `docker-compose.yml` | Three-service stack (api, db, vectordb) | DONE |
| `Dockerfile` | Python 3.12-slim image for the api container | DONE |
| `app/config.py` | Pydantic-settings class (reads .env) | DONE |
| `infra/install_docker.sh` | Docker Engine installer for WSL2 | DONE |

### Detailed Steps

#### Step 1 — Environment Variables (`.env.example`)

Must contain exactly these variables:

```
POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD
DATABASE_URL                        # postgresql+asyncpg://...
ANTHROPIC_API_KEY                   # sk-ant-...
HF_API_KEY                          # hf_...
HF_INFERENCE_ENDPOINT               # https://api-inference.huggingface.co/models/ai4bharat/indictrans2-en-indic-1B
CHROMA_HOST / CHROMA_PORT
LOG_LEVEL
IMD_STALENESS_HOURS=48
FARMER_STALENESS_DAYS=90
ICAR_STALENESS_DAYS=180
IMD_GKMS_BASE_URL
IMD_SCRAPER_CRON_HOUR=6
IMD_SCRAPER_CRON_MINUTE=0
IMD_SCRAPER_TIMEZONE=Asia/Kolkata
IMD_DEV_MOCK=false                  # set true in dev to skip live IMD fetch
```

#### Step 2 — Docker Compose (`docker-compose.yml`)

Three services:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `db` | `pgvector/pgvector:pg15` | 5432 | PostgreSQL 15 + pgvector |
| `vectordb` | `chromadb/chroma:latest` | 8001→8000 | ChromaDB (Member 2 uses) |
| `api` | Built from `Dockerfile` | 8000 | FastAPI app |

Critical details:
- Mount `./db/schema.sql` as `/docker-entrypoint-initdb.d/01_schema.sql:ro` on the `db` service so the schema auto-loads on first start.
- `api` depends on `db` condition `service_healthy` and `vectordb` condition `service_healthy`.
- Pass `DATABASE_URL` to api using the Docker network hostname (`@db:5432`, not `@localhost:5432`).

#### Step 3 — Pydantic Settings (`app/config.py`)

- Use `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_file=".env", extra="ignore")`.
- Expose `imd_dev_mock: bool = Field(default=False)` — this controls whether the scraper hits the real IMD or uses synthetic data.
- All fields should have safe defaults so the app can start without a `.env` file.

#### Step 4 — HuggingFace Inference API Decision

- **Primary:** HuggingFace Inference API (`ai4bharat/indictrans2-en-indic-1B`) — avoids GPU setup complexity.
- **Fallback:** Local GPU inference if HF API latency exceeds 2s consistently.
- This decision is documented in `.env.example` comments and `architecture.md`.
- Member 1 only needs to configure the endpoint in `app/config.py`; the actual translation call is owned by Member 5 (WS3 — Multilingual Pipeline).

### Acceptance Criteria — Task 6.2

- [ ] `docker compose up -d` starts all three containers without errors.
- [ ] `docker exec cropcompass-db psql -U cropcompass -d cropcompass -c "SELECT extname FROM pg_extension;"` shows `vector`, `uuid-ossp`, `pg_trgm`.
- [ ] All tables from `db/schema.sql` are present (`\dt` shows 4 tables).
- [ ] `curl http://localhost:8001/api/v1/heartbeat` returns 200 (ChromaDB up).
- [ ] `docker ps` shows all three containers with status `Up`.
- [ ] `.env.example` contains all keys; `.env` (gitignored) has real API keys filled in.

---

## 4. Task 1.1 — IMD GKMS Advisory Ingestion Pipeline

### What it is

Scrape district-level weather advisories from the IMD agromet portal daily at 6AM IST, parse rainfall probability and temperature data, and upsert into PostgreSQL.

### Files Owned

| File | Purpose | Status |
|------|---------|--------|
| `db/imd_advisory.sql` | IMD advisory table DDL (standalone) | DONE |
| `app/models/imd_advisory.py` | SQLAlchemy ORM: `IMDAdvisory`, `IMDDistrictRef` | DONE |
| `app/models/pipeline_run.py` | SQLAlchemy ORM: `PipelineRun` audit table | DONE |
| `pipeline/imd_scraper.py` | Scraper + parser + upsert + mock mode | DONE |
| `pipeline/scheduler.py` | APScheduler cron wrapper | DONE |

### Detailed Steps

#### Step 1 — Database Table (`db/imd_advisory.sql` + `db/schema.sql`)

The `imd_advisories` table must have:

| Column | Type | Constraint |
|--------|------|-----------|
| `id` | SERIAL PRIMARY KEY | auto |
| `district` | VARCHAR(100) NOT NULL | — |
| `state` | VARCHAR(100) NOT NULL | — |
| `bulletin_date` | DATE NOT NULL | — |
| `rainfall_prob` | DECIMAL(5,4) | 0.0000–1.0000 |
| `rainfall_category` | VARCHAR(10) | CHECK IN ('low','normal','high') |
| `min_temp_c` | DECIMAL(5,2) | — |
| `max_temp_c` | DECIMAL(5,2) | — |
| `humidity_pct` | DECIMAL(5,2) | — |
| `wind_speed_kmh` | DECIMAL(6,2) | — |
| `wind_direction` | VARCHAR(20) | — |
| `season_outlook` | TEXT | — |
| `advisory_text` | TEXT | — |
| `source_url` | VARCHAR(1000) | — |
| `fetched_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | — |
| `is_stale` | BOOLEAN NOT NULL DEFAULT FALSE | — |

Unique constraint: `UNIQUE (district, bulletin_date)` named `uq_advisory_district_date`.

Reference table `imd_districts_ref` must be seeded with **≥ 37 districts** across at least 8 states.

#### Step 2 — HTTP Scraper (`pipeline/imd_scraper.py`)

**Flow:**
```
IMDDistrictRef.is_active=True rows
  → for each district (semaphore=5 concurrent):
      → fetch_district(client, district, state)
          → if IMD_DEV_MOCK=true: return _mock_advisory()
          → else: GET https://mausam.imd.gov.in/responsive/agromet_adv_ser_district_current_en.php
                    params={state, dist}
                  → retry up to 3× on TimeoutException/ConnectError
                  → parse_advisory_html(html, district, state, source_url)
      → upsert_advisory(session, row)
  → update pipeline_run record with outcome
```

**`parse_advisory_html()` logic:**
1. Use BeautifulSoup with `lxml` parser.
2. Walk all `<tr>` rows and match labels: `rainfall`, `min temp`, `max temp`, `humidity`, `wind speed`, `wind direction`.
3. Convert percentage rainfall to decimal (74% → 0.7400).
4. Derive `rainfall_category`: < 0.4 → `low`, 0.4–0.7 → `normal`, > 0.7 → `high`.
5. Try to extract `bulletin_date` from page headings; fall back to `date.today()`.
6. Return `None` if page is blank or an error page (caller adds district to `failed[]`).

**`upsert_advisory()` logic:**
- Use `insert(...).on_conflict_do_update(constraint="uq_advisory_district_date", set_=...)`.
- Update all weather fields and reset `is_stale=False` on conflict.
- Use `RETURNING xmax` to detect INSERT (xmax=0) vs UPDATE (xmax>0).

**Concurrency:** `asyncio.Semaphore(settings.imd_scraper_concurrency)` (default: 5).

**Retry:** `tenacity.retry` with exponential backoff (min=2s, max=10s, 3 attempts) on `httpx.TimeoutException` and `httpx.ConnectError`.

**Headers:** Send browser-like `User-Agent`, `Accept`, `Accept-Language`, `Referer` to avoid 403 blocks.

#### Step 3 — Mock Mode

Set `IMD_DEV_MOCK=true` in `.env` to bypass the real IMD scrape. The mock generates reproducible data seeded on `f"{district}{date.today()}"` so the same district gets consistent values on the same day. Use this during development to avoid IMD network dependency.

#### Step 4 — Scheduler (`pipeline/scheduler.py`)

- Use `APScheduler 3.x` with `AsyncIOScheduler`.
- Register two jobs:
  - `imd_scraper`: `CronTrigger(hour=6, minute=0, timezone="Asia/Kolkata")`
  - `staleness_check`: `CronTrigger(hour=6, minute=30, timezone="Asia/Kolkata")`
- Set `misfire_grace_time=3600` so jobs still run if the container was briefly down.
- The scheduler is also embedded in FastAPI lifespan (`app/main.py`) — only one scheduler instance runs at a time.

#### Step 5 — Real IMD URL (production TODO)

The IMD GKMS portal is JavaScript-rendered. To find the correct GET params:
1. Open Chrome → `https://mausam.imd.gov.in/responsive/agromet_adv_ser_district_current_en.php`.
2. DevTools → Network tab → select a state → filter XHR.
3. Copy the request URL and params.
4. Update `settings.imd_gkms_base_url` and `params={"state": ..., "dist": ...}` in `fetch_district()`.

### Acceptance Criteria — Task 1.1

- [ ] `IMD_DEV_MOCK=true python3 -m pipeline.imd_scraper` completes with `district_count=37, new_records=37, failed_districts=[], status=success`.
- [ ] `pipeline_runs` table has one row with `status='success'` after the run.
- [ ] All 37 districts have a row in `imd_advisories` with `rainfall_prob` between 0 and 1.
- [ ] Re-running the scraper on the same day results in `updated_records=37, new_records=0` (upsert working).
- [ ] A district that fails HTTP returns it in `failed_districts[]` without crashing the whole run.
- [ ] Scheduler logs `scheduler_started` on uvicorn boot.

---

## 5. Task 1.3 — Farmer Profile & Context Schema

### What it is

Define the farmer profile data model and expose CRUD API endpoints that the frontend (Member 4) and Agent (Member 3) can use to read and write farmer context.

### Files Owned

| File | Purpose | Status |
|------|---------|--------|
| `db/farmer_profile.sql` | Farmer table DDL (standalone) | DONE |
| `app/models/farmer.py` | SQLAlchemy `Farmer` ORM | DONE |
| `app/schemas/farmer.py` | Pydantic `FarmerCreate`, `FarmerUpdate`, `FarmerResponse` | DONE |
| `app/routes/profile.py` | REST CRUD endpoints | DONE |

### Detailed Steps

#### Step 1 — Database Table (`db/farmer_profile.sql`)

The `farmers` table must have:

| Column | Type | Notes |
|--------|------|-------|
| `farmer_id` | UUID PRIMARY KEY | `DEFAULT uuid_generate_v4()` |
| `name` | VARCHAR(200) nullable | optional |
| `phone` | VARCHAR(20) nullable | optional |
| `district` | VARCHAR(100) NOT NULL | for IMD forecast lookup |
| `state` | VARCHAR(100) NOT NULL | — |
| `soil_type` | VARCHAR(50) nullable | CHECK enum |
| `crop_variety` | VARCHAR(100) nullable | CHECK enum |
| `growth_stage` | VARCHAR(50) nullable | CHECK enum |
| `lang_pref` | VARCHAR(20) NOT NULL DEFAULT 'eng_Latn' | CHECK 6 FLORES-200 codes |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | — |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | auto-updated by trigger |
| `is_stale` | BOOLEAN NOT NULL DEFAULT FALSE | set by `mark_stale_records()` |

**DB-level enum constraints:**
- `lang_pref IN ('hin_Deva','tam_Taml','tel_Telu','mar_Deva','pan_Guru','eng_Latn')`
- `soil_type IN ('loamy','clay','sandy','black','red','alluvial','laterite')` (nullable)
- `crop_variety IN ('rice','wheat','maize','cotton','soybean','sugarcane','pulses','vegetables')` (nullable)
- `growth_stage IN ('sowing','germination','vegetative','flowering','fruiting','harvesting')` (nullable)

**Auto-update trigger:**
```sql
CREATE TRIGGER trg_farmers_updated_at
    BEFORE UPDATE ON farmers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

#### Step 2 — SQLAlchemy ORM (`app/models/farmer.py`)

- Use `sqlalchemy.orm.Mapped` + `mapped_column` (SQLAlchemy 2.x declarative style).
- UUID primary key using `UUID(as_uuid=True)` from `sqlalchemy.dialects.postgresql`.
- Mirror all CHECK constraints in `__table_args__` so constraint names match the DB exactly.

#### Step 3 — Pydantic Schemas (`app/schemas/farmer.py`)

Three schemas:

**`FarmerCreate`** — for POST body
- `district` and `state` are required (`min_length=2`).
- All other fields are optional.
- `lang_pref` defaults to `"eng_Latn"`.

**`FarmerUpdate`** — for PATCH body
- All fields optional (partial update).
- Do not include `farmer_id`, `created_at`, `updated_at`, `is_stale` — those are not user-updatable.

**`FarmerResponse`** — for all responses
- `model_config = {"from_attributes": True}` to allow ORM object → Pydantic conversion.
- Include `farmer_id` (UUID), `created_at`, `updated_at`, `is_stale`.

Define `SUPPORTED_LANGS: list[str]` at module level — other members import this to validate language codes:
```python
SUPPORTED_LANGS = ["hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru", "eng_Latn"]
```

#### Step 4 — CRUD Routes (`app/routes/profile.py`)

- `POST /api/profile` → `status_code=201`.
- `GET /api/profile/{farmer_id}` → `404` if not found.
- `PATCH /api/profile/{farmer_id}` → `404` if not found, partial update only.
- All three use `Depends(get_session)` for async DB session injection.
- PATCH must manually set `farmer.updated_at = datetime.now(timezone.utc)` because the SQLAlchemy trigger runs at DB level, not ORM level, and the ORM object won't reflect it automatically without `refresh`.

### Acceptance Criteria — Task 1.3

- [ ] `POST /api/profile` with valid body returns `201` and a UUID `farmer_id`.
- [ ] `POST /api/profile` with invalid `lang_pref` returns `422` with a message listing the 6 allowed values.
- [ ] `POST /api/profile` with invalid `soil_type` returns `422`.
- [ ] `GET /api/profile/{valid_uuid}` returns `200` with all fields.
- [ ] `GET /api/profile/{nonexistent_uuid}` returns `404`.
- [ ] `PATCH /api/profile/{uuid}` with only `{"soil_type": "clay"}` updates only that field, leaving others unchanged.
- [ ] `PATCH /api/profile/{uuid}` updates `updated_at` to the current time.
- [ ] `SUPPORTED_LANGS` in `app/schemas/farmer.py` has exactly 6 entries.

---

## 6. Task 1.4 — Data Refresh & Staleness Handling

### What it is

Define staleness thresholds and implement the cron job + SQL function that marks stale records, plus the conflict policy for how the upsert handles duplicate data.

### Files Owned

| File | Purpose | Status |
|------|---------|--------|
| `db/schema.sql` | `mark_stale_records()` SQL function | DONE |
| `pipeline/staleness.py` | Python cron wrapper for the SQL function | DONE |
| `app/config.py` | Staleness threshold env vars | DONE |

### Detailed Steps

#### Step 1 — Staleness Thresholds

| Data Type | Threshold | When `is_stale` is set |
|-----------|-----------|----------------------|
| `imd_advisories` | 48 hours | `fetched_at < NOW() - INTERVAL '48 hours'` |
| `farmers` | 90 days | `updated_at < NOW() - INTERVAL '90 days'` |
| ICAR documents | 180 days | (owned by Member 2 — Member 1 defines the constant only) |

These thresholds are configurable via env vars: `IMD_STALENESS_HOURS`, `FARMER_STALENESS_DAYS`, `ICAR_STALENESS_DAYS`.

#### Step 2 — SQL Function (`mark_stale_records()`)

```sql
CREATE OR REPLACE FUNCTION mark_stale_records()
RETURNS JSONB AS $$
DECLARE
    advisory_count INT;
    farmer_count   INT;
BEGIN
    UPDATE imd_advisories
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND fetched_at < NOW() - INTERVAL '48 hours';
    GET DIAGNOSTICS advisory_count = ROW_COUNT;

    UPDATE farmers
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND updated_at < NOW() - INTERVAL '90 days';
    GET DIAGNOSTICS farmer_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'marked_stale_advisories', advisory_count,
        'marked_stale_farmers',    farmer_count,
        'run_at',                  NOW()
    );
END;
$$ LANGUAGE plpgsql;
```

The function returns a JSONB payload that `staleness.py` logs via structlog.

#### Step 3 — Python Staleness Cron (`pipeline/staleness.py`)

1. Create a `PipelineRun` row with `status='running'`.
2. Call `SELECT mark_stale_records()` via `session.execute(text(...))`.
3. Update the run row: `status='success'`, `finished_at`, `log_payload=payload`.
4. On exception: `status='failed'`, `error_message=str(e)`, then re-raise.
5. Log `marked_stale_advisories` and `marked_stale_farmers` via structlog.

#### Step 4 — Conflict Policy (upsert in `imd_scraper.py`)

When the scraper fetches a district that already has a record for today's date:
- **ON CONFLICT** (`district`, `bulletin_date`): update all weather fields, reset `is_stale=False`, and update `fetched_at` to the current time.
- This ensures the most recently fetched data always wins.
- The `RETURNING xmax` trick distinguishes INSERT (xmax=0) from UPDATE (xmax>0) so the pipeline can log `new_records` vs `updated_records` accurately.

#### Step 5 — structlog JSON Logging

Every pipeline run must emit these structured log fields:

| Logger call | Fields |
|-------------|--------|
| `run_imd_pipeline()` done | `district_count`, `new_records`, `updated_records`, `failed_districts`, `status` |
| `run_staleness_check()` done | `marked_stale_advisories`, `marked_stale_farmers` |
| Per-district upsert | `district`, `action` (new/updated), `rainfall_prob`, `rainfall_category` |

Use `structlog.get_logger()` and `.bind(pipeline=...)` for context propagation.

### Acceptance Criteria — Task 1.4

- [ ] Running `python3 -m pipeline.staleness` returns a JSONB dict with `marked_stale_advisories` and `marked_stale_farmers` keys.
- [ ] Setting `fetched_at = NOW() - INTERVAL '49 hours'` manually on a row and running staleness marks it `is_stale=TRUE`.
- [ ] `pipeline_runs` table records both `imd_scraper` and `staleness_check` runs with `status='success'`.
- [ ] Scraper log output contains `district_count`, `new_records`, `failed_districts` as JSON keys (not free-form strings).
- [ ] Re-running the scraper on existing data sets `is_stale=FALSE` on previously stale records.
- [ ] `app/config.py` exposes `imd_staleness_hours`, `farmer_staleness_days`, `icar_staleness_days` as configurable settings.

---

## 7. Do's and Don'ts

### Do's

**Database**
- DO use `ON CONFLICT DO UPDATE` (upsert) instead of DELETE + INSERT — avoids race conditions and preserves audit history.
- DO use partial indexes (`WHERE is_stale = TRUE`) on staleness columns — much faster than full table scans.
- DO always include `fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` on ingested data tables.
- DO use `uuid_generate_v4()` for farmer IDs — never integer sequences for user-facing keys.
- DO use `DECIMAL(5,4)` for rainfall probability (range 0.0000–1.0000) — floating point rounding causes silent data errors.
- DO mount `schema.sql` via `docker-entrypoint-initdb.d` — the schema auto-loads on fresh container creation.

**Python / FastAPI**
- DO use `SQLAlchemy 2.x` mapped column syntax (`Mapped[T]`, `mapped_column()`) — the old `Column()` style is deprecated.
- DO use `async_sessionmaker` + `AsyncSession` everywhere in routes and pipeline — never use synchronous SQLAlchemy in async code paths.
- DO use `model_dump(exclude_unset=True)` in PATCH handlers — only write fields the client actually sent.
- DO use `Depends(get_session)` for session injection in routes — never create sessions manually inside route functions.
- DO use `pydantic_settings.BaseSettings` for configuration — never read `os.environ` directly in application code.
- DO set `misfire_grace_time=3600` on all APScheduler jobs — daily crons must not be silently skipped if the container restarts at 6AM.

**Pipeline**
- DO use `asyncio.Semaphore` to cap concurrent IMD requests — the portal will rate-limit or block if you open 37 connections simultaneously.
- DO retry HTTP calls with `tenacity` (exponential backoff, 3 attempts) — IMD is a government portal and can be slow.
- DO run the scraper in `IMD_DEV_MOCK=true` mode during development — avoids real network dependency in CI and on local machines without VPN.
- DO log `failed_districts` as a list in the pipeline run record — makes debugging easy when some districts fail.
- DO use `RETURNING xmax` to detect INSERT vs UPDATE in upsert — more reliable than `rowcount` for distinguishing new records.

**Structlog**
- DO use `structlog.get_logger()` (not Python `logging`) — output must be JSON-parseable for downstream monitoring.
- DO call `.bind(pipeline=...)` at the top of each pipeline function — all subsequent log calls inherit the context.

**Env / Secrets**
- DO commit `.env.example` with placeholder values — never commit `.env` with real API keys.
- DO use `Field(default=False)` for boolean env vars — `pydantic_settings` parses `"true"`/`"false"` strings correctly.

---

### Don'ts

**Database**
- DON'T use `DROP TABLE IF EXISTS` in schema migrations — use `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ADD COLUMN IF NOT EXISTS` instead.
- DON'T store `lang_pref` as a free-text string without a CHECK constraint — invalid codes would silently corrupt translation downstream.
- DON'T skip the `uq_advisory_district_date` unique constraint — without it, duplicate rows for the same district+date will accumulate and confuse the staleness logic.
- DON'T use `FLOAT` or `REAL` for rainfall probability — use `DECIMAL(5,4)` to avoid floating-point precision errors.
- DON'T hard-code the 37 districts in Python — always read from the `imd_districts_ref` table so districts can be added/disabled without code changes.

**Python / FastAPI**
- DON'T create a new `engine` instance on every pipeline run — create once and `dispose()` at the end. Multiple engines cause connection pool exhaustion.
- DON'T use `session.execute()` without `await` — all SQLAlchemy 2.x async calls must be awaited.
- DON'T add business logic to the `POST /api/chat` stub — it belongs to Member 3; leave it as a placeholder.
- DON'T set `updated_at` via a default factory in SQLAlchemy — use the DB-level `BEFORE UPDATE` trigger so `updated_at` is accurate regardless of how the row is modified.
- DON'T catch bare `Exception` in routes — let FastAPI's exception handlers return proper 500 responses; only catch specific exceptions where recovery is possible.
- DON'T use `allow_origins=["*"]` in production — restrict to the known frontend origin.

**Pipeline**
- DON'T call `asyncio.run()` inside an already-running event loop — the scheduler runs inside FastAPI's event loop; use `asyncio.gather` or `await` instead.
- DON'T use `time.sleep()` in async code — use `await asyncio.sleep()` if delays are needed.
- DON'T commit the SQLAlchemy session inside `_process()` and also outside it — pick one boundary; the current design commits inside `_process()` per district.
- DON'T parse HTML with regex — always use BeautifulSoup; regex HTML parsing is fragile and breaks on attribute order changes.

**Infrastructure**
- DON'T run `docker compose up` as root — always add the user to the `docker` group first.
- DON'T skip the `healthcheck` on the `db` service — the `api` service must wait for PostgreSQL to be ready, not just started.
- DON'T mount `./` to `/app` with write access in production — use read-only mounts or bake files into the image.

**Code Style**
- DON'T add comments explaining what the code does — only explain WHY if there's a non-obvious constraint or workaround.
- DON'T add error handling for scenarios that can't happen — trust FastAPI's request validation and SQLAlchemy's type system.
- DON'T create new abstractions unless three or more call sites would benefit — single-use wrappers add complexity with no gain.

---

## 8. Acceptance Criteria Summary

| Task | Criterion | Measurement |
|------|-----------|-------------|
| **6.1** | All 5 routes return correct status codes | `curl` tests in §10 |
| **6.1** | APScheduler starts on uvicorn boot | Log: `scheduler_started` |
| **6.1** | `openapi.yaml` validates | `redocly lint openapi.yaml` exits 0 |
| **6.2** | Three Docker services up | `docker ps` shows 3 containers |
| **6.2** | pgvector + uuid-ossp + pg_trgm extensions active | `SELECT extname FROM pg_extension` |
| **6.2** | 4 tables present | `\dt` in psql |
| **1.1** | 37 districts loaded on first run | `new_records=37` in pipeline log |
| **1.1** | Re-run same day = updates only | `new_records=0, updated_records=37` |
| **1.1** | Failed district doesn't crash pipeline | District appears in `failed_districts[]` |
| **1.1** | `pipeline_runs` audit row created | Row with `status='success'` |
| **1.3** | POST /api/profile returns 201 + UUID | curl test |
| **1.3** | Invalid `lang_pref` returns 422 | curl test with `"lang_pref": "invalid"` |
| **1.3** | PATCH updates only sent fields | Before/after comparison |
| **1.3** | `SUPPORTED_LANGS` has 6 entries | `from app.schemas.farmer import SUPPORTED_LANGS; len(SUPPORTED_LANGS) == 6` |
| **1.4** | `mark_stale_records()` marks 48h-old advisories | Manual `fetched_at` update + staleness run |
| **1.4** | Staleness log has `marked_stale_advisories` key | structlog JSON output |
| **1.4** | Pipeline run record created for staleness check | `pipeline_runs` table row |

### Milestone M1 — End of Week 1

| Check | Target | Status |
|-------|--------|--------|
| IMD pipeline | ≥ 30 districts loaded | 37/37 ✅ |
| Farmer CRUD | `POST /api/profile` returns 201 | ✅ tested |
| DB healthy | PostgreSQL + pgvector running in Docker | ✅ running |

---

## 9. Environment Setup

### One-time setup (WSL2)

```bash
# 1. Install Docker Engine
bash infra/install_docker.sh
sudo usermod -aG docker $USER
# Close and reopen WSL2 terminal

# 2. Copy env file and fill in API keys
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY, HF_API_KEY

# 3. Start infrastructure (db + vectordb first, api after Dockerfile is ready)
docker compose up -d db vectordb

# 4. Verify PostgreSQL + pgvector
docker exec -it cropcompass-db psql -U cropcompass -d cropcompass \
  -c "SELECT extname FROM pg_extension;"

# 5. Verify tables
docker exec -it cropcompass-db psql -U cropcompass -d cropcompass -c "\dt"

# 6. Verify district seed data
docker exec -it cropcompass-db psql -U cropcompass -d cropcompass \
  -c "SELECT state, COUNT(*) FROM imd_districts_ref GROUP BY state ORDER BY state;"
```

### Daily development

```bash
# Start all services
docker compose up -d

# Run IMD pipeline with mock data (no real IMD network needed)
IMD_DEV_MOCK=true python3 -m pipeline.imd_scraper

# Run staleness check manually
python3 -m pipeline.staleness

# Start FastAPI server locally (with hot reload)
uvicorn app.main:app --reload --port 8000

# Run full api container via Docker
docker compose up -d api
```

### Makefile shortcuts

```bash
make verify-db        # shows extensions + tables
make check-districts  # shows 37 districts by state
make up               # docker compose up -d
make down             # docker compose down
make logs             # tail all container logs
```

---

## 10. Testing Checklist

Run these commands against a running server (`uvicorn app.main:app --port 8000`):

```bash
BASE="http://localhost:8000"

# Health check
curl -s $BASE/health
# Expected: {"status":"ok"}

# Create farmer profile
curl -s -X POST $BASE/api/profile \
  -H "Content-Type: application/json" \
  -d '{"district":"Chennai","state":"Tamil Nadu","lang_pref":"tam_Taml","crop_variety":"rice","soil_type":"clay"}' | python3 -m json.tool
# Expected: 201 with farmer_id UUID

# Save farmer_id for next tests
FARMER_ID="<uuid from above>"

# Get farmer profile
curl -s $BASE/api/profile/$FARMER_ID | python3 -m json.tool
# Expected: 200 with all fields

# Partial update
curl -s -X PATCH $BASE/api/profile/$FARMER_ID \
  -H "Content-Type: application/json" \
  -d '{"growth_stage":"flowering"}' | python3 -m json.tool
# Expected: 200, growth_stage=flowering, other fields unchanged

# 404 test
curl -s $BASE/api/profile/00000000-0000-0000-0000-000000000000
# Expected: 404

# Invalid lang_pref
curl -s -X POST $BASE/api/profile \
  -H "Content-Type: application/json" \
  -d '{"district":"Delhi","state":"Delhi","lang_pref":"hindi"}' | python3 -m json.tool
# Expected: 422

# Forecast (after running IMD pipeline)
curl -s $BASE/api/forecast/Chennai | python3 -m json.tool
# Expected: 200 with rainfall_prob, rainfall_category, is_stale=false

# Forecast case-insensitive
curl -s $BASE/api/forecast/chennai | python3 -m json.tool
# Expected: same 200 response

# Forecast 404
curl -s $BASE/api/forecast/UnknownCity
# Expected: 404

# Chat stub
curl -s -X POST $BASE/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"farmer_id\":\"$FARMER_ID\",\"message\":\"When should I sow rice?\"}" | python3 -m json.tool
# Expected: 200 with message and session_id
```

---

## File Ownership Summary

```
cropcompass/
├── architecture.md              ← Member 1 [DONE]
├── docker-compose.yml           ← Member 1 [DONE]
├── Dockerfile                   ← Member 1 [DONE]
├── Makefile                     ← Member 1 [DONE]
├── .env.example                 ← Member 1 [DONE]
├── openapi.yaml                 ← Member 1 [PENDING]
├── requirements.txt             ← Member 1 [DONE]
├── db/
│   ├── schema.sql               ← Member 1 [DONE] — master schema, all tables, mark_stale_records()
│   ├── imd_advisory.sql         ← Member 1 [DONE]
│   └── farmer_profile.sql       ← Member 1 [DONE]
├── pipeline/
│   ├── imd_scraper.py           ← Member 1 [DONE]
│   ├── staleness.py             ← Member 1 [DONE]
│   └── scheduler.py             ← Member 1 [DONE]
└── app/
    ├── config.py                ← Member 1 [DONE]
    ├── db.py                    ← Member 1 [DONE]
    ├── main.py                  ← Member 1 [DONE]
    ├── models/
    │   ├── imd_advisory.py      ← Member 1 [DONE]
    │   ├── farmer.py            ← Member 1 [DONE]
    │   └── pipeline_run.py      ← Member 1 [DONE]
    ├── schemas/
    │   ├── farmer.py            ← Member 1 [DONE]
    │   └── forecast.py          ← Member 1 [DONE]
    └── routes/
        ├── profile.py           ← Member 1 [DONE]
        ├── forecast.py          ← Member 1 [DONE]
        └── chat.py              ← Member 1 stub, Member 3 implements [DONE stub]
```

**Only remaining item:** `openapi.yaml` (generate from running app + redocly lint).
