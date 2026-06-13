# PLAN_MEMBER5.md — Member 5: Frontend & Integration

**Member 5 role:** Frontend & Integration Engineer
**Owned tasks:** 4.1 Web Chat Interface · 4.3 Farmer Onboarding & Profile Capture · 5.5 End-to-End Integration Testing
**Branch:** `feature/frontend`

> Member 5 sits at the **downstream end** of the dependency graph (see `PLAN.md`). Almost
> everything else — the API contract (6.1), the agent loop (2.x), the translation layer
> (3.x) — flows *into* this work. The single biggest risk is **being blocked waiting on
> other members**. The strategy in this plan is therefore: **build everything against a
> mock backend first, swap to the real backend at integration time.**

---

## 0. Strategy: Decouple now, integrate later

Member 5 must not wait for the agent/RAG/translation stack to be ready. The plan is:

1. **Lock the contract early.** Agree the API + Socket.IO contract with Member 1 (6.1)
   and Member 3 (2.4 `AgentResponse`) in Week 1 — even if no implementation exists yet.
2. **Build the entire UI against a mock backend** that honours that contract.
3. **At integration**, flip a single env flag (`VITE_USE_MOCK`) from mock → real, fix the
   inevitable contract drift, then run the E2E suite (5.5) as the acceptance gate.

This means 4.1 and 4.3 can be **fully built and demoable in Week 2–3** with zero dependency
on anyone else's code, and 5.5 becomes the formal "everything actually fits together" gate.

---

## 1. Contract Member 5 depends on (freeze this with the team first)

These are the seams between member 5's code and everyone else's. Get them written down and
agreed **before** writing UI code — this is the cheapest possible integration insurance.

### 1.1 REST endpoints (owned by Member 1 — task 6.1)
| Method | Path | Request | Response |
|--------|------|---------|----------|
| `POST` | `/api/profile` | `FarmerCreate` | `FarmerResponse` (incl. `farmer_id`) |
| `GET`  | `/api/profile/{farmer_id}` | — | `FarmerResponse` |
| `GET`  | `/api/forecast/{district}` | — | latest advisory |
| `GET`  | `/api/districts` *(request this be added)* | — | master district list for onboarding dropdowns |

### 1.2 `FarmerCreate` schema (owned by Member 1 — task 1.3)
```jsonc
{
  "district":     "Pune",
  "soil_type":    "clay_loam",          // clay | loam | sandy | clay_loam | silt_loam
  "crop_variety": "Soybean JS-335",
  "growth_stage": "sowing",             // sowing | vegetative | flowering | maturity
  "lang_pref":    "hin_Deva"            // FLORES-200 code
}
```
FLORES codes: `hin_Deva, tam_Taml, tel_Telu, mar_Deva, pan_Guru, eng_Latn`.

### 1.3 Chat transport — Socket.IO (owned by Member 1 backend + Member 3 agent)
- **Emit** `chat` → `{ farmer_id, message }`
- **Listen** `response` → `AgentResponse`

### 1.4 `AgentResponse` schema (owned by Member 3 — task 2.4)
```jsonc
{
  "text":      "अभी बुवाई करें...",      // already translated to lang_pref
  "lang":      "hin_Deva",
  "verdict":   "PASS",                    // PASS | PARTIAL | REJECT
  "citations": { "claim text": "chunk_id" },
  "session_id":"<sid>"
}
```

> **Action item for Member 5:** open a short `docs/frontend_contract.md` PR capturing exactly
> the above and get Members 1 and 3 to approve it. Any later change to these shapes is a
> contract change that must be communicated — that's the one thing that breaks integration.

---

## 2. Task 4.1 — Web Chat Interface

**Deliverable:** Vite + React chat app in `ui/`, talks to FastAPI over Socket.IO, renders Indic scripts.

### 2.1 Scaffold
```bash
npm create vite@latest ui -- --template react
cd ui
npm install axios socket.io-client react-router-dom
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom msw
```

### 2.2 Component structure
```
ui/
  .env                     VITE_API_URL, VITE_USE_MOCK
  src/
    App.jsx                router (/onboarding, /chat) + farmer_id gate
    main.jsx
    index.css              Noto Indic font imports (see 2.4)
    api/
      client.js            axios instance (baseURL = VITE_API_URL)
      socket.js            socket.io-client singleton
      mock/
        server.js          MSW + mock socket — the decoupling layer (see §5)
    hooks/
      useChat.js           socket state: messages[], sendMessage()
    components/
      ChatWindow.jsx       scrollable message list
      MessageBubble.jsx    user vs assistant rendering
      InputBar.jsx         textarea + send
      LanguageTag.jsx      shows response.lang
      RecommendationCard.jsx  structured display: text + citations + verdict badge
```

### 2.3 `useChat` hook (contract from §1.3 / §1.4)
- On mount: connect socket, register `response` listener, append assistant message.
- `sendMessage(text)`: optimistic-append user bubble, `socket.emit('chat', {farmer_id, message})`.
- Track a `pending` flag (typing indicator) cleared when `response` arrives.
- Clean up listener + disconnect on unmount.

### 2.4 Indic script rendering
- Bundle **Noto fonts as local `woff2`** under `ui/public/fonts/` (not CDN) — per the
  Risk Register, CDN dependency is a demo-day failure mode.
- `index.css` font stack: `'Noto Sans Devanagari','Noto Sans Tamil','Noto Sans Telugu','Noto Sans Gurmukhi', sans-serif`, `white-space: pre-wrap`, `line-height: 1.6`.
- Map `response.lang` → display label in `LanguageTag`.

### 2.5 Recommendation display
`RecommendationCard` renders:
- the translated `text`,
- a **verdict badge** — `PASS` ✓ (green) / `PARTIAL` ⚠ (amber, "some advice unverified") / `REJECT` (the safe-fallback message; never show raw rejected advice),
- **citations** as a collapsible "Sources" list from `citations` values (chunk_ids / source files).

### 2.6 Acceptance criteria
- Sends a query and renders the assistant response with correct Indic glyphs.
- Verdict + citations visible. `REJECT` shows only the safe fallback.
- Works fully against the **mock backend** with no real services running.

---

## 3. Task 4.3 — Farmer Onboarding & Profile Capture

**Deliverable:** 3-step onboarding form, completes in < 3 minutes, posts `FarmerCreate`.

### 3.1 Flow (route `/onboarding`, gated before `/chat`)
```
Step 1 — Location:   State dropdown → District dropdown (filtered; from GET /api/districts)
Step 2 — Farm:       Soil type (5 radio + icons) · Crop variety (autocomplete) · Growth stage (4 radio)
Step 3 — Language:   हिंदी | தமிழ் | తెలుగు | मराठी | ਪੰਜਾਬੀ | English
                     + live preview "नमस्ते, किसान!" to confirm the font renders
```

### 3.2 Submit
```js
const { data } = await api.post('/api/profile', {
  district, soil_type, crop_variety, growth_stage,
  lang_pref: LANG_TO_FLORES[language],
});
localStorage.setItem('farmer_id', data.farmer_id);
navigate('/chat');
```

### 3.3 Validation & state
- All fields required; `crop_variety` ≥ 2 chars; district must be in the master list (server
  authoritative, but pre-filter client-side from `/api/districts`).
- On app load, read `farmer_id` from `localStorage`; if present skip onboarding → `/chat`.
- Surface server 4xx (e.g. unknown district) inline on Step 1.

### 3.4 Acceptance criteria
- New user completes onboarding → lands in chat with a valid `farmer_id`.
- Returning user (localStorage set) skips straight to chat.
- Language preview renders correctly for all 6 options.

---

## 4. Task 5.5 — End-to-End Integration Testing

**This is the integration capstone** — it exercises every member's code in one pipeline and
is the formal acceptance gate for "all parts fit together."

**Deliverable:** `pytest` suite + latency benchmark report.

### 4.1 Structure (Member 5 owns `conftest.py`, `test_e2e.py`, `test_latency.py`)
```
tests/
  conftest.py          shared fixtures: async_client, test DB, seeded farmers, mock scenarios
  test_e2e.py          POST /api/chat → translated, verified response
  test_latency.py      P50/P95 benchmarks vs the <15s target
```
> Per-component tests (`test_ingestion`, `test_rag`, `test_agent`, `test_verification`,
> `test_translation`) are owned by their respective members; Member 5 owns the **glue
> fixtures** and the **whole-pipeline** tests, and aggregates everyone's tests into one CI run.

### 4.2 Core E2E tests (from `PLAN.md` §5.5)
- `test_full_pipeline_hindi` — Hindi query → `lang == hin_Deva`, non-empty text, `verdict in {PASS,PARTIAL}`, elapsed < 15s.
- `test_missing_forecast` — graceful degradation message when no forecast.
- `test_unsupported_language_fallback` — falls back to `eng_Latn`.
- Add: `test_reject_path` — a known-hallucinated scenario surfaces the safe fallback, never raw advice.

### 4.3 Latency benchmark
`benchmark_pipeline(scenario, runs=10)` → `{p50_s, p95_s, mean_s}`; assert P95 < 15s; emit a
small markdown/CSV report committed under `docs/` for the final write-up.

### 4.4 Fixture strategy (the integration-fragility hotspot)
- Use a **dedicated test DB** (SQLite or a throwaway Postgres schema), seeded with farmers
  whose districts have IMD advisories + ICAR chunks present.
- Provide a **`--live` vs default mode**: default mocks the Anthropic API (deterministic,
  free, fast for CI); `--live` hits real services for the demo-day acceptance run. This keeps
  the suite runnable by every member without API keys.

### 4.5 Acceptance criteria
- Full `pytest` green against the integrated stack.
- P95 latency report produced and < 15s.
- Each milestone-relevant failure mode (missing forecast, unsupported lang, reject) covered.

---

## 5. The mock backend (decoupling layer — build this in Week 1)

So 4.1/4.3 don't block on anyone. Two thin mocks behind a single flag `VITE_USE_MOCK=true`:

1. **REST mock (MSW)** — `/api/profile`, `/api/profile/{id}`, `/api/districts` return
   contract-shaped fixtures.
2. **Socket mock** — a stub that, on `emit('chat')`, replies after ~1s with a canned
   `AgentResponse` (one PASS Hindi sample, one PARTIAL, one REJECT to exercise all UI paths).

`api/socket.js` chooses the real or mock transport off `VITE_USE_MOCK`. **Nothing else in the
UI knows whether it's talking to a mock** — that's what makes the cutover a one-line change.

---

## 6. Integration plan — merging into the repo where all other tasks are done

This is the part that matters most: how member 5's work lands cleanly into the assembled repo.

### 6.1 What member 5 adds vs. touches (conflict surface)
| Path | Ownership | Conflict risk |
|------|-----------|---------------|
| `ui/**` | **New, member 5 only** | None — brand-new directory |
| `tests/test_e2e.py`, `tests/test_latency.py` | **New, member 5** | None |
| `tests/conftest.py` | **Shared** | Medium — coordinate fixtures with all members |
| `api/main.py` | Member 1 owns; member 5 needs Socket.IO mount + CORS + static-serve | **High — the one real merge point** |
| `requirements.txt` | Shared | Low — additive (`pytest-asyncio`, `httpx`, `python-socketio`) |
| `docker-compose.yml` | Member 1 owns; add a `ui` service / build step | Medium |

**Takeaway:** member 5's footprint is almost entirely *additive new directories*, so merge
conflicts are minimal. The two coordination points are **`api/main.py`** (Socket.IO + CORS +
serving the built UI) and **`tests/conftest.py`** (shared fixtures). Agree these explicitly.

### 6.2 Branch & merge sequence
```
main ── (other members merge their feature branches into an `integration` branch first)
         │
feature/frontend ─────────────────────────────► merge into `integration` LAST
                                                  (UI is downstream of everything)
         integration ──(E2E green via 5.5)──► main
```
1. Other members merge their work into an `integration` branch and the backend boots.
2. Member 5 rebases `feature/frontend` onto `integration`.
3. Resolve the `api/main.py` + `conftest.py` + `requirements.txt` seams (small, known).
4. Flip `VITE_USE_MOCK=false`, point `VITE_API_URL` at the real backend.
5. Run the 5.5 E2E + latency suite. **Green = integration accepted.** This is the gate.

### 6.3 Wiring the real backend (the cutover checklist)
- **CORS**: backend must allow the UI origin (dev `http://localhost:5173`). Coordinate with Member 1.
- **Socket.IO mount**: confirm event names (`chat`/`response`) and that the server is
  mounted at the URL `VITE_API_URL` points to (`socketio.ASGIApp` on the FastAPI app).
- **Env**: `ui/.env` → `VITE_API_URL`, `VITE_USE_MOCK=false`. Backend → `ANTHROPIC_API_KEY`, `HF_TOKEN`, `DATABASE_URL`.
- **Serving in prod**: either (a) `npm run build` → FastAPI serves `ui/dist` as static at `/`,
  or (b) add a `ui` service to `docker-compose.yml`. Pick (a) for a single-container course demo.
- **Contract drift fixes**: the realistic work — field renames, `lang` mismatches, citation
  shape — caught by the E2E suite. Budget time here, not in writing new UI.

### 6.4 Integration risks & mitigations
| Risk | Mitigation |
|------|-----------|
| Backend not ready when UI is | Mock backend (§5) — UI is fully demoable regardless |
| `AgentResponse` shape drifts from §1.4 | Frozen contract doc + E2E contract test fails loudly on drift |
| Socket.IO event/version mismatch | Pin `python-socketio` ↔ `socket.io-client` versions in the contract doc |
| Indic fonts fail on demo machine | Local `woff2` bundle, no CDN |
| `conftest.py` fixture collisions | One shared fixtures PR, namespaced fixtures, member 5 owns the merge |

---

## 7. Timeline & milestone mapping

| Week | Member 5 focus | Ties to milestone |
|------|----------------|-------------------|
| 1 | Freeze contract (§1) + build mock backend (§5) + scaffold `ui/` | — |
| 2 | Build 4.3 onboarding + 4.1 chat **against mock** → fully demoable UI | (independent of M2) |
| 3 | Polish UI; write 5.5 fixtures + E2E tests against mock; prep cutover | M3 (UI exists for multilingual demo) |
| 4 | Rebase onto `integration`, cutover to real backend, run 5.5, latency report | **M4** — E2E pass, P95 < 15s |

---

## 8. Definition of Done (Member 5)
- [ ] `ui/` React app: onboarding (4.3) + chat (4.1), Indic rendering, verdict + citations display.
- [ ] Runs standalone against the mock backend (`VITE_USE_MOCK=true`).
- [ ] Cuts over to the real backend with a single flag flip + env change.
- [ ] `tests/test_e2e.py` + `tests/test_latency.py` green against the integrated stack.
- [ ] Latency report committed; P95 < 15s.
- [ ] `feature/frontend` merged into `integration` → `main` with the 5.5 suite passing as the gate.
- [ ] `docs/frontend_contract.md` approved by Members 1 and 3.
