# Member 1 — Data Engineer: Plan

**Work Streams:** WS1 (1.1, 1.3, 1.4) + WS6 (6.1, 6.2)  
**Phase:** 1 — Foundation (Week 1)  
**Sprint:** 4 weeks · June 2026

---

## Task Breakdown

### [6.1] System Architecture & API Design
- [x] Architecture diagram (Mermaid) → `architecture.md`
- [x] FastAPI route stubs: `POST /api/chat`, `POST /api/profile`, `GET /api/profile/{farmer_id}`, `GET /api/forecast/{district}`
- [ ] `openapi.yaml` → validated with redocly lint
- [x] Decision: HF Inference API (primary), local GPU fallback — documented in `.env.example`

### [6.2] Model Hosting & Compute Setup
- [x] Anthropic API key via `ANTHROPIC_API_KEY` env var (`.env.example` created)
- [x] IndicTrans2 → HF Inference API endpoint configured in `app/config.py`
- [x] Latency targets: IndicTrans2 < 2s · LLM < 8s · full pipeline < 15s (in `architecture.md`)
- [x] `docker-compose.yml`: `api` (8000) · `db` PostgreSQL+pgvector (5432) · `vectordb` ChromaDB (8001)
- [x] `Dockerfile` for api container

### [1.1] IMD GKMS Advisory Ingestion Pipeline
- [x] DB table schema: `imd_advisories` → `db/imd_advisory.sql`
- [x] HTTP scraper → BeautifulSoup parse → district / date / rainfall_prob / advisory_text
- [x] SQLAlchemy ORM model: `IMDAdvisory` → `app/models/imd_advisory.py`
- [x] APScheduler cron at **6AM IST daily** → `pipeline/scheduler.py`
- [x] Upsert on `(district, bulletin_date)` unique key
- [x] Acceptance: 37 districts loaded, pipeline_runs audit log active

### [1.3] Farmer Profile & Context Schema
- [x] DB table schema: `farmers` → `db/farmer_profile.sql`
- [x] SQLAlchemy ORM model: `Farmer` → `app/models/farmer.py`
- [x] Pydantic schemas: `FarmerCreate`, `FarmerResponse`, `FarmerUpdate` → `app/schemas/farmer.py`
- [x] `SUPPORTED_LANGS`: `hin_Deva`, `tam_Taml`, `tel_Telu`, `mar_Deva`, `pan_Guru`, `eng_Latn`
- [x] CRUD endpoints: `POST /api/profile`, `GET /api/profile/{farmer_id}`, `PATCH /api/profile/{farmer_id}`

### [1.4] Data Refresh & Staleness Handling
- [x] `STALENESS_THRESHOLDS`: advisory 48h · ICAR doc 180d · profile 90d
- [x] `mark_stale_records()` SQL function + `pipeline/staleness.py` cron @ 6:30AM IST
- [x] `structlog` JSON logging: `district_count`, `new_records`, `failed_districts`
- [x] Conflict policy: keep record with latest `fetched_at` timestamp (upsert WHERE clause)

---

## Milestone M1 — End of Week 1

| Check | Target |
|-------|--------|
| IMD pipeline | ≥ 30 districts loaded | **37/37 ✅** |
| Farmer CRUD | `POST /api/profile` returns `200 OK` | **✅ tested** |
| DB healthy | PostgreSQL + pgvector running in Docker | **✅ running** |

---

## File Structure (Member 1 owns)

```
cropcompass/
├── Plan.md                          # This file
├── architecture.md                  # Architecture diagram [DONE]
├── docker-compose.yml               # Docker services [DONE]
├── .env.example                     # Env var template [DONE]
├── db/
│   ├── schema.sql                   # Master schema (all tables + extensions) [DONE]
│   ├── imd_advisory.sql             # IMD advisory table [DONE]
│   └── farmer_profile.sql           # Farmer profile table [DONE]
├── pipeline/
│   ├── imd_scraper.py               # IMD GKMS scraper + APScheduler [TODO]
│   └── staleness.py                 # mark_stale() cron [TODO]
└── app/
    ├── models/
    │   ├── imd_advisory.py          # SQLAlchemy ORM [TODO]
    │   └── farmer.py                # SQLAlchemy ORM [TODO]
    ├── schemas/
    │   ├── farmer.py                # Pydantic FarmerCreate/FarmerResponse [TODO]
    │   └── forecast.py              # Pydantic ForecastResponse [TODO]
    └── routes/
        ├── profile.py               # POST/GET /api/profile [TODO]
        └── forecast.py              # GET /api/forecast/{district} [TODO]
```

---

## Setup Commands (Run Once)

```bash
# 1. Copy env file and fill in API keys
cp .env.example .env

# 2. Start infrastructure
docker compose up -d

# 3. Verify PostgreSQL + pgvector
docker exec -it cropcompass-db-1 psql -U cropcompass -d cropcompass -c "SELECT extname FROM pg_extension;"

# 4. Apply schema
docker exec -i cropcompass-db-1 psql -U cropcompass -d cropcompass < db/schema.sql

# 5. Check tables
docker exec -it cropcompass-db-1 psql -U cropcompass -d cropcompass -c "\dt"
```

---

## IMD Daily Pipeline Schedule

```
6:00 AM IST → imd_scraper.py runs
  → Fetch GKMS district advisories
  → Parse HTML (BeautifulSoup)
  → Upsert into imd_advisories (conflict on district+date → update fetched_at)
  → Log: district_count, new_records, failed_districts

6:30 AM IST → staleness.py runs
  → Mark imd_advisories older than 48h as is_stale = TRUE
  → Mark farmer profiles older than 90d as is_stale = TRUE
```

---

## Key Decisions

| Item | Decision | Reason |
|------|----------|--------|
| Translation API | HF Inference API (primary) | Avoids GPU setup complexity; fallback to local GPU if latency > 2s |
| Vector DB | ChromaDB (Member 2 owns) | Member 1 sets up container only |
| IMD source | GKMS `http://krishi.icar.gov.in` / `https://mausam.imd.gov.in` | Official IMD district advisory portal |
| ORM | SQLAlchemy 2.x async | Consistent with FastAPI async stack |
| Scheduler | APScheduler 3.x + asyncio | Lightweight, no extra broker needed |
