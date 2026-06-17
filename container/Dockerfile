# rocminfo lives in the already-built runner image — no need to pull the 20GB dev image
FROM local-llm-runner-rocm:latest AS rocm-tools

FROM python:3.12-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    build-essential \
    pciutils \
    libvulkan1 \
    vulkan-tools \
    mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rocm-tools /usr/bin/rocminfo /usr/local/bin/rocminfo

WORKDIR /app

COPY container/pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY container/backend/ ./backend/
COPY container/ui-dist/ ./ui-dist/
COPY scripts/ /scripts/
COPY container/entrypoint.sh .

EXPOSE 3100

ENV LOCAL_LLM_STATE_DIR=/state
ENV LLAMA_CPP_DIR=/llama.cpp
ENV MODELS_CACHE_DIR=/models
ENV LLAMA_SERVER_PORT=8080

ENTRYPOINT ["/app/entrypoint.sh"]
