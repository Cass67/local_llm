#!/usr/bin/env bash
set -euo pipefail

remote_host="${OC_LOCAL_REMOTE_HOST:-ubt26}"
remote_dir="${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}"
bench_dir="$remote_dir/bench-heretic-context"

ssh "$remote_host" 'bash -s' -- "$bench_dir" "$remote_dir" <<'REMOTE'
set -euo pipefail
bench_dir="$1"
remote_dir="$2"
mkdir -p "$bench_dir" "$remote_dir/templates"
test -f "$remote_dir/templates/qwen36-opencode.jinja"
REMOTE

scp "scripts/bench-heretic-context-remote.sh" "$remote_host:$bench_dir/run.sh"
ssh "$remote_host" 'bash -s' -- "$bench_dir" <<'REMOTE'
set -euo pipefail
bench_dir="$1"
chmod +x "$bench_dir/run.sh"
"$bench_dir/run.sh"
REMOTE

scp "$remote_host:$bench_dir/results.csv" ./heretic-context-results.csv
