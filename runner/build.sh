#!/usr/bin/env bash
# Build (and optionally run) a local-llm-runner backend image.
#
# Usage:
#   ./build.sh <vulkan|rocm|cuda>            # build only
#   ./build.sh <vulkan|rocm|cuda> --run      # build then run with --help
#   ./build.sh <vulkan|rocm|cuda> --no-cache # force fresh llama.cpp clone

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="${1:-}"
case "$BACKEND" in
  vulkan | vulkanqwen4exp | rocm | cuda | rocmfp4 | rocmdflash | rocmdflash2 | rocmfork | rocmqwen4exp | rocmqwen4exp2 | rocmmain | rocmmainmtp | rocmunsloth | rocmunslothsrc) ;;
  *)
    echo "Usage: $0 <vulkan|vulkanqwen4exp|rocm|cuda|rocmfp4|rocmdflash|rocmdflash2|rocmfork|rocmqwen4exp|rocmqwen4exp2|rocmmain|rocmmainmtp|rocmunsloth|rocmunslothsrc> [--run] [--no-cache]"
    exit 1
    ;;
esac
shift

IMAGE="local-llm-runner-${BACKEND}:latest"
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
docker build "${NETWORK_FLAG[@]}" "${BUILD_ARGS[@]}" -t "$IMAGE" "$SCRIPT_DIR/$BACKEND"

echo ""
docker run --rm "$IMAGE" llama-server --version

# Every runner ships llama-perplexity so the ppl harness can run against the same
# image being measured. A new backend that forgets it fails here, not weeks later.
if ! docker run --rm --entrypoint test "$IMAGE" -x /usr/local/bin/llama-perplexity; then
  echo "ERROR: $IMAGE has no llama-perplexity" >&2
  echo "  add it to the cmake --build --target list and COPY it into the final stage" >&2
  exit 1
fi

if $RUN_AFTER; then
  echo ""
  docker run --rm "$IMAGE" llama-server --help
fi
