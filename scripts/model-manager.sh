#!/usr/bin/env bash
# model-manager.sh - manage model lifecycle: candidate -> benchmarked -> accepted -> wired.
#
# Usage:
#   model-manager discover [family]
#   model-manager list-candidates
#   model-manager select <family> <hf_repo> <quant>
#   model-manager benchmark <family:candidate-id>
#   model-manager accept <family:candidate-id>
#   model-manager status [family]
#
# Notes:
# - Metadata stored in:
#   - configs/candidates.json
#   - runs/benchmarks/<id>.json
# - On accept, model is wired into profiles.json as a new profile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
source "$SCRIPT_DIR/lib.sh"

CANDIDATES_JSON="$CONFIG_DIR/candidates.json"
BENCHMARKS_DIR="$RUNS_DIR/benchmarks"

ensure_dirs
mkdir -p "$BENCHMARKS_DIR"
require_jq

# Ensure candidates.json exists
if [[ ! -f "$CANDIDATES_JSON" ]]; then
  echo '{}' | jq '.' > "$CANDIDATES_JSON"
fi

# Subcommands

cmd_discover() {
  local family="${1:-}"
  if [[ -z "$family" ]]; then
    log_info "Usage: model-manager discover [family]"
    log_info "Example: model-manager discover qwen"
    return
  fi

  # Validate family
  local fam
  fam="$(get_family "$family")"
  if [[ -z "$fam" ]]; then
    die "Unknown family: $family"
  fi

  log_info "Discovery for family: $family"
  log_info "This should call model-search.py or HuggingFace API to list candidate GGUFs."
  log_info "For now, this is a scaffold."
  log_info "TODO: integrate model-search.py and write candidates to $CANDIDATES_JSON"
}

cmd_list_candidates() {
  local entries
  entries="$(jq -r 'to_entries[] | .key' "$CANDIDATES_JSON" 2>/dev/null || true)"
  if [[ -z "$entries" ]]; then
    log_info "No candidates recorded."
    return
  fi

  echo "Candidates:"
  echo "$entries" | while IFS= read -r id; do
    local summary
    summary="$(jq -r --arg id "$id" '.[$id] | "\(.family):\(.quant) from \(.hf_repo) status=\(.status)"' "$CANDIDATES_JSON")"
    echo "  $summary"
  done
}

cmd_select() {
  local family="$1"
  local hf_repo="$2"
  local quant="$3"

  # Validate family
  get_family "$family" >/dev/null || die "Unknown family: $family"

  local id
  id="${family}_$(date -u +%Y%m%d%H%M%S)"

  # Upsert candidate
  local tmp
  tmp="$(jq \
    --arg id "$id" \
    --arg family "$family" \
    --arg hf_repo "$hf_repo" \
    --arg quant "$quant" \
    '.[$id] = {
        family: $family,
        hf_repo: $hf_repo,
        quant: $quant,
        status: "candidate",
        created_at: (now | todate)
      }' "$CANDIDATES_JSON")"
  echo "$tmp" > "$CANDIDATES_JSON"

  log_info "Candidate created: $id"
  log_info "Details: family=$family hf_repo=$hf_repo quant=$quant"
}

cmd_benchmark() {
  local key="$1"
  # Expect family:candidate-id or similar; for now treat as candidate ID.
  local candidate_id
  candidate_id="$(echo "$key" | cut -d: -f2)"

  if [[ -z "$candidate_id" ]]; then
    die "Usage: model-manager benchmark <family:candidate-id>"
  fi

  local entry
  entry="$(jq -r --arg id "$candidate_id" '.[$id] // empty' "$CANDIDATES_JSON")"
  if [[ -z "$entry" ]]; then
    die "Unknown candidate: $candidate_id"
  fi

  log_info "Benchmark for candidate: $candidate_id"
  log_info "TODO: actually run benchmark (e.g., llama-bench or custom prompt set)."
  log_info "For now, mark as 'benchmarked' with placeholder metrics."

  local bench_file="$BENCHMARKS_DIR/${candidate_id}.json"
  jq -n \
    --arg id "$candidate_id" \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    '{
        candidate_id: $id,
        timestamp: $ts,
        tokens_per_sec: 0,
        latency_p50: 0,
        latency_p95: 0,
        quality_score: 0,
        notes: "placeholder"
      }' > "$bench_file"

  # Update status
  local tmp
  tmp="$(jq --arg id "$candidate_id" '.[$id].status = "benchmarked"' "$CANDIDATES_JSON")"
  echo "$tmp" > "$CANDIDATES_JSON"

  log_info "Benchmark recorded at: $bench_file"
}

cmd_accept() {
  local key="$1"
  local candidate_id
  candidate_id="$(echo "$key" | cut -d: -f2)"

  if [[ -z "$candidate_id" ]]; then
    die "Usage: model-manager accept <family:candidate-id>"
  fi

  local entry
  entry="$(jq -r --arg id "$candidate_id" '.[$id] // empty' "$CANDIDATES_JSON")"
  if [[ -z "$entry" ]]; then
    die "Unknown candidate: $candidate_id"
  fi

  local family hf_repo quant
  family="$(echo "$entry" | jq -r '.family')"
  hf_repo="$(echo "$entry" | jq -r '.hf_repo')"
  quant="$(echo "$entry" | jq -r '.quant')"

  # Generate a profile key: family:accepted-<short-id>
  local short_id
  short_id="$(echo "$candidate_id" | rev | cut -d_ -f1 | rev)"
  local profile_key="${family}:accepted-${short_id}"

  # Add profile to profiles.json
  local tmp
  tmp="$(jq \
    --arg pk "$profile_key" \
    --arg fam "$family" \
    --arg hf "$hf_repo" \
    --arg q "$quant" \
    '.profiles[$pk] = {
        family: $fam,
        model_name: ($fam + "-" + $q),
        hf_repo: $hf,
        quant: $q,
        context: 32768,
        ngl: 999,
        batch: 256,
        ubatch: 256,
        mmproj: "none",
        reasoning_effort: "none",
        extra_flags: [],
        output_limit: 4096
      }' "$PROFILES_JSON")"
  echo "$tmp" > "$PROFILES_JSON"

  # Update candidate status
  local ctmp
  ctmp="$(jq --arg id "$candidate_id" '.[$id].status = "accepted"' "$CANDIDATES_JSON")"
  echo "$ctmp" > "$CANDIDATES_JSON"

  log_info "Candidate accepted and wired into profiles.json as: $profile_key"
}

cmd_status() {
  local family="${1:-}"
  if [[ -n "$family" ]]; then
    log_info "Status for family: $family"
    jq -r --arg f "$family" '
      to_entries[]
      | select(.value.family == $f)
      | "\(.key) \(.value.status) (\(.value.hf_repo))"
    ' "$CANDIDATES_JSON" 2>/dev/null || log_info "No candidates for family: $family"
  else
    log_info "Overall model lifecycle status:"
    # Count by status
    jq -r '
      to_entries
      | group_by(.value.status)
      | map({status: (.[0].value.status), count: length})
      | .[]
      | "\(.status): \(.count)"
    ' "$CANDIDATES_JSON" 2>/dev/null || log_info "No candidates."
  fi
}

# Dispatch

case "${1:-}" in
  discover) shift; cmd_discover "$@" ;;
  list-candidates) cmd_list_candidates ;;
  select) shift; cmd_select "$@" ;;
  benchmark) shift; cmd_benchmark "$@" ;;
  accept) shift; cmd_accept "$@" ;;
  status) shift; cmd_status "$@" ;;
  *)
    echo "Usage: model-manager {discover|list-candidates|select|benchmark|accept|status} [args...]"
    exit 1
    ;;
esac
