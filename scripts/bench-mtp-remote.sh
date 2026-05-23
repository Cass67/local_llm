#!/usr/bin/env bash
set -euo pipefail

llama_cpp_dir="${LLAMA_CPP_DIR:-/home/cass/llama.cpp}"
results_dir="bench-mtp"
run_id="${LLAMA_MTP_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
logs_dir="$results_dir/logs/$run_id"
results_csv="$results_dir/results.csv"
port="${LLAMA_MTP_BENCH_PORT:-8080}"
chat_template_file="${LLAMA_MTP_CHAT_TEMPLATE:-$llama_cpp_dir/templates/qwen36-opencode.jinja}"
server_pid=""

cd "$llama_cpp_dir"
mkdir -p "$logs_dir"

if [[ "${LLAMA_MTP_APPEND:-false}" != true ]]; then
  printf '%s\n' 'family,repo,hf_file,ctx,batch,ubatch,spec_n,status,model_mib,kv_mib,rs_mib,compute_mib,prompt_tps,decode_tps,reason' >"$results_csv"
elif [[ ! -e "$results_csv" ]]; then
  printf '%s\n' 'family,repo,hf_file,ctx,batch,ubatch,spec_n,status,model_mib,kv_mib,rs_mib,compute_mib,prompt_tps,decode_tps,reason' >"$results_csv"
fi

stop_server() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  sleep 3
  server_pid=""
}

clear_existing_servers() {
  if ! pgrep -f '[l]lama-server' >/dev/null 2>&1; then
    return
  fi

  if [[ "${LLAMA_MTP_KILL_EXISTING:-false}" == true ]]; then
    pkill -f '[l]lama-server' >/dev/null 2>&1 || true
    sleep 5
    return
  fi

  printf '%s\n' 'Refusing to start: existing llama-server process found. Stop it first or set LLAMA_MTP_KILL_EXISTING=true.' >&2
  exit 1
}

last_number_for() {
  local pattern="$1"
  local log_file="$2"

  awk -v pattern="$pattern" '
        $0 ~ pattern {
            for (i = 1; i <= NF; i++) {
                if ($i ~ /^[0-9]+([.][0-9]+)?$/) {
                    value = $i
                }
            }
        }
        END { print value }
    ' "$log_file"
}

detect_thread_count() {
  local count=""

  if command -v nproc >/dev/null 2>&1; then
    count="$(nproc 2>/dev/null || true)"
    case "$count" in
      '' | *[!0-9]*) ;;
      *)
        printf '%s\n' "$count"
        return
        ;;
    esac
  fi

  if command -v sysctl >/dev/null 2>&1; then
    count="$(sysctl -n hw.ncpu 2>/dev/null || true)"
    case "$count" in
      '' | *[!0-9]*) ;;
      *)
        printf '%s\n' "$count"
        return
        ;;
    esac
  fi

  printf '%s\n' 4
}

json_string() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

chat_completion_request() {
  local alias="$1"
  local model_json
  model_json="$(json_string "$alias")"

  printf '{"model":%s,"messages":[{"role":"user","content":"Write a concise paragraph about speculative decoding."}],"max_tokens":256}' "$model_json"
}

csv_reason() {
  local reason="$1"
  reason="${reason//$'\n'/ }"
  reason="${reason//$'\r'/ }"
  reason="${reason//,/;}"
  printf '%s' "$reason"
}

append_result() {
  local family="$1"
  local repo="$2"
  local hf_file="$3"
  local ctx="$4"
  local batch="$5"
  local ubatch="$6"
  local spec_n="$7"
  local status="$8"
  local model_mib="$9"
  local kv_mib="${10}"
  local rs_mib="${11}"
  local compute_mib="${12}"
  local prompt_tps="${13}"
  local decode_tps="${14}"
  local reason="${15}"

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$family" "$repo" "$hf_file" "$ctx" "$batch" "$ubatch" "$spec_n" "$status" \
    "$model_mib" "$kv_mib" "$rs_mib" "$compute_mib" "$prompt_tps" "$decode_tps" "$(csv_reason "$reason")" \
    >>"$results_csv"
}

run_trial() {
  local family="$1"
  local repo="$2"
  local hf_file="$3"
  local ctx="$4"
  local batch="$5"
  local ubatch="$6"
  local spec_n="$7"
  local alias="$8"
  local log_file="$logs_dir/${family}-spec${spec_n}.log"
  local response_file="$logs_dir/${family}-spec${spec_n}.response.json"
  local status="success"
  local reason=""
  local model_mib=""
  local kv_mib=""
  local rs_mib=""
  local compute_mib=""
  local prompt_tps=""
  local decode_tps=""
  local ready=false
  local iteration
  local thread_count
  local chat_request
  local models_response

  stop_server
  : >"$log_file"
  thread_count="$(detect_thread_count)"
  printf 'START family=%s repo=%s file=%s ctx=%s batch=%s ubatch=%s spec_n=%s alias=%s\n' \
    "$family" "$repo" "$hf_file" "$ctx" "$batch" "$ubatch" "$spec_n" "$alias"

  ./build/bin/llama-server \
    -hf "$repo" \
    --hf-file "$hf_file" \
    --chat-template-file "$chat_template_file" \
    --no-mmproj \
    --host 0.0.0.0 \
    --port "$port" \
    -ngl 999 \
    -c "$ctx" \
    --flash-attn on \
    -ub "$ubatch" \
    -b "$batch" \
    --threads "$thread_count" \
    --prio 2 \
    --no-warmup \
    --temp 0.6 \
    --top-p 0.95 \
    --min-p 0.0 \
    --spec-type draft-mtp \
    --spec-draft-n-max "$spec_n" \
    --alias "$alias" \
    >>"$log_file" 2>&1 &
  server_pid="$!"

  for ((iteration = 1; iteration <= 180; iteration++)); do
    if models_response="$(curl -fsS --max-time 5 "http://127.0.0.1:$port/v1/models" 2>/dev/null)" && [[ "$models_response" == *"$alias"* ]]; then
      ready=true
      break
    fi
    if ! kill -0 "$server_pid" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  if [[ "$ready" != true ]]; then
    status="timeout"
    reason="server did not become ready"
  elif ! chat_request="$(chat_completion_request "$alias")"; then
    status="error"
    reason="chat request construction failed"
  elif ! curl -fsS --max-time 300 "http://127.0.0.1:$port/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "$chat_request" \
    >"$response_file" 2>>"$log_file"; then
    status="error"
    reason="chat completion failed"
  fi

  stop_server

  if grep -Eiq 'hipMalloc failed|out of memory|OOM|cannot allocate memory|std::bad_alloc' "$log_file"; then
    status="oom"
    reason="OOM detected"
  fi

  model_mib="$(last_number_for 'model.*buffer.*MiB' "$log_file")"
  kv_mib="$(last_number_for 'KV.*buffer.*MiB' "$log_file")"
  rs_mib="$(last_number_for 'recompute|RS.*buffer.*MiB' "$log_file")"
  compute_mib="$(last_number_for 'compute.*buffer.*MiB' "$log_file")"
  prompt_tps="$(last_number_for 'prompt.*tokens per second|prompt.*tok/s|prompt.*t/s' "$log_file")"
  decode_tps="$(last_number_for 'eval.*tokens per second|decode.*tok/s|decode.*t/s' "$log_file")"

  append_result "$family" "$repo" "$hf_file" "$ctx" "$batch" "$ubatch" "$spec_n" "$status" \
    "$model_mib" "$kv_mib" "$rs_mib" "$compute_mib" "$prompt_tps" "$decode_tps" "$reason"
  printf 'END family=%s spec_n=%s status=%s prompt_tps=%s decode_tps=%s reason=%s\n' \
    "$family" "$spec_n" "$status" "$prompt_tps" "$decode_tps" "$reason"
}

trap stop_server EXIT

spec_values=(2 4 8 12 16 24 32)

clear_existing_servers
stop_server
printf 'RUN run_id=%s results=%s logs=%s\n' "$run_id" "$results_csv" "$logs_dir"

for spec_n in "${spec_values[@]}"; do
  run_trial qwen-mtp 'unsloth/Qwen3.6-35B-A3B-MTP-GGUF' 'Qwen3.6-35B-A3B-UD-IQ4_NL.gguf' 65536 64 64 "$spec_n" qwen3.6-35b-a3b-mtp
  run_trial qwen-27b-mtp 'unsloth/Qwen3.6-27B-MTP-GGUF' 'Qwen3.6-27B-Q3_K_M.gguf' 65536 64 64 "$spec_n" qwen3.6-27b-mtp
  run_trial qwen-heretic-mtp 'llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF' 'Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf' 65536 64 64 "$spec_n" qwen3.6-27b-heretic-mtp
  # Nearest MTP-capable Qwopus candidate, not the original Jackrong Qwen3.5 Opus distill.
  run_trial qwen-opus-mtp 'noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF' 'Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf' 65536 64 64 "$spec_n" qwen3.6-27b-opus-mtp
done
