#!/usr/bin/env bash
# Show and apply unslothai/llama.cpp prebuilt updates for runner/rocmunsloth.
#
# The CLI twin of the Updates panel's unsloth build, and it resolves the tag the same way the
# panel does: newest release carrying a gfx110X asset, passed as --build-arg and stamped on the
# image as the `unsloth.tag` label. The Dockerfile holds no default tag, so that label is the
# only record of what the image is at -- read it, never a pin in the tree.
#
#   ./scripts/update-unsloth.sh            # what is available, and what changed. changes nothing
#   ./scripts/update-unsloth.sh --apply    # bump the pin and rebuild
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/runner/rocmunsloth"
IMAGE="local-llm-runner-rocmunsloth:latest"
ASSET_SUFFIX="linux-x64-rocm-gfx110X.tar.gz" # gfx1100 = 7900 XT
API="https://api.github.com/repos/unslothai/llama.cpp"

cur_tag=$(docker image inspect "$IMAGE" --format '{{index .Config.Labels "unsloth.tag"}}' 2>/dev/null || true)
[ -n "$cur_tag" ] || cur_tag="(no image built yet)"

# Newest release that actually carries a gfx110X asset: a release whose ROCm leg failed
# publishes without one, and bumping to it would break the build rather than the download.
releases=$(curl -fsSL "${API}/releases?per_page=20")
read -r new_tag new_asset < <(
  python3 -c '
import json,sys
sfx = sys.argv[1]
for r in json.load(sys.stdin):
    for a in r.get("assets", []):
        if a["name"].endswith(sfx):
            print(r["tag_name"], a["name"]); sys.exit()
' "$ASSET_SUFFIX" <<<"$releases"
)

echo "current: $cur_tag"
echo "latest:  $new_tag"

if [ "$cur_tag" = "$new_tag" ]; then
  echo
  echo "already up to date"
  exit 0
fi

# Changelog: their release body lists the upstream base and every pinned PR merged into it.
# Print each release newer than what we run, oldest first, so the notes read in order.
echo
echo "=== changes between $cur_tag and $new_tag ==="
python3 -c '
import json,sys
cur = sys.argv[1]
rs  = json.load(sys.stdin)
newer = []
for r in rs:                       # newest first
    if r["tag_name"] == cur:
        break
    newer.append(r)
if not newer:
    print("  (no release notes found newer than the current pin)")
for r in reversed(newer):          # oldest first
    print(f"--- {r[\"tag_name\"]}  {r.get(\"published_at\",\"\")}")
    body = (r.get("body") or "").strip()
    print("\n".join("    " + ln for ln in body.splitlines()) or "    (no notes)")
    print()
' "$cur_tag" <<<"$releases"

if [ "${1:-}" != "--apply" ]; then
  echo "run with --apply to rebuild at the newer tag"
  exit 0
fi

echo "building $cur_tag -> $new_tag"

docker build --network host \
  --build-arg "UNSLOTH_TAG=$new_tag" \
  --build-arg "UNSLOTH_ASSET=$new_asset" \
  --label "unsloth.tag=$new_tag" \
  -t "$IMAGE" "$DIR"

echo
docker run --rm "$IMAGE" llama-server --version 2>&1 | grep -i version
cat <<'NOTE'

restart the cluster to pick it up:
  curl -s -X POST localhost:3100/api/clusters/d5e88d19/stop
  docker rm -f local-llm-runner-cluster-7900s-unsloth-d5e88d19   # mgmt 409s on a stale container
  curl -s -X POST localhost:3100/api/clusters/d5e88d19/start -H 'Content-Type: application/json' \
       -d '{"family":"qwen3.8-flash-next-reap320-rocm","profile":"unsloth"}'
NOTE
