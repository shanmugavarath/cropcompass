"""MCP server: ChromaDB-backed semantic search over the ICAR/SAU knowledge base.

This is the project's vector-search MCP. It exposes the tool contract the
agent runner already expects (query_knowledge_base -> {"chunks": [...]}), so no
agent code changes are required — only the wiring (MCP_SERVER_URLS) is swapped.

Tools exposed:
  query_knowledge_base - semantic search; returns top_k chunks with similarity
  fetch_chunk          - by chunk_id (exact lookup)
  list_collections     - which Chroma collections exist + their counts

Data:
  Reads the persisted Chroma store at $CHROMA_PATH (default: <repo>/data/chromadb).
  See README_CHROMADB_SETUP.md for how that store is produced.

Run:
  uvicorn mcp_servers.chroma_server.server:app --host 0.0.0.0 --port 9103
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp

from . import retriever

registry = MCPToolRegistry()


@registry.tool(
    name="query_knowledge_base",
    description=(
        "Semantic search over ICAR/SAU agronomy chunks (ChromaDB). Returns top_k "
        "chunks with similarity in [0,1] and source metadata. Multilingual: English "
        "queries also retrieve Tamil chunks."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language question."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "crop": {"type": "string", "description": "Optional crop filter (matches metadata.crop)."},
            "soil": {"type": "string", "description": "Optional soil type (signature parity; not a hard filter)."},
        },
        "required": ["query"],
    },
)
async def _query_knowledge_base(
    query: str, top_k: int = 5, crop: str | None = None, soil: str | None = None
) -> dict[str, Any]:
    return await retriever.query_knowledge_base(query=query, crop=crop, soil=soil, top_k=top_k)


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
    return await retriever.fetch_chunk(chunk_id)


@registry.tool(
    name="list_collections",
    description="List Chroma knowledge collections and their chunk counts.",
    input_schema={"type": "object", "properties": {}},
)
async def _list_collections() -> dict[str, Any]:
    return await retriever.list_collections()


app = FastAPI(title="CropCompass Chroma MCP Server", version="0.1.0")
mount_mcp(app, registry)


@app.on_event("startup")
async def _startup() -> None:
    """Warm the model + chroma client in the BACKGROUND.

    Loading the embedding model can take a while; doing it inline would block
    uvicorn's startup and make /health (and everything else) unreachable. We fire
    it as a background task so the server answers immediately and the first query
    either reuses the warm client or lazily initialises it.
    """
    import asyncio

    import structlog

    log = structlog.get_logger(__name__)

    async def _warm() -> None:
        try:
            info = await retriever.list_collections()
            log.info("chroma.ready", collections=info.get("collections"))
        except Exception as exc:
            log.warning("chroma.warmup.failed", error=str(exc))

    asyncio.create_task(_warm())
