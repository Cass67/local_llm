#!/usr/bin/env bash
# Replay an unsloth release recipe onto an upstream base.
#   replay-mix.sh <unsloth-tag> <upstream-base-sha>
#
# Lives in a script rather than inline in the Dockerfile because Docker performs ${...}
# substitution on RUN instructions, which mangles shell parameter expansions like ${url##*/}
# before the shell sees them -- the loop then runs with an empty sha and dies before printing.
set -euo pipefail

TAG="$1"
BASE="$2"
RAW="https://raw.githubusercontent.com/unslothai/llama.cpp/${TAG}/scripts/unsloth"

curl -fsSL "${RAW}/pr-set.json" -o /tmp/pr-set.json
curl -fsSL "${RAW}/additive_merge.py" -o /tmp/additive_merge.py

jq -r '.prs[] | if type=="object" then .url else . end' /tmp/pr-set.json >/tmp/urls
echo "=== replaying $(wc -l </tmp/urls) pinned PRs onto ${BASE} ==="

n=0
while read -r url; do
  n=$((n + 1))
  sha="${url##*/}"
  case "$url" in
    *ggml-org*) rem=origin ;;
    *) rem=unsloth ;;
  esac
  printf '%2d/%s  %-8s %s  ' "$n" "$(wc -l </tmp/urls)" "$rem" "${sha:0:12}"

  git fetch -q "$rem" "$sha" || {
    echo "FATAL: cannot fetch $sha from $rem ($url)" >&2
    exit 1
  }

  if git -c merge.conflictStyle=diff3 merge --no-ff --no-edit -m "mix $sha" "$sha" >/dev/null 2>&1; then
    echo "ok"
  # Their CI's fallback: resolves ONLY provably pure add/add conflicts (two PRs registering an
  # architecture at the same spot) and refuses when either side edited shared text, so a real
  # disagreement still hard-fails here. 2 of the 14 need this.
  elif python3 /tmp/additive_merge.py >/dev/null 2>&1 && [ -z "$(git diff --name-only --diff-filter=U)" ]; then
    git commit -q --no-edit
    echo "ok (additive)"
  else
    echo "FATAL"
    echo "  $sha does not merge onto $BASE plus the PRs listed before it" >&2
    git diff --name-only --diff-filter=U >&2
    exit 1
  fi
done </tmp/urls

echo "=== mix HEAD: $(git log --oneline -1)"
