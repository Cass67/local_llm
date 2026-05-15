#!/usr/bin/env bash
set -euo pipefail

profile="${1:-speed}"

case "$profile" in
  speed)
    ngl=999
    ctx=32768
    batch=1024
    ubatch=1024
    quant="UD-Q3_K_XL"
    ;;
  fastlong)
    ngl=999
    ctx=40960
    batch=1024
    ubatch=1024
    quant="UD-Q3_K_XL"
    ;;
  balanced)
    ngl=999
    ctx=49152
    batch=1024
    ubatch=1024
    quant="UD-Q3_K_XL"
    ;;
  reliable)
    ngl=45
    ctx=65536
    batch=256
    ubatch=256
    quant="UD-Q3_K_XL"
    ;;
  tiny)
    ngl=999
    ctx=40960
    batch=1024
    ubatch=1024
    quant="UD-Q2_K_XL"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/Qwen3.6-35B-A3B-GGUF:${quant}" \
  --host 0.0.0.0 \
  --port 8080 \
  -ngl "$ngl" \
  -c "$ctx" \
  --flash-attn on \
  -ub "$ubatch" \
  -b "$batch" \
  --threads "$(nproc)" \
  --prio 2 \
  --mlock \
  --no-warmup \
  --temp 0.6 \
  --top-p 0.95 \
  --top-k 20 \
  --min-p 0.0 \
  --presence-penalty 0.0 \
  --reasoning off \
  --alias qwen3.6-35b-a3b
