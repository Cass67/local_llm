#!/usr/bin/env bash
# Restore an archive made by scripts/backup-full.sh.
#
#   scripts/restore-full.sh <archive>                 # list contents, change nothing
#   scripts/restore-full.sh <archive> --yes           # restore everything
#   scripts/restore-full.sh <archive> --yes --only state,env
#   scripts/restore-full.sh <archive> --yes --into /tmp/probe   # dry restore to a scratch dir
#
# Components: env, cloudflared, agents, state, langfuse, open-webui
#
# Nothing is written without --yes. Existing targets are moved aside to
# <path>.pre-restore-<ts> rather than overwritten, so a wrong restore is
# recoverable. --into redirects file components to a scratch tree, which is the
# safe way to inspect an archive without touching live state.

set -euo pipefail

ARCHIVE="${1:-}"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || {
  echo "usage: $0 <archive> [--yes] [--only a,b] [--into DIR]" >&2
  exit 2
}
shift

OWNER="${LOCAL_LLM_USER:-cass}"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
REPO="${LOCAL_LLM_REPO:-$OWNER_HOME/git/local_llm}"
STATE="${LOCAL_LLM_STATE_DIR:-$OWNER_HOME/.local/share/local_llm}"
AGENTS="${AGENTS_CONFIG_DIR:-$OWNER_HOME/.config/local_llm/agents}"
CFD="$OWNER_HOME/.cloudflared"
VOLUMES="/var/lib/docker/volumes"

APPLY=0
ONLY="env,cloudflared,agents,state,langfuse,open-webui"
INTO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      APPLY=1
      shift
      ;;
    --only)
      ONLY="$2"
      shift 2
      ;;
    --into)
      INTO="$2"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

wants() { [[ ",$ONLY," == *",$1,"* ]]; }
TS="$(date +%Y%m%d-%H%M%S)"
say() { printf '  %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
zstd -dq -c "$ARCHIVE" | tar -C "$WORK" -x
ROOT="$(find "$WORK" -maxdepth 1 -mindepth 1 -type d | head -1)"

echo "== archive =="
sed 's/^/  /' "$ROOT/MANIFEST.txt" 2>/dev/null || say "(no manifest)"
echo "== contents =="
(cd "$ROOT" && du -sh -- * | sed 's/^/  /')

if [[ $APPLY -eq 0 ]]; then
  echo
  echo "Nothing written. Re-run with --yes to restore (add --into DIR to stage it safely first)."
  exit 0
fi

[[ $EUID -eq 0 || -n "$INTO" ]] || {
  echo "must run as root to restore in place" >&2
  exit 1
}

# Move aside rather than overwrite, so a mistaken restore can be undone.
preserve() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  mv "$path" "$path.pre-restore-$TS"
  say "kept old -> $(basename "$path").pre-restore-$TS"
}
target() { [[ -n "$INTO" ]] && echo "$INTO/$1" || echo "$2"; }

echo "== restoring =="
[[ -n "$INTO" ]] && {
  mkdir -p "$INTO"
  say "staging into $INTO (live state untouched)"
}

if wants env && [[ -f "$ROOT/env" ]]; then
  d="$(target env "$REPO/.env")"
  mkdir -p "$(dirname "$d")"
  preserve "$d"
  install -m 0600 "$ROOT/env" "$d"
  say "env -> $d"
fi

if wants cloudflared && [[ -d "$ROOT/cloudflared" ]]; then
  d="$(target cloudflared "$CFD")"
  mkdir -p "$d"
  cp -p "$ROOT"/cloudflared/* "$d"/
  say "cloudflared -> $d"
fi

if wants agents && [[ -f "$ROOT/agents.tar" ]]; then
  d="$(target agents "$AGENTS")"
  if [[ -n "$INTO" ]]; then
    mkdir -p "$d"
    tar -C "$d" -xf "$ROOT/agents.tar"
  else
    preserve "$d"
    tar -C "$(dirname "$d")" -xf "$ROOT/agents.tar"
  fi
  say "agents -> $d"
fi

if wants state && [[ -f "$ROOT/state.tar" ]]; then
  d="$(target state "$STATE")"
  if [[ -n "$INTO" ]]; then
    mkdir -p "$d"
    tar -C "$d" -xf "$ROOT/state.tar"
  else
    preserve "$d"
    tar -C "$(dirname "$d")" -xf "$ROOT/state.tar"
  fi
  say "state -> $d  (runs/ was never archived)"
fi

if wants open-webui && [[ -f "$ROOT/open-webui.tar" ]]; then
  if [[ -n "$INTO" ]]; then
    mkdir -p "$INTO/open-webui"
    tar -C "$INTO/open-webui" -xf "$ROOT/open-webui.tar"
    say "open-webui -> $INTO/open-webui"
  else
    docker stop open-webui >/dev/null 2>&1 || true
    preserve "$VOLUMES/local_llm_open-webui/_data"
    tar -C "$VOLUMES/local_llm_open-webui" -xf "$ROOT/open-webui.tar"
    docker start open-webui >/dev/null 2>&1 || true
    say "open-webui volume restored"
  fi
fi

if wants langfuse && [[ -f "$ROOT/langfuse.sql" ]]; then
  if [[ -n "$INTO" ]]; then
    cp "$ROOT/langfuse.sql" "$INTO/"
    say "langfuse.sql -> $INTO (not loaded)"
  elif docker ps --format '{{.Names}}' | grep -qx local-llm-postgres; then
    # Drop and recreate: pg_dump output is not idempotent against a populated db.
    docker exec -i local-llm-postgres psql -U langfuse -d postgres \
      -c "DROP DATABASE IF EXISTS langfuse WITH (FORCE);" -c "CREATE DATABASE langfuse OWNER langfuse;" >/dev/null
    docker exec -i local-llm-postgres psql -U langfuse -d langfuse <"$ROOT/langfuse.sql" >/dev/null
    say "langfuse database reloaded"
  else
    say "SKIPPED langfuse: local-llm-postgres is not running"
  fi
fi

echo
echo "Done. Restart the stack if you restored state or env:  ./deploy.sh"
