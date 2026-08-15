#!/usr/bin/env bash
# Seed the state dir the backend writes to, so a rebuilt host starts with the
# tuned profiles instead of an empty set (routes/profiles.py `_load` returns
# {"families": {}} when the file is absent -- nothing regenerates it).
# Safe to re-run: existing state is never overwritten.
#
# configs/profiles.json is a point-in-time export, not the live copy. The live
# one is /state/profiles.json and it changes on every profile edit; refresh the
# export with `scripts/state-init.sh --export` and commit it. For rolling
# backups of the whole state dir (including snapshots), use scripts/backup.sh.
#
# Usage: scripts/state-init.sh [state-dir]
#        scripts/state-init.sh --export [state-dir]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="$REPO_DIR/configs/profiles.json"

if [[ "${1:-}" == "--export" ]]; then
  shift
  STATE_DIR="${1:-${LOCAL_LLM_STATE_DIR:-$HOME/.local/share/local_llm}}"
  [[ -f "$STATE_DIR/profiles.json" ]] || {
    echo "no $STATE_DIR/profiles.json to export" >&2
    exit 1
  }
  cp "$STATE_DIR/profiles.json" "$SEED"
  echo "exported $STATE_DIR/profiles.json -> $SEED"
  exit 0
fi

STATE_DIR="${1:-${LOCAL_LLM_STATE_DIR:-$HOME/.local/share/local_llm}}"
mkdir -p "$STATE_DIR"

if [[ -e "$STATE_DIR/profiles.json" ]]; then
  echo "keep  $STATE_DIR/profiles.json"
else
  cp "$SEED" "$STATE_DIR/profiles.json"
  echo "seed  $STATE_DIR/profiles.json"
fi

echo
echo "State dir: $STATE_DIR"
echo "Set LOCAL_LLM_STATE_DIR to override."
