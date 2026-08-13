#!/usr/bin/env bash
# deploy.sh — push local commits and rebuild on ubt26
set -euo pipefail

REMOTE_HOST="${1:-ubt26}"

echo "=== Pushing to origin ==="
git push

echo "=== Building and deploying on $REMOTE_HOST ==="
ssh "$REMOTE_HOST" "FORCE_DEPLOY=${FORCE_DEPLOY:-0} bash -s" <<'EOF'
set -euo pipefail
cd ~/git/local_llm
# Recreating mgmt kills whatever it is running: job state lives in memory and any
# docker client is its child. A llama.cpp rebuild dies mid-compile, a SPEED-Bench
# sweep loses its rows. Check every endpoint that reports long-running work --
# a new kind of job needs a line here too.
if [ "$FORCE_DEPLOY" != "1" ]; then
  # Two shapes in the wild: a job dict with "running": true, and job lists whose
  # entries carry "status": "running".
  for endpoint in update/build/status speed-bench/status benchmark/jobs bakeoff/jobs sweep; do
    if curl -sf --max-time 5 "localhost:3100/api/$endpoint" |
       grep -Eq '"running": *true|"status": *"running"'; then
      echo "!! $endpoint reports work in flight -- wait, or rerun with FORCE_DEPLOY=1" >&2
      exit 1
    fi
  done
fi
# ui-dist is tracked (the image copies it from the build context, and nothing in
# the image build runs npm) but this script rebuilds it in place, so the remote
# checkout is always dirty there and the pull would abort. It is regenerated
# below, so discarding it costs nothing.
git checkout -- container/ui-dist && git clean -fdq container/ui-dist
git pull
cd ui && npm install --silent && npm run build
cd ..
docker rm -f searxng 2>/dev/null || true
docker compose build
docker compose up -d
echo "=== Done ==="
EOF
