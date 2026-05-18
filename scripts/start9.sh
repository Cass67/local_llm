#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"

case "$profile" in
  speed)
    ngl=999
    ctx=49152
    batch=128
    ubatch=128
    hf_file="Qwen3.5-27B.Q4_K_S.gguf"
    ;;
  fastlong)
    ngl=999
    ctx=49152
    batch=128
    ubatch=128
    hf_file="Qwen3.5-27B.Q4_K_S.gguf"
    ;;
  balanced)
    ngl=999
    ctx=49152
    batch=64
    ubatch=64
    hf_file="Qwen3.5-27B.Q4_K_S.gguf"
    ;;
  reliable)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    hf_file="Qwen3.5-27B.Q3_K_M.gguf"
    ;;
  tiny)
    ngl=999
    ctx=98304
    batch=64
    ubatch=64
    hf_file="Qwen3.5-27B.Q3_K_S.gguf"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF" \
  --hf-file "$hf_file" \
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
  --alias qwen3.5-27b-opus-reasoning
