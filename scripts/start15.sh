#!/usr/bin/env bash
set -euo pipefail
profile="${1:-reliable}"
case "$profile" in speed | fastlong | balanced | reliable | tiny) ;; *)
  echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
  exit 2
  ;;
esac
ctx=65536
batch=64
ubatch=64
ngl=999
exec ./build/bin/llama-server \
  -hf unsloth/Qwen3-Coder-Next-GGUF \
  --hf-file Qwen3-Coder-Next-UD-TQ1_0.gguf \
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
  --alias qwen3-coder-next \
  --reasoning off
