#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"

case "$profile" in
  speed)
    ngl=999
    ctx=49152
    batch=128
    ubatch=128
    quant="IQ4_XS"
    ;;
  fastlong)
    ngl=999
    ctx=49152
    batch=128
    ubatch=128
    quant="IQ4_XS"
    ;;
  balanced)
    ngl=999
    ctx=49152
    batch=64
    ubatch=64
    quant="IQ4_XS"
    ;;
  reliable)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    quant="IQ4_XS"
    ;;
  tiny)
    ngl=999
    ctx=98304
    batch=64
    ubatch=64
    quant="UD-Q3_K_XL"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/Qwen3.6-27B-GGUF:${quant}" \
  --no-mmproj \
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
  --alias qwen3.6-27b
