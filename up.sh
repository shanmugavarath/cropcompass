#!/usr/bin/env bash
# One-shot bring-up script. Idempotent.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[up] Created .env from template. Set LLM_STUDIO_MODEL (or ANTHROPIC_API_KEY for production)."
fi

echo "[up] Building images..."
docker compose build

echo "[up] Starting stack..."
docker compose up -d

echo "[up] Waiting for /health..."
for i in {1..30}; do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "[up] Agent is healthy."
    break
  fi
  sleep 2
done

echo ""
echo "Agent:       http://localhost:8000"
echo "  /health    liveness"
echo "  /tools     registered tools (agent + both MCPs)"
echo "  /api/chat  POST {farmer_id, message}"
echo "  /ws/chat   websocket (token stream)"
echo "  /sse/chat  server-sent events (token stream)"
echo ""
echo "DB MCP:      http://localhost:9101/mcp"
echo "Vector MCP:  http://localhost:9102/mcp"
echo ""
echo "Logs:    docker compose logs -f agent"
echo "Stop:    docker compose down"
echo "Reset:   docker compose down -v   (also drops the database)"
