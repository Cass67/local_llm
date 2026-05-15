#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"

case "$profile" in
  speed)
    ngl=999
    ctx=131072
    batch=1024
    ubatch=1024
    quant="UD-Q8_K_XL"
    reasoning_effort=medium
    ;;
  fastlong)
    ngl=999
    ctx=131072
    batch=512
    ubatch=512
    quant="UD-Q8_K_XL"
    reasoning_effort=medium
    ;;
  balanced)
    ngl=999
    ctx=131072
    batch=256
    ubatch=256
    quant="UD-Q8_K_XL"
    reasoning_effort=high
    ;;
  reliable)
    ngl=999
    ctx=131072
    batch=128
    ubatch=128
    quant="UD-Q8_K_XL"
    reasoning_effort=high
    ;;
  tiny)
    ngl=999
    ctx=131072
    batch=256
    ubatch=256
    quant="UD-Q4_K_XL"
    reasoning_effort=high
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/gpt-oss-20b-GGUF:${quant}" \
  --host 0.0.0.0 \
  --port 8080 \
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
  --chat-template-kwargs "{\"reasoning_effort\":\"${reasoning_effort}\"}" \
  --alias gpt-oss-20b
