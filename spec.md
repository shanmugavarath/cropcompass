# SPEC.md — CropCompass (Web Chat, 5-Member Team)

## 1. Project Scope

CropCompass is a multilingual agentic advisory system that bridges the gap between
official meteorological forecasts and smallholder farm decisions. This implementation
is scoped to a **web-based chat interface only** — no SMS, no voice, no IVR.

**Out of scope (removed):**
- ASR / speech-to-text (IndicConformer)
- TTS / text-to-speech (Indic Parler TTS)
- SMS delivery (160-char constraints)
- IVR / feature-phone voice flows

**Retained multilingual capability:** text translation via IndicTrans2 and Indic script
rendering in the chat UI.

---

## 2. Work Streams & Tasks (21 Tasks)

### WS1 — Data & Knowledge Integration (4 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 1.1 | IMD GKMS advisory ingestion pipeline — scrape/API district-level forecasts, parse rainfall probabilities and seasonal outlooks | Member 1 |
| 1.2 | ICAR & State Agricultural University knowledge base — collect, chunk, and embed crop advisory documents into a retrieval-ready vector store | Member 2 |
| 1.3 | Farmer profile & context schema — define and store farmer location, soil type, crop variety, growth stage, and language preference | Member 1 |
| 1.4 | Data refresh & staleness handling — schedule IMD advisory refresh, handle missing/delayed forecasts, log data freshness | Member 1 |

### WS2 — Agentic Architecture & MCP (5 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 2.1 | Central planning agent — orchestrator that decomposes farmer queries into sub-tasks and coordinates MCP tool calls | Member 3 |
| 2.2 | MCP tool definitions — `fetch_forecast`, `query_knowledge_base`, `get_farmer_profile`, `translate_output` with specs and acceptance criteria | Member 3 |
| 2.3 | Verification agent — cross-checks every recommendation against ICAR/SAU sources; each claim must map to a retrievable source chunk | Member 4 |
| 2.4 | Agentic loop & context engineering — three-phase loop: Gather Context → Generate Recommendation → Verify; define context window assembly strategy | Member 3 |
| 2.5 | Prompt & specification design — SDD spec for each agent (goal, constraints, I/O schema, acceptance criteria); plain-language system prompts | Member 3 |

### WS3 — Multilingual Text Pipeline (2 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 3.1 | IndicTrans2 translation integration — English-to-Indic translation for Hindi, Tamil, Telugu, Marathi, Punjabi; handle script rendering | Member 2 |
| 3.4 | Language detection & routing — detect farmer's input language, route to IndicTrans2 pipeline; handle code-switching (mixed Hindi-English) | Member 2 |

### WS4 — Interface & Delivery (2 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 4.1 | Web Chat Interface — React/HTML chat UI with Indic script rendering, structured recommendation display, REST/WebSocket backend integration | Member 5 |
| 4.3 | Farmer onboarding & profile capture — first-use flow collecting language preference, district, and soil type & crop in under 3 minutes | Member 5 |

### WS5 — Evaluation & Testing (5 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 5.1 | Curated test scenario suite — 30–50 labelled scenarios across districts, seasons, soil types, and crops with ground-truth recommendations | Member 4 |
| 5.2 | Recommendation relevance evaluation — agronomic accuracy, actionability, and alignment with official advisories scored against the test suite | Member 4 |
| 5.3 | Multilingual quality evaluation — back-translation evaluation + native-speaker contextual accuracy checks across 3–5 Indic languages | Member 2 |
| 5.4 | Verification agent effectiveness — precision and recall on hallucinated/unsupported recommendations; reported per weather and crop context | Member 4 |
| 5.5 | End-to-end integration testing — full pipeline: text chat → planning agent → tool calls → verification → translated output; latency benchmarks | Member 5 |

### WS6 — Infrastructure & Project Management (3 tasks)

| ID  | Task | Owner |
|-----|------|-------|
| 6.1 | System architecture & API design — architecture diagram, API contracts between agent / MCP tools / translation / delivery; deployment decisions | Member 1 |
| 6.2 | Model hosting & compute setup — IndicTrans2 on GPU/HuggingFace; LLM via Anthropic API; inference latency benchmarks | Member 1 |
| 6.3 | Project milestones & team assignment — map 21 tasks to 5 members; 4 milestone checkpoints | All |

---

## 3. Architecture

```
Farmer (Web Chat)
      │  text query
      ▼
  Web Chat UI  (React/HTML, Indic script rendering)
      │  REST / WebSocket
      ▼
  Planning Agent  (LLM orchestrator via Anthropic API)
      │  MCP tool calls
      ├──► fetch_forecast(district, date)         → IMD pipeline
      ├──► query_knowledge_base(crop, soil, query) → ICAR vector store
      ├──► get_farmer_profile(id)                 → Farmer DB
      └──► translate_output(text, lang)           → IndicTrans2
      │
      ▼
  Verification Agent  (checks against ICAR/SAU sources)
      │
      ▼
  Recommendation  (Indic text, rendered in chat UI)
```

---

## 4. Team Assignment (5 Members)

### Member 1 — Data Engineer
- 1.1 IMD advisory ingestion pipeline
- 1.3 Farmer profile schema & DB
- 1.4 Data refresh & staleness handling
- 6.1 System architecture & API design
- 6.2 Model hosting & compute setup

### Member 2 — Knowledge / RAG Engineer
- 1.2 ICAR corpus & vector store
- 3.1 IndicTrans2 translation integration
- 3.4 Language detection & routing
- 5.3 Multilingual quality evaluation

### Member 3 — Agent Engineer
- 2.1 Central planning agent
- 2.2 MCP tool definitions
- 2.4 Agentic loop & context engineering
- 2.5 Prompt & specification design

### Member 4 — Verification & Evaluation
- 2.3 Verification agent
- 5.1 Test scenario suite
- 5.2 Recommendation relevance evaluation
- 5.4 Verification agent effectiveness measurement

### Member 5 — Frontend & Integration
- 4.1 Web Chat Interface
- 4.3 Farmer onboarding & profile capture
- 5.5 End-to-end integration testing

---

## 5. Execution Phases

| Phase | Work Streams | Goal |
|-------|-------------|------|
| 1 | WS1 + WS6.1–6.2 | Data pipelines live; infrastructure locked down |
| 2 | WS2 | Core agent loop working end-to-end in English |
| 3 | WS3 | Multilingual text translation layer integrated |
| 4 | WS4 | Web chat UI and farmer onboarding shipped |
| 5 | WS5 | Evaluation suite run; final report ready |

Key risk areas: Task 2.3 (verification agent) and Task 5.3 (multilingual quality
evaluation) are the most technically complex — plan extra time for these.

---

## 6. Evaluation Dimensions

1. **Recommendation relevance** — agronomic accuracy vs. ground-truth test suite
2. **Multilingual output quality** — back-translation similarity + native-speaker checks
3. **Verification agent effectiveness** — precision/recall on hallucinated recommendations

---

## 7. Timeline (4 Weeks)

| Week | Focus |
|------|-------|
| 1 | Phase 1: Data pipelines + infrastructure (WS1, WS6.1–6.2) |
| 2 | Phase 2: Agent loop in English (WS2) |
| 3 | Phase 3 + 4: Multilingual layer + web chat UI (WS3, WS4) |
| 4 | Phase 5: Evaluation, integration testing, final report (WS5) |

---

## 8. Deliverables

- Working web chat application
- Multilingual recommendation engine (text only)
- Verification agent with grounding rubric
- Evaluation report (relevance + multilingual quality + verification effectiveness)
