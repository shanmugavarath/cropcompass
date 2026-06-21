# Dedicated image for the Chroma MCP.
#
# Unlike the shared mcp_servers/Dockerfile, this one BAKES the multilingual
# embedding model into the image at build time and then switches HuggingFace to
# offline mode. Result: the container never needs network access to HF at
# runtime -- it's fully self-contained and safe to recreate / redeploy anywhere.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# torch (a sentence-transformers dep) is a large wheel; give uv room on slow links.
ENV UV_HTTP_TIMEOUT=900

# Keep the HF cache in a fixed, image-baked location.
ENV HF_HOME=/opt/hf-cache

WORKDIR /app

# Install dependencies. uv cache mount => the huge torch wheel downloads ONCE
# and is reused across rebuilds even when source changes. Needs BuildKit.
COPY pyproject.toml ./
COPY src ./src
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
        uv pip install --system -e ".[mcp-servers]"

# Bake the embedding model into the image (downloaded ONCE, at build time).
# Must match CHROMA_EMBED_MODEL / the version the store was embedded with.
ARG EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

# Everything is local now -- never reach out to HF at runtime.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 9103
