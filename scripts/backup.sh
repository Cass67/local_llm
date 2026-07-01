#!/usr/bin/env bash
# Backup or restore local_llm state. Uses rsync if available, falls back to tar.
set -euo pipefail

STATE_DIR="${LOCAL_LLM_STATE_DIR:-$HOME/.local/share/local_llm}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface/hub}"
BACKUP_DIR="${1:-$HOME/local_llm_backup}"

backup() {
  mkdir -p "$BACKUP_DIR"
  local ts
  ts=$(date +%Y%m%d_%H%M%S)
  local backup_path="$BACKUP_DIR/state_$ts"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --progress "$STATE_DIR/" "$backup_path/state/"
    rsync -a --progress "$HF_CACHE_DIR/" "$backup_path/hf_cache/" 2>/dev/null || true
  else
    mkdir -p "$backup_path"
    tar -czf "$backup_path/state.tar.gz" -C "$STATE_DIR" .
    tar -czf "$backup_path/hf_cache.tar.gz" -C "$(dirname "$HF_CACHE_DIR")" "$(basename "$HF_CACHE_DIR")" 2>/dev/null || true
  fi

  echo "Backup complete: $backup_path"
}

restore() {
  local backup_path="$1"
  if [[ ! -d "$backup_path" ]]; then
    echo "Backup directory not found: $backup_path"
    exit 1
  fi

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --progress "$backup_path/state/" "$STATE_DIR/"
    # HF cache: restore only if explicitly requested, otherwise skip
    if [[ -d "$backup_path/hf_cache" ]]; then
      echo "Skipping HF cache restore. Run manually if needed:"
      echo "rsync -a $backup_path/hf_cache/ $HF_CACHE_DIR/"
    fi
  else
    tar -xzf "$backup_path/state.tar.gz" -C "$STATE_DIR"
  fi

  echo "State restored: $STATE_DIR"
}

case "${2:-backup}" in
  backup) backup ;;
  restore)
    if [[ -n "$3" ]]; then
      restore "$3"
    else
      echo "Usage: $0 <backup_dir> restore"
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 <backup_dir> [backup|restore]"
    exit 1
    ;;
esac
