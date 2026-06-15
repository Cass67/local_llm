#!/usr/bin/env bash
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
CADDYFILE="${CADDYFILE:-$LLAMA_DIR/Caddyfile.local-llm}"
NAME="${LOCAL_LLM_CADDY_CONTAINER:-local-llm-caddy}"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --network host \
  -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" \
  caddy:2
