"""Pluggable embedder interface for the vector MCP server.

Default backend: sentence-transformers (local, no API key).
Swap by setting EMBEDDING_BACKEND=huggingface and HF_API_KEY in env.
"""

from __future__ import annotations

import os
from typing import Protocol


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformersEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        def _run() -> list[list[float]]:
            return self._model.encode(texts, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(_run)


class HuggingFaceEmbedder:
    def __init__(self, model_name: str, token: str) -> None:
        import httpx

        self._url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_name}"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = httpx.AsyncClient(timeout=30.0)
        self.dim = int(os.getenv("EMBEDDING_DIM", "384"))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        r = await self._http.post(self._url, headers=self._headers, json={"inputs": texts})
        r.raise_for_status()
        return r.json()


def build_embedder() -> Embedder:
    backend = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
    model = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    if backend == "huggingface":
        token = os.getenv("HF_API_KEY", "")
        if not token:
            raise RuntimeError("HF_API_KEY required for huggingface embedder")
        return HuggingFaceEmbedder(model, token)
    return SentenceTransformersEmbedder(model)
