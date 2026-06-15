FROM python:3.12-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY backend/ ./backend/
COPY ui-dist/ ./ui-dist/
COPY scripts/ /scripts/
COPY entrypoint.sh .

EXPOSE 3100

ENV LOCAL_LLM_STATE_DIR=/state
ENV LLAMA_CPP_DIR=/llama.cpp
ENV MODELS_CACHE_DIR=/models
ENV LLAMA_SERVER_PORT=8080

ENTRYPOINT ["/app/entrypoint.sh"]
