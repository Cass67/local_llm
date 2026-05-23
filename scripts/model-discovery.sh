#!/usr/bin/env bash
# model-discovery.sh - search and rank compatible GGUF models.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
MODEL_FIT_SCRIPT="$SCRIPT_DIR/model-fit.py"
if [[ ! -f "$MODEL_FIT_SCRIPT" ]]; then
  MODEL_FIT_SCRIPT="$repo_root/scripts/model-fit.py"
fi

usage() {
  cat <<'EOF'
Usage: model-discovery [options]

Options:
  --query <text>       Hugging Face search query. Default: GGUF
  --limit <n>          maximum ranked candidates to print. Default: 8
  --host <host>        inspect a remote model host over SSH
  --local              inspect local hardware instead of the remote host
  --installed-only     show only already tuned profiles
  --detailed           show detailed tuned-profile notes
  --json               print ranked discovery JSON
  -h, --help           show this help
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

ssh_probe() {
  local host="$1"
  local command_text="$2"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" "$command_text" 2>/dev/null || true
}

first_nonempty() {
  local value
  for value in "$@"; do
    if [[ -n "$value" ]]; then
      printf '%s\n' "$value"
      return 0
    fi
  done
  printf 'unknown\n'
}

get_cpu_cores() {
  if command -v nproc &>/dev/null; then
    nproc
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    sysctl -n hw.ncpu
  else
    echo "unknown"
  fi
}

get_ram() {
  if command -v free &>/dev/null; then
    free -g | awk '/^Mem:/{print $2}'
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    sysctl -n hw.memsize | awk '{print int($1/1073741824)}'
  else
    echo "unknown"
  fi
}

get_local_gpu() {
  local gpu=''
  if command -v system_profiler >/dev/null 2>&1; then
    gpu="$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chipset Model" | head -1 | sed 's/.*Chipset Model: //' || true)"
  fi
  first_nonempty "$gpu"
}

get_local_vram() {
  local vram=''
  if command -v system_profiler >/dev/null 2>&1; then
    vram="$(system_profiler SPDisplaysDataType 2>/dev/null | grep "VRAM" | head -1 | xargs || true)"
  fi
  first_nonempty "$vram"
}

get_remote_cpu_cores() {
  local host="$1"
  first_nonempty "$(ssh_probe "$host" 'nproc')"
}

get_remote_ram() {
  local host="$1"
  first_nonempty "$(ssh_probe "$host" "free -g | awk '/^Mem:/{print \$2}'")"
}

get_remote_gpu() {
  local host="$1"
  local gpu
  gpu="$(ssh_probe "$host" "rocminfo 2>/dev/null | grep -i 'Marketing Name' | grep -vi 'Intel' | head -1 | sed 's/.*Marketing Name:[[:space:]]*//' | xargs")"
  if [[ -n "$gpu" ]]; then
    printf '%s\n' "$gpu"
    return 0
  fi
  gpu="$(ssh_probe "$host" "rocminfo 2>/dev/null | grep -i 'Marketing Name' | head -1 | sed 's/.*Marketing Name:[[:space:]]*//' | xargs")"
  first_nonempty "$gpu"
}

get_remote_vram() {
  local host="$1"
  local bytes
  bytes="$(ssh_probe "$host" "for f in /sys/class/drm/card*/device/mem_info_vram_total; do [ -r \"\${f}\" ] && cat \"\${f}\" && break; done")"
  if [[ "$bytes" =~ ^[0-9]+$ ]]; then
    awk -v bytes="$bytes" 'BEGIN { printf "%.0f GB", bytes / 1073741824 }'
    return 0
  fi
  printf 'unknown\n'
}

hardware_json() {
  local source="$1"
  local cpu="$2"
  local ram="$3"
  local gpu="$4"
  local vram="$5"
  python3 - "$source" "$cpu" "$ram" "$gpu" "$vram" <<'PY'
import json
import re
import sys

source, cpu, ram, gpu, vram = sys.argv[1:]

def number(value):
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", value or "")
    return float(match.group(0)) if match else None

payload = {
    "source": source,
    "cpu_cores": number(cpu),
    "ram_gb": number(ram),
    "gpu_name": gpu or "unknown",
    "vram_gb": number(vram),
    "display_cpu_cores": cpu or "unknown",
    "display_ram_gb": ram or "unknown",
    "display_gpu": gpu or "unknown",
    "display_vram": vram or "unknown",
}
print(json.dumps(payload, separators=(",", ":")))
PY
}

detect_hardware() {
  local mode="$1"
  local host="$2"
  if [[ "$mode" == remote ]]; then
    hardware_json "remote:$host" "$(get_remote_cpu_cores "$host")" "$(get_remote_ram "$host")" "$(get_remote_gpu "$host")" "$(get_remote_vram "$host")"
  else
    hardware_json "local" "$(get_cpu_cores)" "$(get_ram)" "$(get_local_gpu)" "$(get_local_vram)"
  fi
}

fetch_candidates() {
  local query="$1"
  local limit="$2"
  if [[ -n "${OC_LOCAL_HF_FIXTURE:-}" ]]; then
    python3 - "$OC_LOCAL_HF_FIXTURE" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(handle.read(), end="")
PY
    return 0
  fi
  local fetch_limit="${OC_LOCAL_HF_FETCH_LIMIT:-50}"
  if [[ "$fetch_limit" =~ ^[0-9]+$ ]] && ((fetch_limit < limit)); then
    fetch_limit="$limit"
  fi
  local encoded_query
  encoded_query="$(
    python3 - "$query" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1]))
PY
  )"
  curl -fsSL "https://huggingface.co/api/models?search=${encoded_query}&limit=${fetch_limit}&sort=downloads&direction=-1"
}

enrich_candidates() {
  local limit="$1"
  local candidates_json
  candidates_json="$(cat)"
  python3 - "$limit" "${LOCAL_LLM_HF_TREE_FIXTURE:-}" "$candidates_json" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

limit = int(sys.argv[1])
fixture = sys.argv[2]
candidates = json.loads(sys.argv[3])
fixture_tree = None
if fixture:
    with open(fixture, encoding="utf-8") as handle:
        fixture_tree = json.load(handle)

def repo_id(item):
    return str(item.get("id") or item.get("repo") or item.get("name") or "")

def fetch_tree(repo):
    if fixture_tree is not None:
        return fixture_tree
    url = f"https://huggingface.co/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main"
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            return json.load(response)
    except Exception:
        return []

def has_sized_gguf(item):
    for file_info in item.get("siblings") or item.get("gguf_files") or []:
        if not isinstance(file_info, dict):
            continue
        path = file_info.get("path") or file_info.get("rfilename")
        size = file_info.get("size")
        if isinstance(path, str) and path.lower().endswith(".gguf") and isinstance(size, (int, float)):
            return True
    return False

for item in candidates:
    if not isinstance(item, dict) or has_sized_gguf(item):
        continue
    tree = fetch_tree(repo_id(item))
    siblings = []
    for file_info in tree if isinstance(tree, list) else []:
        if not isinstance(file_info, dict):
            continue
        path = file_info.get("path") or file_info.get("rfilename")
        size = file_info.get("size")
        if isinstance(path, str) and path.lower().endswith(".gguf") and isinstance(size, (int, float)):
            siblings.append({"rfilename": path, "size": size})
    if siblings:
        item["siblings"] = siblings
print(json.dumps(candidates, separators=(",", ":")))
PY
}

rank_candidates() {
  local hardware="$1"
  local query="$2"
  local limit="$3"
  python3 "$MODEL_FIT_SCRIPT" --hardware-json "$hardware" --query "$query" --limit "$limit" --json
}

print_header() {
  local hardware="$1"
  python3 - "$hardware" <<'PY'
import json
import sys

hardware = json.loads(sys.argv[1])
gpu = hardware["display_gpu"]
gpu_lower = gpu.lower()
rocm = "yes" if "amd" in gpu_lower or "radeon" in gpu_lower else "unknown"
print("Model Discovery Results:")
print("-----------------------")
print(f"Hardware source: {hardware['source']}")
print("Based on your system configuration:")
print(f"- CPU Cores: {hardware['display_cpu_cores']}")
print(f"- RAM: {hardware['display_ram_gb']} GB")
print(f"- GPU: {gpu}")
print(f"- VRAM: {hardware['display_vram']}")
print(f"- ROCm target: {rocm}")
PY
}

print_ranked_candidates() {
  local ranked="$1"
  printf '\n%s\n' 'Hugging Face GGUF Candidates'
  printf '%s\n' '----------------------------'
  python3 - "$ranked" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
for candidate in payload.get("candidates", []):
    params = candidate.get("params_b")
    params_text = "unknown" if params is None else f"{params:g}B"
    file_text = f" | file={candidate['best_file']}" if candidate.get("best_file") else ""
    print(
        f"{candidate['repo']} | purpose={candidate['use_case']} | class={candidate['size_class']} | "
        f"params={params_text} | fit={candidate['fit_level']} | quant={candidate['best_quant']} | "
        f"score={candidate['score']:.2f}{file_text}"
    )
PY
}

print_tuned_profiles() {
  cat <<'EOF'

Already Tuned Profiles
----------------------
- oc-qwen-reliable --lean
- oc-qwen-coder-reliable --lean
- oc-gemma-reliable --lean
- oc-gpt-oss-speed --lean
EOF
}

detailed_discovery() {
  cat <<'EOF'
Detailed Model Information:
---------------------------
Qwen3.6-35B-A3B:
  - Context: 65k tokens
  - Recommended quantization: UD-Q3_K_XL
  - VRAM requirement: ~16GB (with full offload)

Qwen3-Coder-30B-A3B-Instruct:
  - Context: 65k tokens
  - Recommended quantization: UD-Q3_K_XL
  - VRAM requirement: ~16GB (with full offload)

Gemma-4-31B-it:
  - Context: 65k tokens
  - Recommended quantization: UD-Q2_K_XL
  - VRAM requirement: ~12GB (with full offload)

gpt-oss-20B:
  - Context: 131k tokens
  - Recommended quantization: UD-Q8_K_XL
  - VRAM requirement: ~20GB (with full offload)
EOF
}

main() {
  local query='GGUF'
  local limit=8
  local host="${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local mode='auto'
  local installed_only=false
  local json=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --query)
        [[ $# -ge 2 ]] || die "--query requires text"
        query="$2"
        shift 2
        ;;
      --limit)
        [[ $# -ge 2 ]] || die "--limit requires a number"
        limit="$2"
        shift 2
        ;;
      --host)
        [[ $# -ge 2 ]] || die "--host requires a value"
        host="$2"
        mode='remote'
        shift 2
        ;;
      --local)
        mode='local'
        shift
        ;;
      --installed-only)
        installed_only=true
        shift
        ;;
      --detailed)
        detailed_discovery
        return 0
        ;;
      --json)
        json=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        query="$1"
        shift
        ;;
    esac
  done

  [[ "$limit" =~ ^[0-9]+$ ]] || die "invalid limit: $limit"
  if [[ "$mode" == auto ]]; then
    if [[ -n "$host" && "$host" != __none__ ]]; then
      mode='remote'
    else
      mode='local'
    fi
  fi

  local hardware ranked candidates
  hardware="$(detect_hardware "$mode" "$host")"
  ranked='{"candidates":[]}'
  if [[ "$installed_only" != true ]]; then
    candidates="$(fetch_candidates "$query" "$limit")"
    candidates="$(printf '%s' "$candidates" | enrich_candidates "$limit")"
    ranked="$(printf '%s' "$candidates" | rank_candidates "$hardware" "$query" "$limit")"
  fi

  if [[ "$json" == true ]]; then
    python3 - "$hardware" "$ranked" <<'PY'
import json
import sys

hardware = json.loads(sys.argv[1])
ranked = json.loads(sys.argv[2])
ranked["hardware"] = hardware
print(json.dumps(ranked, separators=(",", ":")))
PY
    return 0
  fi

  print_header "$hardware"
  if [[ "$installed_only" != true ]]; then
    print_ranked_candidates "$ranked"
  fi
  print_tuned_profiles
}

main "$@"
