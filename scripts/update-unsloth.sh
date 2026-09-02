#!/usr/bin/env bash
# Bump runner/rocmunsloth to the newest unslothai/llama.cpp release and rebuild.
#
# The Updates panel cannot do this one: it rebuilds from ggml-org master with
# --build-arg LLAMA_CPP_REF, whereas rocmunsloth vendors a prebuilt release tarball
# (the release is an ephemeral CI merge with no fetchable ref -- see the Dockerfile).
#
#   ./scripts/update-unsloth.sh            # show what is available, change nothing
#   ./scripts/update-unsloth.sh --apply    # bump the Dockerfile and rebuild
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/runner/rocmunsloth"
DOCKERFILE="$DIR/Dockerfile"
ASSET_SUFFIX="linux-x64-rocm-gfx110X.tar.gz" # gfx1100 = 7900 XT

cur_tag=$(grep -oP '^ARG UNSLOTH_TAG=\K.*' "$DOCKERFILE")

# newest release carrying a gfx110X asset (skip any release that failed to publish one)
read -r new_tag new_asset < <(
  curl -fsSL "https://api.github.com/repos/unslothai/llama.cpp/releases?per_page=20" |
    python3 -c '
import json,sys
for r in json.load(sys.stdin):
    for a in r.get("assets", []):
        if a["name"].endswith("'"$ASSET_SUFFIX"'"):
            print(r["tag_name"], a["name"]); sys.exit()
'
)

echo "current: $cur_tag"
echo "latest:  $new_tag"
[ "$cur_tag" = "$new_tag" ] && {
  echo "already up to date"
  exit 0
}

if [ "${1:-}" != "--apply" ]; then
  echo
  echo "run with --apply to bump and rebuild"
  exit 0
fi

sed -i "s|^ARG UNSLOTH_TAG=.*|ARG UNSLOTH_TAG=$new_tag|" "$DOCKERFILE"
sed -i "s|^ARG UNSLOTH_ASSET=.*|ARG UNSLOTH_ASSET=$new_asset|" "$DOCKERFILE"
echo "bumped $cur_tag -> $new_tag"

docker build --network host -t local-llm-runner-rocmunsloth:latest "$DIR"

echo
docker run --rm local-llm-runner-rocmunsloth:latest llama-server --version 2>&1 | grep -i version
# the radix TOP_K (upstream f8dbcd61, 2026-08-31 13:00) missed tag b10715 by under three
# hours; any release built on b10716 or later has it and this warning should disappear.
echo "restart the cluster to pick it up:"
echo "  curl -s -X POST localhost:3100/api/clusters/<id>/stop"
echo "  docker rm -f local-llm-runner-cluster-<name>-<id>   # mgmt 409s on a stale container"
echo "  curl -s -X POST localhost:3100/api/clusters/<id>/start -H 'Content-Type: application/json' \\"
echo "       -d '{\"family\":\"qwen3.8-flash-next-reap320-rocm\",\"profile\":\"unsloth\"}'"
