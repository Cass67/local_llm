#!/usr/bin/env bash
# scripts/migrate-to-container.sh
# Migrate local_llm state from Mac client to ubt26 container.
# Run from Mac, requires SSH access to ubt26.
set -euo pipefail

HOST="${1:-ubt26}"
REMOTE_SHARE="${2:-~/.local/share/local_llm}"

echo "=== Migrating local_llm state to $HOST ==="

LOCAL_RUNS="$HOME/.local/share/local_llm/runs"

if [[ ! -d "$LOCAL_RUNS" ]]; then
  echo "No local runs directory found at $LOCAL_RUNS"
  echo "Nothing to migrate."
  exit 0
fi

# Backup remote state if it exists
echo "Backing up remote state..."
ssh "$HOST" "
    if [[ -d $REMOTE_SHARE/runs ]]; then
        cp -r $REMOTE_SHARE/runs $REMOTE_SHARE/runs.bak.\$(date +%Y%m%d-%H%M%S)
        echo 'Remote backup created.'
    else
        mkdir -p $REMOTE_SHARE
        echo 'Created remote share directory.'
    fi
"

# Copy accepted metadata
if [[ -d "$LOCAL_RUNS/accepted" ]]; then
  echo "Copying accepted metadata..."
  ssh "$HOST" "mkdir -p $REMOTE_SHARE/runs/accepted"
  scp "$LOCAL_RUNS/accepted"/*.json "$HOST:$REMOTE_SHARE/runs/accepted/"
fi

# Copy launchers
if [[ -d "$LOCAL_RUNS/launchers" ]]; then
  echo "Copying launchers..."
  ssh "$HOST" "mkdir -p $REMOTE_SHARE/runs/launchers"
  scp "$LOCAL_RUNS/launchers"/*.sh "$HOST:$REMOTE_SHARE/runs/launchers/"
  ssh "$HOST" "chmod +x $REMOTE_SHARE/runs/launchers/*.sh"
fi

# Copy config
if [[ -f "$LOCAL_RUNS/config.json" ]]; then
  echo "Copying config..."
  scp "$LOCAL_RUNS/config.json" "$HOST:$REMOTE_SHARE/runs/config.json"
fi

echo ""
echo "=== Migration complete ==="
echo "Remote state: $HOST:$REMOTE_SHARE/runs/"
echo ""
echo "Next steps on $HOST:"
echo "  1. cd ~/local_llm/container"
echo "  2. ./build.sh"
echo "  3. docker compose up -d"
echo "  4. Verify: curl http://127.0.0.1:3100/api/health"
echo "  5. Update Caddyfile and restart caddy"
