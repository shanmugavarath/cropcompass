FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system -e .

# Copy rest of source (prompts, etc.)
COPY prompts ./prompts

EXPOSE 8000
CMD ["uvicorn", "agent_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
