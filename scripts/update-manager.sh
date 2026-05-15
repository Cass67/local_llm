#!/usr/bin/env bash
# update-manager.sh - high-level update helper wired to model-manager and profiles.json.
#
# Usage:
#   update-manager.sh              # check for updates
#   update-manager.sh --candidates # list candidate models
#   update-manager.sh --discover <family>
#   update-manager.sh --status
#
# Delegates to model-manager.sh for lifecycle operations.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

MODEL_MANAGER="$SCRIPT_DIR/model-manager.sh"

ensure_dirs

usage() {
  echo "Usage: update-manager.sh [options]"
  echo ""
  echo "Options:"
  echo "  (no args)            Check for updates (profiles + candidates)"
  echo "  --candidates         List model candidates"
  echo "  --discover <family>  Discover new candidate models for a family"
  echo "  --status             Show overall model lifecycle status"
}

check_updates() {
  echo "LocalLLM Update Status"
  echo "======================"
  echo ""

  # Check profiles.json
  if [[ -f "$PROFILES_JSON" ]]; then
    local count
    count="$(jq '.profiles | length' "$PROFILES_JSON")"
    echo "Profiles in profiles.json: $count"
  else
    echo "profiles.json: MISSING"
  fi

  echo ""
  echo "Model lifecycle (via model-manager):"
  bash "$MODEL_MANAGER" status
}

case "${1:-}" in
  --candidates)
    bash "$MODEL_MANAGER" list-candidates
    ;;
  --discover)
    if [[ -z "${2:-}" ]]; then
      die "Usage: update-manager.sh --discover <family>"
    fi
    bash "$MODEL_MANAGER" discover "$2"
    ;;
  --status)
    bash "$MODEL_MANAGER" status
    ;;
  --help|-h)
    usage
    ;;
  "")
    check_updates
    ;;
  *)
    usage
    exit 1
    ;;
esac