# Use the existing local-llm-runner image that's already on ubt26
# This image should already have dependencies installed from a previous build
FROM local-llm-runner:latest AS base

# Add Python support if needed (we'll copy our backend directly)
WORKDIR /app
COPY container/backend/ ./backend/
COPY container/pyproject.toml .
# Skip pip install - dependencies must be pre-installed
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
