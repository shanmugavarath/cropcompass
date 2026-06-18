# PLAN_MEMBER2.md — Member 2: RAG Pipeline & Multilingual Services

**Member 2 role:** Knowledge Base & Translation Engineer
**Owned tasks:** 1.2 ICAR/SAU Knowledge Base · 3.1 IndicTrans2 Translation · 3.4 Language Detection & Routing · 5.3 Multilingual Quality Evaluation
**Branch:** `Shanu/RAG`

---

## Your Role in the System

You sit at two critical positions in the pipeline:

1. **Upstream of the agent (Task 1.2):** The planning agent (Member 3) calls `query_knowledge_base()` on every chat request. If your RAG function isn't ready or returns bad results, the agent produces hallucinations that the verification agent must reject. Your work is the factual backbone of every recommendation.

2. **Downstream of the agent (Tasks 3.1 and 3.4):** After the agent generates an English recommendation, it is passed to your `TranslationService` to convert it into the farmer's language. Your translation quality is what the farmer actually reads.

```
[Your RAG ──►] Planning Agent ──► Verification ──► [Your Translation ──►] Farmer
```

Your four tasks span all four weeks. Nothing about them blocks on other members except that Member 3 calls your functions — so define the function signatures first and implement later.

---

## Dependency Map

| Your task | Depends on | Blocks |
|---|---|---|
| 1.2 RAG Knowledge Base | Nothing (standalone pipeline) | Member 3 Task 2.2 (calls `query_knowledge_base`) |
| 3.1 IndicTrans2 Translation | Nothing (standalone service) | Member 3 Task 2.4 (calls `translate_output`) |
| 3.4 Language Detection | Task 3.1 done (routing feeds into translation) | Member 3 `AgentRunner.run()` |
| 5.3 Multilingual Evaluation | Tasks 3.1 + 3.4 done, Task 5.1 data ready | Final report (Week 4 milestone M4) |

**Action Item (do this in Week 1):** Publish the function signatures below to Member 3 so they can stub their MCP tool calls without waiting for your implementation.

---

## Files You Own

```
api/
  services/
    rag.py              — ChromaDB wrapper + query_knowledge_base()
    translation.py      — TranslationService (IndicTrans2)
    lang_detect.py      — detect_language(), detect_with_codeswitching()
ingestion/
  icar_loader.py        — PDF download + chunking + embedding pipeline
data/
  raw/icar/             — downloaded PDFs (not committed to git, gitignored)
  chromadb/             — persistent ChromaDB store (not committed, gitignored)
tests/
  test_rag.py           — retrieval accuracy tests
  test_translation.py   — IndicTrans2 output quality tests
docs/
  multilingual_eval_report.md  — Week 4 evaluation results
```

---

## Week 1 — Task 1.2: ICAR & SAU Knowledge Base

**Goal:** A populated ChromaDB vector store that `query_knowledge_base(crop, soil, query)` can serve in < 200 ms with ≥ 0.7 precision.

### Step 1 — Install Dependencies

```bash
pip install langchain chromadb sentence-transformers pdfplumber requests beautifulsoup4
```

### Step 2 — Download PDFs (`ingestion/icar_loader.py`)

Target: 200–500 PDFs covering **rice, wheat, maize, cotton, soybean** from:
- ICAR main site crop advisories
- State Agricultural University (SAU) extension bulletins

```python
import requests, os
from pathlib import Path

RAW_DIR = Path("data/raw/icar")
RAW_DIR.mkdir(parents=True, exist_ok=True)

ICAR_SOURCES = [
    # (filename, url) — fill in actual URLs during download sprint
    ("ICAR_Rice_Kharif_2023.pdf", "https://..."),
    ("ICAR_Wheat_Rabi_2023.pdf", "https://..."),
    # ... add more
]

def download_pdfs():
    for filename, url in ICAR_SOURCES:
        dest = RAW_DIR / filename
        if dest.exists():
            continue  # skip already downloaded
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"Downloaded {filename}")
```

**Minimum viable corpus (if download is slow):** 50 PDFs covering all 5 crops × 2 seasons (kharif/rabi) is enough to pass the precision threshold on the 20-query validation set. Aim for 200+ for quality.

### Step 3 — Chunk & Embed (`ingestion/icar_loader.py` continued)

```python
import pdfplumber
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb

splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    separators=["\n\n", "\n", ".", " "]
)

embed_model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim

chroma_client = chromadb.PersistentClient(path="./data/chromadb")
collection = chroma_client.get_or_create_collection(
    name="icar_knowledge",
    metadata={"hnsw:space": "cosine"}
)

# Metadata you must extract/infer from each PDF:
# crop        — "rice" | "wheat" | "maize" | "cotton" | "soybean"
# soil_type   — "clay" | "loam" | "sandy" | "clay_loam" | "silt_loam"  (or "all")
# season      — "kharif" | "rabi" | "zaid"
# These can be inferred from the filename convention: ICAR_{Crop}_{Season}_{Year}.pdf

def load_pdf(pdf_path: Path, crop: str, soil_type: str, season: str):
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text or len(text.strip()) < 50:
                continue
            chunks = splitter.split_text(text)
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{crop}_{soil_type}_{season}_{page_num:03d}_{chunk_idx:03d}"
                embedding = embed_model.encode(chunk).tolist()
                collection.add(
                    ids=[chunk_id],
                    embeddings=[embedding],
                    documents=[chunk],
                    metadatas=[{
                        "source":    pdf_path.name,
                        "page":      page_num,
                        "crop":      crop,
                        "soil_type": soil_type,
                        "season":    season,
                        "chunk_id":  chunk_id,
                    }]
                )
```

**Chunk ID convention:** `{crop}_{soil_type}_{season}_{page:03d}_{chunk:03d}`
Example: `rice_clay_kharif_004_002`

### Step 4 — RAG Service (`api/services/rag.py`)

This is the file Member 3 imports. The signature must not change after you publish it.

```python
from sentence_transformers import SentenceTransformer
import chromadb

_embed_model = SentenceTransformer("all-MiniLM-L6-v2")
_client = chromadb.PersistentClient(path="./data/chromadb")
_collection = _client.get_collection("icar_knowledge")

def query_knowledge_base(crop: str, soil: str, query: str, k: int = 5) -> list[dict]:
    """
    Returns top-k ICAR/SAU source chunks relevant to the query.
    Each dict has: text, source, chunk_id.
    """
    embedding = _embed_model.encode(query).tolist()
    results = _collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where={"crop": crop}   # metadata pre-filter by crop
    )
    return [
        {
            "text":     doc,
            "source":   meta["source"],
            "chunk_id": meta["chunk_id"],
        }
        for doc, meta in zip(
            results["documents"][0],
            results["metadatas"][0]
        )
    ]
```

**Important:** If ChromaDB returns 0 results (crop not in store yet), return `[]` — do not raise an exception. The agent handles empty RAG gracefully.

### Step 5 — Validation (20-Query Set)

Before handing off to Member 3, validate your RAG with a manual precision check:

```python
# tests/test_rag.py
VALIDATION_QUERIES = [
    {"crop": "rice", "soil": "clay", "query": "when to irrigate during vegetative stage", "expected_keyword": "irrigation"},
    {"crop": "wheat", "soil": "loam", "query": "fertilizer dose at sowing", "expected_keyword": "urea"},
    # ... 18 more — write them based on what you know from the PDFs
]

def test_retrieval_precision():
    hits = 0
    for q in VALIDATION_QUERIES:
        results = query_knowledge_base(q["crop"], q["soil"], q["query"])
        if any(q["expected_keyword"].lower() in r["text"].lower() for r in results):
            hits += 1
    precision = hits / len(VALIDATION_QUERIES)
    assert precision >= 0.70, f"Retrieval precision {precision:.2f} below 0.70 threshold"

def test_retrieval_latency():
    import time
    start = time.perf_counter()
    query_knowledge_base("rice", "clay", "when to sow")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 200, f"Retrieval took {elapsed_ms:.0f}ms — too slow"
```

Run with: `pytest tests/test_rag.py`

### Task 1.2 Acceptance Criteria
- [ ] 200+ chunks in ChromaDB (check: `collection.count()`)
- [ ] All 5 crops represented (rice, wheat, maize, cotton, soybean)
- [ ] `query_knowledge_base("rice", "clay", "when to irrigate")` returns 5 dicts with `text`, `source`, `chunk_id`
- [ ] Retrieval precision ≥ 0.70 on 20-query validation set
- [ ] Single query latency < 200 ms

---

## Week 3 (Part A) — Task 3.1: IndicTrans2 Translation Integration

**Goal:** A `TranslationService` class that Member 3 can call as `translation_service.translate(text, tgt_lang)` and get back a valid Indic-script string in < 3 seconds on CPU.

### Model Choice

The plan recommends **Option A (HuggingFace Inference API)** for a course project — no GPU required, no 4GB download per run.

**Option A — HuggingFace Inference API (recommended):**
```bash
pip install huggingface_hub
# Set env var: HF_TOKEN=<your token from huggingface.co>
```

**Option B — Local model (only if you have a GPU with ≥ 8GB VRAM):**
```bash
pip install transformers==4.38.0 sentencepiece==0.1.99 sacremoses
pip install torch==2.1.0+cu118 --extra-index-url https://download.pytorch.org/whl/cu118
```

### Implementation (`api/services/translation.py`)

```python
import os
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch

class TranslationService:
    SUPPORTED_LANGS = {
        "hin_Deva",   # Hindi
        "tam_Taml",   # Tamil
        "tel_Telu",   # Telugu
        "mar_Deva",   # Marathi
        "pan_Guru",   # Punjabi
    }
    # English (eng_Latn) is pass-through — no translation needed

    def __init__(
        self,
        model_name: str = "ai4bharat/indictrans2-en-indic-1B",
        device: str = "cpu"
    ):
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name, trust_remote_code=True
        ).to(device)
        self.device = device

    def translate(self, text: str, tgt_lang: str) -> dict:
        """
        Translates English text to tgt_lang (FLORES-200 code).
        Returns {"translated": str, "lang": str}.
        Falls back to English if tgt_lang not supported.
        """
        if tgt_lang not in self.SUPPORTED_LANGS:
            return {"translated": text, "lang": "eng_Latn", "fallback": True}

        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        ).to(self.device)

        with torch.no_grad():
            generated = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.lang_code_to_id[tgt_lang],
                max_new_tokens=512,
                num_beams=4,
                early_stopping=True,
            )

        translated = self.tokenizer.batch_decode(
            generated, skip_special_tokens=True
        )[0]
        return {"translated": translated, "lang": tgt_lang}
```

**Notes:**
- The model outputs correct Unicode — no post-processing for scripts.
- Always pass `trust_remote_code=True` — the model uses custom tokenizer code.
- `max_length=512` for input truncation is safe; recommendations are < 200 words.

### Singleton Pattern (used in `api/main.py`)

The model takes 10–20s to load. Instantiate once at startup, reuse across requests:

```python
# api/main.py (coordinate with Member 1)
from api.services.translation import TranslationService

translation_service = TranslationService()  # loads on startup
```

### Tests (`tests/test_translation.py`)

```python
import pytest
from api.services.translation import TranslationService

@pytest.fixture(scope="module")
def svc():
    return TranslationService()   # load once for the whole module

def test_hindi_translation(svc):
    result = svc.translate("Sow your rice seeds now.", "hin_Deva")
    assert result["lang"] == "hin_Deva"
    assert len(result["translated"]) > 5
    # Check for Devanagari characters (U+0900–U+097F)
    assert any('ऀ' <= c <= 'ॿ' for c in result["translated"])

def test_tamil_translation(svc):
    result = svc.translate("Apply urea fertilizer at 25 kg per acre.", "tam_Taml")
    assert result["lang"] == "tam_Taml"
    # Tamil Unicode range: U+0B80–U+0BFF
    assert any('஀' <= c <= '௿' for c in result["translated"])

def test_unsupported_lang_fallback(svc):
    result = svc.translate("Irrigate now.", "xyz_Unknown")
    assert result["lang"] == "eng_Latn"
    assert result["translated"] == "Irrigate now."
    assert result.get("fallback") is True

def test_english_passthrough(svc):
    result = svc.translate("Apply fertilizer.", "eng_Latn")
    # eng_Latn is not in SUPPORTED_LANGS → fallback
    assert result["lang"] == "eng_Latn"
```

### Task 3.1 Acceptance Criteria
- [ ] `translate("...200-word text...", "hin_Deva")` completes in < 3 s on CPU
- [ ] Output contains correct Devanagari/Tamil/Telugu/Marathi/Punjabi Unicode characters
- [ ] Fallback to English when `tgt_lang` not in supported set
- [ ] No post-processing needed — model output is clean UTF-8

---

## Week 3 (Part B) — Task 3.4: Language Detection & Routing

**Goal:** A `detect_language(text)` function that returns the correct FLORES-200 code, plus handling for mixed Hindi-English (Hinglish) inputs.

### Why lingua-py (not langdetect)

`langdetect` frequently mis-classifies short Indic text and confuses Hindi/Marathi/Nepali. `lingua-py` uses a statistical model trained specifically to distinguish closely related languages — better for the 5–30 word queries farmers will type.

### Implementation (`api/services/lang_detect.py`)

```bash
pip install lingua-language-detector
```

```python
from lingua import Language, LanguageDetectorBuilder

# Map lingua's enum → FLORES-200 code
LINGUA_TO_FLORES = {
    Language.HINDI:   "hin_Deva",
    Language.TAMIL:   "tam_Taml",
    Language.TELUGU:  "tel_Telu",
    Language.MARATHI: "mar_Deva",
    Language.PUNJABI: "pan_Guru",
    Language.ENGLISH: "eng_Latn",
}

# Build detector once at module import — takes ~1s the first time
_detector = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH,
    Language.HINDI,
    Language.TAMIL,
    Language.TELUGU,
    Language.MARATHI,
    Language.PUNJABI,
).build()


def detect_language(text: str) -> str:
    """Returns FLORES-200 code for the detected language. Defaults to eng_Latn."""
    lang = _detector.detect_language_of(text)
    return LINGUA_TO_FLORES.get(lang, "eng_Latn")


def detect_with_codeswitching(text: str) -> str:
    """
    Handles Hinglish / mixed-script text.
    If Devanagari characters outnumber Latin letters, classify as Hindi.
    """
    devanagari = sum(1 for c in text if 'ऀ' <= c <= 'ॿ')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if devanagari > latin:
        return "hin_Deva"
    return detect_language(text)
```

### Where This Is Called (Integration Point)

Member 3 calls this in `AgentRunner.run()` when `farmer.lang_pref` is not set. The code will look like:

```python
# api/agents/planner.py (Member 3's code — shown for context only)
from api.services.lang_detect import detect_with_codeswitching

async def run(self, farmer_id, user_message, session_id):
    profile = await get_farmer_profile(farmer_id)
    # Use profile lang_pref if set; otherwise detect from the message
    lang = profile.get("lang_pref") or detect_with_codeswitching(user_message)
    ...
```

**Tell Member 3:** the function is in `api.services.lang_detect` and returns a FLORES-200 string — no further mapping needed on their side.

### Tests

```python
def test_hindi_detection():
    assert detect_language("क्या मुझे अभी बुवाई करनी चाहिए?") == "hin_Deva"

def test_tamil_detection():
    assert detect_language("இப்போது விதைக்க வேண்டுமா?") == "tam_Taml"

def test_english_detection():
    assert detect_language("Should I sow now?") == "eng_Latn"

def test_hinglish_codeswitching():
    # Mixed: "Kya mujhe abhi बुवाई करनी chahiye?" — Devanagari dominant
    result = detect_with_codeswitching("क्या mujhe abhi sow karna chahiye?")
    assert result == "hin_Deva"

def test_unknown_lang_fallback():
    assert detect_language("Bonjour le monde") == "eng_Latn"
```

### Task 3.4 Acceptance Criteria
- [ ] Correctly identifies Hindi, Tamil, Telugu, Marathi, Punjabi, English
- [ ] `detect_with_codeswitching` returns `hin_Deva` for Hinglish text where Devanagari > Latin
- [ ] Default fallback is `eng_Latn` for unrecognised input
- [ ] Detection latency < 50 ms per query (lingua is fast; single call is near-instant)

---

## Week 4 — Task 5.3: Multilingual Quality Evaluation

**Goal:** Prove that your translation doesn't lose agronomic meaning. Method: translate English → Indic → back to English → measure semantic similarity. Must hit ≥ 0.65 per language.

### What You Need Before Starting

- Task 3.1 `TranslationService` working ✓
- **Also need:** `ai4bharat/indictrans2-indic-en-1B` (the reverse model: Indic → English)
- `data/test_scenarios.json` from Member 4 (Task 5.1) — use the `ground_truth_recommendation` field as your source English texts

### Implementation

```python
# You need BOTH models for back-translation
from api.services.translation import TranslationService
from sentence_transformers import SentenceTransformer, util
import json, csv

fwd_translator = TranslationService("ai4bharat/indictrans2-en-indic-1B")
bwd_translator = TranslationService("ai4bharat/indictrans2-indic-en-1B")
embed_model    = SentenceTransformer("all-MiniLM-L6-v2")


def back_translation_score(original_en: str, tgt_lang: str) -> dict:
    """Translate English → Indic → back to English, measure semantic drift."""
    forward  = fwd_translator.translate(original_en, tgt_lang)["translated"]
    backward = bwd_translator.translate(forward, "eng_Latn")["translated"]

    emb_orig = embed_model.encode(original_en, convert_to_tensor=True)
    emb_back = embed_model.encode(backward,    convert_to_tensor=True)
    sim = util.cos_sim(emb_orig, emb_back).item()

    return {
        "language":     tgt_lang,
        "original":     original_en,
        "forward":      forward,
        "back":         backward,
        "semantic_sim": round(sim, 4),
        "pass":         sim >= 0.65,
    }


def run_full_evaluation(scenarios_path: str, output_csv: str):
    with open(scenarios_path) as f:
        scenarios = json.load(f)

    rows = []
    TARGET_LANGS = ["hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru"]

    for scenario in scenarios:
        en_text = scenario["ground_truth_recommendation"]
        for lang in TARGET_LANGS:
            result = back_translation_score(en_text, lang)
            result["scenario_id"] = scenario["scenario_id"]
            rows.append(result)

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # Print per-language summary
    for lang in TARGET_LANGS:
        lang_rows = [r for r in rows if r["language"] == lang]
        avg_sim = sum(r["semantic_sim"] for r in lang_rows) / len(lang_rows)
        passed  = sum(1 for r in lang_rows if r["pass"])
        print(f"{lang}: avg_sim={avg_sim:.3f}, passed={passed}/{len(lang_rows)}")
```

Run it:
```bash
python -m scripts.run_multilingual_eval   # or however you wire the script
# Output: docs/multilingual_eval_report.csv
```

### Native Speaker Checks

Pick 2 scenarios per language (10 total). For each, share:
- The original English recommendation
- Your model's forward translation (Indic)
- The back-translation

Ask the reviewer: "Does the translated advice mean the same thing in your language? Is anything lost, added, or culturally inappropriate?"

Document findings in `docs/multilingual_eval_report.md`.

### Task 5.3 Acceptance Criteria
- [ ] Back-translation semantic similarity ≥ 0.65 for all 5 languages
- [ ] Results CSV committed to `docs/multilingual_eval_report.csv`
- [ ] 2 native-speaker checks per language documented in `docs/multilingual_eval_report.md`
- [ ] Summary table shows per-language pass/fail

---

## Dependencies You Must Install

Collect these in your section of `requirements.txt`:

```
# Task 1.2 — RAG
langchain>=0.1.0
chromadb>=0.4.0
sentence-transformers>=2.2.2
pdfplumber>=0.10.0
requests>=2.31.0

# Task 3.1 — Translation
transformers==4.38.0
sentencepiece==0.1.99
sacremoses>=0.0.53
torch>=2.1.0              # CPU build; GPU build needs --extra-index-url

# Task 3.4 — Language Detection
lingua-language-detector>=1.3.0

# Task 5.3 — Evaluation (shared with sentence-transformers above)
rouge-score>=0.1.2        # if you want ROUGE in addition to cosine
```

---

## Week-by-Week Timeline

| Week | Task | Deliverable | Done when |
|---|---|---|---|
| 1 | 1.2 | Download 200+ PDFs, load into ChromaDB | `query_knowledge_base("rice","clay","when to sow")` returns 5 chunks |
| 1 | 1.2 | Publish `api/services/rag.py` stub to Member 3 | Function signature locked, even if DB is empty |
| 2 | 1.2 | Validate retrieval precision on 20-query set | `pytest tests/test_rag.py` green |
| 3A | 3.1 | `TranslationService` implemented | Hindi translation test passing, < 3s CPU |
| 3A | 3.4 | `lang_detect.py` implemented | 5-language detection tests passing |
| 3A | 3.1+3.4 | Notify Member 3 | Integration test: they call your services from `AgentRunner` |
| 4 | 5.3 | Back-translation evaluation on all 5 languages | CSV committed, all ≥ 0.65 |
| 4 | 5.3 | Native speaker checks (2 per language) | `multilingual_eval_report.md` committed |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| HuggingFace Inference API rate-limited | Download local model early; use API for evaluation only |
| IndicTrans2 local model OOM on CPU | Use batch size 1; truncate inputs at 256 tokens instead of 512 |
| PDFs are scanned images (no text layer) | Use `pdfplumber` first; fall back to `pytesseract` OCR for image-only pages |
| ChromaDB returns 0 results for rare crop | Return `[]` gracefully; do NOT filter by soil_type if that also returns 0 |
| Back-translation sim < 0.65 for one language | Report it honestly; add a note that the model struggles with that language; flag for native-speaker review |
| Member 3 changes `query_knowledge_base` signature | You own the signature — push back if they ask to change it mid-sprint |

---

## Definition of Done (Member 2)

- [ ] `api/services/rag.py` — `query_knowledge_base()` functional, tested, precision ≥ 0.70
- [ ] `api/services/translation.py` — `TranslationService.translate()` for all 5 Indic langs, < 3s CPU
- [ ] `api/services/lang_detect.py` — `detect_language()` + `detect_with_codeswitching()` tested
- [ ] `ingestion/icar_loader.py` — PDF ingestion pipeline complete, data in ChromaDB
- [ ] `tests/test_rag.py` — retrieval precision and latency tests green
- [ ] `tests/test_translation.py` — translation output tests green for all 5 languages
- [ ] `docs/multilingual_eval_report.csv` + `docs/multilingual_eval_report.md` committed
- [ ] Member 3 has confirmed they can call your services end-to-end
