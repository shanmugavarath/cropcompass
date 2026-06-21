#!/usr/bin/env python3
"""
Ingests OCR JSON files (output of ocr_pdfs.py) into ChromaDB.

--- SETUP ---
    pip install chromadb sentence-transformers langchain-text-splitters tqdm

    Embedding model: 'paraphrase-multilingual-MiniLM-L12-v2'
    We use this instead of the plan's 'all-MiniLM-L6-v2' because the TNAU
    corpus is 95% Tamil. The multilingual model maps Tamil text and English
    queries into the same vector space — no translation needed.

--- USAGE ---
    # Pilot: load 10 representative files and run test queries
    python -m ingestion.ingest_to_chromadb --pilot --test-query

    # Run test queries on an already-loaded DB without loading anything
    python -m ingestion.ingest_to_chromadb --query-only

    # Load all 225 files
    python -m ingestion.ingest_to_chromadb

    # Preview what would be loaded without writing
    python -m ingestion.ingest_to_chromadb --pilot --dry-run

    # Wipe the collection and reload from scratch
    python -m ingestion.ingest_to_chromadb --pilot --reset --test-query
"""

import re
import json
import time
import argparse
from collections import Counter
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    separators=["\n\n", "\n", ".", " ", ""],
)

MIN_PAGE_CHARS  = 80   # pages shorter than this are covers/ads/blanks — skip whole page
MIN_CHUNK_LEN   = 30   # discard OCR noise sub-chunks shorter than this

ROOT          = Path(__file__).parent.parent
DEFAULT_INPUT = str(ROOT / "data" / "raw" / "SAU_ocr_output")
DEFAULT_DB    = str(ROOT / "data" / "chromadb")

# 10 files spread across years (2007–2024) and all three seasons
PILOT_FILES = [
    "SAU_TNAU_VV_UVV July 2024.json",
    "SAU_TNAU_VV_UVV December 2023.json",
    "SAU_TNAU_VV_August 2021.json",
    "SAU_TNAU_VV_january 2021.json",
    "SAU_TNAU_VV_7 JULY 2020.json",
    "SAU_TNAU_VV_1 JANUARY 2020.json",
    "SAU_TNAU_VV_August_2014.json",
    "SAU_TNAU_VV_january2014.json",
    "SAU_TNAU_VV_tnau publication_vv_April 2007.json",
    "SAU_TNAU_VV_tnau publication_September 2008 Final.json",
]


# ---------------------------------------------------------------------------
# Metadata repair
# ---------------------------------------------------------------------------
# ocr_pdfs.py uses \b word-boundary anchors which fail when a year is adjacent
# to an underscore (e.g. "2015_april" — Python treats _ as a word character).
# We re-derive year/season here from the JSON filename using a boundary-free regex.

_MONTH_MAP = {
    "january": 1,  "jan": 1,  "february": 2, "feb": 2,
    "march":   3,  "mar": 3,  "april":    4,  "apr": 4,
    "may":     5,  "june":    6, "jun":    6,
    "july":    7,  "jul":     7, "august":  8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_TO_SEASON = {
    1: "rabi",   2: "rabi",   3: "rabi",
    4: "zaid",   5: "zaid",
    6: "kharif", 7: "kharif", 8: "kharif",
    9: "kharif", 10: "kharif",
    11: "rabi",  12: "rabi",
}


def fix_metadata(filename: str, existing: dict) -> dict:
    """
    Re-derives year and season from the JSON filename.
    Returns a copy of `existing` with corrected year (int) and season (str).
    """
    name = filename.lower().replace(".json", "").replace(".pdf", "")

    # Year: any 4-digit 20xx / 19xx — no word boundary
    m = re.search(r"(20\d{2}|19\d{2})", name)
    year = int(m.group()) if m else (existing.get("year") or 0)

    # Month: longest match wins (avoids "jan" matching inside "january")
    month_num, best = None, 0
    for abbr, num in _MONTH_MAP.items():
        if abbr in name and len(abbr) > best:
            best, month_num = len(abbr), num

    season = _MONTH_TO_SEASON.get(month_num, existing.get("season", "general"))

    return {**existing, "year": year, "season": season}


# ---------------------------------------------------------------------------
# Crop tagging (Tamil keyword matching)
# ---------------------------------------------------------------------------
# Strategy (Option A — agreed): most-mentioned crop wins; tie or zero → "general".
# Keywords are distinctive Tamil terms; substring count is sufficient.

_CROP_KEYWORDS: dict[str, list[str]] = {
    "rice":       ["நெல்", "நெல்லு", "அரிசி", "கதிர்"],
    "wheat":      ["கோதுமை"],
    "maize":      ["மக்காச்சோளம்"],
    "cotton":     ["பருத்தி"],
    "groundnut":  ["நிலக்கடலை", "கடலை"],
    "blackgram":  ["உளுந்து"],
    "greengram":  ["பாசிப்பயறு"],
    "sugarcane":  ["கரும்பு"],
    "sorghum":    ["சோளம்", "கம்பு"],
    "banana":     ["வாழை"],
    "coconut":    ["தென்னை"],
    "sesame":     ["எள்"],
    "soybean":    ["சோயா"],
    "redgram":    ["துவரை"],
    "sunflower":  ["சூரியகாந்தி"],
    "chilli":     ["மிளகாய்"],
    "onion":      ["வெங்காயம்"],
    "tomato":     ["தக்காளி"],
    "turmeric":   ["மஞ்சள்"],
    "cardamom":   ["ஏலக்காய்"],
}


def tag_crop(text: str) -> str:
    """Returns the dominant crop in `text`, or 'general' on zero/tied counts."""
    counts: Counter = Counter()
    for crop, keywords in _CROP_KEYWORDS.items():
        for kw in keywords:
            counts[crop] += text.count(kw)

    if not any(counts.values()):
        return "general"

    top = counts.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return "general"   # tie → general

    return top[0][0]


# ---------------------------------------------------------------------------
# Performance test queries
# ---------------------------------------------------------------------------

_TEST_QUERIES = [
    ("rice",      "clay",      "when to irrigate during vegetative stage"),
    ("cotton",    "loam",      "pest control bollworm spray schedule"),
    ("groundnut", "sandy",     "fertilizer dose at sowing nitrogen phosphorus"),
    ("rice",      "clay",      "nitrogen application kharif top dressing"),
    ("cotton",    "clay_loam", "disease management fungicide spray"),
]


def run_test_queries(collection, model: SentenceTransformer) -> None:
    print("\n" + "=" * 65)
    print("PERFORMANCE TEST — English queries against Tamil corpus")
    print("=" * 65)

    for crop, soil, query in _TEST_QUERIES:
        t0 = time.perf_counter()
        embedding = model.encode(query).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=3,
            where={"crop": crop},
        )
        filter_note = f"crop={crop} filter"

        if not results["documents"][0]:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=3,
            )
            filter_note = "no crop filter (fallback)"

        elapsed_ms = (time.perf_counter() - t0) * 1000

        print(f"\nQ: {query!r}")
        print(f"   {filter_note} | {elapsed_ms:.1f} ms")

        if not results["documents"][0]:
            print("   [no results — collection may be empty]")
            continue

        for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
            preview = doc[:160].replace("\n", " ")
            print(f"   [{i+1}] crop={meta['crop']:<12} season={meta['season']:<8} {meta['source'][:45]}")
            print(f"        {preview!r}")


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------

def ingest(
    input_dir: str,
    db_path: str,
    collection_name: str,
    dry_run: bool,
    reset: bool,
    pilot: bool,
    test_query: bool,
    query_only: bool,
) -> None:
    input_path = Path(input_dir)

    if pilot:
        json_files = []
        for name in PILOT_FILES:
            p = input_path / name
            if p.exists():
                json_files.append(p)
            else:
                print(f"  WARN: pilot file not found: {name}")
        if not json_files:
            print("No pilot files found. Check --input path.")
            return
    else:
        json_files = sorted(input_path.glob("*.json"))

    print(f"Loading embedding model: {EMBED_MODEL_NAME} ...")
    model = SentenceTransformer(EMBED_MODEL_NAME)
    print("Model loaded.\n")

    Path(db_path).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=db_path)

    if reset and not dry_run:
        try:
            client.delete_collection(collection_name)
            print(f"[reset] Deleted collection '{collection_name}'")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    if query_only:
        run_test_queries(collection, model)
        return

    if not json_files:
        print(f"No JSON files found in {input_dir}")
        return

    if dry_run:
        print("[DRY RUN] — nothing will be written to ChromaDB.\n")

    mode = "pilot (10 files)" if pilot else f"all ({len(json_files)} files)"
    print(f"Processing: {mode}\n")

    total_chunks       = 0
    total_skip_pages   = 0
    total_skip_chunks  = 0
    crop_tally: Counter = Counter()

    for json_file in tqdm(json_files, desc="Ingesting", unit="doc"):
        doc = json.loads(json_file.read_text(encoding="utf-8"))
        source   = doc["source"]
        meta_fix = fix_metadata(json_file.name, doc)

        doc_chunks: list[dict] = []

        for page in doc.get("pages", []):
            page_text = page["text"].strip()

            # Skip entire page if it's a cover / ad / blank
            if len(page_text) < MIN_PAGE_CHARS:
                total_skip_pages += 1
                continue

            page_num   = page["page"]
            sub_chunks = SPLITTER.split_text(page_text)

            for chunk_idx, chunk_text in enumerate(sub_chunks):
                chunk_text = chunk_text.strip()
                if len(chunk_text) < MIN_CHUNK_LEN:
                    total_skip_chunks += 1
                    continue

                crop     = tag_crop(chunk_text)
                chunk_id = f"sau_{Path(source).stem}_p{page_num:03d}_c{chunk_idx:03d}"
                crop_tally[crop] += 1

                doc_chunks.append({
                    "id":   chunk_id,
                    "text": chunk_text,
                    "metadata": {
                        "source":    source,
                        "page":      page_num,
                        "crop":      crop,
                        "soil_type": "general",
                        "season":    meta_fix["season"],
                        "year":      meta_fix["year"],
                        "chunk_id":  chunk_id,
                        "lang":      "tam",
                    },
                })

        if dry_run:
            tqdm.write(f"  [dry-run] {source}: {len(doc_chunks)} chunks")
            total_chunks += len(doc_chunks)
            continue

        if doc_chunks:
            texts      = [c["text"]     for c in doc_chunks]
            ids        = [c["id"]       for c in doc_chunks]
            metadatas  = [c["metadata"] for c in doc_chunks]
            embeddings = model.encode(texts, show_progress_bar=False).tolist()

            collection.upsert(
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids,
            )
            total_chunks += len(doc_chunks)
            tqdm.write(f"  OK  {source}: {len(doc_chunks)} chunks")

    # Summary
    print(f"\n{'=' * 55}")
    if dry_run:
        print(f"[DRY RUN] {total_chunks} chunks would be stored.")
        print(f"          {total_skip_pages} pages would be skipped (covers/blanks).")
    else:
        print(f"Done. {total_chunks} chunks stored | collection total: {collection.count()}")
        print(f"      {total_skip_pages} pages skipped (covers/blanks)")
        print(f"      {total_skip_chunks} sub-chunks skipped (OCR noise < {MIN_CHUNK_LEN} chars)")
        if crop_tally:
            print(f"\nCrop distribution across stored chunks:")
            max_count = max(crop_tally.values())
            for crop, count in crop_tally.most_common():
                bar = "#" * (count * 30 // max_count)
                print(f"  {crop:<14} {count:5d}  {bar}")

    if test_query and not dry_run:
        run_test_queries(collection, model)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Ingest SAU/ICAR OCR JSON files into ChromaDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input",      default=DEFAULT_INPUT,    help="Directory with OCR JSON files")
    parser.add_argument("--db",         default=DEFAULT_DB,       help="ChromaDB persistence path")
    parser.add_argument("--collection", default="icar_knowledge", help="ChromaDB collection name")
    parser.add_argument("--pilot",      action="store_true",      help="Load only 10 pilot files")
    parser.add_argument("--dry-run",    action="store_true",      help="Preview without writing to ChromaDB")
    parser.add_argument("--reset",      action="store_true",      help="Delete and recreate collection first")
    parser.add_argument("--test-query", action="store_true",      help="Run English test queries after loading")
    parser.add_argument("--query-only", action="store_true",      help="Skip loading; only run test queries")
    args = parser.parse_args()

    ingest(
        input_dir=args.input,
        db_path=args.db,
        collection_name=args.collection,
        dry_run=args.dry_run,
        reset=args.reset,
        pilot=args.pilot,
        test_query=args.test_query,
        query_only=args.query_only,
    )
