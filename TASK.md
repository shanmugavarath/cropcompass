# TASK.md — Member 2: RAG Pipeline & Multilingual Services

**Branch:** `Shanu/RAG` · **Source plan:** `PLAN_MEMBER2.md` · **Last updated:** 2026-06-19

Status legend: ✅ done · 🟡 partial / needs validation · ⬜ not started · 🚫 blocked

---

## Snapshot

| Item | State |
|---|---|
| ChromaDB `icar_knowledge` | **82,748 chunks** (66,752 SAU Tamil + 15,996 IMD English) |
| ChromaDB `icar_knowledge_en` | **17,126 chunks** (15,996 IMD + 1,130 translated SAU) |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` (384-dim) |
| IMD coverage | 6 states (TN, KL, KA, AP, TL, PY), 2025-09-02 → 2026-06-16 |
| RAG service | Dual-collection: queries both `icar_knowledge_en` + `icar_knowledge`, merges by distance |
| Integrity tests | `tests/test_imd_ingestion.py` — 17/17 green; `tests/test_rag.py` — 57/58 green |
| Retrieval gates | precision ≥ 0.70 ✅ · latency < 200 ms ✅ |
| Translation (indic→en) | `TranslationService` built, used for SAU normalization |
| Overall | Task 1.2 ✅ · Task 3.1 🟡 · Task 3.4 ⬜ · Task 5.3 🚫 |

---

## Task 1.2 — ICAR & SAU Knowledge Base ✅ (COMPLETE)

- ✅ `api/services/rag.py` — `query_knowledge_base(crop, soil, query, k)` implemented; frozen signature honored; crop pre-filter with no-result fallback.
- ✅ Dual-collection retrieval: queries `icar_knowledge_en` (primary, all-English) + `icar_knowledge` (fallback, Tamil SAU), merges by distance, deduplicates by chunk_id.
- ✅ ChromaDB populated far beyond the 200-chunk target (82,748 chunks in source, 17,126 in English-normalized).
- ✅ SAU ingestion: `ingestion/ingest_to_chromadb.py` + `ocr_pdfs.py` + `check_quality.py` (TNAU Tamil corpus).
- ✅ IMD ingestion: `ingestion/imd_scraper.py` + `ingestion/ingest_imd_to_chromadb.py` (extract → table-strip → crop-tag → dedup → embed).
- ✅ Corpus normalization: `ingestion/normalize_to_english.py` + `colab_normalize.ipynb` — translates Tamil SAU → English, re-embeds, saves to `icar_knowledge_en`. Resumable. 1,130/66,752 SAU chunks translated so far (can continue on Colab).
- ✅ `api/services/translation.py` — `TranslationService` (IndicTrans2 indic→en), sentence-aware batched translation with timeout handling.
- ✅ Metadata schema complete (source, chunk_id, doc_type, state, district, date, year, season, crop, soil_type, lang).
- ✅ `tests/test_rag.py` — 25 queries / 14 crops; precision ≥ 0.70 and latency < 200 ms PASS.
- ✅ `tests/test_imd_ingestion.py` — 17/17 green.
- ✅ `requirements.txt` — all Member 2 deps pinned.

**Acceptance criteria (from plan)**
- [x] 200+ chunks in ChromaDB → **82,748** (source) + **17,126** (english-normalized)
- [x] `query_knowledge_base(...)` returns dicts with `text`, `source`, `chunk_id`
- [x] Retrieval precision ≥ 0.70 — **PASS**
- [x] Single-query latency < 200 ms — **PASS**
- [🟡] All 5 plan crops → rice ✓ maize ✓ cotton ✓ soybean ✓ (sparse), **wheat ✗** (corpus pivoted to South-Indian crops — documented deviation)

---

## Task 3.1 — IndicTrans2 Translation 🟡 (indic→en done; en→indic API + tests pending)

**Done**
- ✅ `api/services/translation.py` — `TranslationService` class with IndicTrans2, sentence-aware batched translation, GPU support, timeout handling.
- ✅ indic→en direction working (used for SAU corpus normalization).
- ✅ `IndicTransToolkit` integration with compatibility patches for newer transformers.

**To do**
- ⬜ Add en→indic `translate(text, tgt_lang)` method returning `{"translated": str, "lang": str}` — the API Member 3 calls for output translation.
- ⬜ English fallback when `tgt_lang` not in supported set.
- ⬜ `tests/test_translation.py` — Unicode-range checks for all 5 Indic languages + fallback test.
- **Acceptance:** < 3 s/translation on CPU, correct Indic Unicode, English fallback for unsupported langs.

---

## Task 3.4 — Language Detection & Routing ⬜ (not started)

- ⬜ `api/services/lang_detect.py` — `detect_language()` + `detect_with_codeswitching()` via `lingua-language-detector`.
- ⬜ Detection tests (Hindi/Tamil/Telugu/Marathi/Punjabi/English + Hinglish).
- **Acceptance:** correct FLORES-200 codes, Hinglish → `hin_Deva` when Devanagari > Latin, < 50 ms/query.

---

## Task 5.3 — Multilingual Quality Evaluation 🚫 (blocked)

- 🚫 Blocked on Task 3.1 (forward + reverse IndicTrans2) and Task 3.4.
- 🚫 Needs `data/test_scenarios.json` (Member 4 / Task 5.1) — **absent**.
- ⬜ Back-translation semantic-similarity harness (target ≥ 0.65 per language).
- ⬜ `docs/multilingual_eval_report.csv` + `.md` (+ 2 native-speaker checks per language).

---

## Deviations from PLAN_MEMBER2.md (intentional, worth noting)

1. **Embedding model:** plan said `all-MiniLM-L6-v2`; using `paraphrase-multilingual-MiniLM-L12-v2` so English queries match the Tamil SAU corpus (same 384-dim, so cross-compatible).
2. **Corpus:** plan targeted ICAR PDFs (rice/wheat/maize/cotton/soybean); actual corpus is **TNAU SAU (Tamil) + IMD district agromet bulletins** for 6 South-Indian states.
3. **File naming:** no `ingestion/icar_loader.py`; that role is covered by `ingest_to_chromadb.py`, `imd_scraper.py`, `ingest_imd_to_chromadb.py`.
4. **Chunk IDs:** plan's `{crop}_{soil}_{season}_{page}_{chunk}`; actual `sau_<stem>_p###_c###` (SAU) and `imd_<contenthash>` (IMD, enables dedup).
5. **Dual-collection RAG:** added `icar_knowledge_en` collection to solve cross-lingual retrieval gap; `rag.py` queries both and merges results.
