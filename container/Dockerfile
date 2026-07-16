# Use the existing local-llm-runner image that's already on ubt26
FROM local-llm-runner:latest AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip docker.io docker-compose-v2 git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY container/backend/ ./backend/
COPY container/pyproject.toml .
RUN pip install --break-system-packages --no-cache-dir .
ARG CACHEBUST=1
RUN rm -rf ./ui-dist/assets/index-*.js ./ui-dist/assets/index-*.css ./ui-dist/index.html
COPY --link container/ui-dist/ ./ui-dist/
COPY scripts/ /scripts/
COPY container/entrypoint.sh .

EXPOSE 3100

ENV LOCAL_LLM_STATE_DIR=/state
ENV LLAMA_CPP_DIR=/llama.cpp
ENV MODELS_CACHE_DIR=/models
ENV LLAMA_SERVER_PORT=8080

ENTRYPOINT ["/app/entrypoint.sh"]
