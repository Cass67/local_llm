#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"

case "$profile" in
  speed)
    ngl=999
    ctx=16384
    batch=128
    ubatch=128
    quant="Q3_K_M"
    ;;
  fastlong)
    ngl=999
    ctx=16384
    batch=64
    ubatch=64
    quant="Q3_K_M"
    ;;
  balanced)
    ngl=999
    ctx=16384
    batch=64
    ubatch=64
    quant="Q3_K_M"
    ;;
  reliable)
    ngl=999
    ctx=16384
    batch=64
    ubatch=64
    quant="Q3_K_M"
    ;;
  tiny)
    ngl=999
    ctx=32768
    batch=64
    ubatch=64
    quant="Q2_K"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF:${quant}" \
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
  --alias deepseek-r1-distill-qwen-32b
