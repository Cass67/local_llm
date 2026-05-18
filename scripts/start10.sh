#!/usr/bin/env bash
set -euo pipefail

profile="${1:-reliable}"
llama_cpp_dir="${LLAMA_CPP_DIR:-${OC_LOCAL_LLAMA_DIR:-$(pwd)}}"
chat_template_file="${llama_cpp_dir}/templates/qwen36-opencode.jinja"
chat_template_kwargs=()

case "$profile" in
  speed)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    hf_file="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf"
    chat_template_kwargs=(--chat-template-kwargs '{"enable_thinking":false}')
    ;;
  fastlong)
    ngl=999
    ctx=98304
    batch=64
    ubatch=64
    hf_file="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf"
    ;;
  balanced)
    ngl=999
    ctx=98304
    batch=64
    ubatch=64
    hf_file="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf"
    ;;
  reliable)
    ngl=999
    ctx=65536
    batch=64
    ubatch=64
    hf_file="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf"
    ;;
  tiny)
    ngl=999
    ctx=131072
    batch=64
    ubatch=64
    hf_file="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ2_M.gguf"
    ;;
  *)
    echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2
    exit 2
    ;;
esac

exec ./build/bin/llama-server \
  -hf "DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF" \
  --hf-file "$hf_file" \
  --chat-template-file "$chat_template_file" \
  "${chat_template_kwargs[@]}" \
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
  --alias qwen3.6-27b-heretic-code
