#!/usr/bin/env python3
"""
ingest_imd_to_chromadb.py -- Ingest IMD district Agromet Advisory Bulletins (PDF) into ChromaDB.

These bulletins (downloaded by ingestion/imd_scraper.py into data/raw/imd_agromet/<State>/)
are text-based PDFs, so we extract text directly with pdfplumber -- no OCR step needed.

What we keep vs drop
--------------------
Each bulletin contains ephemeral numeric tables (past-weather + 5-day forecast) and reusable
prose advisories (Forecast Summary, Weather Warnings, "Likely impacts ... Agromet advisories",
General/SMS Advisory). The agent already pulls *live* forecasts via fetch_forecast(), so the
numeric tables are noise for retrieval. We strip the dense numeric rows + flattened
multi-column rows + boilerplate and keep the advisory prose. Use --keep-tables to disable.

Speed (this version)
--------------------
  * --device auto   : uses CUDA if PyTorch sees a GPU (20-40x faster than CPU). Same model,
                      so vectors stay compatible with the SAU corpus already in the DB.
  * --embed-batch   : encode batch size (default 128; raise on a big GPU).
  * --workers       : PDF text extraction runs across processes (pdfplumber is the slow part).
  * resume          : chunks whose id is already in the collection are skipped before embedding,
                      so an interrupted run continues cheaply (disable with --no-resume).

Volume control
--------------
  --sample-days N : keep ~1 bulletin every N days PER DISTRICT (e.g. 14 = fortnightly). Covers
                    the full crop calendar while cutting near-duplicate chunks and runtime.

Compatibility (api/services/rag.py + ingest_to_chromadb.py)
-----------------------------------------------------------
  DB data/chromadb | collection icar_knowledge | model paraphrase-multilingual-MiniLM-L12-v2
  splitter 512/64  | crop metadata so where={"crop": ...} (with no-filter fallback) works.

SETUP
-----
    pip install chromadb sentence-transformers langchain-text-splitters pdfplumber tqdm torch

USAGE
-----
    # Preview chunks/dedup/sampling -- no model, no DB write
    python -m ingestion.ingest_imd_to_chromadb --sample-days 14 --dry-run

    # Recommended: GPU, fortnightly sample, all 6 states
    python -m ingestion.ingest_imd_to_chromadb --sample-days 14

    # Everything, explicit GPU + bigger batch
    python -m ingestion.ingest_imd_to_chromadb --device cuda --embed-batch 256

    # Reload only the IMD docs from scratch
    python -m ingestion.ingest_imd_to_chromadb --sample-days 14 --reset-imd
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pdfplumber
from tqdm import tqdm

# Heavy deps (chromadb, sentence-transformers, torch, langchain) are imported lazily in main()
# so --dry-run runs with only pdfplumber + tqdm installed.

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "raw" / "imd_agromet"
DEFAULT_DB = ROOT / "data" / "chromadb"
DEFAULT_COLLECTION = "icar_knowledge"
EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
MIN_DOC_CHARS = 200
MIN_CHUNK_LEN = 40
UPSERT_BATCH = 1024   # chunks embedded+upserted per flush

_MONTH_TO_SEASON = {
    1: "rabi", 2: "rabi", 3: "rabi", 4: "zaid", 5: "zaid",
    6: "kharif", 7: "kharif", 8: "kharif", 9: "kharif", 10: "kharif",
    11: "rabi", 12: "rabi",
}

_CROP_KEYWORDS = {
    "rice": ["paddy", "rice"], "cotton": ["cotton"],
    "groundnut": ["groundnut", "peanut"], "maize": ["maize", "corn"],
    "redgram": ["redgram", "red gram", "pigeon pea", "pigeonpea", "tur", "arhar"],
    "blackgram": ["blackgram", "black gram", "urdbean", "urd"],
    "greengram": ["greengram", "green gram", "moong", "mung"],
    "sugarcane": ["sugarcane", "sugar cane"], "sorghum": ["sorghum", "jowar"],
    "pearlmillet": ["pearl millet", "bajra"], "fingermillet": ["finger millet", "ragi"],
    "banana": ["banana"], "coconut": ["coconut"], "chilli": ["chilli", "chili", "chillies"],
    "turmeric": ["turmeric"], "tomato": ["tomato"], "onion": ["onion"],
    "sunflower": ["sunflower"], "sesame": ["sesame", "gingelly", "til"],
    "soybean": ["soybean", "soya"], "wheat": ["wheat"], "blackpepper": ["black pepper"],
    "rubber": ["rubber"], "coffee": ["coffee"], "arecanut": ["arecanut", "areca nut", "areca"],
    "mango": ["mango"],
}
_CROP_PATTERNS = {
    crop: [re.compile(r"\b" + re.escape(k) + r"\b", re.I) for k in kws]
    for crop, kws in _CROP_KEYWORDS.items()
}

_BOILERPLATE = re.compile(
    r"(https?://)|(\bE[\s-]?mail\b)|(\bPhone\s*no\b)|(\bFax\b)|"
    r"(^\d{1,2}/\d{1,2}/\d{2,4},?\s*\d)|(^Page\s*\d+\b)", re.I,
)
_NUMTOKEN = re.compile(r"^[-+(]?\d[\d.,:;°%/()-]*$")
_FNAME_RE = re.compile(r"^(?P<state>.+)_(?P<district>.+)_(?P<lang>[A-Za-z]+)_(?P<date>\d{4}-\d{2}-\d{2})$")


# --------------------------------------------------------------------------------------
# Pure helpers (used by worker processes -- must stay top-level / picklable)
# --------------------------------------------------------------------------------------

def parse_filename(pdf_path: Path) -> dict | None:
    m = _FNAME_RE.match(pdf_path.stem)
    if not m:
        return None
    d = m.groupdict()
    year, month, _ = d["date"].split("-")
    return {
        "state": d["state"], "district": d["district"], "date": d["date"],
        "year": int(year), "season": _MONTH_TO_SEASON.get(int(month), "general"),
    }


def clean_lines(raw: str, keep_tables: bool) -> str:
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s == "District Advisory" or _BOILERPLATE.search(s):
            continue
        if not keep_tables:
            tokens = s.split()
            numlike = sum(1 for t in tokens if _NUMTOKEN.match(t))
            if tokens and numlike >= 3 and numlike >= 0.5 * len(tokens):
                continue
            if len(tokens) >= 5:
                top = Counter(t.lower() for t in tokens).most_common(1)[0][1]
                if top >= 3 and top >= 0.30 * len(tokens):
                    continue
        out.append(s)
    text = "\n".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def tag_crop(text: str) -> str:
    counts: Counter = Counter()
    for crop, patterns in _CROP_PATTERNS.items():
        c = sum(len(p.findall(text)) for p in patterns)
        if c:
            counts[crop] = c
    if not counts:
        return "general"
    top = counts.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return "general"
    return top[0][0]


def _extract_worker(task: tuple[str, bool]):
    """Runs in a subprocess: returns (filename, meta, cleaned_text) or None."""
    path_str, keep_tables = task
    p = Path(path_str)
    meta = parse_filename(p)
    if meta is None:
        return None
    try:
        with pdfplumber.open(p) as pdf:
            raw = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return None
    cleaned = clean_lines(raw, keep_tables)
    if len(cleaned) < MIN_DOC_CHARS:
        return None
    return (p.name, meta, cleaned)


# --------------------------------------------------------------------------------------
# File selection + sampling
# --------------------------------------------------------------------------------------

def list_pdfs(input_dir: Path, states: list[str] | None) -> list[Path]:
    targets = states or [p.name for p in sorted(input_dir.iterdir()) if p.is_dir()]
    pdfs = []
    for st in targets:
        pdfs.extend(sorted((input_dir / st).glob("*.pdf")))
    return pdfs


def sample_by_days(pdfs: list[Path], days: int) -> list[Path]:
    """Greedy: per (state, district), keep dates spaced >= `days` apart."""
    if not days:
        return pdfs
    groups: dict[tuple, list[tuple[str, Path]]] = defaultdict(list)
    passthrough = []
    for p in pdfs:
        m = parse_filename(p)
        if not m:
            passthrough.append(p)
            continue
        groups[(m["state"], m["district"])].append((m["date"], p))
    kept = list(passthrough)
    for items in groups.values():
        items.sort(key=lambda x: x[0])
        last = None
        for dstr, p in items:
            d = date.fromisoformat(dstr)
            if last is None or (d - last).days >= days:
                kept.append(p)
                last = d
    return kept


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def pick_device(opt: str) -> str:
    if opt != "auto":
        return opt
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Ingest IMD district agromet bulletins into ChromaDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--states", nargs="+", help="Only these states (folder names)")
    ap.add_argument("--sample-days", type=int, default=0,
                    help="Keep ~1 bulletin every N days per district (e.g. 14). 0 = all.")
    ap.add_argument("--limit", type=int, help="Cap at N PDFs (after sampling) for testing")
    ap.add_argument("--keep-tables", action="store_true", help="Do NOT strip numeric tables")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--embed-batch", type=int, default=128, help="Embedding batch size")
    ap.add_argument("--workers", type=int, default=min(8, (os.cpu_count() or 4)),
                    help="Parallel PDF-extraction processes")
    ap.add_argument("--no-resume", action="store_true", help="Do not skip ids already in DB")
    ap.add_argument("--reset-imd", action="store_true",
                    help="Delete existing doc_type=imd_agromet chunks before loading")
    ap.add_argument("--dry-run", action="store_true",
                    help="Extract/sample/chunk/dedup and report only -- no model, no DB write")
    args = ap.parse_args(argv)

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"Input dir not found: {input_dir}", file=sys.stderr)
        return 1

    pdfs = list_pdfs(input_dir, args.states)
    n_all = len(pdfs)
    pdfs = sample_by_days(pdfs, args.sample_days)
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print("No PDFs matched.", file=sys.stderr)
        return 1
    print(f"PDFs: {n_all} found -> {len(pdfs)} selected "
          f"(sample_days={args.sample_days}, keep_tables={args.keep_tables})", file=sys.stderr)

    # ---- Phase 1: parallel text extraction ----
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    tasks = [(str(p), args.keep_tables) for p in pdfs]
    extracted = []
    workers = max(1, args.workers)
    print(f"Extracting text with {workers} worker(s)...", file=sys.stderr)
    if workers == 1:
        for t in tqdm(tasks, desc="Extract", unit="pdf"):
            r = _extract_worker(t)
            if r:
                extracted.append(r)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r in tqdm(ex.map(_extract_worker, tasks, chunksize=8),
                          total=len(tasks), desc="Extract", unit="pdf"):
                if r:
                    extracted.append(r)
    n_empty = len(pdfs) - len(extracted)

    # ---- Phase 2: split + tag + global dedup ----
    seen: dict[str, int] = {}
    records: list[dict] = []
    crop_tally: Counter = Counter()
    state_tally: Counter = Counter()
    n_raw = 0
    for name, meta, cleaned in extracted:
        for piece in splitter.split_text(cleaned):
            piece = piece.strip()
            if len(piece) < MIN_CHUNK_LEN:
                continue
            n_raw += 1
            h = hashlib.sha1(re.sub(r"\s+", " ", piece).strip().lower().encode("utf-8")).hexdigest()[:16]
            if h in seen:
                seen[h] += 1
                continue
            seen[h] = 1
            crop = tag_crop(piece)
            crop_tally[crop] += 1
            state_tally[meta["state"]] += 1
            cid = f"imd_{h}"
            records.append({
                "id": cid, "text": piece,
                "metadata": {
                    "source": name, "chunk_id": cid, "doc_type": "imd_agromet",
                    "state": meta["state"], "district": meta["district"], "date": meta["date"],
                    "year": meta["year"], "season": meta["season"], "crop": crop,
                    "soil_type": "general", "lang": "eng", "duplicate_count": 1,
                },
            })
    n_unique = len(records)
    dup_cut = n_raw - n_unique
    print(f"Chunks: {n_raw} raw -> {n_unique} unique "
          f"({(100*dup_cut/n_raw):.1f}% dedup); empty PDFs: {n_empty}", file=sys.stderr)

    if args.dry_run:
        print(f"\nTop crops: {dict(crop_tally.most_common(8))}", file=sys.stderr)
        print(f"By state : {dict(state_tally)}", file=sys.stderr)
        print("\n[DRY RUN] sample chunks:", file=sys.stderr)
        for rec in records[:6]:
            m = rec["metadata"]
            print(f"  {m['state']}/{m['district']} {m['date']} crop={m['crop']}: "
                  f"{rec['text'][:160]!r}", file=sys.stderr)
        print("\n[DRY RUN] nothing written.", file=sys.stderr)
        return 0

    # ---- Phase 3: model + collection ----
    import chromadb
    from sentence_transformers import SentenceTransformer
    device = pick_device(args.device)
    print(f"Loading model on device={device} ...", file=sys.stderr)
    model = SentenceTransformer(EMBED_MODEL_NAME, device=device)
    Path(args.db).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=args.db)
    collection = client.get_or_create_collection(name=args.collection,
                                                  metadata={"hnsw:space": "cosine"})
    if args.reset_imd:
        try:
            collection.delete(where={"doc_type": "imd_agromet"})
            print("[reset-imd] removed existing imd_agromet chunks", file=sys.stderr)
        except Exception as e:
            print(f"[reset-imd] skipped: {e}", file=sys.stderr)

    # ---- Phase 4: resume (skip ids already stored) ----
    if not args.no_resume and not args.reset_imd:
        existing = set()
        ids = [r["id"] for r in records]
        for i in range(0, len(ids), 512):
            got = collection.get(ids=ids[i:i + 512])
            existing.update(got["ids"])
        if existing:
            records = [r for r in records if r["id"] not in existing]
            print(f"resume: {len(existing)} already in DB, {len(records)} left to embed",
                  file=sys.stderr)

    # ---- Phase 5: embed + upsert ----
    for i in tqdm(range(0, len(records), UPSERT_BATCH), desc="Embed+upsert", unit="batch"):
        batch = records[i:i + UPSERT_BATCH]
        texts = [r["text"] for r in batch]
        embs = model.encode(texts, batch_size=args.embed_batch,
                            show_progress_bar=False, convert_to_numpy=True).tolist()
        collection.upsert(
            documents=texts, embeddings=embs,
            metadatas=[r["metadata"] for r in batch], ids=[r["id"] for r in batch],
        )

    # ---- Phase 6: record how many bulletins shared each advisory ----
    dupes = {f"imd_{h}": c for h, c in seen.items() if c > 1}
    if dupes:
        ids = list(dupes)
        for i in range(0, len(ids), 256):
            got = collection.get(ids=ids[i:i + 256])
            if got["ids"]:
                metas = []
                for cid, md in zip(got["ids"], got["metadatas"]):
                    md = dict(md); md["duplicate_count"] = dupes[cid]; metas.append(md)
                collection.update(ids=got["ids"], metadatas=metas)

    print(f"\nTop crops: {dict(crop_tally.most_common(8))}", file=sys.stderr)
    print(f"By state : {dict(state_tally)}", file=sys.stderr)
    print(f"Done. Collection '{args.collection}' total: {collection.count()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
