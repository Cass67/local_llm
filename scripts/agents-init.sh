#!/usr/bin/env bash
# Seed the bind-mounted config dirs for the coding agents (pi, opencode).
# Safe to re-run: existing config is never overwritten.
#
# Usage: scripts/agents-init.sh [config-dir]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${1:-${AGENTS_CONFIG_DIR:-$HOME/.config/local_llm/agents}}"

mkdir -p "$CONFIG_DIR/pi/agent" "$CONFIG_DIR/opencode" "$CONFIG_DIR/opencode-data"

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
seed "$REPO_DIR/agents/opencode.json" "$CONFIG_DIR/opencode/opencode.json"

echo
echo "Agent config dir: $CONFIG_DIR"
echo "Set AGENTS_CONFIG_DIR in .env to override."
