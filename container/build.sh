#!/usr/bin/env bash
# container/build.sh — build UI, then build container image
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Building Svelte UI ==="
cd "$PROJECT_ROOT/ui"
npm ci
npm run build

echo "=== Building runner image ==="
cd "$PROJECT_ROOT"
docker build -t local-llm-runner:latest -f runner/Dockerfile runner

echo "=== Building management Docker image ==="
cd "$SCRIPT_DIR"
docker compose build

echo "=== Done ==="
echo "Start with: docker compose up -d"
echo "UI at: http://localhost:3100/ui/"
echo "API at: http://localhost:3100/api/health"
