#!/usr/bin/env bash
# Seed the bind-mounted config dirs for the coding agents (pi, opencode).
# Safe to re-run: existing config is never overwritten.
#
# Usage: scripts/agents-init.sh [config-dir]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${1:-${AGENTS_CONFIG_DIR:-$HOME/.config/local_llm/agents}}"

mkdir -p "$CONFIG_DIR/pi/agent" "$CONFIG_DIR/opencode" "$CONFIG_DIR/opencode-data" \
  "$CONFIG_DIR/opencode2" "$CONFIG_DIR/opencode2-data"

seed() {
  local src="$1" dest="$2"
  if [[ -e "$dest" ]]; then
    echo "keep  $dest"
  else
    cp "$src" "$dest"
    echo "seed  $dest"
  fi
}

seed "$REPO_DIR/agents/pi-models.json" "$CONFIG_DIR/pi/agent/models.json"
# Without compaction.reserveTokens pi falls back to DEFAULT_COMPACTION_SETTINGS
# (16384), which is too small for one tool loop: the turn walks past
# contextWindow - 4096, where pi clamps max_tokens to 1 and the session dies.
seed "$REPO_DIR/agents/pi-settings.json" "$CONFIG_DIR/pi/agent/settings.json"
seed "$REPO_DIR/agents/opencode.json" "$CONFIG_DIR/opencode/opencode.json"
# v2 reuses v1's XDG paths verbatim, so it gets its own host dirs mounted at the
# same in-container locations. It does not read v1's auth.json: sign in once with
# `opencode2 auth login` (or /connect in the TUI) and the credentials land here.
seed "$REPO_DIR/agents/opencode2.json" "$CONFIG_DIR/opencode2/opencode.json"

echo
echo "Agent config dir: $CONFIG_DIR"
echo "Set AGENTS_CONFIG_DIR in .env to override."
