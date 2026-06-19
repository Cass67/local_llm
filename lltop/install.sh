#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [--dry-run] [--prefix PATH]

Install lltop to PREFIX/bin/lltop.

Options:
  --dry-run       Print the install target without writing files
  --prefix PATH   Install under PATH instead of $HOME/.local
  -h, --help      Show this help
EOF
}

prefix="${PREFIX:-$HOME/.local}"
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=true
      shift
      ;;
    --prefix)
      if [[ $# -lt 2 ]]; then
        printf 'error: --prefix requires a path\n' >&2
        exit 2
      fi
      prefix="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source_file="$script_dir/lltop"
target_dir="$prefix/bin"
target_file="$target_dir/lltop"

if [[ ! -f "$source_file" ]]; then
  printf 'error: lltop script not found at %s\n' "$source_file" >&2
  exit 1
fi

if [[ "$dry_run" == true ]]; then
  printf 'would install %s to %s\n' "$source_file" "$target_file"
  exit 0
fi

mkdir -p "$target_dir"
cp "$source_file" "$target_file"
chmod 0755 "$target_file"
printf 'installed %s\n' "$target_file"
