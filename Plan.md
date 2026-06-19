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

### [1.5] Monsoon Outlook & Historical Rainfall Enhancement
**Goal:** Enable long-horizon crop planning queries — *"Will sugarcane/turmeric get enough rainfall in my district over one year?"*

#### New DB tables
- [x] `crop_water_requirements` — 8 crops seeded (sugarcane/turmeric/rice/wheat/maize/cotton/soybean/pulses) → `db/rainfall_schema.sql`
- [x] `imd_historical_rainfall` — 37 districts × 137 months loaded via Open-Meteo (mock) → `db/rainfall_schema.sql`
- [x] `imd_seasonal_outlook` — kharif 2026 outlook for 37 districts → `db/rainfall_schema.sql`

#### New ORM models
- [x] `app/models/crop_water_req.py` — `CropWaterRequirement`
- [x] `app/models/historical_rainfall.py` — `IMDHistoricalRainfall`
- [x] `app/models/seasonal_outlook.py` — `IMDSeasonalOutlook`

#### New Pydantic schemas
- [x] `app/schemas/rainfall.py` — `CropSuitabilityResponse`, `HistoricalRainfallStats`, `SeasonalOutlookInfo`, `CropRequirementInfo`

#### New API endpoint
- [x] `app/routes/rainfall.py` — `GET /api/rainfall/{district}/crop-suitability/{crop}`
  - Returns verdict: `SUFFICIENT / MARGINAL / INSUFFICIENT / EXCESS — DRAINAGE RISK / UNKNOWN`
  - Returns `surplus_deficit_mm`, `dry_months`, `confidence`, `recommendation`
- [x] Register rainfall router in `app/main.py`

#### New pipeline files
- [x] `pipeline/historical_rainfall_loader.py` — Open-Meteo backfill 2015→now, mock mode, monthly upsert, rate-limit delay
- [x] `pipeline/imd_seasonal_scraper.py` — IMD LRF scrape with mock fallback, weekly schedule

#### Scheduler updates
- [x] `pipeline/scheduler.py` — `historical_rainfall_monthly` job (1st of month 01:00 IST)
- [x] `pipeline/scheduler.py` — `imd_seasonal_scraper` job (every Monday 07:00 IST)

#### Schema updates
- [x] `db/rainfall_schema.sql` — `mark_stale_records()` extended for `imd_historical_rainfall` (35d) and `imd_seasonal_outlook` (14d)
- [x] `db/rainfall_schema.sql` — `district_rainfall_summary` view for pre-aggregated annual stats

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
├── Plan.md                               # This file
├── SPEC.md                               # Full specification [DONE]
├── architecture.md                       # Architecture diagram [DONE]
├── docker-compose.yml                    # Docker services [DONE]
├── Dockerfile                            # API container image [DONE]
├── Makefile                              # Dev shortcuts [DONE]
├── .env.example                          # Env var template [DONE]
├── requirements.txt                      # Python dependencies [DONE]
├── db/
│   ├── schema.sql                        # Master schema + mark_stale_records() [DONE]
│   ├── imd_advisory.sql                  # IMD advisory table standalone [DONE]
│   ├── farmer_profile.sql                # Farmer profile table standalone [DONE]
│   └── rainfall_schema.sql               # Rainfall tables + crop seed data [PENDING]
├── pipeline/
│   ├── imd_scraper.py                    # GKMS daily scraper [DONE]
│   ├── staleness.py                      # mark_stale_records() cron [DONE]
│   ├── scheduler.py                      # APScheduler — all cron jobs [DONE → extend]
│   ├── historical_rainfall_loader.py     # Open-Meteo backfill + monthly [PENDING]
│   └── imd_seasonal_scraper.py           # IMD LRF weekly scrape [PENDING]
└── app/
    ├── config.py                         # Pydantic settings [DONE]
    ├── db.py                             # Async engine + session [DONE]
    ├── main.py                           # FastAPI app + lifespan [DONE → extend]
    ├── models/
    │   ├── imd_advisory.py               # IMDAdvisory ORM [DONE]
    │   ├── farmer.py                     # Farmer ORM [DONE]
    │   ├── pipeline_run.py               # PipelineRun ORM [DONE]
    │   ├── historical_rainfall.py        # IMDHistoricalRainfall ORM [PENDING]
    │   ├── seasonal_outlook.py           # IMDSeasonalOutlook ORM [PENDING]
    │   └── crop_water_req.py             # CropWaterRequirement ORM [PENDING]
    ├── schemas/
    │   ├── farmer.py                     # FarmerCreate/Update/Response [DONE]
    │   ├── forecast.py                   # ForecastResponse [DONE]
    │   └── rainfall.py                   # CropSuitabilityResponse + sub-schemas [PENDING]
    └── routes/
        ├── profile.py                    # POST/GET/PATCH /api/profile [DONE]
        ├── forecast.py                   # GET /api/forecast/{district} [DONE]
        ├── chat.py                       # POST /api/chat stub [DONE]
        └── rainfall.py                   # GET /api/rainfall/{district}/crop-suitability/{crop} [PENDING]
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

## Pipeline Schedule

```
On startup (once)       → historical_rainfall_loader  — backfill Jan 2015 → present for all districts
06:00 AM IST daily      → imd_scraper                 — GKMS district advisories
                              → Upsert into imd_advisories
                              → Log: district_count, new_records, failed_districts
06:30 AM IST daily      → staleness_check             — mark_stale_records()
                              → imd_advisories older than 48h → is_stale = TRUE
                              → farmers older than 90d → is_stale = TRUE
                              → imd_historical_rainfall older than 35d → is_stale = TRUE  [NEW]
                              → imd_seasonal_outlook older than 14d → is_stale = TRUE     [NEW]
07:00 AM IST every Mon  → imd_seasonal_scraper        — IMD LRF seasonal forecast         [NEW]
                              → Upsert into imd_seasonal_outlook
01:00 AM IST 1st of month → historical_rainfall_loader — add previous month's data        [NEW]
```

---

## Key Decisions

| Item | Decision | Reason |
|------|----------|--------|
| Translation API | HF Inference API (primary) | Avoids GPU setup complexity; fallback to local GPU if latency > 2s |
| Vector DB | ChromaDB (Member 2 owns) | Member 1 sets up container only |
| IMD daily source | GKMS `https://mausam.imd.gov.in` | Official IMD district advisory portal |
| Historical rainfall source | Open-Meteo archive API | Free, no auth, covers India back to 1940, lat/lon based |
| Seasonal outlook source | IMD LRF page (weekly scrape) | Official IMD long-range forecast, updated weekly in monsoon season |
| Crop water requirements | ICAR static reference | Seeded once, no external API needed |
| ORM | SQLAlchemy 2.x async | Consistent with FastAPI async stack |
| Scheduler | APScheduler 3.x + asyncio | Lightweight, no extra broker needed |
| Verdict logic | Rule-based (hist avg + outlook) | Fast, deterministic, easy to audit — LLM handles nuance in chat response |
