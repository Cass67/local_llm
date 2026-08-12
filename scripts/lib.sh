#!/usr/bin/env bash
# lib.sh - shared utilities for oc-local tooling.
# Sourced by: oc-local, model-manager, model-discovery, update-manager, hardware-analyzer.
#
# This is a sourced library: most vars below are consumed by the scripts that
# source it, so shellcheck cannot see their uses.
# shellcheck disable=SC2034

set -euo pipefail

# Determine install layout:
# - SCRIPT_DIR: directory where lib.sh lives
# - STATE_DIR: ~/.local/share/local_llm (mounted as /state in the containers)
# - CONFIG_DIR: ~/.local/share/local_llm/config
# - RUNS_DIR: ~/.local/share/local_llm/runs
SCRIPT_DIR="${LIB_SH_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
STATE_DIR="${LOCAL_LLM_STATE_DIR:-$HOME/.local/share/local_llm}"
CONFIG_DIR="${LOCAL_LLM_CONFIG_DIR:-$STATE_DIR/config}"
RUNS_DIR="${LOCAL_LLM_RUNS_DIR:-$STATE_DIR/runs}"
# Single source of truth for profiles: the state dir the backend writes to
# (container/backend/config.py PROFILES_CONFIG). There is no repo-side seed.
PROFILES_JSON="${LOCAL_LLM_PROFILES_JSON:-$STATE_DIR/profiles.json}"

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

# Run a command on the remote host via SSH.
# Usage: ssh_run "uname -a"
ssh_run() {
  [[ -n "$REMOTE_HOST" ]] || die "REMOTE_HOST not set; cannot ssh_run"
  local remote_cmd="$*"
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

  "${clean_ssh_cmd[@]}" "$remote_cmd"
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
  local run_file
  run_file="$RUNS_DIR/${profile_key//:/_}_$(date -u +"%Y%m%dT%H%M%S").json"

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
