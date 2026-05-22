#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"
hf_file="Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"

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
    ctx=65536
    batch=64
    ubatch=64
    ;;
  reliable)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    ;;
  tiny)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "unsloth/Qwen3.6-35B-A3B-MTP-GGUF" \
  --hf-file "$hf_file" \
  --mmproj-auto \
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
  --chat-template-kwargs '{"enable_thinking":false}' \
  --temp 0.6 \
  --top-p 0.95 \
  --top-k 20 \
  --min-p 0.0 \
  --presence-penalty 0.0 \
  --spec-type draft-mtp \
  --spec-draft-n-max 2 \
  --alias qwen3.6-35b-a3b-mtp
