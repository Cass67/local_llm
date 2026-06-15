#!/usr/bin/env bash
set -euo pipefail

base_url="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:8080}"
model="${LOCAL_LLM_MODEL:-}"
context_file="${1:-}"

usage() {
  cat <<'EOF'
Usage: preload-current-context.sh [context-file]

Preload the current llama.cpp prompt cache by sending a large context once with
max_tokens=1. Reads stdin when context-file is omitted or '-'.

Environment:
  LOCAL_LLM_BASE_URL  llama.cpp base URL, default http://127.0.0.1:8080
  LOCAL_LLM_MODEL     model id; if unset, read first id from /v1/models
EOF
}

case "${context_file:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

if [[ -z "$model" ]]; then
  model="$(
    python3 - "$base_url" <<'PY'
import json, sys, urllib.request
base=sys.argv[1].rstrip('/')
with urllib.request.urlopen(base + '/v1/models', timeout=10) as r:
    body=json.load(r)
print(body['data'][0]['id'])
PY
  )"
fi

if [[ -n "$context_file" && "$context_file" != "-" ]]; then
  context="$(cat -- "$context_file")"
else
  context="$(cat)"
fi

if [[ -z "$context" ]]; then
  echo "empty context; nothing to preload" >&2
  exit 2
fi

python3 - "$base_url" "$model" "$context" <<'PY'
import json, sys, time, urllib.request
base, model, context = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {
    'model': model,
    'messages': [{'role': 'user', 'content': context + '\n\nReply with exactly: cached'}],
    'max_tokens': 1,
    'temperature': 0,
    'stream': False,
}
req = urllib.request.Request(
    base.rstrip('/') + '/v1/chat/completions',
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json'},
)
t0=time.perf_counter()
with urllib.request.urlopen(req, timeout=600) as r:
    body=json.load(r)
t1=time.perf_counter()
usage=body.get('usage', {})
print(json.dumps({
    'ok': True,
    'model': model,
    'seconds': round(t1-t0, 3),
    'prompt_tokens': usage.get('prompt_tokens'),
    'completion_tokens': usage.get('completion_tokens'),
}, sort_keys=True))
PY
