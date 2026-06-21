FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# torch (a sentence-transformers dep) is a large wheel; give uv room on slow links.
ENV UV_HTTP_TIMEOUT=900

WORKDIR /app

# Install dependencies. The uv cache is mounted so wheels (esp. the huge torch
# wheel) are downloaded ONCE and reused across rebuilds — even when source files
# change and this layer re-runs. Requires BuildKit (default in modern Docker).
COPY pyproject.toml ./
COPY src ./src
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
        uv pip install --system -e ".[mcp-servers]"

EXPOSE 9101 9103
