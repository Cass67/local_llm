# Self-contained base. mgmt orchestrates runner containers via the Docker socket and
# never runs llama-server itself; GPU inventory reads sysfs (/sys/bus/pci, /sys/class/drm),
# not vendor tools. So it needs no runner/ROCm base — just python + docker CLI + git/curl.
# (Previously FROM an untracked local-llm-runner:latest, which a `docker prune -a` deleted.)
FROM ubuntu:24.04 AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 python3-pip docker.io docker-compose-v2 git curl \
    && rm -rf /var/lib/apt/lists/*

ARG DOCKER_BUILDX_VERSION=0.35.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) buildx_arch="linux-amd64" ;; \
        arm64) buildx_arch="linux-arm64" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    mkdir -p /usr/local/lib/docker/cli-plugins; \
    curl -fsSL \
        -o /usr/local/lib/docker/cli-plugins/docker-buildx \
        "https://github.com/docker/buildx/releases/download/v${DOCKER_BUILDX_VERSION}/buildx-v${DOCKER_BUILDX_VERSION}.${buildx_arch}"; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

WORKDIR /app
COPY container/backend/ ./backend/
COPY container/pyproject.toml .
RUN pip install --break-system-packages --no-cache-dir .
ARG CACHEBUST=1
RUN rm -rf ./ui-dist/assets/index-*.js ./ui-dist/assets/index-*.css ./ui-dist/index.html
COPY --link container/ui-dist/ ./ui-dist/
COPY scripts/ /scripts/
COPY runner/ ./runner/
COPY container/entrypoint.sh .

EXPOSE 3100

ENV LOCAL_LLM_STATE_DIR=/state
ENV LLAMA_CPP_DIR=/llama.cpp
ENV MODELS_CACHE_DIR=/models
ENV LLAMA_SERVER_PORT=8080

ENTRYPOINT ["/app/entrypoint.sh"]
