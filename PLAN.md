# PLAN.md — CropCompass Technical Execution Plan

**Project:** CropCompass — Multilingual Agentic Advisory System (Web Chat)
**Team:** 5 members | **Duration:** 4 weeks | **Tasks:** 21 across 6 work streams

---

## Tech Stack Overview

| Layer | Technology |
|-------|-----------|
| LLM / Agent | Anthropic API (`claude-sonnet-4-6`) via MCP tool-use |
| Translation | AI4Bharat `IndicTrans2` (`indictrans2-en-indic-1B`) |
| Language Detection | `lingua-py` or `fasttext` (lid.176.bin) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Vector Store | `ChromaDB` (local) or `FAISS` |
| Backend API | `FastAPI` + `Uvicorn` |
| Frontend | `React` (Vite) + Noto Indic Fonts |
| Database | `PostgreSQL` + `SQLAlchemy` (ORM) + `Alembic` (migrations) |
| Scheduling | `APScheduler` (in-process) |
| Testing | `pytest` + `pytest-asyncio` |
| Containerisation | `Docker` + `docker-compose` |
| Model Serving | HuggingFace Inference API or local GPU (CUDA 11.8, PyTorch 2.1) |

---

## Dependency Graph

```
WS6.1 ──► WS6.2
          │
WS1.1 ──► │
WS1.2 ──► │
WS1.3 ──► ├──► WS2.1 ──► WS2.2 ──► WS2.4 ──► WS2.3
WS1.4 ──► │                                      │
           │                                      ▼
           │         WS3.4 ──► WS3.1 ────────► WS2.5
           │                                      │
           └──────────────────────────────────► WS4.1
                                                  │
                                               WS4.3
                                                  │
                                               WS5.1 ──► WS5.2
                                               WS5.1 ──► WS5.3
                                               WS5.1 ──► WS5.4
                                               WS5.5 (all of above)
```

---

## Phase 1 — Foundation (Week 1)

**Goal:** Data pipelines running, infrastructure decisions locked, farmer profile DB ready.
**Tasks:** 1.1, 1.2, 1.3, 1.4, 6.1, 6.2

---

### Task 6.1 — System Architecture & API Design
**Owner:** Member 1

**Deliverable:** Architecture diagram + OpenAPI 3.0 spec

**Technical steps:**
1. Draw system architecture in Mermaid (committed as `docs/architecture.md`)
2. Define REST API contracts with FastAPI route stubs:
   - `POST /api/chat` — accepts `{farmer_id, message, session_id}`, returns recommendation
   - `POST /api/profile` — creates/updates farmer profile
   - `GET /api/profile/{farmer_id}` — fetch profile
   - `GET /api/forecast/{district}` — latest IMD advisory
3. Define internal service boundaries: agent service, RAG service, translation service
4. Decide deployment: Docker Compose (dev), single-server (prod)
5. Write `openapi.yaml` and validate with `redocly lint`

**Key decisions to lock:**
- Self-hosted IndicTrans2 vs HuggingFace Inference API (cost vs latency)
- Sync vs async agent calls (use `async/await` throughout FastAPI)
- Session storage: server-side dict (dev) → Redis (prod)

---

### Task 6.2 — Model Hosting & Compute Setup
**Owner:** Member 1

**Deliverable:** Running IndicTrans2 endpoint + Anthropic API key configured

**Technical steps:**

*Option A — HuggingFace Inference API (recommended for course project):*
```python
from huggingface_hub import InferenceClient
client = InferenceClient(model="ai4bharat/indictrans2-en-indic-1B", token=HF_TOKEN)
```

*Option B — Local GPU hosting:*
```bash
# Requirements: CUDA 11.8+, 8 GB VRAM minimum
pip install torch==2.1.0+cu118 transformers==4.38.0 sentencepiece
# Model download (~4 GB)
python -c "from transformers import AutoModelForSeq2SeqLM; AutoModelForSeq2SeqLM.from_pretrained('ai4bharat/indictrans2-en-indic-1B')"
```

*Anthropic API setup:*
```python
import anthropic
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

**Latency targets:**
| Component | Target P95 latency |
|-----------|-------------------|
| IndicTrans2 (1 sentence) | < 2 s |
| LLM planning agent (1 turn) | < 8 s |
| Full pipeline (chat → response) | < 15 s |

**Environment config (`docker-compose.yml` services):**
- `api` — FastAPI backend (port 8000)
- `db` — PostgreSQL 15 (port 5432)
- `vectordb` — ChromaDB (port 8001)

---

### Task 1.1 — IMD GKMS Advisory Ingestion Pipeline
**Owner:** Member 1

**Deliverable:** Scheduled scraper + structured forecast records in PostgreSQL

**Data source:** IMD Gramin Krishi Mausam Sewa bulletins
- URL pattern: district-level HTML/PDF bulletins, updated daily
- Fallback: download PDF bulletins and parse with `pdfplumber`

**Technical steps:**
```python
# Dependencies
pip install requests beautifulsoup4 pdfplumber apscheduler sqlalchemy psycopg2-binary

# DB schema (SQLAlchemy model)
class IMDAdvisory(Base):
    __tablename__ = "imd_advisories"
    id            = Column(Integer, primary_key=True)
    district      = Column(String, index=True)
    state         = Column(String)
    bulletin_date = Column(Date, index=True)
    rainfall_prob = Column(Float)          # 0.0–1.0
    season_outlook= Column(String)         # "normal" | "deficient" | "excess"
    raw_text      = Column(Text)
    fetched_at    = Column(DateTime, default=func.now())
    is_stale      = Column(Boolean, default=False)
```

**Parsing pipeline:**
1. HTTP GET bulletin page → BeautifulSoup parse table rows
2. Extract `district`, `date`, `rainfall_probability`, `season_outlook`, `crop_advisory_text`
3. Validate: reject records where `rainfall_prob` is null or `district` not in master list
4. Upsert into `imd_advisories` (unique on `district + bulletin_date`)

**Scheduler:**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(fetch_imd_advisories, 'cron', hour=6)  # 6 AM daily
```

**Acceptance criteria:**
- Covers all 36 meteorological districts used in test scenarios
- Records persisted within 1 hour of IMD bulletin publication
- Stale flag set if bulletin older than 48 hours

---

### Task 1.2 — ICAR & SAU Knowledge Base
**Owner:** Member 2

**Deliverable:** Populated ChromaDB vector store with ICAR and SAU documents

**Data collection:**
- Sources: ICAR website PDFs, State Agricultural University extension bulletins
- Target: 200–500 documents covering major crops (rice, wheat, maize, cotton, soybean)
- Download with `requests`, store raw PDFs in `data/raw/icar/`

**Processing pipeline:**
```python
# Dependencies
pip install langchain chromadb sentence-transformers pdfplumber

# Chunking strategy
from langchain.text_splitter import RecursiveCharacterTextSplitter
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    separators=["\n\n", "\n", ".", " "]
)

# Embeddings
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim, fast, sufficient quality

# ChromaDB collection
import chromadb
client = chromadb.PersistentClient(path="./data/chromadb")
collection = client.get_or_create_collection(
    name="icar_knowledge",
    metadata={"hnsw:space": "cosine"}
)
```

**Document metadata schema per chunk:**
```json
{
  "source": "ICAR_Rice_Advisory_2023.pdf",
  "page": 4,
  "crop": "rice",
  "soil_type": "clay_loam",
  "season": "kharif",
  "chunk_id": "rice_clay_kharif_004_002"
}
```

**Retrieval function (used by MCP tool):**
```python
def query_knowledge_base(crop: str, soil: str, query: str, k: int = 5) -> list[dict]:
    embedding = model.encode(query).tolist()
    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where={"crop": crop}  # metadata filter
    )
    return [{"text": doc, "source": meta["source"], "chunk_id": meta["chunk_id"]}
            for doc, meta in zip(results["documents"][0], results["metadatas"][0])]
```

**Acceptance criteria:**
- Top-5 retrieval precision ≥ 0.7 on a 20-query validation set
- < 200 ms retrieval latency for a single query

---

### Task 1.3 — Farmer Profile & Context Schema
**Owner:** Member 1

**Deliverable:** `farmers` table + Pydantic schema + CRUD API endpoints

**DB schema:**
```python
class Farmer(Base):
    __tablename__ = "farmers"
    farmer_id    = Column(UUID, primary_key=True, default=uuid4)
    name         = Column(String, nullable=True)
    district     = Column(String, nullable=False)  # matches IMD district names
    block        = Column(String, nullable=True)
    soil_type    = Column(Enum("clay","loam","sandy","clay_loam","silt_loam"), nullable=False)
    crop_variety = Column(String, nullable=False)  # e.g. "IR-36 rice", "HD-2967 wheat"
    growth_stage = Column(Enum("sowing","vegetative","flowering","maturity"), nullable=False)
    lang_pref    = Column(String, nullable=False)  # FLORES-200 code e.g. "hin_Deva"
    created_at   = Column(DateTime, default=func.now())
    updated_at   = Column(DateTime, onupdate=func.now())
```

**Pydantic schema (FastAPI request/response):**
```python
class FarmerCreate(BaseModel):
    district: str
    soil_type: Literal["clay","loam","sandy","clay_loam","silt_loam"]
    crop_variety: str
    growth_stage: Literal["sowing","vegetative","flowering","maturity"]
    lang_pref: str  # validated against SUPPORTED_LANGS list

class FarmerResponse(FarmerCreate):
    farmer_id: UUID
    created_at: datetime
```

**FLORES-200 language codes supported:**
```python
SUPPORTED_LANGS = {
    "Hindi":   "hin_Deva",
    "Tamil":   "tam_Taml",
    "Telugu":  "tel_Telu",
    "Marathi": "mar_Deva",
    "Punjabi": "pan_Guru",
    "English": "eng_Latn",
}
```

---

### Task 1.4 — Data Refresh & Staleness Handling
**Owner:** Member 1

**Deliverable:** Scheduler + staleness flags + structured logs

**Staleness rules:**
```python
STALENESS_THRESHOLDS = {
    "imd_advisory":    timedelta(hours=48),
    "icar_document":   timedelta(days=180),
    "farmer_profile":  timedelta(days=90),
}

def mark_stale(db: Session):
    cutoff = datetime.utcnow() - STALENESS_THRESHOLDS["imd_advisory"]
    db.query(IMDAdvisory).filter(
        IMDAdvisory.bulletin_date < cutoff
    ).update({"is_stale": True})
    db.commit()
```

**Structured logging (JSON):**
```python
import structlog
log = structlog.get_logger()
log.info("imd_fetch_complete",
         district_count=36,
         new_records=12,
         failed_districts=["Vizianagaram"],
         duration_s=4.2)
```

**Conflict handling:** if two advisories exist for same district+date, keep the one with the later `fetched_at` timestamp.

---

## Phase 2 — Core Agent Loop in English (Week 2)

**Goal:** Planning agent + MCP tools + verification agent working end-to-end, English only.
**Tasks:** 2.1, 2.2, 2.3, 2.4, 2.5

---

### Task 2.1 — Central Planning Agent
**Owner:** Member 3

**Deliverable:** LLM orchestrator that decomposes queries and coordinates tool calls

**Model:** `claude-sonnet-4-6` via Anthropic API with tool-use (MCP style)

**Agent flow:**
```
User query
    │
    ▼
[Phase A: Gather Context]
    ├── get_farmer_profile(farmer_id)
    ├── fetch_forecast(district, date=today)
    └── query_knowledge_base(crop, soil, query)
    │
    ▼
[Phase B: Generate Recommendation]
    └── LLM call with assembled context → structured recommendation
    │
    ▼
[Phase C: Verify]
    └── verification_agent(recommendation, source_chunks) → verified / rejected
    │
    ▼
[Phase D: Translate]
    └── translate_output(recommendation, lang_pref) → Indic text
```

**Anthropic tool-use call pattern:**
```python
import anthropic

client = anthropic.Anthropic()

tools = [
    {
        "name": "fetch_forecast",
        "description": "Fetch latest IMD weather forecast for a district",
        "input_schema": {
            "type": "object",
            "properties": {
                "district": {"type": "string"},
                "date": {"type": "string", "format": "date"}
            },
            "required": ["district"]
        }
    },
    # ... other tools
]

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    tools=tools,
    messages=[{"role": "user", "content": assembled_context}]
)

# Handle tool_use blocks in response
for block in response.content:
    if block.type == "tool_use":
        result = dispatch_tool(block.name, block.input)
        # append tool_result to messages and loop
```

**Context assembly order (priority, fits in ~4k tokens):**
1. System prompt (agent persona, output format)
2. Farmer profile (district, crop, soil, growth stage)
3. IMD advisory (current district forecast, 300 tokens max)
4. ICAR source chunks (top-5, 1000 tokens max)
5. User question

---

### Task 2.2 — MCP Tool Definitions
**Owner:** Member 3

**Deliverable:** 4 callable tool functions with JSON schemas and unit tests

**Tool implementations:**
```python
# tools.py

async def fetch_forecast(district: str, date: str | None = None) -> dict:
    """Returns latest IMD advisory for district."""
    record = await db.query(IMDAdvisory).filter_by(
        district=district,
        is_stale=False
    ).order_by(IMDAdvisory.bulletin_date.desc()).first()
    if not record:
        return {"error": "no_forecast", "district": district}
    return {
        "district": district,
        "date": str(record.bulletin_date),
        "rainfall_prob": record.rainfall_prob,
        "season_outlook": record.season_outlook,
        "advisory_text": record.raw_text[:500]
    }

async def query_knowledge_base(crop: str, soil: str, query: str) -> list[dict]:
    """Returns top-5 ICAR/SAU source chunks."""
    return rag_service.query(crop=crop, soil=soil, query=query, k=5)

async def get_farmer_profile(farmer_id: str) -> dict:
    """Returns farmer context record."""
    farmer = await db.get(Farmer, UUID(farmer_id))
    return FarmerResponse.from_orm(farmer).dict() if farmer else {"error": "not_found"}

async def translate_output(text: str, target_lang: str) -> dict:
    """Translates English recommendation to target Indic language."""
    if target_lang == "eng_Latn":
        return {"translated": text, "lang": "eng_Latn"}
    return translation_service.translate(text=text, tgt_lang=target_lang)
```

**Tool dispatcher:**
```python
TOOL_MAP = {
    "fetch_forecast":       fetch_forecast,
    "query_knowledge_base": query_knowledge_base,
    "get_farmer_profile":   get_farmer_profile,
    "translate_output":     translate_output,
}

async def dispatch_tool(name: str, inputs: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"unknown_tool: {name}"})
    result = await fn(**inputs)
    return json.dumps(result, ensure_ascii=False)
```

**Acceptance criteria (unit tests):**
- `fetch_forecast("Pune")` returns record when DB has data; returns `error: no_forecast` when stale
- `query_knowledge_base("rice", "clay", "when to irrigate")` returns 5 chunks, each with `source` and `chunk_id`
- `get_farmer_profile(unknown_id)` returns `error: not_found` without raising exception
- `translate_output("Sow now", "hin_Deva")` returns non-empty Hindi string

---

### Task 2.3 — Verification Agent
**Owner:** Member 4

**Deliverable:** Agent that grounds every claim in a source chunk, rejects hallucinations

**Architecture:** Separate LLM call after main recommendation is generated

**Grounding rubric:**
```
For each claim in the recommendation:
  1. Is there a retrieved source chunk that supports this claim?
  2. Does the chunk come from ICAR or a recognised SAU?
  3. Is the claim consistent with the current season and district forecast?

Verdict: PASS (all claims grounded) | PARTIAL (some claims ungrounded, flag them)
       | REJECT (core advice unsupported — do not deliver)
```

**Implementation:**
```python
VERIFICATION_SYSTEM_PROMPT = """
You are an agricultural fact-checker. Given a recommendation and a set of source chunks,
check every factual claim in the recommendation:
- Each sowing window, irrigation schedule, fertilizer dose, or pest control advice
  must be traceable to one of the provided source chunks.
- If a claim has no supporting source, mark it as UNSUPPORTED.
- If ALL core agronomic claims are supported, return verdict: PASS.
- If any core claim is unsupported, return verdict: REJECT with reasons.

Respond strictly in JSON:
{
  "verdict": "PASS" | "PARTIAL" | "REJECT",
  "unsupported_claims": ["claim text ..."],
  "supporting_citations": {"claim text": "chunk_id"}
}
"""

async def verify_recommendation(recommendation: str, source_chunks: list[dict]) -> dict:
    chunks_text = "\n\n".join(
        f"[{c['chunk_id']}] {c['text']}" for c in source_chunks
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=VERIFICATION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Recommendation:\n{recommendation}\n\nSources:\n{chunks_text}"
        }]
    )
    return json.loads(response.content[0].text)
```

**Fallback policy:**
- `REJECT` → return a safe fallback message: "Please consult your local Krishi Vigyan Kendra for current advice."
- `PARTIAL` → deliver recommendation with unsupported claims removed and a disclaimer added

---

### Task 2.4 — Agentic Loop & Context Engineering
**Owner:** Member 3

**Deliverable:** `AgentRunner` class implementing the full three-phase loop

**Token budget management:**
```python
CONTEXT_BUDGET = {
    "system_prompt":   800,   # tokens
    "farmer_profile":  200,
    "imd_forecast":    300,
    "icar_chunks":    1200,   # 5 chunks × ~240 tokens
    "user_query":      200,
    "conversation_history": 500,
    # Total: ~3200 tokens → safe for 4k context window
}
```

**AgentRunner:**
```python
class AgentRunner:
    def __init__(self, db, rag, translator):
        self.db = db
        self.rag = rag
        self.translator = translator

    async def run(self, farmer_id: str, user_message: str, session_id: str) -> AgentResponse:
        # Phase A: Gather
        profile  = await get_farmer_profile(farmer_id)
        forecast = await fetch_forecast(profile["district"])
        chunks   = await query_knowledge_base(
            profile["crop_variety"], profile["soil_type"], user_message
        )

        # Phase B: Generate
        context  = self._assemble_context(profile, forecast, chunks, user_message)
        rec_text = await self._llm_generate(context)

        # Phase C: Verify
        verdict  = await verify_recommendation(rec_text, chunks)
        if verdict["verdict"] == "REJECT":
            rec_text = SAFE_FALLBACK_MESSAGE
        elif verdict["verdict"] == "PARTIAL":
            rec_text = self._strip_unsupported(rec_text, verdict["unsupported_claims"])

        # Phase D: Translate
        translated = await translate_output(rec_text, profile["lang_pref"])

        return AgentResponse(
            text=translated["translated"],
            lang=profile["lang_pref"],
            verdict=verdict["verdict"],
            citations=verdict.get("supporting_citations", {}),
            session_id=session_id
        )
```

---

### Task 2.5 — Prompt & Specification Design
**Owner:** Member 3

**Deliverable:** System prompts for planning agent + verification agent, SDD written as `docs/agent_spec.md`

**Planning agent system prompt:**
```
You are CropCompass, an agricultural advisory assistant for smallholder farmers in India.

Rules:
1. Always answer in plain, simple language. Avoid jargon. Assume the farmer has
   primary school education.
2. Structure every recommendation as:
   - What to do (action)
   - When to do it (timing)
   - Why (one sentence, reference to forecast or agronomic knowledge)
3. Never make up fertilizer doses or pesticide names. Only use information from
   the provided source chunks.
4. If the forecast data is missing or stale, say so explicitly.
5. Keep recommendations under 200 words.
```

**SDD fields per agent:**
```yaml
# docs/agent_spec.md structure for each agent
agent: planning_agent
goal: Produce a personalised, actionable crop recommendation
constraints:
  - max_output_tokens: 512
  - max_tool_rounds: 4
  - must_use_tools: [fetch_forecast, query_knowledge_base, get_farmer_profile]
input_schema:
  farmer_id: UUID
  user_message: string (max 500 chars)
output_schema:
  recommendation: string
  citations: dict[claim -> chunk_id]
acceptance_criteria:
  - Recommendation references at least one ICAR chunk
  - No hallucinated crop varieties or chemical names
  - Output < 200 words
```

---

## Phase 3 — Multilingual Text Layer (Week 3, Part A)

**Goal:** IndicTrans2 translation and language detection integrated into the agent pipeline.
**Tasks:** 3.1, 3.4

---

### Task 3.1 — IndicTrans2 Translation Integration
**Owner:** Member 2

**Deliverable:** `TranslationService` class wrapping IndicTrans2 with batch support

**Model:** `ai4bharat/indictrans2-en-indic-1B`
**HuggingFace model card:** https://huggingface.co/ai4bharat/indictrans2-en-indic-1B

**Installation:**
```bash
pip install transformers==4.38.0 sentencepiece==0.1.99 sacremoses
# For local GPU
pip install torch==2.1.0+cu118 --extra-index-url https://download.pytorch.org/whl/cu118
```

**TranslationService:**
```python
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch

class TranslationService:
    SUPPORTED_LANGS = {
        "hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru"
    }

    def __init__(self, model_name="ai4bharat/indictrans2-en-indic-1B", device="cpu"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name, trust_remote_code=True
        ).to(device)
        self.device = device

    def translate(self, text: str, tgt_lang: str) -> dict:
        if tgt_lang not in self.SUPPORTED_LANGS:
            return {"translated": text, "lang": "eng_Latn", "fallback": True}

        # IndicTrans2 uses FLORES-200 language tokens
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512
        ).to(self.device)

        with torch.no_grad():
            generated = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.lang_code_to_id[tgt_lang],
                max_new_tokens=512,
                num_beams=4,
                early_stopping=True
            )

        translated = self.tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
        return {"translated": translated, "lang": tgt_lang}
```

**Script rendering:** Ensure UTF-8 throughout. The model outputs correct Unicode for all supported scripts — no post-processing needed. The web UI handles font rendering via CSS.

**Acceptance criteria:**
- Translates a 200-word English recommendation to Hindi in < 3 s on CPU
- Output is valid UTF-8 with correct Devanagari/Tamil/Telugu/etc. characters
- Fallback to English when `tgt_lang` not in supported set

---

### Task 3.4 — Language Detection & Routing
**Owner:** Member 2

**Deliverable:** `detect_language(text)` function + routing logic in the agent pipeline

**Library:** `lingua-py` (more accurate than `langdetect` for short Indic text)
```bash
pip install lingua-language-detector
```

**Implementation:**
```python
from lingua import Language, LanguageDetectorBuilder

LINGUA_TO_FLORES = {
    Language.HINDI:   "hin_Deva",
    Language.TAMIL:   "tam_Taml",
    Language.TELUGU:  "tel_Telu",
    Language.MARATHI: "mar_Deva",
    Language.PUNJABI: "pan_Guru",
    Language.ENGLISH: "eng_Latn",
}

detector = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH, Language.HINDI, Language.TAMIL,
    Language.TELUGU, Language.MARATHI, Language.PUNJABI
).build()

def detect_language(text: str) -> str:
    """Returns FLORES-200 language code."""
    lang = detector.detect_language_of(text)
    return LINGUA_TO_FLORES.get(lang, "eng_Latn")  # default to English
```

**Code-switching handling (mixed Hindi-English):**
```python
def detect_with_codeswitching(text: str) -> str:
    # If majority script is Devanagari → treat as Hindi
    devanagari_chars = sum(1 for c in text if 'ऀ' <= c <= 'ॿ')
    latin_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    if devanagari_chars > latin_chars:
        return "hin_Deva"
    return detect_language(text)
```

**Integration point:** called in `AgentRunner.run()` when `farmer.lang_pref` is not pre-set, and also when routing incoming queries for display language.

---

## Phase 4 — Web Chat Interface (Week 3, Part B)

**Goal:** Working web chat UI with Indic rendering and farmer onboarding.
**Tasks:** 4.1, 4.3

---

### Task 4.1 — Web Chat Interface
**Owner:** Member 5

**Deliverable:** React chat app served at `/` that communicates with FastAPI backend

**Tech stack:**
```bash
npm create vite@latest cropcompass-ui -- --template react
cd cropcompass-ui
npm install axios socket.io-client
```

**Component structure:**
```
src/
  App.jsx             — router, global state
  components/
    ChatWindow.jsx    — message list, scroll management
    MessageBubble.jsx — renders user vs assistant messages
    InputBar.jsx      — text input + send button
    LanguageTag.jsx   — shows detected language of response
  hooks/
    useChat.js        — WebSocket / polling state management
  utils/
    api.js            — axios instance pointing to FastAPI
```

**Indic font CSS (public/index.css):**
```css
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari&family=Noto+Sans+Tamil&family=Noto+Sans+Telugu&family=Noto+Sans+Gujarati&display=swap');

.message-text {
  font-family: 'Noto Sans Devanagari', 'Noto Sans Tamil',
               'Noto Sans Telugu', 'Noto Sans Gujarati',
               'Segoe UI', sans-serif;
  line-height: 1.6;
  white-space: pre-wrap;
}
```

**WebSocket integration:**
```javascript
// hooks/useChat.js
import { useState, useEffect } from 'react';
import io from 'socket.io-client';

export function useChat(farmerId) {
  const [messages, setMessages] = useState([]);
  const [socket] = useState(() => io(import.meta.env.VITE_API_URL));

  const sendMessage = (text) => {
    const userMsg = { role: 'user', text, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    socket.emit('chat', { farmer_id: farmerId, message: text });
  };

  useEffect(() => {
    socket.on('response', (data) => {
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: data.text,
        lang: data.lang,
        verdict: data.verdict,
        citations: data.citations,
        ts: Date.now()
      }]);
    });
    return () => socket.disconnect();
  }, [socket]);

  return { messages, sendMessage };
}
```

**Backend Socket.IO handler (FastAPI + python-socketio):**
```python
import socketio
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

@sio.on('chat')
async def handle_chat(sid, data):
    farmer_id   = data['farmer_id']
    user_message = data['message']
    result = await agent_runner.run(farmer_id, user_message, session_id=sid)
    await sio.emit('response', result.dict(), room=sid)
```

**Recommendation display format in UI:**
```
┌─────────────────────────────────────────────┐
│ 🌾 Recommendation (Hindi)                   │
│ ─────────────────────────────────────────── │
│ अभी बुवाई करें। मानसून सामान्य रहेगा...    │
│                                             │
│ Sources: ICAR_Rice_2023.pdf, page 4         │
│ Verified ✓                                  │
└─────────────────────────────────────────────┘
```

---

### Task 4.3 — Farmer Onboarding & Profile Capture
**Owner:** Member 5

**Deliverable:** Multi-step onboarding form (3 steps, under 3 minutes)

**Onboarding steps:**
```
Step 1: Location
  - State dropdown (all Indian states)
  - District dropdown (filtered by state, loaded from DB)

Step 2: Farm Details
  - Soil type: Clay / Loam / Sandy / Clay Loam / Silt Loam  (radio buttons with icons)
  - Crop variety: text input with autocomplete from ICAR crop list
  - Growth stage: Sowing / Vegetative / Flowering / Maturity  (radio buttons)

Step 3: Language Preference
  - Buttons: हिंदी | தமிழ் | తెలుగు | मराठी | ਪੰਜਾਬੀ | English
  - Preview: show "नमस्ते, किसान!" in selected language to confirm font renders
```

**API call on completion:**
```javascript
const createProfile = async (formData) => {
  const { data } = await axios.post('/api/profile', {
    district:     formData.district,
    soil_type:    formData.soilType,
    crop_variety: formData.cropVariety,
    growth_stage: formData.growthStage,
    lang_pref:    LANG_TO_FLORES[formData.language]
  });
  localStorage.setItem('farmer_id', data.farmer_id);
  navigate('/chat');
};
```

**Validation rules:**
- District must exist in the master IMD districts list (server-side check)
- `crop_variety` min 2 characters
- All fields required before submitting

---

## Phase 5 — Evaluation & Testing (Week 4)

**Goal:** Run all evaluation suites, measure all 3 evaluation dimensions, produce final report.
**Tasks:** 5.1, 5.2, 5.3, 5.4, 5.5

---

### Task 5.1 — Curated Test Scenario Suite
**Owner:** Member 4

**Deliverable:** `data/test_scenarios.json` — 30–50 labelled scenarios

**Scenario schema:**
```json
{
  "scenario_id": "S001",
  "district": "Pune",
  "state": "Maharashtra",
  "season": "kharif",
  "soil_type": "clay_loam",
  "crop_variety": "Soybean JS-335",
  "growth_stage": "sowing",
  "imd_rainfall_prob": 0.72,
  "imd_season_outlook": "normal",
  "user_query": "Should I sow this week?",
  "ground_truth_recommendation": "Yes, sow within the next 5–7 days. Soil moisture is adequate with 72% rainfall probability. Use certified JS-335 seed at 75 kg/ha spacing.",
  "ground_truth_source": "ICAR_Soybean_Kharif_2022.pdf",
  "negative_example": "Do not sow yet, wait for monsoon to end."
}
```

**Scenario distribution (30–50 total):**
| Dimension | Values to cover |
|-----------|----------------|
| States | Maharashtra, Punjab, Tamil Nadu, Andhra Pradesh, Uttar Pradesh |
| Seasons | Kharif, Rabi, Zaid |
| Soil types | All 5 types |
| Crops | Rice, Wheat, Soybean, Cotton, Maize, Sorghum |
| Growth stages | All 4 stages |
| Rainfall scenarios | Low (< 0.4), Normal (0.4–0.7), High (> 0.7) |

---

### Task 5.2 — Recommendation Relevance Evaluation
**Owner:** Member 4

**Deliverable:** Evaluation script + scored results CSV

**Metrics:**
```python
from sentence_transformers import SentenceTransformer, util
from rouge_score import rouge_scorer

embed_model = SentenceTransformer("all-MiniLM-L6-v2")
scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)

def evaluate_relevance(predicted: str, ground_truth: str) -> dict:
    # Semantic similarity
    emb_pred = embed_model.encode(predicted, convert_to_tensor=True)
    emb_gt   = embed_model.encode(ground_truth, convert_to_tensor=True)
    cosine_sim = util.cos_sim(emb_pred, emb_gt).item()

    # ROUGE scores
    rouge = scorer.score(ground_truth, predicted)

    return {
        "cosine_similarity": round(cosine_sim, 4),
        "rouge1_f":  round(rouge['rouge1'].fmeasure, 4),
        "rouge2_f":  round(rouge['rouge2'].fmeasure, 4),
        "rougeL_f":  round(rouge['rougeL'].fmeasure, 4),
    }
```

**Passing threshold:** cosine similarity ≥ 0.70 on ≥ 80% of scenarios

**Expert rubric (manual, 10 scenarios reviewed by domain expert):**
```
Score each on 1–5:
  - Agronomic accuracy (does the crop advice align with ICAR guidelines?)
  - Actionability (can a farmer follow this immediately?)
  - Forecast alignment (does it use the rainfall probability correctly?)
```

---

### Task 5.3 — Multilingual Quality Evaluation
**Owner:** Member 2

**Deliverable:** Back-translation scores for 5 Indic languages

**Back-translation pipeline:**
```python
# English → Indic → back to English → compare to original

from indictrans2_service import TranslationService

# Note: needs both en-indic and indic-en models
fwd_translator = TranslationService("ai4bharat/indictrans2-en-indic-1B")
bwd_translator = TranslationService("ai4bharat/indictrans2-indic-en-1B")

def back_translation_score(original_en: str, tgt_lang: str) -> dict:
    translated   = fwd_translator.translate(original_en, tgt_lang)["translated"]
    back_to_en   = bwd_translator.translate(translated, "eng_Latn")["translated"]

    emb_orig = embed_model.encode(original_en, convert_to_tensor=True)
    emb_back = embed_model.encode(back_to_en, convert_to_tensor=True)
    sim = util.cos_sim(emb_orig, emb_back).item()

    return {
        "language":     tgt_lang,
        "forward":      translated,
        "back":         back_to_en,
        "semantic_sim": round(sim, 4)
    }
```

**Passing threshold:** Back-translation semantic similarity ≥ 0.65 per language

**Native-speaker checks:** 2 scenarios per language reviewed by a native speaker (team members or volunteers) for contextual accuracy and cultural appropriateness.

---

### Task 5.4 — Verification Agent Effectiveness Measurement
**Owner:** Member 4

**Deliverable:** Precision and recall of verification agent on a gold set of hallucinations

**Gold set construction:**
- 20 deliberately hallucinated recommendations (wrong doses, wrong seasons, invented varieties)
- 20 correct, ICAR-grounded recommendations (from test suite)

**Metrics:**
```python
# True positive = hallucination correctly caught (verdict: REJECT or PARTIAL)
# False negative = hallucination delivered as PASS
# False positive = correct recommendation rejected as REJECT

def compute_verification_metrics(gold_set: list[dict]) -> dict:
    tp = fp = fn = tn = 0
    for item in gold_set:
        verdict = item["agent_verdict"]  # PASS | PARTIAL | REJECT
        is_hallucination = item["is_hallucination"]
        caught = verdict in ("REJECT", "PARTIAL")

        if is_hallucination and caught:     tp += 1
        elif is_hallucination and not caught: fn += 1
        elif not is_hallucination and caught: fp += 1
        else:                               tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall    = tp / (tp + fn) if (tp + fn) else 0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
```

**Target:** Recall ≥ 0.80 (miss no more than 20% of hallucinations)

---

### Task 5.5 — End-to-End Integration Testing
**Owner:** Member 5

**Deliverable:** pytest test suite + latency benchmark report

**Test file structure:**
```
tests/
  conftest.py          — shared fixtures (db, client, mock scenarios)
  test_ingestion.py    — IMD pipeline, DB writes
  test_rag.py          — ChromaDB retrieval accuracy
  test_agent.py        — planning agent tool-use loop
  test_verification.py — verification agent verdicts
  test_translation.py  — IndicTrans2 output quality
  test_e2e.py          — full pipeline: HTTP request → translated response
  test_latency.py      — P50/P95 latency benchmarks
```

**E2E test example:**
```python
# tests/test_e2e.py
import pytest, time
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_full_pipeline_hindi(async_client: AsyncClient, seeded_farmer_hi):
    start = time.perf_counter()
    resp = await async_client.post("/api/chat", json={
        "farmer_id": str(seeded_farmer_hi.farmer_id),
        "message": "क्या मुझे अभी बुवाई करनी चाहिए?"
    })
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    data = resp.json()
    assert data["lang"] == "hin_Deva"
    assert len(data["text"]) > 20
    assert data["verdict"] in ("PASS", "PARTIAL")
    assert elapsed < 15.0, f"Pipeline took {elapsed:.1f}s — too slow"
```

**Failure mode tests:**
```python
@pytest.mark.asyncio
async def test_missing_forecast(async_client, seeded_farmer_no_forecast):
    resp = await async_client.post("/api/chat", json={
        "farmer_id": str(seeded_farmer_no_forecast.farmer_id),
        "message": "Should I irrigate today?"
    })
    assert resp.status_code == 200
    assert "forecast" in resp.json()["text"].lower() or \
           "data" in resp.json()["text"].lower()  # graceful degradation message

@pytest.mark.asyncio
async def test_unsupported_language_fallback(async_client, seeded_farmer_en):
    # When lang_pref is unsupported → fallback to English
    resp = await async_client.post("/api/chat", json={
        "farmer_id": str(seeded_farmer_en.farmer_id),
        "message": "Best time to sow wheat?"
    })
    assert resp.json()["lang"] == "eng_Latn"
```

**Latency benchmark:**
```python
# tests/test_latency.py
import statistics

async def benchmark_pipeline(async_client, scenario, runs=10):
    latencies = []
    for _ in range(runs):
        t0 = time.perf_counter()
        await async_client.post("/api/chat", json=scenario)
        latencies.append(time.perf_counter() - t0)
    return {
        "p50_s": round(statistics.median(latencies), 2),
        "p95_s": round(sorted(latencies)[int(0.95 * runs)], 2),
        "mean_s": round(statistics.mean(latencies), 2)
    }
```

---

## Milestone Checkpoints

| Milestone | Date (approx.) | Exit Criteria |
|-----------|---------------|---------------|
| M1 — Data Live | End of Week 1 | IMD pipeline fetching ≥ 30 districts; ICAR vector store has ≥ 100 chunks; farmer CRUD API returns 200 |
| M2 — English Agent | End of Week 2 | `POST /api/chat` returns a grounded recommendation in English; verification agent catches ≥ 1 hallucinated test case |
| M3 — Multilingual | Mid Week 3 | Hindi, Tamil, Telugu translations pass back-translation ≥ 0.65; language detection correctly routes 5 test inputs |
| M4 — Evaluation Done | End of Week 4 | All 3 evaluation dimensions reported; E2E tests pass; P95 latency < 15 s |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| IMD website structure changes (scraper breaks) | Medium | High | Cache last 7 days of bulletins; add fallback PDF parser |
| IndicTrans2 GPU OOM on free-tier Colab | High | Medium | Use HuggingFace Inference API as primary; local GPU as fallback |
| Verification agent over-rejects (recall high, precision low) | Medium | Medium | Tune grounding rubric with 5 pilot scenarios before full evaluation |
| Task 2.3 (verification) takes > 1 week | Medium | High | Start with rule-based keyword matching as interim fallback |
| Indic fonts not rendering in target browser | Low | Low | Include Noto fonts as local woff2 files (not CDN-dependent) |

---

## Repository Structure

```
cropcompass/
  api/
    main.py              — FastAPI app + Socket.IO mount
    routes/
      chat.py            — /api/chat endpoint
      profile.py         — /api/profile CRUD
      forecast.py        — /api/forecast/{district}
    agents/
      planner.py         — AgentRunner, LLM loop
      verifier.py        — verify_recommendation()
      tools.py           — fetch_forecast, query_knowledge_base, ...
      dispatcher.py      — dispatch_tool()
    services/
      rag.py             — ChromaDB wrapper
      translation.py     — TranslationService (IndicTrans2)
      lang_detect.py     — detect_language(), detect_with_codeswitching()
    models/
      db.py              — SQLAlchemy Base, engine, session
      farmer.py          — Farmer ORM model
      advisory.py        — IMDAdvisory ORM model
    schemas/
      farmer.py          — FarmerCreate, FarmerResponse
      agent.py           — AgentResponse
  ingestion/
    imd_scraper.py       — IMD GKMS scraper
    icar_loader.py       — PDF download + chunking + embedding
    scheduler.py         — APScheduler jobs
  ui/
    (Vite React app)
  data/
    raw/icar/            — downloaded PDFs
    chromadb/            — persistent vector store
    test_scenarios.json  — evaluation scenarios
  tests/
    (pytest suite)
  docs/
    architecture.md      — Mermaid diagram
    agent_spec.md        — SDD for planning + verification agents
    openapi.yaml         — API contract
  docker-compose.yml
  requirements.txt
  .env.example           — ANTHROPIC_API_KEY, HF_TOKEN, DATABASE_URL
```
