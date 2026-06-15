#!/usr/bin/env bash
# Build (and optionally run) the local-llm-runner image.
#
# Usage:
#   ./build.sh            # build only
#   ./build.sh --run      # build then run with --help
#   ./build.sh --no-cache # force fresh llama.cpp clone

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="local-llm-runner:latest"
BUILD_ARGS=()
RUN_AFTER=false

for arg in "$@"; do
  case "$arg" in
    --no-cache) BUILD_ARGS+=(--no-cache) ;;
    --run) RUN_AFTER=true ;;
    *)
      echo "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

# Linux needs --network host so apt-get can resolve DNS inside the build container.
NETWORK_FLAG=()
if [[ "$(uname)" == "Linux" ]]; then
  NETWORK_FLAG=(--network host)
fi

echo "Building $IMAGE ..."
docker build "${NETWORK_FLAG[@]}" "${BUILD_ARGS[@]}" -t "$IMAGE" "$SCRIPT_DIR"

echo ""
docker run --rm "$IMAGE" llama-server --version

if $RUN_AFTER; then
  echo ""
  docker run --rm "$IMAGE" llama-server --help
fi
