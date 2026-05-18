#!/usr/bin/env bash
set -euo pipefail

cd /home/cass/llama.cpp
mkdir -p bench-heretic-context/logs
csv='bench-heretic-context/results.csv'
printf 'quant,ctx,status,model_mib,kv_mib,rs_mib,compute_mib,prompt_tps,decode_tps,reason\n' > "$csv"

repo='DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF'
template='/home/cass/llama.cpp/templates/qwen36-opencode.jinja'
alias='qwen3.6-27b-heretic-bench'

quants=(
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ2_M.gguf'
)
contexts=(65536 98304 131072 196608 262144)

stop_server() {
  pkill -f './build/bin/llama-server .*qwen3.6-27b-heretic' 2>/dev/null || true
  sleep 3
}

last_number_for() {
  local pattern="$1"
  local log="$2"
  grep -E "$pattern" "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true
}

for quant in "${quants[@]}"; do
  for ctx in "${contexts[@]}"; do
    stop_server
    safe_quant="${quant//[^A-Za-z0-9_]/_}"
    log="bench-heretic-context/logs/${safe_quant}-${ctx}.log"
    : > "$log"

    ./build/bin/llama-server \
      -hf "$repo" \
      --hf-file "$quant" \
      --chat-template-file "$template" \
      --no-mmproj \
      --host 0.0.0.0 \
      --port 8080 \
      -ngl 999 \
      -c "$ctx" \
      --flash-attn on \
      -ub 64 \
      -b 64 \
      --threads "$(nproc)" \
      --prio 2 \
      --no-warmup \
      --temp 0.6 \
      --top-p 0.95 \
      --top-k 20 \
      --min-p 0.0 \
      --presence-penalty 0.0 \
      --alias "$alias" > "$log" 2>&1 &
    pid=$!

    status='fail'
    reason='startup_timeout'
    for _ in $(seq 1 120); do
      if curl -fsS http://127.0.0.1:8080/v1/models >/dev/null 2>&1; then
        status='loaded'
        reason='loaded'
        break
      fi
      if ! kill -0 "$pid" 2>/dev/null; then
        reason='process_exited'
        break
      fi
      sleep 2
    done

    if [[ "$status" == loaded ]]; then
      if curl -fsS http://127.0.0.1:8080/v1/chat/completions \
        -H 'Content-Type: application/json' \
        -d '{"model":"qwen3.6-27b-heretic-bench","messages":[{"role":"user","content":"Say OK only."}],"max_tokens":64}' >> "$log" 2>&1; then
        reason='completion_ok'
      else
        status='completion_fail'
        reason='completion_failed'
      fi
      sleep 2
    fi

    model_mib="$(last_number_for 'ROCm0 model buffer size' "$log")"
    kv_mib="$(last_number_for 'ROCm0 KV buffer size' "$log")"
    rs_mib="$(last_number_for 'ROCm0 RS buffer size' "$log")"
    compute_mib="$(last_number_for 'ROCm0 compute buffer size' "$log")"
    prompt_tps="$(grep -E 'prompt eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"
    decode_tps="$(grep -E '^       eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"

    if [[ "$status" == fail ]]; then
      if grep -qi 'out of memory\|failed to allocate\|cudaMalloc failed' "$log"; then
        reason='oom'
      elif grep -qi 'failed to load model' "$log"; then
        reason='load_failed'
      fi
    fi

    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$quant" "$ctx" "$status" "$model_mib" "$kv_mib" "$rs_mib" "$compute_mib" "$prompt_tps" "$decode_tps" "$reason" >> "$csv"
    stop_server
  done
done
