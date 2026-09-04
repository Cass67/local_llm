#!/usr/bin/env bash
# Back up everything that makes this stack work and cannot be rebuilt from git.
#
#   scripts/backup-full.sh                    # to $DEST, keeping $KEEP archives
#   scripts/backup-full.sh --dest /mnt/other --keep 30
#   scripts/backup-full.sh --no-stop          # do not pause open-webui (see below)
#
# Deliberately EXCLUDES:
#   /mnt/hfcache      244G of models -- re-downloadable, and it would dominate
#   /state/runs       benchmark artifacts -- history, not function
#
# Everything here lives on the root disk (nvme0n1), so the destination must be
# another spindle. /mnt/spare is nvme1n1 -- use that.
#
# Needs root to read the docker volume dirs. Run under sudo or via the timer.
# Restore with scripts/restore-full.sh.

set -euo pipefail

OWNER="${LOCAL_LLM_USER:-cass}"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
REPO="${LOCAL_LLM_REPO:-$OWNER_HOME/git/local_llm}"
STATE="${LOCAL_LLM_STATE_DIR:-$OWNER_HOME/.local/share/local_llm}"
AGENTS="${AGENTS_CONFIG_DIR:-$OWNER_HOME/.config/local_llm/agents}"
CFD="$OWNER_HOME/.cloudflared"
VOLUMES="/var/lib/docker/volumes"

DEST="${BACKUP_DEST:-/mnt/spare/local_llm-backups}"
KEEP="${BACKUP_KEEP:-14}"
STOP_WEBUI=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      DEST="$2"
      shift 2
      ;;
    --keep)
      KEEP="$2"
      shift 2
      ;;
    --no-stop)
      STOP_WEBUI=0
      shift
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

[[ $EUID -eq 0 ]] || {
  echo "must run as root (docker volume dirs are root-owned)" >&2
  exit 1
}

TS="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/local_llm-$TS"
mkdir -p "$STAGE"

say() { printf '  %s\n' "$1"; }

echo "== staging =="

{
  echo "created:  $(date -Is)"
  echo "host:     $(hostname)"
  echo "git:      $(git -C "$REPO" log --oneline -1 2>/dev/null || echo 'n/a')"
  echo "excludes: /mnt/hfcache (models), $STATE/runs"
} >"$STAGE/MANIFEST.txt"

# Secrets and credentials -- the whole reason this archive must not be casually synced.
if [[ -f "$REPO/.env" ]]; then
  install -m 0600 "$REPO/.env" "$STAGE/env"
  say "env"
fi
if [[ -d "$CFD" ]]; then
  mkdir -p "$STAGE/cloudflared"
  # The tunnel credentials json: lose it and the tunnel must be recreated.
  find "$CFD" -maxdepth 1 -type f -exec cp -p {} "$STAGE/cloudflared/" \;
  say "cloudflared credentials"
fi

# Agent config: opencode/opencode2 auth.json plus pi and opencode session history.
if [[ -d "$AGENTS" ]]; then
  tar -C "$(dirname "$AGENTS")" -cf "$STAGE/agents.tar" "$(basename "$AGENTS")"
  say "agents config ($(du -sh "$STAGE/agents.tar" | cut -f1))"
fi

# State minus runs/: profiles.json, 40+ profile snapshots, speed-bench, backups.
if [[ -d "$STATE" ]]; then
  tar -C "$(dirname "$STATE")" --exclude="$(basename "$STATE")/runs" \
    -cf "$STAGE/state.tar" "$(basename "$STATE")"
  say "state ($(du -sh "$STAGE/state.tar" | cut -f1))"
fi

# Postgres must be dumped, never file-copied: a live data dir copies torn.
if docker ps --format '{{.Names}}' | grep -qx local-llm-postgres; then
  docker exec local-llm-postgres pg_dump -U langfuse -d langfuse >"$STAGE/langfuse.sql"
  say "langfuse.sql ($(du -sh "$STAGE/langfuse.sql" | cut -f1))"
fi

# Open WebUI is SQLite with no sqlite3 binary in the image, so there is no
# online .backup path -- pause the container for a consistent copy instead.
WEBUI_VOL="$VOLUMES/local_llm_open-webui/_data"
if [[ -d "$WEBUI_VOL" ]]; then
  RESTART=0
  if [[ $STOP_WEBUI -eq 1 ]] && docker ps --format '{{.Names}}' | grep -qx open-webui; then
    docker stop open-webui >/dev/null && RESTART=1
  fi
  tar -C "$(dirname "$WEBUI_VOL")" -cf "$STAGE/open-webui.tar" "$(basename "$WEBUI_VOL")"
  [[ $RESTART -eq 1 ]] && docker start open-webui >/dev/null
  say "open-webui ($(du -sh "$STAGE/open-webui.tar" | cut -f1))"
fi

echo "== writing archive =="
mkdir -p "$DEST"
ARCHIVE="$DEST/local_llm-$TS.tar.zst"
tar -C "$WORK" -c "local_llm-$TS" | zstd -T0 -3 -q -o "$ARCHIVE"
chmod 0600 "$ARCHIVE"
chown "$OWNER":"$OWNER" "$ARCHIVE" 2>/dev/null || true
say "$ARCHIVE ($(du -sh "$ARCHIVE" | cut -f1))"

echo "== retention (keep $KEEP) =="
mapfile -t OLD < <(find "$DEST" -maxdepth 1 -name 'local_llm-*.tar.zst' -printf '%T@ %p\n' |
  sort -rn | tail -n "+$((KEEP + 1))" | cut -d' ' -f2-)
if [[ ${#OLD[@]} -eq 0 ]]; then
  say "nothing to prune"
else
  for f in "${OLD[@]}"; do
    rm -f "$f"
    say "pruned $(basename "$f")"
  done
fi

echo
echo "Done. $(find "$DEST" -maxdepth 1 -name 'local_llm-*.tar.zst' | wc -l) archive(s) in $DEST"
