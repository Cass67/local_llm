#!/usr/bin/env bash
set -euo pipefail

config_file="${LLAMA_CURRENT_MODEL_ENV:-current-model.env}"

if [[ ! -f "$config_file" ]]; then
  echo "missing $config_file; write REMOTE_SCRIPT and REMOTE_PROFILE before starting" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$config_file"

: "${REMOTE_SCRIPT:?REMOTE_SCRIPT is required in $config_file}"
: "${REMOTE_PROFILE:?REMOTE_PROFILE is required in $config_file}"

case "$REMOTE_SCRIPT" in
  ./*) ;;
  *)
    echo "REMOTE_SCRIPT must be a relative launcher path such as ./start1.sh" >&2
    exit 1
    ;;
esac

case "$REMOTE_PROFILE" in
  speed | fastlong | balanced | reliable | tiny) ;;
  *)
    echo "REMOTE_PROFILE must be one of speed, fastlong, balanced, reliable, tiny" >&2
    exit 1
    ;;
esac

exec "$REMOTE_SCRIPT" "$REMOTE_PROFILE"
