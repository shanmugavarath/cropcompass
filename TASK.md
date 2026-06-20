# TASK.md — Member 2: RAG Pipeline & Multilingual Services

**Branch:** `Shanu/RAG` · **Source plan:** `PLAN_MEMBER2.md` · **Last updated:** 2026-06-20

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
| Translation | `TranslationService.translate(text, tgt_lang)` — en→indic, 5 languages, < 3s CPU |
| Language detection | `detect_language()` + `detect_with_codeswitching()` — 6 languages, < 50ms |
| Tests | 79 fast tests green, 6 slow (model-dependent) tests green |
| Overall | Task 1.2 ✅ · Task 3.1 ✅ · Task 3.4 ✅ · Task 5.3 🚫 |

---

## Task 1.2 — ICAR & SAU Knowledge Base ✅ (COMPLETE)

- ✅ `api/services/rag.py` — `query_knowledge_base(crop, soil, query, k)` implemented; frozen signature honored; crop pre-filter with no-result fallback.
- ✅ Dual-collection retrieval: queries `icar_knowledge_en` (primary, all-English) + `icar_knowledge` (fallback, Tamil SAU), merges by distance, deduplicates by chunk_id.
- ✅ ChromaDB populated far beyond the 200-chunk target (82,748 chunks in source, 17,126 in English-normalized).
- ✅ SAU ingestion: `ingestion/ingest_to_chromadb.py` + `ocr_pdfs.py` + `check_quality.py` (TNAU Tamil corpus).
- ✅ IMD ingestion: `ingestion/imd_scraper.py` + `ingestion/ingest_imd_to_chromadb.py` (extract → table-strip → crop-tag → dedup → embed).
- ✅ Corpus normalization: `ingestion/normalize_to_english.py` + `colab_normalize.ipynb` — translates Tamil SAU → English, re-embeds, saves to `icar_knowledge_en`. Resumable. 1,130/66,752 SAU chunks translated so far (can continue on Colab).
- ✅ Metadata schema complete (source, chunk_id, doc_type, state, district, date, year, season, crop, soil_type, lang).
- ✅ `tests/test_rag.py` — 25 queries / 14 crops; precision ≥ 0.70 and latency < 200 ms PASS.
- ✅ `tests/test_imd_ingestion.py` — 27 tests green.
- ✅ `requirements.txt` — all Member 2 deps pinned.
- ✅ `README_VECTORDB.md` — reference doc for Member 3 (API, metadata fields, citation format).

**Acceptance criteria (from plan)**
- [x] 200+ chunks in ChromaDB → **82,748** (source) + **17,126** (english-normalized)
- [x] `query_knowledge_base(...)` returns dicts with `text`, `source`, `chunk_id`
- [x] Retrieval precision ≥ 0.70 — **PASS**
- [x] Single-query latency < 200 ms — **PASS**
- [🟡] All 5 plan crops → rice ✓ maize ✓ cotton ✓ soybean ✓ (sparse), **wheat ✗** (corpus pivoted to South-Indian crops — documented deviation)

---

## Task 3.1 — IndicTrans2 Translation ✅ (COMPLETE)

- ✅ `api/services/translation.py` — `TranslationService` class with IndicTrans2, sentence-aware batched translation, GPU support, timeout handling.
- ✅ `translate(text, tgt_lang) → {"translated": str, "lang": str}` — matches PLAN.md signature exactly. Member 3 calls this for output translation.
- ✅ English fallback when `tgt_lang` not in supported set or is `eng_Latn`.
- ✅ Both model directions supported: en→indic (output translation), indic→en (corpus normalization, query translation).
- ✅ `tests/test_translation.py` — 7 fast tests (sentence splitting, fallback contract) + 6 slow tests (Unicode checks for all 5 Indic languages + latency). All green.

**Acceptance criteria (from plan)**
- [x] `translate("...200-word text...", "hin_Deva")` completes in < 3s on CPU
- [x] Output contains correct Devanagari/Tamil/Telugu/Marathi/Punjabi Unicode characters
- [x] Fallback to English when `tgt_lang` not in supported set
- [x] No post-processing needed — model output is clean UTF-8

---

## Task 3.4 — Language Detection & Routing ✅ (COMPLETE)

- ✅ `api/services/lang_detect.py` — `detect_language()` + `detect_with_codeswitching()` via `lingua-language-detector`.
- ✅ Singleton detector built once at module import (~1s first time, near-instant after).
- ✅ FLORES-200 code output: `hin_Deva`, `tam_Taml`, `tel_Telu`, `mar_Deva`, `pan_Guru`, `eng_Latn`.
- ✅ Hinglish codeswitching: Devanagari > Latin → `hin_Deva`.
- ✅ Fallback to `eng_Latn` for unrecognized languages.
- ✅ `tests/test_lang_detect.py` — 13 tests (all 6 languages, codeswitching, fallback, latency). All green.

**Acceptance criteria (from plan)**
- [x] Correctly identifies Hindi, Tamil, Telugu, Marathi, Punjabi, English
- [x] `detect_with_codeswitching` returns `hin_Deva` for Hinglish text where Devanagari > Latin
- [x] Default fallback is `eng_Latn` for unrecognised input
- [x] Detection latency < 50 ms per query

---

## Task 5.3 — Multilingual Quality Evaluation 🚫 (blocked)

- ✅ Task 3.1 done (forward en→indic + reverse indic→en both available)
- ✅ Task 3.4 done
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
6. **Codeswitching test:** plan's Hinglish test string had Latin-dominant text; fixed to use Devanagari-dominant input matching the plan's intent.
