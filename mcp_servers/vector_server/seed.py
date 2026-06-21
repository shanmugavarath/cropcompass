"""Auto-seed knowledge_chunks from the existing DB on first boot.

Pulls real, queryable content already loaded by cropcompass_dump.sql:
  - crop_water_requirements.notes -> one chunk per crop
  - latest imd_advisories.advisory_text per district -> one chunk per district

Idempotent: if knowledge_chunks already has rows, does nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger(__name__)


async def seed_if_empty(pool: asyncpg.Pool, embedder: Any) -> int:
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM knowledge_chunks")
        if existing and int(existing) > 0:
            log.info("seed.skip", existing=int(existing))
            return 0

        crop_rows = await conn.fetch(
            """
            SELECT crop_name, notes, optimal_rainfall_mm, water_sensitivity,
                   kharif_suitable, rabi_suitable
              FROM crop_water_requirements
             WHERE notes IS NOT NULL AND notes <> ''
            """
        )
        advisory_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (district)
                   district, state, bulletin_date, advisory_text, season_outlook,
                   rainfall_category
              FROM imd_advisories
             WHERE advisory_text IS NOT NULL AND advisory_text <> ''
             ORDER BY district, bulletin_date DESC, fetched_at DESC
             LIMIT 200
            """
        )

    chunks: list[dict[str, Any]] = []
    for r in crop_rows:
        season = []
        if r["kharif_suitable"]:
            season.append("kharif")
        if r["rabi_suitable"]:
            season.append("rabi")
        text = (
            f"Crop: {r['crop_name']}. Optimal rainfall: {r['optimal_rainfall_mm']} mm. "
            f"Water sensitivity: {r['water_sensitivity']}. "
            f"Suitable seasons: {', '.join(season) or 'n/a'}. {r['notes']}"
        )
        chunks.append(
            {
                "chunk_id": f"icar:crop:{r['crop_name'].lower()}",
                "collection": "icar",
                "content": text,
                "source": "ICAR crop_water_requirements",
                "metadata": {"crop": r["crop_name"], "kind": "crop_profile"},
            }
        )

    for r in advisory_rows:
        text = (
            f"District: {r['district']} ({r['state']}). Bulletin date: {r['bulletin_date']}. "
            f"Rainfall category: {r['rainfall_category'] or 'n/a'}. "
            f"Season outlook: {r['season_outlook'] or 'n/a'}. Advisory: {r['advisory_text']}"
        )
        chunks.append(
            {
                "chunk_id": f"imd:advisory:{r['district'].lower()}:{r['bulletin_date']}",
                "collection": "imd",
                "content": text,
                "source": "IMD GKMS district advisory",
                "metadata": {"district": r["district"], "state": r["state"], "kind": "advisory"},
            }
        )

    if not chunks:
        log.warning("seed.no_source_data")
        return 0

    log.info("seed.embedding", count=len(chunks))
    embeddings = await embedder.embed([c["content"] for c in chunks])

    import json as _json

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO knowledge_chunks (chunk_id, collection, content, source, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            [
                (
                    c["chunk_id"],
                    c["collection"],
                    c["content"],
                    c["source"],
                    _json.dumps(c["metadata"]),
                    str(e),
                )
                for c, e in zip(chunks, embeddings)
            ],
        )

    log.info("seed.done", inserted=len(chunks))
    return len(chunks)


async def main() -> None:
    import os

    from .embedder import build_embedder

    db = os.getenv(
        "DATABASE_URL", "postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass"
    ).replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    pool = await asyncpg.create_pool(db, min_size=1, max_size=2)
    embedder = build_embedder()
    try:
        await seed_if_empty(pool, embedder)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
