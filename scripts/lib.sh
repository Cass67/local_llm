#!/usr/bin/env bash
# lib.sh - shared utilities for oc-local tooling.
# Sourced by: oc-local, model-manager, model-discovery, update-manager, hardware-analyzer.

set -euo pipefail

# Determine install layout:
# - SCRIPT_DIR: directory where lib.sh lives
# - CONFIG_DIR: ~/.local/share/local_llm/config
# - RUNS_DIR: ~/.local/share/local_llm/runs
SCRIPT_DIR="${LIB_SH_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
CONFIG_DIR="${LOCAL_LLM_CONFIG_DIR:-$HOME/.local/share/local_llm/config}"
RUNS_DIR="${LOCAL_LLM_RUNS_DIR:-$HOME/.local/share/local_llm/runs}"
PROFILES_JSON="${CONFIG_DIR}/profiles.json"

# Runtime
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$HOME/local_llm/llama.cpp}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$LLAMA_CPP_DIR/llama-server}"
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-$HOME/.cache/local_llm/models}"
HF_TOKEN="${HF_TOKEN:-}"
REMOTE_USER="${REMOTE_USER:-$(whoami)}"
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Colors
if [[ -t 1 ]]; then
  BOLD="$(tput bold 2>/dev/null || true)"
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  YELLOW="$(tput setaf 3 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
else
  BOLD=""
  GREEN=""
  YELLOW=""
  RED=""
  RESET=""
fi

log_info() {
  echo "${GREEN}[INFO]${RESET} $*" >&2
}

log_warn() {
  echo "${YELLOW}[WARN]${RESET} $*" >&2
}

log_error() {
  echo "${RED}[ERROR]${RESET} $*" >&2
}

die() {
  log_error "$@"
  exit 1
}

ensure_dirs() {
  mkdir -p "$RUNS_DIR" "$MODEL_CACHE_DIR"
}

# JSON helper - requires jq
require_jq() {
  command -v jq &>/dev/null || die "jq is required but not installed."
}

# Read a profile from profiles.json by family:profile
# Usage: get_profile "qwen:reliable"
get_profile() {
  local key="$1"
  require_jq
  [[ -f "$PROFILES_JSON" ]] || die "profiles.json not found at $PROFILES_JSON"
  jq -r --arg k "$key" '.profiles[$k] // empty' "$PROFILES_JSON"
}

# Get family metadata
get_family() {
  local family="$1"
  require_jq
  jq -r --arg f "$family" '.families[$f] // empty' "$PROFILES_JSON"
}

# List all profile keys
list_profiles() {
  require_jq
  jq -r '.profiles | keys[]' "$PROFILES_JSON"
}

# Build llama-server command from profile JSON (on stdin)
# Usage: get_profile "qwen:reliable" | build_llama_cmd <extra-args>
build_llama_cmd() {
  local profile_json
  profile_json="$(cat)"
  local model_name context ngl batch ubatch mmproj reasoning_effort output_limit
  local extra_args
  extra_args=("$@")

  model_name="$(echo "$profile_json" | jq -r '.model_name')"
  context="$(echo "$profile_json" | jq -r '.context')"
  ngl="$(echo "$profile_json" | jq -r '.ngl')"
  batch="$(echo "$profile_json" | jq -r '.batch')"
  ubatch="$(echo "$profile_json" | jq -r '.ubatch')"
  mmproj="$(echo "$profile_json" | jq -r '.mmproj')"
  reasoning_effort="$(echo "$profile_json" | jq -r '.reasoning_effort // "none"')"
  output_limit="$(echo "$profile_json" | jq -r '.output_limit // 4096')"

  local model_path
  model_path="$(echo "$profile_json" | jq -r '.model_path // empty')"
  if [[ -z "$model_path" ]]; then
    local quant
    quant="$(echo "$profile_json" | jq -r '.quant')"
    model_path="$MODEL_CACHE_DIR/${model_name}-${quant}.gguf"
  fi

  local cmd
  cmd=(
    "$LLAMA_SERVER_BIN"
    "--model" "$model_path"
    "--ctx-size" "$context"
    "--ngl" "$ngl"
    "--batch" "$batch"
    "--ubatch" "$ubatch"
    "--host" "127.0.0.1"
    "--port" "8080"
    "--threads" "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
  )

  # mlock if requested
  local has_mlock
  has_mlock="$(echo "$profile_json" | jq -r '.extra_flags // [] | map(select(. == "--mlock")) | any')"
  if [[ "$has_mlock" == "true" ]]; then
    cmd+=("--mlock")
  fi

  # multimodal projector
  if [[ "$mmproj" == "enabled" ]]; then
    local mmproj_path
    mmproj_path="$(echo "$profile_json" | jq -r '.mmproj_path // empty')"
    if [[ -n "$mmproj_path" ]]; then
      cmd+=("--mmproj" "$mmproj_path")
    fi
  fi

  # reasoning effort (for reasoning models)
  if [[ "$reasoning_effort" != "none" && -n "$reasoning_effort" ]]; then
    cmd+=("--reasoning-effort" "$reasoning_effort")
  fi

  # extra user args
  if [[ ${#extra_args[@]} -gt 0 ]]; then
    cmd+=("${extra_args[@]}")
  fi

  # output as single-line command (caller may eval)
  # join array into one line; elements are already simple tokens/paths
  local IFS=" "
  echo "${cmd[*]}"
}

# Run a command on the remote host via SSH.
# Usage: ssh_run "uname -a"
ssh_run() {
  [[ -n "$REMOTE_HOST" ]] || die "REMOTE_HOST not set; cannot ssh_run"
  local cmd="$*"
  local base_ssh_cmd=(
    ssh
    "${REMOTE_SSH_OPTS:-}"
    "${REMOTE_USER}@${REMOTE_HOST}"
  )

  # Remove empty elements (e.g., when REMOTE_SSH_OPTS is unset)
  local clean_ssh_cmd=()
  for part in "${base_ssh_cmd[@]}"; do
    [[ -n "$part" ]] && clean_ssh_cmd+=("$part")
  done

  "${clean_ssh_cmd[@]}" "$cmd"
}

# Wait for llama-server to respond (HTTP GET /)
wait_for_api() {
  local port="${1:-8080}"
  local max_attempts="${2:-30}"
  local attempt=0
  while ((attempt < max_attempts)); do
    if curl -sf "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((attempt++))
  done
  return 1
}

# Write run metadata JSON.
# Usage: write_run_metadata "qwen:reliable" "start"
write_run_metadata() {
  local profile_key="$1"
  local phase="$2" # start | stop | error
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  local run_file="$RUNS_DIR/${profile_key//:/_}_$(date -u +"%Y%m%dT%H%M%S").json"

  local meta
  meta=$(jq -n \
    --arg profile "$profile_key" \
    --arg phase "$phase" \
    --arg ts "$ts" \
    '{profile: $profile, phase: $phase, timestamp: $ts}')

  if [[ "$phase" == "start" ]]; then
    echo "$meta" >"$run_file"
    echo "$run_file"
  else
    # if file exists, patch it; otherwise create minimal
    if [[ -f "$run_file" ]]; then
      jq --arg phase "$phase" --arg ts "$ts" '.phase = $phase | .stop_time = $ts' "$run_file" >"${run_file}.tmp"
      mv "${run_file}.tmp" "$run_file"
    else
      echo "$meta" >"$run_file"
    fi
  fi
}
