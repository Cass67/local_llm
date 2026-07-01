#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: bench-installed-kv-remote.sh --family FAMILY --repo REPO --quant-mode file|selector --quant QUANT --alias ALIAS [options]

Options:
  --ctx N
  --batch N
  --ubatch N
  --mmproj enabled|disabled|none
  --template none|qwen_thinking_off|qwen_template_file|qwen_template_thinking_off|reasoning_off|gpt_oss_high
  --extra none|mtp
EOF
}

family=''
repo=''
quant_mode=''
quant=''
alias=''
ctx='65536'
batch='64'
ubatch='64'
mmproj='none'
template_mode='none'
extra_mode='none'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --family)
      family="${2:-}"
      shift 2
      ;;
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --quant-mode)
      quant_mode="${2:-}"
      shift 2
      ;;
    --quant)
      quant="${2:-}"
      shift 2
      ;;
    --alias)
      alias="${2:-}"
      shift 2
      ;;
    --ctx)
      ctx="${2:-}"
      shift 2
      ;;
    --batch)
      batch="${2:-}"
      shift 2
      ;;
    --ubatch)
      ubatch="${2:-}"
      shift 2
      ;;
    --mmproj)
      mmproj="${2:-}"
      shift 2
      ;;
    --template)
      template_mode="${2:-}"
      shift 2
      ;;
    --extra)
      extra_mode="${2:-}"
      shift 2
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$family" || -z "$repo" || -z "$quant_mode" || -z "$quant" || -z "$alias" ]]; then
  usage
  exit 2
fi

llama_cpp_dir="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
port="${LLAMA_PORT:-8080}"
host="127.0.0.1"
listen_host="0.0.0.0"
wait_attempts="${WAIT_ATTEMPTS:-180}"
logs_dir="${LOGS_DIR:-${TMPDIR:-/tmp}/installed-kv-cache-logs}"
server_pid=""
service_was_active=false

cd "$llama_cpp_dir"
mkdir -p "$logs_dir"

case "${RUN_Q4:-0}" in
  0) kv_modes=(default q8_0) ;;
  1) kv_modes=(default q8_0 q4_0) ;;
  *)
    printf 'RUN_Q4 must be 0 or 1\n' >&2
    exit 2
    ;;
esac

cases=("$family|$repo|$quant_mode|$quant|$alias|$ctx|$batch|$ubatch|$mmproj|$template_mode|$extra_mode")

stop_tracked_server() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  server_pid=""
}

capture_service_state() {
  if systemctl --user is-active --quiet llama-server.service >/dev/null 2>&1; then
    service_was_active=true
  fi
}

stop_managed_service() {
  if systemctl --user is-active --quiet llama-server.service >/dev/null 2>&1; then
    systemctl --user stop llama-server.service >/dev/null 2>&1 || true
  fi
  sleep 3
}

restore_service() {
  stop_tracked_server
  if [[ "$service_was_active" == true ]]; then
    systemctl --user restart llama-server.service >/dev/null 2>&1 || true
  fi
}

thread_count() {
  local count=""

  if command -v nproc >/dev/null 2>&1; then
    count="$(nproc 2>/dev/null || true)"
    if [[ "$count" =~ ^[0-9]+$ ]] && ((count > 0)); then
      printf '%s\n' "$count"
      return
    fi
  fi

  if command -v sysctl >/dev/null 2>&1; then
    count="$(sysctl -n hw.ncpu 2>/dev/null || true)"
    if [[ "$count" =~ ^[0-9]+$ ]] && ((count > 0)); then
      printf '%s\n' "$count"
      return
    fi
  fi

  printf '1\n'
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

chat_request() {
  local alias="$1"
  local alias_json
  alias_json="$(json_string "$alias")"
  printf '{"model":%s,"messages":[{"role":"user","content":"Reply with exactly: ok"}],"max_tokens":64,"temperature":0}' "$alias_json"
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

first_log_match() {
  local pattern="$1"
  local log_file="$2"

  awk -v pattern="$pattern" '
    $0 ~ pattern {
      gsub(/\t/, " ")
      print
      exit
    }
  ' "$log_file"
}

tsv_clean() {
  local value="$1"
  value="${value//$'\t'/ }"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "$value"
}

add_model_args() {
  local repo="$1"
  local quant_mode="$2"
  local quant="$3"

  if [[ "$quant_mode" == file ]]; then
    args+=(-hf "$repo" --hf-file "$quant")
  else
    args+=(-hf "${repo}:${quant}")
  fi
}

add_mmproj_args() {
  local mmproj="$1"

  case "$mmproj" in
    enabled) args+=(--mmproj-auto) ;;
    disabled) args+=(--no-mmproj) ;;
    none) ;;
    *)
      printf 'unknown mmproj mode: %s\n' "$mmproj" >&2
      exit 2
      ;;
  esac
}

add_template_args() {
  local template_mode="$1"

  case "$template_mode" in
    none) ;;
    qwen_thinking_off)
      args+=(--chat-template-kwargs '{"enable_thinking":false}')
      ;;
    qwen_template_file)
      args+=(--chat-template-file "${llama_cpp_dir}/templates/qwen36-opencode.jinja")
      ;;
    qwen_template_thinking_off)
      args+=(--chat-template-file "${llama_cpp_dir}/templates/qwen36-opencode.jinja")
      args+=(--chat-template-kwargs '{"enable_thinking":false}')
      ;;
    reasoning_off)
      args+=(--reasoning off)
      ;;
    gpt_oss_high)
      args+=(--chat-template-kwargs '{"reasoning_effort":"high"}')
      ;;
    *)
      printf 'unknown template mode: %s\n' "$template_mode" >&2
      exit 2
      ;;
  esac
}

add_extra_args() {
  local extra_mode="$1"

  case "$extra_mode" in
    none) ;;
    mtp) args+=(--spec-type draft-mtp --spec-draft-n-max 2) ;;
    *)
      printf 'unknown extra mode: %s\n' "$extra_mode" >&2
      exit 2
      ;;
  esac
}

add_kv_args() {
  local kv="$1"

  case "$kv" in
    default) ;;
    q8_0) args+=(--cache-type-k q8_0 --cache-type-v q8_0) ;;
    q4_0) args+=(--cache-type-k q4_0 --cache-type-v q4_0) ;;
    *)
      printf 'unknown KV mode: %s\n' "$kv" >&2
      exit 2
      ;;
  esac
}

wait_for_models() {
  local alias="$1"
  local attempt
  local response

  for ((attempt = 1; attempt <= wait_attempts; attempt++)); do
    if response="$(curl -fsS --max-time 5 "http://${host}:${port}/v1/models" 2>/dev/null)" && [[ "$response" == *"$alias"* ]]; then
      return 0
    fi
    if [[ -n "$server_pid" ]] && ! kill -0 "$server_pid" >/dev/null 2>&1; then
      return 1
    fi
    sleep 2
  done

  return 1
}

sanity_status() {
  local alias="$1"
  local response_file="$2"
  local request
  request="$(chat_request "$alias")"

  if ! curl -fsS --max-time 300 "http://${host}:${port}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "$request" \
    >"$response_file"; then
    printf 'fail'
    return
  fi

  if awk 'BEGIN { found = 0 } /"content"[[:space:]]*:[[:space:]]*"ok"/ { found = 1 } END { exit found ? 0 : 1 }' "$response_file"; then
    printf 'ok'
  else
    printf 'mismatch'
  fi
}

run_one() {
  local family="$1"
  local repo="$2"
  local quant_mode="$3"
  local quant="$4"
  local alias="$5"
  local ctx="$6"
  local batch="$7"
  local ubatch="$8"
  local mmproj="$9"
  local template_mode="${10}"
  local extra_mode="${11}"
  local kv="${12}"
  local safe_name="${family}-${kv}"
  local log_file
  local response_file
  local status="success"
  local sanity="not_run"
  local notes=""
  local prompt_tps=""
  local decode_tps=""
  local kv_log=""
  local args
  local sampler_temp="0.6"
  local sampler_top_p="0.95"
  local sampler_top_k="20"
  if [[ "${family,,}" == gemma* || "${alias,,}" == gemma* || "${repo,,}" == *gemma* ]]; then
    sampler_temp="1.0"
    sampler_top_p="0.95"
    sampler_top_k="64"
  fi

  log_file="$(mktemp "${logs_dir}/${safe_name}.XXXXXX.log")"
  response_file="$(mktemp "${logs_dir}/${safe_name}.XXXXXX.response.json")"
  printf 'START family=%s model=%s kv=%s log=%s\n' "$family" "$alias" "$kv" "$log_file" >&2

  stop_tracked_server
  stop_managed_service

  args=(./build/bin/llama-server)
  add_model_args "$repo" "$quant_mode" "$quant"
  add_mmproj_args "$mmproj"
  args+=(--host "$listen_host" --port "$port" -ngl 999 -c "$ctx" --flash-attn on -ub "$ubatch" -b "$batch")
  args+=(--threads "$(thread_count)" --prio 2 --no-warmup)
  args+=(--temp "$sampler_temp" --top-p "$sampler_top_p" --top-k "$sampler_top_k" --min-p 0.0 --presence-penalty 0.0)
  add_template_args "$template_mode"
  add_extra_args "$extra_mode"
  add_kv_args "$kv"
  args+=(--alias "$alias")

  "${args[@]}" >>"$log_file" 2>&1 &
  server_pid="$!"

  if ! wait_for_models "$alias"; then
    status="timeout"
    notes="server did not become ready"
  else
    sanity="$(sanity_status "$alias" "$response_file" 2>>"$log_file")"
    if [[ "$sanity" != ok ]]; then
      status="error"
      notes="sanity ${sanity}"
    fi
  fi

  stop_tracked_server

  if awk 'BEGIN { found = 1 } /hipMalloc failed|out of memory|OOM|cannot allocate memory|std::bad_alloc/ { found = 0 } END { exit found }' "$log_file"; then
    status="oom"
    notes="OOM detected"
  fi

  prompt_tps="$(last_number_for 'prompt.*tokens per second|prompt.*tok/s|prompt.*t/s' "$log_file")"
  decode_tps="$(last_number_for 'eval.*tokens per second|decode.*tok/s|decode.*t/s' "$log_file")"
  kv_log="$(first_log_match 'KV.*buffer|cache.*type|cache_type|cache-type' "$log_file")"

  if [[ "$status" == success && (-z "$prompt_tps" || -z "$decode_tps") ]]; then
    status="parse_failed"
    notes="missing throughput metrics"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(tsv_clean "$family")" \
    "$(tsv_clean "$alias")" \
    "$(tsv_clean "$kv")" \
    "$(tsv_clean "$ctx")" \
    "$(tsv_clean "$quant")" \
    "$(tsv_clean "$mmproj")" \
    "$(tsv_clean "$status")" \
    "$(tsv_clean "$prompt_tps")" \
    "$(tsv_clean "$decode_tps")" \
    "$(tsv_clean "$kv_log")" \
    "$(tsv_clean "$sanity")" \
    "$(tsv_clean "$notes")"
}

trap restore_service EXIT

capture_service_state
printf 'logs_dir=%s\n' "$logs_dir" >&2
for case_spec in "${cases[@]}"; do
  IFS='|' read -r family repo quant_mode quant alias ctx batch ubatch mmproj template_mode extra_mode <<<"$case_spec"
  for kv in "${kv_modes[@]}"; do
    run_one "$family" "$repo" "$quant_mode" "$quant" "$alias" "$ctx" "$batch" "$ubatch" "$mmproj" "$template_mode" "$extra_mode" "$kv"
  done
done
