#!/usr/bin/env python3
"""
ingestion/normalize_to_english.py — build an all-English ChromaDB collection.

Why
---
Retrieval is same-language-dominant: an English query never surfaces the Tamil SAU
corpus, and a Tamil query never surfaces the English IMD corpus (see TASK.md). To put
both corpora in one space, we translate the Tamil SAU chunks to English and re-embed
them, alongside the already-English IMD chunks. A single English query then retrieves
BOTH.

Safe & reversible
-----------------
Writes a NEW collection `icar_knowledge_en`; the existing `icar_knowledge` is read-only
and untouched. Validate the new collection, then flip rag.py's _COLLECTION_NAME to it
(rollback = flip it back).

What it does
------------
  1. Copy IMD chunks (doc_type=imd_agromet) as-is — reuses their existing embeddings
     (same model, same English text), so no re-embedding.
  2. For SAU chunks (lang=tam): translate document Tamil->English (IndicTrans2), re-embed
     the English text, keep all metadata, stash the original under `tamil_text`, set
     lang=eng / translated_from=tam.

Resumable: chunks whose id already exists in the destination are skipped.

SETUP
-----
    pip install -r requirements.txt          # incl. torch, transformers, IndicTransToolkit
    # GPU strongly recommended (translating ~66k chunks).

USAGE
-----
    python -m ingestion.normalize_to_english --dry-run        # counts only, no model
    python -m ingestion.normalize_to_english --imd-only       # copy IMD first (fast)
    python -m ingestion.normalize_to_english                  # full build on GPU
    python -m ingestion.normalize_to_english --limit-sau 200  # small trial
"""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

import chromadb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "chromadb"
SRC_COLLECTION = "icar_knowledge"
DST_COLLECTION = "icar_knowledge_en"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDIC_EN_MODEL = "ai4bharat/indictrans2-indic-en-1B"
PAGE = 1000           # rows per ChromaDB get() page (avoids SQLite variable limits)
SAVE_EVERY = 10       # translate+upsert this many chunks at a time (crash-safe checkpoint)
TAMIL_META_CAP = 1500  # chars of original Tamil kept in metadata


def pages(col, where, include, page_size=PAGE):
    offset = 0
    while True:
        got = col.get(where=where, include=include, limit=page_size, offset=offset)
        ids = got.get("ids") or []
        if not ids:
            return
        yield got
        offset += len(ids)
        if len(ids) < page_size:
            return


def existing_ids(col) -> set:
    seen = set()
    for got in pages(col, None, [], PAGE):
        seen.update(got["ids"])
    return seen


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--src", default=SRC_COLLECTION)
    ap.add_argument("--dst", default=DST_COLLECTION)
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--embed-batch", type=int, default=128)
    ap.add_argument("--translate-batch", type=int, default=32)
    ap.add_argument("--num-beams", type=int, default=5, help="Beam width (1=greedy, faster; 5=default)")
    ap.add_argument("--limit-sau", type=int, help="Translate at most N SAU chunks (trial)")
    ap.add_argument("--imd-only", action="store_true", help="Only copy IMD chunks, then stop")
    ap.add_argument("--sau-only", action="store_true", help="Only translate SAU chunks")
    ap.add_argument("--dry-run", action="store_true", help="Count only; no model, no writes")
    args = ap.parse_args(argv)

    client = chromadb.PersistentClient(path=args.db)
    src = client.get_collection(args.src)

    # quick census (metadata-only, no model)
    n_imd = len(src.get(where={"doc_type": "imd_agromet"}, include=[], limit=200000)["ids"])
    n_sau = len(src.get(where={"lang": "tam"}, include=[], limit=200000)["ids"])
    print(f"source '{args.src}': IMD(eng)={n_imd}  SAU(tam)={n_sau}", file=sys.stderr)

    if args.dry_run:
        print(f"[dry-run] would build '{args.dst}': copy {n_imd} IMD + translate {n_sau} SAU "
              f"({'limited to %d' % args.limit_sau if args.limit_sau else 'all'}).",
              file=sys.stderr)
        return 0

    dst = client.get_or_create_collection(name=args.dst, metadata={"hnsw:space": "cosine"})
    done = existing_ids(dst)
    print(f"destination '{args.dst}': {len(done)} chunks already present (resume)", file=sys.stderr)

    # ---- 1) copy IMD as-is (reuse embeddings) ----
    if not args.sau_only:
        copied = 0
        for got in tqdm(pages(src, {"doc_type": "imd_agromet"},
                              ["documents", "embeddings", "metadatas"]),
                        desc="Copy IMD", unit="page"):
            keep = [i for i, cid in enumerate(got["ids"]) if cid not in done]
            if not keep:
                continue
            dst.upsert(
                ids=[got["ids"][i] for i in keep],
                documents=[got["documents"][i] for i in keep],
                embeddings=[got["embeddings"][i] for i in keep],
                metadatas=[got["metadatas"][i] for i in keep],
            )
            copied += len(keep)
        print(f"copied IMD chunks: {copied}", file=sys.stderr)
        if args.imd_only:
            print(f"done (imd-only). '{args.dst}' total: {dst.count()}", file=sys.stderr)
            return 0

    # ---- 2) translate + re-embed SAU ----
    device = args.device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    print(f"loading models on device={device} ...", file=sys.stderr)

    from sentence_transformers import SentenceTransformer
    from api.services.translation import TranslationService

    embedder = SentenceTransformer(EMBED_MODEL, device=device)
    translator = TranslationService(INDIC_EN_MODEL, device=device, num_beams=args.num_beams)

    translated = 0
    budget = args.limit_sau
    for got in tqdm(pages(src, {"lang": "tam"}, ["documents", "metadatas"]),
                    desc="Translate SAU", unit="page"):
        ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
        keep = [i for i, cid in enumerate(ids) if cid not in done]
        if budget is not None:
            keep = keep[: max(0, budget - translated)]
        if not keep:
            if budget is not None and translated >= budget:
                break
            continue

        # process in small groups so each group is upserted independently (crash-safe)
        for g_start in range(0, len(keep), SAVE_EVERY):
            g = keep[g_start : g_start + SAVE_EVERY]
            g_ids = [ids[i] for i in g]
            g_ta = [docs[i] for i in g]
            print(f"  [{translated+1}..{translated+len(g)}] translating {len(g)} chunks ...",
                  file=sys.stderr, flush=True)
            g_en = translator.translate_batch(g_ta, "tam_Taml", "eng_Latn",
                                              batch_size=args.translate_batch)
            print(f"  embedding {len(g_en)} chunks ...", file=sys.stderr, flush=True)
            g_emb = embedder.encode(g_en, batch_size=args.embed_batch,
                                    show_progress_bar=False, convert_to_numpy=True).tolist()
            g_meta = []
            for i, en, ta in zip(g, g_en, g_ta):
                m = dict(metas[i])
                m["tamil_text"] = ta[:TAMIL_META_CAP]
                m["lang"] = "eng"
                m["translated_from"] = "tam"
                g_meta.append(m)
            dst.upsert(ids=g_ids, documents=g_en, embeddings=g_emb, metadatas=g_meta)
            translated += len(g_ids)
            done.update(g_ids)
            del g_en, g_emb, g_meta
            gc.collect()
            print(f"  saved checkpoint → {translated} chunks done", file=sys.stderr, flush=True)
            if budget is not None and translated >= budget:
                break
        if budget is not None and translated >= budget:
            break

    print(f"translated SAU chunks: {translated}", file=sys.stderr)
    print(f"done. '{args.dst}' total: {dst.count()}", file=sys.stderr)
    print("Next: validate, then set _COLLECTION_NAME = 'icar_knowledge_en' in api/services/rag.py",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
