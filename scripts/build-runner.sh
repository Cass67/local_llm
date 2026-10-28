#!/usr/bin/env bash
# Build a runner image (runner/<name>) with zstd layers.
#
# The containerd image store gzips every layer on export with one core, minutes on a 14 GB runner image;
# zstd is multi-threaded and local containerd reads it natively. Docker has no daemon-wide default for
# this, so every runner build goes through here.
#
#   ./scripts/build-runner.sh maya v1.1.36-glmdsa            # -> local-llm-runner-maya:v1.1.36-glmdsa
#   ./scripts/build-runner.sh rocm latest --build-arg X=Y    # extra args go to docker buildx build
set -euo pipefail

name="${1:?usage: build-runner.sh <runner dir name> <tag> [docker build args...]}"
tag="${2:?usage: build-runner.sh <runner dir name> <tag> [docker build args...]}"
shift 2
dir="$(cd "$(dirname "$0")/.." && pwd)/runner/$name"
[ -f "$dir/Dockerfile" ] || {
  echo "no $dir/Dockerfile" >&2
  exit 1
}

docker buildx build "$@" \
  --output "type=image,name=local-llm-runner-$name:$tag,compression=zstd,compression-level=3" \
  "$dir"
