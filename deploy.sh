#!/usr/bin/env bash
# deploy.sh — push local commits and rebuild on ubt26
set -euo pipefail

REMOTE_HOST="${1:-ubt26}"

echo "=== Pushing to origin ==="
git push

echo "=== Building and deploying on $REMOTE_HOST ==="
ssh "$REMOTE_HOST" "bash -s" <<'EOF'
set -euo pipefail
cd ~/git/local_llm
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
