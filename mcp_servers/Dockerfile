FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
COPY src ./src
COPY mcp_servers ./mcp_servers
RUN uv pip install --system -e ".[mcp-servers]"

EXPOSE 9101 9102
