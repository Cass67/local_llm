#!/usr/bin/env bash
set -euo pipefail

profile="${1:-speed}"

case "$profile" in
  speed)
    ngl=999
    ctx=32768
    batch=128
    ubatch=128
    quant="UD-Q2_K_XL"
    ;;
  fastlong)
    ngl=999
    ctx=40960
    batch=64
    ubatch=64
    quant="UD-Q2_K_XL"
    ;;
  balanced)
    ngl=999
    ctx=32768
    batch=64
    ubatch=64
    quant="UD-Q2_K_XL"
    ;;
  reliable)
    ngl=999
    ctx=32768
    batch=64
    ubatch=64
    quant="UD-Q2_K_XL"
    ;;
  tiny)
    ngl=999
    ctx=32768
    batch=64
    ubatch=64
    quant="UD-IQ2_M"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/gemma-4-31B-it-GGUF:${quant}" \
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
  --reasoning off \
  --alias gemma-4-31b-it-vision
