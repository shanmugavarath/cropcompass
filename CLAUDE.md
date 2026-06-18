# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CropCompass is a multilingual agentic advisory system that turns monsoon forecasts into actionable farm decisions for smallholder farmers in India. It uses Anthropic Claude (`claude-sonnet-4-6`) as the LLM planner with MCP-style tool use, IndicTrans2 for translation into Indic languages, ChromaDB for RAG over ICAR/SAU agricultural documents, PostgreSQL for farmer profiles + IMD advisory data, and a Vite + React frontend.

## Repository Structure

```
cropcompass/
  api/                   FastAPI backend
    main.py              FastAPI app + Socket.IO mount
    routes/              chat.py, profile.py, forecast.py
    agents/              planner.py (AgentRunner), verifier.py, tools.py, dispatcher.py
    services/            rag.py (ChromaDB), translation.py (IndicTrans2), lang_detect.py
    models/              db.py, farmer.py (ORM), advisory.py (ORM)
    schemas/             farmer.py (Pydantic), agent.py (AgentResponse)
  ingestion/             imd_scraper.py, icar_loader.py, scheduler.py
  ui/                    Vite + React frontend (Member 5 — branch: feature/frontend)
  tests/                 pytest suite (conftest.py, test_e2e.py, test_latency.py)
  docs/                  architecture.md, agent_spec.md, openapi.yaml, frontend_contract.md
  data/
    raw/icar/            downloaded PDFs
    chromadb/            persistent ChromaDB vector store
    test_scenarios.json  30–50 labelled evaluation scenarios
  docker-compose.yml     services: api (8000), db postgres (5432), vectordb chroma (8001)
  requirements.txt
  .env.example           ANTHROPIC_API_KEY, HF_TOKEN, DATABASE_URL
```

## Always Do First (Frontend Sessions)

- Follow the plan in `PLAN_MEMBER5.md` for all steps.
- **Invoke the `frontend-design` skill** before writing any frontend code, every session.
- **Follow `coding_guidelines.md`** for all Vite + React code.

## Frontend Commands (`ui/`)

```bash
cd ui
npm run dev       # dev server at http://localhost:5173
npm run build     # production build → ui/dist/
npm run preview   # preview the prod build
npm run lint      # ESLint
npx vitest        # run unit/component tests
npx vitest run    # single test run (CI mode)
```

### Key env vars (`ui/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | FastAPI backend URL |
| `VITE_USE_MOCK` | `true` | Use MSW + socket stub instead of real backend |

Set `VITE_USE_MOCK=false` when cutting over to the real backend. **Nothing else in the UI changes** — the mock/real switch is entirely in `api/socket.js`.

## Backend Commands (`api/`)

```bash
# Run FastAPI dev server
uvicorn api.main:app --reload --port 8000

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Run ingestion pipeline manually
python -m ingestion.imd_scraper
python -m ingestion.icar_loader
```

## Testing

```bash
# Backend — from project root
pip install -r requirements-test.txt
pytest                          # unit + integration (excludes slow benchmarks)
pytest -m slow --live           # latency benchmarks + real API calls
pytest tests/test_e2e.py        # full pipeline tests only

# Frontend — from ui/
npx vitest                      # watch mode
npx vitest run --reporter=verbose
```

`pytest.ini` sets `asyncio_mode = auto`. Slow/live tests are excluded by default; use `--live` for the acceptance run against real services.

## Architecture: Agent Loop

```
User query
  ├── get_farmer_profile(farmer_id)
  ├── fetch_forecast(district)
  └── query_knowledge_base(crop, soil, query)  ← ChromaDB top-5
       ↓
  LLM generate (claude-sonnet-4-6) → recommendation text
       ↓
  verify_recommendation(rec_text, source_chunks) → PASS | PARTIAL | REJECT
       ↓
  translate_output(rec_text, lang_pref)  ← IndicTrans2
       ↓
  AgentResponse { text, lang, verdict, citations, session_id }
```

`AgentResponse` flows to the frontend via **Socket.IO** (primary) or `POST /api/chat` (fallback). Both transports emit the same shape — the mock in `ui/src/api/mock/server.js` must match this exactly.

## Frontend Architecture

```
ui/src/
  App.jsx                    BrowserRouter: /onboarding → OnboardingWizard, /chat → ChatWindow (protected)
  api/
    client.js                axios instance (baseURL = VITE_API_URL)
    socket.js                socket.io-client singleton; switches real↔mock on VITE_USE_MOCK
    mock/server.js           MSW handlers + socket stub (PASS/PARTIAL/REJECT samples)
  hooks/useChat.js           socket state: messages[], sendMessage(), pending flag
  components/
    OnboardingWizard.jsx     3-step form (Location → Farm → Language)
    ChatWindow.jsx           scrollable message list
    MessageBubble.jsx        user vs assistant rendering
    RecommendationCard.jsx   text + verdict badge + collapsible citations
    InputBar.jsx             textarea + send
    LanguageTag.jsx          maps response.lang (FLORES-200) → display label
```

`farmer_id` is stored in `localStorage`. On app load: if present → `/chat`, else → `/onboarding`.

## Key Data Contracts

### `AgentResponse` (owned by Member 3 — Task 2.4)
```jsonc
{
  "text":      "अभी बुवाई करें...",
  "lang":      "hin_Deva",
  "verdict":   "PASS",                    // PASS | PARTIAL | REJECT
  "citations": { "claim text": "chunk_id" },
  "session_id": "<sid>"
}
```

### `FarmerCreate` (POST /api/profile)
```jsonc
{
  "district": "Pune",
  "soil_type": "clay_loam",
  "crop_variety": "Soybean JS-335",
  "growth_stage": "sowing",
  "lang_pref": "hin_Deva"
}
```

**FLORES-200 language codes:** `hin_Deva`, `tam_Taml`, `tel_Telu`, `mar_Deva`, `pan_Guru`, `eng_Latn`

### Verdict rendering rules
- `PASS` → green badge ✓
- `PARTIAL` → amber badge ⚠ with "some advice unverified" note
- `REJECT` → show only the safe fallback message; **never display raw rejected advice**

## Indic Font Setup

Noto fonts are bundled as local `woff2` under `ui/public/fonts/` — not loaded from CDN. This prevents demo-day failure from network issues. The font stack in `index.css`:
```css
font-family: 'Noto Sans Devanagari', 'Noto Sans Tamil', 'Noto Sans Telugu',
             'Noto Sans Gurmukhi', 'Segoe UI', sans-serif;
```

## Integration: Cutting Over from Mock to Real Backend

1. Confirm backend CORS allows `http://localhost:5173`
2. Confirm Socket.IO event names match: emit `chat`, listen `response`
3. Set `VITE_USE_MOCK=false` and `VITE_API_URL=<backend url>` in `ui/.env`
4. Run `pytest --live` as the acceptance gate (P95 < 15s)
5. Build: `npm run build` → backend serves `ui/dist` as static at `/`

## Styling

- Tailwind CSS is the primary styling mechanism.
- No inline `style` props except for values Tailwind cannot express.
- `@/` path alias is configured in `vite.config.js` → resolves to `ui/src/`.

## Branch Strategy

| Branch | Purpose |
|---|---|
| `feature/frontend` | Member 5: all UI code, E2E tests |
| `Shanu/RAG` | RAG pipeline work |
| `main` | Integration target after all branches merge |

Feature/frontend should merge into `integration` **last** (UI is downstream of everything). The E2E suite (`pytest tests/test_e2e.py`) is the formal integration acceptance gate.
