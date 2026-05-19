#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"
port="${LLAMA_PORT:-8080}"
hf_file="GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"

case "$profile" in
  speed)
    ngl=999
    ctx=32768
    batch=128
    ubatch=128
    ;;
  fastlong)
    ngl=999
    ctx=49152
    batch=128
    ubatch=128
    ;;
  balanced)
    ngl=999
    ctx=49152
    batch=64
    ubatch=64
    ;;
  reliable)
    ngl=999
    ctx=49152
    batch=64
    ubatch=64
    ;;
  tiny)
    ngl=999
    ctx=49152
    batch=64
    ubatch=64
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "HauhauCS/GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive" \
  --hf-file "$hf_file" \
  --no-mmproj \
  --host 0.0.0.0 \
  --port "$port" \
  -ngl "$ngl" \
  -c "$ctx" \
  --flash-attn on \
  -ub "$ubatch" \
  -b "$batch" \
  --threads "$(nproc)" \
  --prio 2 \
  --no-warmup \
  --temp 0.6 \
  --top-p 0.95 \
  --top-k 20 \
  --min-p 0.0 \
  --presence-penalty 0.0 \
  --alias glm-4.7-flash-hauhau
