#!/usr/bin/env python3
"""
Rigorous semantic quality verification for the ChromaDB corpus.

Runs 35 agronomic queries across 10 crop types and reports:
  - Per-query: similarity score, auto-relevance signal (Tamil keyword hit)
  - Per-crop: mean sim, hit-rate (sim >= threshold), fallback rate
  - Global: coverage score, latency stats, quality verdict

Auto-relevance uses Tamil keyword presence in the retrieved chunk to give a
machine-readable signal alongside the raw similarity score. This is a proxy —
human review of the printed Tamil text is the gold standard.

Usage:
    python -m ingestion.check_quality
    python -m ingestion.check_quality --top 5          # show top-5 per query
    python -m ingestion.check_quality --full           # full chunk text (no truncation)
    python -m ingestion.check_quality --threshold 0.25 # change relevance cutoff
    python -m ingestion.check_quality --verbose        # print chunk text for every result
"""

import sys
import time
import argparse
import statistics
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from sentence_transformers import SentenceTransformer
import chromadb

ROOT         = Path(__file__).parent.parent
DB_PATH      = str(ROOT / "data" / "chromadb")
COLLECTION   = "icar_knowledge"
MODEL_NAME   = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# ---------------------------------------------------------------------------
# Test query suite — 35 queries across 10 crops, 3-5 per crop
# ---------------------------------------------------------------------------
# Format: (crop_filter, query_text, [tamil_relevance_hints])
# Hints: if ANY hint word appears in the retrieved chunk, it counts as relevant.
# "general" hints are always counted (they're domain words that can appear anywhere).
# ---------------------------------------------------------------------------

QUERIES = [
    # --- RICE (நெல்) ---
    ("rice",      "when to irrigate paddy during vegetative stage",
                  ["நெல்", "நீர்", "பாசனம்", "தண்ணீர்", "நடவு", "வளர்ச்சி"]),
    ("rice",      "nitrogen top dressing timing kharif paddy",
                  ["நெல்", "யூரியா", "உரம்", "தழை", "மேலுரம்"]),
    ("rice",      "pest management brown plant hopper in paddy",
                  ["நெல்", "பூச்சி", "தாள்", "இலை", "மருந்து", "தெளிக்க"]),
    ("rice",      "seed treatment fungicide before sowing",
                  ["நெல்", "விதை", "நோய்", "பூசண", "கார்போ"]),
    ("rice",      "weed control transplanted paddy",
                  ["நெல்", "களை", "நடவு", "நாற்று", "நீர்"]),

    # --- COTTON (பருத்தி) ---
    ("cotton",    "bollworm pest control spray schedule",
                  ["பருத்தி", "புழு", "பூச்சி", "மருந்து", "தெளிக்க"]),
    ("cotton",    "disease management fungicide anthracnose",
                  ["பருத்தி", "நோய்", "பூசண", "மருந்து"]),
    ("cotton",    "fertilizer potassium dose square formation",
                  ["பருத்தி", "உரம்", "சாம்பல்", "பொட்டாஷ்"]),
    ("cotton",    "defoliation picking harvest timing",
                  ["பருத்தி", "பறிக்க", "அறுவடை", "காய்"]),

    # --- GROUNDNUT (நிலக்கடலை) ---
    ("groundnut", "fertilizer dose nitrogen phosphorus at sowing",
                  ["நிலக்கடலை", "கடலை", "உரம்", "தழை", "மண்"]),
    ("groundnut", "aflatoxin pod rot disease control",
                  ["நிலக்கடலை", "கடலை", "நோய்", "காய்", "பூசண"]),
    ("groundnut", "irrigation frequency during pegging stage",
                  ["நிலக்கடலை", "கடலை", "நீர்", "பாசனம்", "ஈரம்"]),
    ("groundnut", "foliar spray micronutrient boron zinc",
                  ["நிலக்கடலை", "கடலை", "உரம்", "தெளிக்க", "போரான்"]),

    # --- BLACKGRAM (உளுந்து) ---
    ("blackgram", "sowing time seed rate spacing for blackgram",
                  ["உளுந்து", "விதை", "விதைக்க", "இடைவெளி"]),
    ("blackgram", "rhizobium inoculant biofertilizer application",
                  ["உளுந்து", "விதை", "பாக்டீரியா", "உயிர்"]),
    ("blackgram", "yellow mosaic virus disease management",
                  ["உளுந்து", "நோய்", "வைரஸ்", "மஞ்சள்"]),

    # --- SUGARCANE (கரும்பு) ---
    ("sugarcane", "ratoon crop management fertilizer application",
                  ["கரும்பு", "உரம்", "தழை", "பட்டை"]),
    ("sugarcane", "irrigation scheduling sugarcane grand growth period",
                  ["கரும்பு", "நீர்", "பாசனம்", "வளர்ச்சி"]),
    ("sugarcane", "trash mulching weed control between rows",
                  ["கரும்பு", "களை", "மண்", "மேலட்டை"]),
    ("sugarcane", "pest early shoot borer management",
                  ["கரும்பு", "புழு", "பூச்சி", "தண்டு"]),

    # --- BANANA (வாழை) ---
    ("banana",    "bunch emergence management potassium spray",
                  ["வாழை", "குலை", "பொட்டாஷ்", "உரம்"]),
    ("banana",    "panama wilt fusarium disease control",
                  ["வாழை", "நோய்", "வாடல்", "பூசண"]),
    ("banana",    "tissue culture plant management irrigation",
                  ["வாழை", "நடவு", "நீர்", "திசு"]),

    # --- COCONUT (தென்னை) ---
    ("coconut",   "coconut nut drop management boron deficiency",
                  ["தென்னை", "காய்", "போரான்", "உரம்"]),
    ("coconut",   "rhinoceros beetle pest control coconut",
                  ["தென்னை", "வண்டு", "பூச்சி", "மருந்து"]),
    ("coconut",   "intercropping banana cocoa under coconut",
                  ["தென்னை", "வாழை", "இடைப்பயிர்"]),

    # --- SORGHUM / MAIZE (சோளம்) ---
    ("sorghum",   "sorghum shoot fly pest management",
                  ["சோளம்", "கம்பு", "பூச்சி", "புழு"]),
    ("sorghum",   "stem borer damage control kharif sorghum",
                  ["சோளம்", "தண்டு", "புழு", "மருந்து"]),

    # --- CHILLI (மிளகாய்) ---
    ("chilli",    "thrips mite pest control in chilli",
                  ["மிளகாய்", "பூச்சி", "பூஞ்சை", "மருந்து"]),
    ("chilli",    "anthracnose fruit rot disease spray",
                  ["மிளகாய்", "நோய்", "காய்", "பூசண", "மருந்து"]),

    # --- TOMATO (தக்காளி) ---
    ("tomato",    "early blight late blight disease tomato",
                  ["தக்காளி", "நோய்", "பூசண", "மருந்து"]),
    ("tomato",    "irrigation drip fertigation tomato production",
                  ["தக்காளி", "நீர்", "சொட்டு", "உரம்"]),

    # --- GENERAL fallback test (crop unlikely to be in DB) ---
    ("wheat",     "wheat rust disease fungicide spray",
                  ["கோதுமை", "நோய்", "மருந்து"]),
    ("greengram", "greengram yellow mosaic virus resistance variety",
                  ["பாசிப்பயறு", "நோய்", "வைரஸ்", "ரகம்"]),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bar(value: float, width: int = 30) -> str:
    filled = int(value * width)
    return "#" * filled + "-" * (width - filled)


def auto_relevance(doc: str, hints: list[str]) -> bool:
    """Return True if any Tamil hint word appears in the retrieved chunk."""
    return any(h in doc for h in hints)


def sep(char="=", width=72):
    print(char * width)


# ---------------------------------------------------------------------------
# Main verification run
# ---------------------------------------------------------------------------

def run(top_k: int, preview_len: int, threshold: float, verbose: bool):
    print(f"Loading model: {MODEL_NAME} ...")
    t_load = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME)
    print(f"Model loaded in {(time.perf_counter() - t_load)*1000:.0f} ms\n")

    client     = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_collection(COLLECTION)
    total_chunks = collection.count()

    sep()
    print(f"  ChromaDB collection : {COLLECTION}")
    print(f"  Persistent path     : {DB_PATH}")
    print(f"  Total chunks        : {total_chunks:,}")
    print(f"  Queries to run      : {len(QUERIES)}")
    print(f"  top_k per query     : {top_k}")
    print(f"  Similarity threshold: {threshold}")
    sep()

    # -----------------------------------------------------------------------
    # Collection metadata stats (crop + season distribution from metadata)
    # -----------------------------------------------------------------------
    print("\nFetching collection crop/season distribution (sample of 5000 chunks)...")
    sample = collection.get(limit=5000, include=["metadatas"])
    crop_counts: dict[str, int] = defaultdict(int)
    season_counts: dict[str, int] = defaultdict(int)
    for m in sample["metadatas"]:
        crop_counts[m.get("crop", "?")] += 1
        season_counts[m.get("season", "?")] += 1

    sep("-")
    print("CROP DISTRIBUTION (sample)")
    sep("-")
    max_c = max(crop_counts.values(), default=1)
    for crop, cnt in sorted(crop_counts.items(), key=lambda x: -x[1]):
        pct = cnt / sum(crop_counts.values()) * 100
        print(f"  {crop:<14} {cnt:5d}  {pct:5.1f}%  {bar(cnt/max_c, 25)}")
    sep("-")
    print("SEASON DISTRIBUTION (sample)")
    sep("-")
    for season, cnt in sorted(season_counts.items(), key=lambda x: -x[1]):
        pct = cnt / sum(season_counts.values()) * 100
        print(f"  {season:<10} {cnt:5d}  {pct:5.1f}%")
    sep()

    # -----------------------------------------------------------------------
    # Run queries
    # -----------------------------------------------------------------------
    per_crop_sims: dict[str, list[float]] = defaultdict(list)
    per_crop_hits: dict[str, list[bool]]  = defaultdict(list)
    fallback_crops: list[str] = []
    all_latencies: list[float] = []

    print()
    for crop, query, hints in QUERIES:
        sep("=")
        print(f"  Crop   : {crop}")
        print(f"  Query  : {query!r}")
        sep("-")

        t0 = time.perf_counter()
        embedding = model.encode(query).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where={"crop": crop},
            include=["documents", "metadatas", "distances"],
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        all_latencies.append(latency_ms)

        used_fallback = False
        if not results["documents"][0]:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            used_fallback = True
            fallback_crops.append(crop)

        filter_note = "FALLBACK (no crop filter)" if used_fallback else f"crop={crop!r} filter"
        print(f"  Filter : {filter_note}  |  latency={latency_ms:.1f} ms")
        print()

        docs      = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        if not docs:
            print("  [no results]\n")
            continue

        query_sims: list[float] = []
        for rank, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            sim     = max(0.0, 1.0 - dist)
            is_rel  = auto_relevance(doc, hints)
            rel_tag = "[RELEVANT]" if is_rel else "[off-topic]"
            above   = ">" if sim >= threshold else "<"
            print(f"  Rank {rank}  sim={sim:.3f} {above}{threshold}  {rel_tag}")
            print(f"    crop={meta['crop']:<12}  season={meta['season']:<8}  "
                  f"year={meta.get('year','?')}  src={meta['source'][:40]}")

            if verbose or rank == 1:
                text = doc if preview_len == 0 else doc[:preview_len]
                if preview_len and len(doc) > preview_len:
                    text += "..."
                for line in text.split("\n"):
                    print(f"    | {line}")

            print()
            query_sims.append(sim)
            per_crop_sims[crop].append(sim)
            per_crop_hits[crop].append(is_rel)

    # -----------------------------------------------------------------------
    # Per-crop summary
    # -----------------------------------------------------------------------
    sep("=")
    print("PER-CROP SUMMARY")
    sep("=")
    header = f"  {'Crop':<14}  {'Queries':>7}  {'MeanSim':>8}  {'MinSim':>7}  {'MaxSim':>7}  {'HitRate':>8}  {'Above':>7}"
    print(header)
    sep("-")

    global_sims: list[float] = []
    global_hits: list[bool]  = []

    for crop in sorted(per_crop_sims.keys()):
        sims = per_crop_sims[crop]
        hits = per_crop_hits[crop]
        n = len(sims)
        mean_s = statistics.mean(sims) if sims else 0.0
        min_s  = min(sims) if sims else 0.0
        max_s  = max(sims) if sims else 0.0
        hit_r  = sum(hits) / len(hits) if hits else 0.0
        above  = sum(1 for s in sims if s >= threshold) / n if n else 0.0
        grade  = "PASS" if mean_s >= threshold else ("PARTIAL" if mean_s >= threshold * 0.6 else "FAIL")

        print(f"  {crop:<14}  {n:>7}  {mean_s:>8.3f}  {min_s:>7.3f}  {max_s:>7.3f}  "
              f"{hit_r:>8.1%}  {above:>7.1%}  [{grade}]")

        global_sims.extend(sims)
        global_hits.extend(hits)

    sep("-")
    # Global row
    n = len(global_sims)
    if n:
        g_mean = statistics.mean(global_sims)
        g_min  = min(global_sims)
        g_max  = max(global_sims)
        g_hit  = sum(global_hits) / len(global_hits)
        g_abv  = sum(1 for s in global_sims if s >= threshold) / n
        print(f"  {'GLOBAL':<14}  {n:>7}  {g_mean:>8.3f}  {g_min:>7.3f}  {g_max:>7.3f}  "
              f"{g_hit:>8.1%}  {g_abv:>7.1%}")

    sep()

    # -----------------------------------------------------------------------
    # Fallback and latency stats
    # -----------------------------------------------------------------------
    print("FALLBACK ANALYSIS")
    sep("-")
    if fallback_crops:
        print(f"  Queries that hit fallback (crop filter returned 0): {len(fallback_crops)}")
        for fc in fallback_crops:
            print(f"    - crop={fc!r}")
    else:
        print("  All queries satisfied by crop filter — no fallbacks.")

    sep()
    print("LATENCY STATS")
    sep("-")
    if all_latencies:
        sorted_lat = sorted(all_latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
        print(f"  Queries: {len(all_latencies)}  "
              f"Mean: {statistics.mean(all_latencies):.1f} ms  "
              f"P50: {p50:.1f} ms  P95: {p95:.1f} ms  P99: {p99:.1f} ms")
        print(f"  (excludes model warm-up; first query is typically 3-5x slower)")
    sep()

    # -----------------------------------------------------------------------
    # Overall verdict
    # -----------------------------------------------------------------------
    print("OVERALL VERDICT")
    sep("-")
    if not global_sims:
        print("  No results — collection may be empty.")
        return

    criteria = {
        "Total chunks >= 15,000":        total_chunks >= 15_000,
        "Global mean sim >= threshold":  g_mean >= threshold,
        "Global above-threshold >= 50%": g_abv >= 0.50,
        "Auto-relevance hit rate >= 40%": g_hit >= 0.40,
        "Fallback rate < 30%":           len(fallback_crops) / len(QUERIES) < 0.30,
        "P95 latency < 500 ms":          p95 < 500,
    }
    pass_count = sum(criteria.values())
    for name, passed in criteria.items():
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}]  {name}")
    sep("-")
    overall = "READY FOR INTEGRATION" if pass_count >= 5 else \
              "NEEDS ATTENTION" if pass_count >= 3 else "NOT READY"
    print(f"\n  {pass_count}/{len(criteria)} criteria met  →  {overall}\n")
    sep("=")

    print("\nTAMIL VOCABULARY REFERENCE (for manual chunk review)")
    sep("-")
    vocab = [
        ("நெல்",         "rice/paddy"),
        ("நீர் / பாசனம்","water / irrigation"),
        ("பூச்சி",        "pest / insect"),
        ("உரம்",          "fertilizer"),
        ("நோய்",          "disease"),
        ("விதை",          "seed"),
        ("தெளிக்க",       "to spray"),
        ("தழை சத்து",    "nitrogen"),
        ("பொட்டாஷ்",      "potassium"),
        ("மண்",           "soil"),
        ("பூசண நோய்",    "fungal disease"),
        ("அறுவடை",        "harvest"),
        ("களை",           "weed"),
        ("நடவு",          "transplanting / planting"),
        ("கரும்பு",       "sugarcane"),
        ("வாழை",          "banana"),
        ("தென்னை",        "coconut"),
        ("பருத்தி",       "cotton"),
        ("சோளம்",         "sorghum / maize"),
    ]
    for tamil, english in vocab:
        print(f"  {tamil:<20} = {english}")
    sep("=")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rigorous semantic quality check for ChromaDB corpus")
    parser.add_argument("--top",       type=int,   default=3,    help="Results per query (default 3)")
    parser.add_argument("--full",      action="store_true",       help="Show full chunk text")
    parser.add_argument("--threshold", type=float, default=0.25,  help="Similarity threshold (default 0.25)")
    parser.add_argument("--verbose",   action="store_true",       help="Print chunk text for every result")
    args = parser.parse_args()

    run(
        top_k=args.top,
        preview_len=0 if args.full else 350,
        threshold=args.threshold,
        verbose=args.verbose,
    )
