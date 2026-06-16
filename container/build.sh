#!/usr/bin/env bash
# container/build.sh — build UI, then build container image
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Building Svelte UI ==="
cd "$PROJECT_ROOT/ui"
npm ci
npm run build

echo "=== Building runner images ==="
cd "$PROJECT_ROOT"
for backend in vulkan rocm cuda; do
  docker build -t "local-llm-runner-${backend}:latest" -f "runner/${backend}/Dockerfile" "runner/${backend}"
done

echo "=== Building management Docker image ==="
cd "$SCRIPT_DIR"
docker compose build

echo "=== Done ==="
echo "Start with: docker compose up -d"
echo "UI at: http://localhost:3100/ui/"
echo "API at: http://localhost:3100/api/health"
