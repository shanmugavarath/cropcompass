"""Load documents into knowledge_chunks for the vector MCP server.

Usage examples:

  # Load all .txt and .pdf files from a folder
  python -m mcp_servers.vector_server.loader --dir /path/to/icar/pdfs

  # Load a single file
  python -m mcp_servers.vector_server.loader --file report.pdf --collection icar

  # Load a plain text string directly (good for scripting)
  python -m mcp_servers.vector_server.loader --text "Soybean needs 600-800mm rain" \
      --chunk-id icar:soybean:manual:01 --collection icar

  # Wipe a collection and reload it
  python -m mcp_servers.vector_server.loader --dir ./pdfs --collection icar --replace

Env vars used:
  DATABASE_URL         Postgres connection string
  EMBEDDING_MODEL      sentence-transformers model name (default: all-MiniLM-L6-v2)
  EMBEDDING_BACKEND    sentence_transformers (default) | huggingface
  HF_API_KEY           only needed when EMBEDDING_BACKEND=huggingface
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass",
).replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

CHUNK_SIZE = 400        # target tokens per chunk
CHUNK_OVERLAP = 40      # overlap between consecutive chunks (words)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(path)
    if suffix in {".txt", ".md", ".rst"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {suffix}. Supported: .pdf .txt .md .rst")


def _pdf_text(path: Path) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except ImportError:
        raise ImportError("pypdf not installed. Run: uv pip install pypdf")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Word-based sliding window. Works on any language."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap
    return [c.strip() for c in chunks if len(c.strip()) > 30]


def _chunk_id(collection: str, source_name: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source_name.lower()).strip("-")
    return f"{collection}:{slug}:{index:04d}"


# ---------------------------------------------------------------------------
# Inserting into Postgres
# ---------------------------------------------------------------------------

async def insert_chunks(
    pool: asyncpg.Pool,
    embedder: Any,
    chunks: list[dict[str, Any]],
    replace: bool = False,
) -> int:
    if not chunks:
        return 0

    if replace:
        collections = {c["collection"] for c in chunks}
        sources = {c["source"] for c in chunks}
        async with pool.acquire() as conn:
            for col in collections:
                for src in sources:
                    deleted = await conn.execute(
                        "DELETE FROM knowledge_chunks WHERE collection=$1 AND source=$2",
                        col, src,
                    )
                    log.info("loader.replaced", collection=col, source=src, deleted=deleted)

    texts = [c["content"] for c in chunks]
    log.info("loader.embedding", count=len(texts))
    embeddings = await embedder.embed(texts)

    async with pool.acquire() as conn:
        inserted = await conn.executemany(
            """
            INSERT INTO knowledge_chunks (chunk_id, collection, content, source, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
            ON CONFLICT (chunk_id) DO UPDATE
              SET content   = EXCLUDED.content,
                  embedding = EXCLUDED.embedding,
                  metadata  = EXCLUDED.metadata
            """,
            [
                (
                    c["chunk_id"],
                    c["collection"],
                    c["content"],
                    c["source"],
                    json.dumps(c["metadata"]),
                    str(e),
                )
                for c, e in zip(chunks, embeddings)
            ],
        )
    log.info("loader.done", inserted=len(chunks))
    return len(chunks)


# ---------------------------------------------------------------------------
# Public helpers (importable from other scripts)
# ---------------------------------------------------------------------------

async def load_text(
    text: str,
    *,
    collection: str = "icar",
    source: str = "manual",
    metadata: dict[str, Any] | None = None,
    chunk_id: str | None = None,
    replace: bool = False,
    pool: asyncpg.Pool | None = None,
    embedder: Any = None,
) -> int:
    """Embed and insert a single piece of text. Good for scripting."""
    from .embedder import build_embedder

    _pool = pool or await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    _embedder = embedder or build_embedder()
    chunks_text = split_into_chunks(text)
    records = [
        {
            "chunk_id": chunk_id or _chunk_id(collection, source, i),
            "collection": collection,
            "content": ch,
            "source": source,
            "metadata": metadata or {},
        }
        for i, ch in enumerate(chunks_text)
    ]
    try:
        return await insert_chunks(_pool, _embedder, records, replace=replace)
    finally:
        if pool is None:
            await _pool.close()


async def load_file(
    path: Path,
    *,
    collection: str = "icar",
    metadata: dict[str, Any] | None = None,
    replace: bool = False,
    pool: asyncpg.Pool | None = None,
    embedder: Any = None,
) -> int:
    """Extract text from a file, chunk it, embed and insert."""
    from .embedder import build_embedder

    text = extract_text_from_file(path)
    source = path.name
    _pool = pool or await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    _embedder = embedder or build_embedder()
    raw_chunks = split_into_chunks(text)
    records = [
        {
            "chunk_id": _chunk_id(collection, source, i),
            "collection": collection,
            "content": ch,
            "source": source,
            "metadata": {**(metadata or {}), "filename": path.name},
        }
        for i, ch in enumerate(raw_chunks)
    ]
    log.info("loader.file", path=str(path), chunks=len(records))
    try:
        return await insert_chunks(_pool, _embedder, records, replace=replace)
    finally:
        if pool is None:
            await _pool.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _cli_main(args: argparse.Namespace) -> None:
    from .embedder import build_embedder

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    embedder = build_embedder()
    total = 0

    try:
        if args.text:
            total += await load_text(
                args.text,
                collection=args.collection,
                source=args.source or "cli-text",
                chunk_id=args.chunk_id,
                replace=args.replace,
                pool=pool,
                embedder=embedder,
            )

        if args.file:
            total += await load_file(
                Path(args.file),
                collection=args.collection,
                replace=args.replace,
                pool=pool,
                embedder=embedder,
            )

        if args.dir:
            extensions = {".txt", ".md", ".rst", ".pdf"}
            files = [p for p in Path(args.dir).rglob("*") if p.suffix.lower() in extensions]
            if not files:
                log.warning("loader.no_files", dir=args.dir)
            for f in sorted(files):
                try:
                    total += await load_file(
                        f,
                        collection=args.collection,
                        replace=args.replace,
                        pool=pool,
                        embedder=embedder,
                    )
                except Exception as exc:
                    log.error("loader.file_failed", file=str(f), error=str(exc))
    finally:
        await pool.close()

    print(f"Done. {total} chunks inserted/updated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load documents into knowledge_chunks.")
    parser.add_argument("--text", help="Raw text string to embed directly.")
    parser.add_argument("--file", help="Path to a .txt, .md, or .pdf file.")
    parser.add_argument("--dir", help="Directory; all .txt/.md/.pdf files are loaded recursively.")
    parser.add_argument("--collection", default="icar", help="Collection name (default: icar).")
    parser.add_argument("--source", help="Source label for --text input.")
    parser.add_argument("--chunk-id", dest="chunk_id", help="Explicit chunk_id for --text (single chunk only).")
    parser.add_argument("--replace", action="store_true", help="Delete existing rows for this source before inserting.")
    args = parser.parse_args()

    if not any([args.text, args.file, args.dir]):
        parser.error("Provide at least one of --text, --file, or --dir.")

    asyncio.run(_cli_main(args))


if __name__ == "__main__":
    main()
