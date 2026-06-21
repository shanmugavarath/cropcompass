"""MCP server: pgvector-backed semantic search over the ICAR/SAU knowledge base.

Tools exposed:
  query_knowledge_base - semantic search; returns top_k chunks with similarity
  fetch_chunk          - by chunk_id (exact lookup)
  list_collections     - which knowledge collections exist

Run:
  uvicorn mcp_servers.vector_server.server:app --host 0.0.0.0 --port 9102

Schema dependency (run once on the DB):
  see mcp_servers/vector_server/schema.sql
"""

from __future__ import annotations

import os
from typing import Any

import asyncpg
from fastapi import FastAPI

from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp

from .embedder import build_embedder

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass",
).replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

_pool: asyncpg.Pool | None = None
_embedder = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = build_embedder()
    return _embedder


registry = MCPToolRegistry()


@registry.tool(
    name="query_knowledge_base",
    description="Semantic search over ICAR/SAU agronomy chunks. Returns top_k with similarity in [0,1] and source metadata.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language question."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "collection": {"type": "string", "default": "icar", "description": "Knowledge collection name."},
            "crop": {"type": "string", "description": "Optional crop filter (matches metadata.crop)."},
        },
        "required": ["query"],
    },
)
async def _query_knowledge_base(query: str, top_k: int = 5, collection: str = "icar", crop: str | None = None) -> dict[str, Any]:
    embedder = _get_embedder()
    [vec] = await embedder.embed([query])
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if crop:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, metadata, source, 1 - (embedding <=> $1::vector) AS similarity
                  FROM knowledge_chunks
                 WHERE collection = $2 AND metadata->>'crop' ILIKE $3
                 ORDER BY embedding <=> $1::vector
                 LIMIT $4
                """,
                vec,
                collection,
                crop,
                top_k,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, metadata, source, 1 - (embedding <=> $1::vector) AS similarity
                  FROM knowledge_chunks
                 WHERE collection = $2
                 ORDER BY embedding <=> $1::vector
                 LIMIT $3
                """,
                vec,
                collection,
                top_k,
            )
    return {
        "query": query,
        "collection": collection,
        "chunks": [
            {
                "chunk_id": r["chunk_id"],
                "text": r["content"],
                "source": r["source"],
                "similarity": float(r["similarity"]),
                "metadata": dict(r["metadata"]) if r["metadata"] else {},
            }
            for r in rows
        ],
    }


@registry.tool(
    name="fetch_chunk",
    description="Fetch a single chunk by its chunk_id.",
    input_schema={
        "type": "object",
        "properties": {"chunk_id": {"type": "string"}},
        "required": ["chunk_id"],
    },
)
async def _fetch_chunk(chunk_id: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT chunk_id, content, metadata, source, collection FROM knowledge_chunks WHERE chunk_id = $1",
            chunk_id,
        )
    if row is None:
        return {"error": f"chunk not found: {chunk_id}"}
    return {
        "chunk_id": row["chunk_id"],
        "text": row["content"],
        "metadata": dict(row["metadata"]) if row["metadata"] else {},
        "source": row["source"],
        "collection": row["collection"],
    }


@registry.tool(
    name="list_collections",
    description="List knowledge collections and their chunk counts.",
    input_schema={"type": "object", "properties": {}},
)
async def _list_collections() -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT collection, COUNT(*) AS chunk_count FROM knowledge_chunks GROUP BY collection ORDER BY collection"
        )
    return {"collections": [{"name": r["collection"], "chunks": int(r["chunk_count"])} for r in rows]}


app = FastAPI(title="CropCompass Vector MCP Server", version="0.1.0")
mount_mcp(app, registry)


@app.on_event("startup")
async def _startup() -> None:
    """Auto-seed knowledge_chunks on first boot if the table is empty."""
    import structlog

    from .seed import seed_if_empty

    log = structlog.get_logger(__name__)
    try:
        pool = await _get_pool()
        embedder = _get_embedder()
        await seed_if_empty(pool, embedder)
    except Exception as exc:
        log.warning("vector.seed.failed", error=str(exc))


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
