#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
MODEL_DISCOVERY_SCRIPT="$SCRIPT_DIR/model-discovery.sh"
if [[ ! -f "$MODEL_DISCOVERY_SCRIPT" ]]; then
  MODEL_DISCOVERY_SCRIPT="$SCRIPT_DIR/model-discovery"
fi
if [[ ! -f "$MODEL_DISCOVERY_SCRIPT" ]]; then
  MODEL_DISCOVERY_SCRIPT="$repo_root/scripts/model-discovery.sh"
fi
MODEL_FIT_SCRIPT="$SCRIPT_DIR/model-fit.py"
if [[ ! -f "$MODEL_FIT_SCRIPT" ]]; then
  MODEL_FIT_SCRIPT="$repo_root/scripts/model-fit.py"
fi

runs_dir="${LOCAL_LLM_RUNS_DIR:-$HOME/.local/share/local_llm/runs}"

usage() {
  cat <<'EOF'
Usage: model-manager <command> [options]

Commands:
  list      Show installed and cached models
  update    Show cached model update suggestions
  replace   Replace a cached remote GGUF basename safely
  delete    Delete a repo from local metadata and remote GGUF cache
  discover   Find candidate models
  select     Select a candidate model
  benchmark  Benchmark a selected model
  accept     Accept benchmark results
  status     Show model-manager status

Options:
  -h, --help  Show this help
EOF
  printf '\nRepository: %s\n' "$repo_root"
}

not_implemented() {
  local command_name="$1"
  printf 'model-manager %s: not implemented yet\n' "$command_name" >&2
  return 1
}

ensure_runs_dirs() {
  mkdir -p "$runs_dir/candidates" "$runs_dir/selections" "$runs_dir/benchmarks" "$runs_dir/replacements"
}

count_json_files() {
  local dir="$1"
  local -a files=()

  if [[ -d "$dir" ]]; then
    shopt -s nullglob
    files=("$dir"/*.json)
    shopt -u nullglob
  fi

  printf '%s\n' "${#files[@]}"
}

cmd_status() {
  ensure_runs_dirs
  printf 'Model Manager Status\n'
  printf '====================\n'
  printf 'Runs dir: %s\n' "$runs_dir"
  printf 'Candidates: %s\n' "$(count_json_files "$runs_dir/candidates")"
  printf 'Selections: %s\n' "$(count_json_files "$runs_dir/selections")"
  printf 'Benchmarks: %s\n' "$(count_json_files "$runs_dir/benchmarks")"
}

print_profile_inventory() {
  local profiles_json="$repo_root/configs/profiles.json"

  printf 'Profiles\n\n'
  if [[ ! -f "$profiles_json" ]]; then
    printf '  None\n'
    return 0
  fi
  python3 - "$profiles_json" <<'PY'
import json
import sys
from collections import defaultdict

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, json.JSONDecodeError):
    print("  None")
    raise SystemExit(0)

profiles = data.get("profiles")
if not isinstance(profiles, dict):
    print("  None")
    raise SystemExit(0)

order = {name: index for index, name in enumerate(["speed", "fastlong", "balanced", "reliable", "tiny"])}
by_family = defaultdict(list)
for key in sorted(profiles):
    profile = profiles[key]
    if not isinstance(profile, dict):
        continue
    family = profile.get("family")
    if not isinstance(family, str) or not family:
        family = key.split(":", 1)[0]
    profile_name = key.split(":", 1)[1] if ":" in key else key
    by_family[family].append((profile_name, profile))

if not by_family:
    print("  None")
    raise SystemExit(0)

for family in sorted(by_family):
    rows = sorted(by_family[family], key=lambda item: (order.get(item[0], 99), item[0]))
    print(f"  {family}")
    for profile_name, profile in rows:
        model_name = profile.get("model_name") or "unknown"
        quant = profile.get("quant") or "unknown"
        print(f"    {profile_name:<10} {model_name:<38} {quant}")
    repos = sorted({profile.get("hf_repo") for _, profile in rows if isinstance(profile.get("hf_repo"), str) and profile.get("hf_repo")})
    if len(repos) == 1:
        print(f"    source: {repos[0]}")
    elif repos:
        print("    repos:")
        for repo in repos:
            print(f"      {repo}")
    print()
PY
}

print_selection_inventory() {
  local selection_dir="$runs_dir/selections"
  local -a selection_files=()

  if [[ -d "$selection_dir" ]]; then
    shopt -s nullglob
    selection_files=("$selection_dir"/*.json)
    shopt -u nullglob
  fi

  printf 'Pending Selections\n\n'
  if ((${#selection_files[@]} == 0)); then
    printf '  None\n'
    return 0
  fi
  python3 - "${selection_files[@]}" <<'PY'
import json
import os
import sys

promoted = set()
for line in os.environ.get("LOCAL_LLM_PROMOTED_LAUNCHERS", "").splitlines():
    fields = {}
    for part in line.split():
        key, sep, value = part.partition("=")
        if sep:
            fields[key] = value
    repo = fields.get("repo")
    alias = fields.get("alias")
    if repo and alias:
        promoted.add((repo, alias))

rows = []
for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as handle:
            selection = json.load(handle)
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(selection, dict):
        continue
    repo = selection.get("repo")
    family = selection.get("family")
    alias = selection.get("alias")
    if not all(isinstance(value, str) and value for value in (repo, family, alias)):
        continue
    if (repo, alias) in promoted:
        continue
    fields = {"repo": repo, "family": family, "alias": alias}
    target = selection.get("target")
    if isinstance(target, str) and target:
        fields["target"] = target
    rows.append(fields)

if not rows:
    print("  None")
    raise SystemExit(0)

for fields in sorted(rows, key=lambda item: (item["family"], item["alias"])):
    print(f"  {fields['alias']}")
    print(f"    family: {fields['family']}")
    print(f"    source: {fields['repo']}")
    if fields.get("target"):
        print(f"    target: {fields['target']}")
    print()
PY
}

print_launcher_inventory() {
  local oc_local="$repo_root/scripts/oc-local"
  if [[ ! -x "$oc_local" ]]; then
    oc_local="$SCRIPT_DIR/oc-local"
  fi
  local -a families=(
    qwen
    qwen-hauhau
    qwen-27b-hauhau
    gemma-hauhau
    qwen-27b
    qwen-opus
    qwen-heretic
    qwen-coder
    qwen-coder-next
    gemma
    gemma-vision
    gpt-oss
    deepseek-r1
  )
  local family
  local info

  [[ -x "$oc_local" ]] || return 0
  for family in "${families[@]}"; do
    info="$("$oc_local" "$family" reliable --info --lean 2>/dev/null || true)"
    [[ -n "$info" ]] || continue
    python3 - "$info" <<'PY'
import sys

fields = {}
for line in sys.argv[1].splitlines():
    key, sep, value = line.partition("=")
    if sep:
        fields[key] = value
family = fields.get("family")
repo = fields.get("hf_repo")
if not family or not repo:
    raise SystemExit(0)
parts = [f"launcher family={family}", f"repo={repo}"]
for key in ("quant", "alias", "remote_start"):
    value = fields.get(key)
    if value:
        parts.append(f"{key}={value}")
print(" ".join(parts))
PY
  done
}

print_launcher_cards() {
  local launcher_inventory="$1"

  printf 'Launchers\n\n'
  if [[ -z "$launcher_inventory" ]]; then
    printf '  None\n'
    return 0
  fi
  python3 - "$launcher_inventory" <<'PY'
import sys

rows = []
for line in sys.argv[1].splitlines():
    fields = {}
    for part in line.split():
        key, sep, value = part.partition("=")
        if sep:
            fields[key] = value
    if fields:
        rows.append(fields)

if not rows:
    print("  None")
    raise SystemExit(0)

for fields in sorted(rows, key=lambda item: (item.get("family", ""), item.get("alias", ""))):
    alias = fields.get("alias") or fields.get("family") or "unknown"
    print(f"  {alias}")
    if fields.get("family"):
        print(f"    family: {fields['family']}")
    if fields.get("repo"):
        print(f"    source: {fields['repo']}")
    if fields.get("quant"):
        print(f"    file:   {fields['quant']}")
    if fields.get("remote_start"):
        print(f"    start:  {fields['remote_start']} reliable")
    print()
PY
}

find_existing_launcher() {
  local repo="$1"
  local alias="$2"
  local oc_local="$repo_root/scripts/oc-local"
  if [[ ! -x "$oc_local" ]]; then
    oc_local="$SCRIPT_DIR/oc-local"
  fi
  local -a families=(
    qwen
    qwen-hauhau
    qwen-27b-hauhau
    gemma-hauhau
    qwen-27b
    qwen-opus
    qwen-heretic
    qwen-coder
    qwen-coder-next
    gemma
    gemma-vision
    gpt-oss
    deepseek-r1
  )
  local family
  local info

  [[ -x "$oc_local" ]] || return 1
  for family in "${families[@]}"; do
    info="$("$oc_local" "$family" reliable --info --lean 2>/dev/null || true)"
    [[ -n "$info" ]] || continue
    python3 - "$repo" "$alias" "$info" <<'PY'
import sys

repo, alias, info = sys.argv[1:]
fields = {}
for line in info.splitlines():
    key, sep, value = line.partition("=")
    if sep:
        fields[key] = value
if fields.get("hf_repo") == repo and fields.get("alias") == alias:
    print(fields.get("remote_start", ""))
PY
  done | head -1
}

remove_matching_selections() {
  local repo="$1"
  local alias="$2"
  local selection_dir="$runs_dir/selections"

  [[ -d "$selection_dir" ]] || {
    printf '0\n'
    return 0
  }

  python3 - "$selection_dir" "$repo" "$alias" <<'PY'
import json
import pathlib
import sys

selection_dir = pathlib.Path(sys.argv[1])
repo = sys.argv[2]
alias = sys.argv[3]
removed = 0
for path in selection_dir.glob("*.json"):
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(selection, dict):
        continue
    if selection.get("repo") == repo and selection.get("alias") == alias:
        path.unlink()
        removed += 1
print(removed)
PY
}

ensure_switcher_model() {
  local family="$1"
  local start_script="$2"
  local alias="$3"
  local label="$4"
  local switcher="$repo_root/scripts/local-llm-switcher.py"

  [[ -f "$switcher" ]] || {
    printf 'missing\n'
    return 0
  }

  python3 - "$switcher" "$family" "$start_script" "$alias" "$label" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
family, start_script, alias, label = sys.argv[2:]
remote_script = "./" + pathlib.PurePosixPath(start_script).name
text = path.read_text(encoding="utf-8")
needle = f'Model("{family}", "{remote_script}", "{alias}", '
if needle in text:
    print("existing")
    raise SystemExit(0)
entry = f'    Model("{family}", "{remote_script}", "{alias}", "{label}"),\n'
marker = "]\nMODELS_BY_ID"
if marker not in text:
    raise SystemExit("could not find switcher MODELS block")
text = text.replace(marker, entry + marker, 1)
path.write_text(text, encoding="utf-8")
print("added")
PY
}

remove_switcher_repo_entries() {
  local repo="$1"
  local alias="$2"
  local switcher="$repo_root/scripts/local-llm-switcher.py"
  [[ -f "$switcher" ]] || {
    printf '0\n'
    return 0
  }
  python3 - "$switcher" "$repo" "$alias" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
repo = sys.argv[2]
alias = sys.argv[3]
text = path.read_text(encoding="utf-8")
patterns = [
    rf'^    Model\([^\n]*"{re.escape(alias)}"[^\n]*\),\n',
    rf'^    Model\(\n(?:(?:        .+\n)+?)    \),\n',
]
removed = 0
for pattern in patterns:
    if pattern.endswith(r'    \),\n'):
        def keep_or_remove(match: re.Match[str]) -> str:
            global removed
            block = match.group(0)
            if f'"{alias}"' in block:
                removed += 1
                return ""
            return block

        text = re.sub(pattern, keep_or_remove, text, flags=re.MULTILINE)
    else:
        text, count = re.subn(pattern, "", text, flags=re.MULTILINE)
        removed += count
if removed:
    path.write_text(text, encoding="utf-8")
print(removed)
PY
}

remove_switcher_family_entries() {
  local family="$1"
  local switcher="$repo_root/scripts/local-llm-switcher.py"
  [[ -f "$switcher" ]] || {
    printf '0\n'
    return 0
  }
  python3 - "$switcher" "$family" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
family = sys.argv[2]
text = path.read_text(encoding="utf-8")
removed = 0

single = rf'^    Model\("{re.escape(family)}", [^\n]+\),\n'
text, count = re.subn(single, "", text, flags=re.MULTILINE)
removed += count

block = r'^    Model\(\n(?:(?:        .+\n)+?)    \),\n'

def keep_or_remove(match: re.Match[str]) -> str:
    global removed
    value = match.group(0)
    if f'"{family}"' in value:
        removed += 1
        return ""
    return value

text = re.sub(block, keep_or_remove, text, flags=re.MULTILINE)
if removed:
    path.write_text(text, encoding="utf-8")
print(removed)
PY
}

remove_oc_local_family_entries() {
  local family="$1"
  local oc_local="$repo_root/scripts/oc-local"
  [[ -f "$oc_local" ]] || {
    printf '0\n'
    return 0
  }
  python3 - "$oc_local" "$family" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
family = sys.argv[2]
text = path.read_text(encoding="utf-8")
original = text

lines = []
for line in text.splitlines(keepends=True):
    if line.lstrip().startswith("oc-") and family in line:
        continue
    if "|" in line and family in line and "case \"$1\"" not in line:
        line = line.replace(f"|{family}", "").replace(f"{family}|", "")
    lines.append(line)
text = "".join(lines)

pattern = rf'^  {re.escape(family)}\)\n.*?^    ;;\n'
text, block_count = re.subn(pattern, "", text, flags=re.MULTILINE | re.DOTALL)

if text != original:
    path.write_text(text, encoding="utf-8")
print(1 if text != original else 0)
PY
}

remove_selection_repo_entries() {
  local repo="$1"
  local selection_dir="$runs_dir/selections"
  [[ -d "$selection_dir" ]] || {
    printf '0\n'
    return 0
  }
  python3 - "$selection_dir" "$repo" <<'PY'
import json
import pathlib
import sys

selection_dir = pathlib.Path(sys.argv[1])
repo = sys.argv[2]
removed = 0
for path in selection_dir.glob("*.json"):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if isinstance(data, dict) and data.get("repo") == repo:
        path.unlink()
        removed += 1
print(removed)
PY
}

run_remote_delete_repo_cache() {
  local host="$1"
  local repo="$2"
  local mode="$3"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" python3 - "$repo" "$mode" <<'PY'
import json
import os
import sys

repo, mode = sys.argv[1:]
home = os.path.expanduser("~")
roots = [
    os.path.join(home, ".cache", "huggingface", "hub"),
    os.path.join(home, ".cache", "local_llm", "models"),
    os.path.join(home, ".cache", "llama.cpp"),
]
deleted = 0
planned = 0
for root in roots:
    if not os.path.isdir(root):
        continue
    for current_root, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".gguf"):
                continue
            path = os.path.join(current_root, name)
            found_repo = "unknown"
            marker = "models--"
            if marker in path and "/snapshots/" in path:
                repo_part = path.split(marker, 1)[1].split("/snapshots/", 1)[0]
                found_repo = repo_part.replace("--", "/", 1)
            if found_repo != repo:
                continue
            planned += 1
            print(json.dumps({"repo": found_repo, "file": name, "path": path, "action": mode}, separators=(",", ":")))
            if mode == "delete":
                os.remove(path)
                deleted += 1
print(json.dumps({"planned": planned, "deleted": deleted, "status": "success"}, separators=(",", ":")))
PY
}

remote_cache_inventory() {
  local target="$1"
  local host="${target#remote:}"
  local raw_output

  if ! raw_output="$(
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" python3 - <<'REMOTE_CACHE' 2>/dev/null
import json
import os

home = os.path.expanduser("~")
roots = [
    os.path.join(home, ".cache", "huggingface", "hub"),
    os.path.join(home, ".cache", "local_llm", "models"),
    os.path.join(home, ".cache", "llama.cpp"),
]
seen = set()
for root in roots:
    if root in seen or not os.path.isdir(root):
        continue
    seen.add(root)
    for current_root, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".gguf"):
                continue
            path = os.path.join(current_root, name)
            repo = "unknown"
            marker = "models--"
            if marker in path and "/snapshots/" in path:
                repo_part = path.split(marker, 1)[1].split("/snapshots/", 1)[0]
                repo = repo_part.replace("--", "/", 1)
            try:
                size_gb = os.path.getsize(path) / 1_000_000_000
            except OSError:
                size_gb = 0
            revision = ""
            if marker in path and "/snapshots/" in path:
                revision = path.split("/snapshots/", 1)[1].split("/", 1)[0]
            print(json.dumps({"repo": repo, "file": name, "path": path, "size_gb": f"{size_gb:.1f}", "cache": "remote", "revision": revision}, separators=(",", ":")))
REMOTE_CACHE
  )"; then
    printf 'Warning: remote cache inventory failed for %s\n' "$target" >&2
    return 0
  fi

  [[ -n "$raw_output" ]] || return 0
  python3 - "$raw_output" <<'PY'
import json
import sys

for line in sys.argv[1].splitlines():
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        continue
    else:
        fields = parsed if isinstance(parsed, dict) else {}
    if fields.get("cache") != "remote":
        continue
    print(json.dumps({key: fields.get(key, "") for key in ("cache", "repo", "file", "path", "size_gb", "revision")}, separators=(",", ":")))
PY
}

print_remote_cache_inventory() {
  local inventory
  inventory="$(remote_cache_inventory "$1")"
  printf 'Remote Cache\n\n'
  if [[ -z "$inventory" ]]; then
    printf '  None\n'
    return 0
  fi
  python3 - "$inventory" <<'PY'
import json
import sys
from collections import defaultdict

by_repo = defaultdict(list)
for line in sys.argv[1].splitlines():
    try:
        fields = json.loads(line)
    except json.JSONDecodeError:
        continue
    repo = fields.get("repo") or "unknown"
    file_name = fields.get("file") or "unknown"
    size_gb = fields.get("size_gb") or "?"
    by_repo[repo].append((file_name, size_gb))

if not by_repo:
    print("  None")
    raise SystemExit(0)

for repo in sorted(by_repo):
    print(f"  {repo}")
    for file_name, size_gb in sorted(by_repo[repo]):
        print(f"    {file_name:<52} {size_gb} GB")
    print()
PY
}

cache_inventory_repo_file() {
  local line="$1"
  python3 - "$line" <<'PY'
import json
import sys

line = sys.argv[1]
try:
    parsed = json.loads(line)
except json.JSONDecodeError:
    fields = {}
else:
    fields = parsed if isinstance(parsed, dict) else {}
print(f"{fields.get('repo', '')}\t{fields.get('file', '')}\t{fields.get('revision', '')}\t{fields.get('path', '')}")
PY
}

run_remote_delete_exact_path() {
  local host="$1"
  local old_path="$2"
  local old_path_b64

  old_path_b64="$(
    python3 - "$old_path" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode())
PY
  )"

  {
    printf "old_path_b64='%s'\n" "$old_path_b64"
    cat <<'REMOTE_DELETE_EXACT'
set -euo pipefail

old_path="$(python3 - "$old_path_b64" <<'PY'
import base64
import sys

print(base64.b64decode(sys.argv[1]).decode(), end="")
PY
)"

home="${HOME:?}"
case "$old_path" in
  "$home/.cache/huggingface/hub/"*|"$home/.cache/local_llm/models/"*|"$home/.cache/llama.cpp/"*) ;;
  *)
    printf 'deleted=none\n'
    printf 'delete_status=unsafe_path\n'
    exit 0
    ;;
esac

case "$old_path" in
  *.gguf|*.GGUF) ;;
  *)
    printf 'deleted=none\n'
    printf 'delete_status=unsafe_path\n'
    exit 0
    ;;
esac

if [[ -f "$old_path" ]]; then
  rm -f -- "$old_path"
  printf 'deleted=%s\n' "$(basename -- "$old_path")"
  printf 'delete_status=deleted\n'
else
  printf 'deleted=none\n'
  printf 'delete_status=not_found\n'
fi
REMOTE_DELETE_EXACT
  } | ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" bash -s
}

run_remote_delete_repo_basename() {
  local host="$1"
  local repo="$2"
  local basename="$3"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" python3 - "$repo" "$basename" <<'PY'
import os
import sys

repo, basename = sys.argv[1:]
roots = [
    os.path.expanduser("~/.cache/huggingface/hub"),
    os.path.expanduser("~/.cache/local_llm/models"),
    os.path.expanduser("~/.cache/llama.cpp"),
]
deleted = 0
for root in roots:
    if not os.path.isdir(root):
        continue
    for current_root, _, files in os.walk(root):
        if basename not in files:
            continue
        path = os.path.join(current_root, basename)
        found_repo = "unknown"
        marker = "models--"
        if marker in path and "/snapshots/" in path:
            repo_part = path.split(marker, 1)[1].split("/snapshots/", 1)[0]
            found_repo = repo_part.replace("--", "/", 1)
        if found_repo != repo:
            continue
        os.remove(path)
        deleted += 1
print(f"deleted={basename if deleted else 'none'}")
print(f"delete_status={'deleted' if deleted else 'not_found'}")
print(f"deleted_count={deleted}")
PY
}

update_local_model_references() {
  local repo="$1"
  local old_file="$2"
  local new_file="$3"

  python3 - "$repo_root" "$repo" "$old_file" "$new_file" <<'PY'
import pathlib
import sys

repo_root = pathlib.Path(sys.argv[1])
repo = sys.argv[2]
old_file = sys.argv[3]
new_file = sys.argv[4]
candidate_files = [
    repo_root / "scripts" / "oc-local",
    repo_root / "scripts" / "bench-mtp-remote.sh",
    repo_root / "scripts" / "bench-installed-kv-remote.sh",
]
candidate_files.extend(sorted((repo_root / "scripts").glob("start*.sh")))

changed = []
for path in candidate_files:
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    if old_file not in text or repo not in text:
        continue
    updated = text.replace(old_file, new_file)
    if updated == text:
        continue
    path.write_text(updated, encoding="utf-8")
    changed.append(str(path.relative_to(repo_root)))

print(f"reference_status={'updated' if changed else 'unchanged'}")
print(f"reference_files={','.join(changed) if changed else 'none'}")
PY
}

hf_latest_revision() {
  local repo="$1"
  if [[ -n "${LOCAL_LLM_HF_REVISION_FIXTURE:-}" ]]; then
    printf '%s\n' "$LOCAL_LLM_HF_REVISION_FIXTURE"
    return 0
  fi
  python3 - "$repo" <<'PY'
import json
import sys
import urllib.request
import urllib.parse

repo = sys.argv[1]
url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/")
try:
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.load(response)
except Exception:
    print("")
else:
    print(data.get("sha") or data.get("lastModified") or "")
PY
}

cmd_list() {
  local target='local'

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 || "$2" == --* ]]; then
          printf '%s\n' '--target requires local or remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown list option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        printf 'list accepts options only, got: %s\n' "$1" >&2
        return 2
        ;;
    esac
  done

  case "$target" in
    local) ;;
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      if [[ "${target#remote:}" == -* ]]; then
        printf 'remote target host must not start with '\''-'\'': %s\n' "$target" >&2
        return 2
      fi
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      return 2
      ;;
  esac

  ensure_runs_dirs
  local launcher_inventory
  launcher_inventory="$(print_launcher_inventory)"
  printf 'Models\n\n'
  print_profile_inventory
  printf '\n'
  if [[ -n "$launcher_inventory" ]]; then
    print_launcher_cards "$launcher_inventory"
  else
    print_launcher_cards ''
  fi
  printf '\n'
  LOCAL_LLM_PROMOTED_LAUNCHERS="$launcher_inventory" print_selection_inventory
  if [[ "$target" == remote:* ]]; then
    printf '\n'
    print_remote_cache_inventory "$target"
  fi
}

cmd_update() {
  local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local dry_run=false
  local yes=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 || "$2" == --* ]]; then
          printf '%s\n' '--target requires local or remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      --dry-run)
        dry_run=true
        shift
        ;;
      --yes)
        yes=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown update option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        printf 'update accepts options only, got: %s\n' "$1" >&2
        return 2
        ;;
    esac
  done

  if [[ "$dry_run" == "$yes" ]]; then
    printf '%s\n' 'update requires exactly one of --dry-run or --yes' >&2
    return 2
  fi

  case "$target" in
    local) ;;
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      if [[ "${target#remote:}" == -* ]]; then
        printf 'remote target host must not start with '\''-'\'': %s\n' "$target" >&2
        return 2
      fi
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      return 2
      ;;
  esac

  ensure_runs_dirs
  if [[ "$dry_run" == true ]]; then
    printf 'Recommended Updates\n'
  else
    printf 'Update result\n'
  fi
  [[ "$target" == remote:* ]] || return 0

  local inventory line repo_file repo file cached_revision cached_path cached_basename dynamic_choice latest_quant latest_file latest_basename lower_file latest_revision reason update_number
  local remote_output delete_status deleted_file download_status key value audit_file
  update_number=0
  inventory="$(remote_cache_inventory "$target")"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    repo_file="$(cache_inventory_repo_file "$line")"
    IFS=$'\t' read -r repo file cached_revision cached_path <<<"$repo_file"
    [[ -n "$repo" && -n "$file" && "$repo" != unknown ]] || continue
    lower_file="$(printf '%s' "${file##*/}" | tr '[:upper:]' '[:lower:]')"
    case "$lower_file" in
      mmproj* | *mmproj* | *projector*) continue ;;
    esac
    dynamic_choice="$(resolve_dynamic_quant_file "$repo" "$target")"
    latest_quant="$(printf '%s\n' "$dynamic_choice" | sed -n '1p')"
    latest_file="$(printf '%s\n' "$dynamic_choice" | sed -n '2p')"
    cached_basename="${file##*/}"
    latest_basename="${latest_file##*/}"
    reason='new-file'
    latest_revision=''
    if [[ -n "$latest_file" && "$latest_basename" == "$cached_basename" ]]; then
      latest_revision="$(hf_latest_revision "$repo")"
      if [[ -n "$cached_revision" && -n "$latest_revision" && "$cached_revision" != "$latest_revision" ]]; then
        reason='same-file-newer-snapshot'
      else
        continue
      fi
    fi
    [[ -n "$latest_file" ]] || continue
    update_number=$((update_number + 1))
    if [[ "$dry_run" == true ]]; then
      printf '\n[%s] %s\n\n' "$update_number" "$repo"
      printf '  Replace this cached file:\n\n'
      printf '    %s\n' "$file"
      if [[ -n "$cached_revision" ]]; then
        printf '    cached revision: %s\n' "$cached_revision"
      fi
      printf '\n'
      printf '  With this Hugging Face file:\n\n'
      printf '    %s\n' "$latest_file"
      if [[ -n "$latest_quant" ]]; then
        printf '    quant: %s\n' "$latest_quant"
      fi
      if [[ "$reason" == same-file-newer-snapshot ]]; then
        printf '    latest revision: %s\n' "$latest_revision"
      fi
      printf '\n'
      printf '  Why this is recommended:\n\n'
      case "$reason" in
        same-file-newer-snapshot)
          printf '    The same GGUF filename exists in a newer Hugging Face snapshot.\n'
          ;;
        *)
          printf '    Hugging Face has a better-fitting GGUF for this host.\n'
          ;;
      esac
      printf '    Projector files such as mmproj*.gguf were ignored.\n'
      printf '\n'
      printf '  What --yes will do:\n\n'
      printf '    1. Download %s.\n' "$latest_file"
      printf '    2. Delete %s only after the download succeeds.\n' "$cached_basename"
      printf '\n'
      printf '  Target: %s\n' "$target"
      continue
    fi

    local remote_output_file
    remote_output_file="$(mktemp)"
    if ! run_remote_replace "${target#remote:}" "__local_llm_download_only__.gguf" "$repo" "$latest_file" "$latest_quant" | tee "$remote_output_file"; then
      rm -f "$remote_output_file"
      printf 'remote update failed for %s current=%s\n' "$repo" "$cached_basename" >&2
      return 1
    fi
    remote_output="$(<"$remote_output_file")"
    rm -f "$remote_output_file"
    delete_status='unknown'
    deleted_file='none'
    download_status='unknown'
    while IFS= read -r line; do
      key="${line%%=*}"
      value="${line#*=}"
      case "$key" in
        deleted) deleted_file="$value" ;;
        download_status) download_status="$value" ;;
      esac
    done <<<"$remote_output"
    if [[ "$download_status" == success && "$reason" == new-file ]]; then
      local delete_output
      delete_output="$(run_remote_delete_repo_basename "${target#remote:}" "$repo" "$cached_basename")"
      printf '%s\n' "$delete_output"
      while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
          deleted) deleted_file="$value" ;;
          delete_status) delete_status="$value" ;;
        esac
      done <<<"$delete_output"
    elif [[ "$download_status" == success && -n "$cached_path" ]]; then
      local delete_output
      delete_output="$(run_remote_delete_exact_path "${target#remote:}" "$cached_path")"
      printf '%s\n' "$delete_output"
      while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
          deleted) deleted_file="$value" ;;
          delete_status) delete_status="$value" ;;
        esac
      done <<<"$delete_output"
    elif [[ "$download_status" == success ]]; then
      delete_status=not_found
      deleted_file=none
    else
      delete_status=not_attempted
      deleted_file=none
    fi
    local reference_output reference_status reference_files
    reference_status=not_attempted
    reference_files=none
    if [[ "$download_status" == success ]]; then
      reference_output="$(update_local_model_references "$repo" "$cached_basename" "$latest_file")"
      printf '%s\n' "$reference_output"
      while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
          reference_status) reference_status="$value" ;;
          reference_files) reference_files="$value" ;;
        esac
      done <<<"$reference_output"
    fi
    audit_file="$(write_replacement_audit "$cached_basename" "$repo" "$latest_quant" "$latest_file" "$target" update "$delete_status" "$deleted_file" "$download_status")"
    printf 'updated repo=%s old=%s new=%s target=%s\n' "$repo" "$cached_basename" "$latest_file" "$target"
    printf 'download_status=%s\n' "$download_status"
    printf 'delete_status=%s\n' "$delete_status"
    printf 'deleted=%s\n' "$deleted_file"
    printf 'reference_status=%s\n' "$reference_status"
    printf 'reference_files=%s\n' "$reference_files"
    printf 'audit_file=%s\n' "$audit_file"
    if [[ "$delete_status" != deleted || "$download_status" != success ]]; then
      return 1
    fi
  done <<<"$inventory"
}

write_replacement_audit() {
  local old_file="$1"
  local new_repo="$2"
  local selected_quant="$3"
  local selected_file="$4"
  local target="$5"
  local action="$6"
  local delete_status="$7"
  local deleted_file="$8"
  local download_status="$9"
  local timestamp result_timestamp safe_old output_file unique_suffix

  timestamp="$(date +%Y%m%d-%H%M%S)"
  result_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  safe_old="${old_file//[^A-Za-z0-9_.-]/-}"
  unique_suffix="$$"
  output_file="$runs_dir/replacements/${timestamp}-${safe_old}-${unique_suffix}.json"
  while [[ -e "$output_file" ]]; do
    unique_suffix="${unique_suffix}x"
    output_file="$runs_dir/replacements/${timestamp}-${safe_old}-${unique_suffix}.json"
  done

  python3 - "$output_file" "$old_file" "$new_repo" "$selected_quant" "$selected_file" "$target" "$action" "$delete_status" "$deleted_file" "$download_status" "$result_timestamp" <<'PY'
import json
import sys

(
    output_file,
    old_file,
    new_repo,
    selected_quant,
    selected_file,
    target,
    action,
    delete_status,
    deleted_file,
    download_status,
    timestamp,
) = sys.argv[1:]
record = {
    "old_file": old_file,
    "new_repo": new_repo,
    "selected_quant": selected_quant,
    "selected_file": selected_file,
    "target": target,
    "action": action,
    "delete_status": delete_status,
    "deleted_file": deleted_file,
    "download_status": download_status,
    "timestamp": timestamp,
}
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(record, handle, separators=(",", ":"))
    handle.write("\n")
PY
  printf '%s\n' "$output_file"
}

run_remote_replace() {
  local host="$1"
  local old_file="$2"
  local new_repo="$3"
  local selected_file="$4"
  local selected_quant="$5"
  local old_file_b64 new_repo_b64 selected_file_b64 selected_quant_b64

  old_file_b64="$(
    python3 - "$old_file" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode())
PY
  )"
  new_repo_b64="$(
    python3 - "$new_repo" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode())
PY
  )"
  selected_file_b64="$(
    python3 - "$selected_file" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode())
PY
  )"
  selected_quant_b64="$(
    python3 - "$selected_quant" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode())
PY
  )"

  {
    printf "old_file_b64='%s'\n" "$old_file_b64"
    printf "new_repo_b64='%s'\n" "$new_repo_b64"
    printf "selected_file_b64='%s'\n" "$selected_file_b64"
    printf "selected_quant_b64='%s'\n" "$selected_quant_b64"
    cat <<'REMOTE_REPLACE'
set -euo pipefail

decode_b64() {
  python3 - "$1" <<'PY'
import base64
import sys

print(base64.b64decode(sys.argv[1]).decode(), end="")
PY
}

old_file="$(decode_b64 "$old_file_b64")"
new_repo="$(decode_b64 "$new_repo_b64")"
selected_file="$(decode_b64 "$selected_file_b64")"
selected_quant="$(decode_b64 "$selected_quant_b64")"

ensure_download_tool() {
  export PATH="$HOME/.local/bin:$PATH"
  if command -v huggingface-cli >/dev/null 2>&1 || command -v hf >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf 'download_tool=missing\n'
    return 1
  fi
  printf 'download_tool_bootstrap=python3 -m pip install --user huggingface_hub[cli]\n'
  python3 -m pip install --user -U 'huggingface_hub[cli]'
  export PATH="$HOME/.local/bin:$PATH"
  command -v huggingface-cli >/dev/null 2>&1 || command -v hf >/dev/null 2>&1
}

download_with_python() {
  python3 - "$new_repo" "$selected_file" <<'PY'
import json
import os
import pathlib
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request

repo, selected_file = sys.argv[1:]
api_url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/")
with urllib.request.urlopen(api_url, timeout=60) as response:
    metadata = json.load(response)
revision = metadata.get("sha") or "main"
repo_cache = "models--" + repo.replace("/", "--")
target_dir = pathlib.Path.home() / ".cache" / "huggingface" / "hub" / repo_cache / "snapshots" / revision / pathlib.PurePosixPath(selected_file).parent
target_dir.mkdir(parents=True, exist_ok=True)
target_path = target_dir / pathlib.PurePosixPath(selected_file).name
url = "https://huggingface.co/" + urllib.parse.quote(repo, safe="/") + "/resolve/main/" + urllib.parse.quote(selected_file, safe="/")
fd, temp_name = tempfile.mkstemp(prefix=target_path.name + ".", suffix=".tmp", dir=str(target_dir))
downloaded = 0
try:
    with os.fdopen(fd, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"download_progress={downloaded}/{total}")
            else:
                print(f"download_progress={downloaded}")
    shutil.move(temp_name, target_path)
except Exception:
    try:
        os.unlink(temp_name)
    except OSError:
        pass
    raise
print(f"download_path={target_path}")
PY
}

case "$old_file" in
  ''|*/*|*..*)
    printf '%s\n' 'error=unsafe_old_file'
    exit 2
    ;;
esac
if [[ ! "$old_file" =~ ^[A-Za-z0-9._+-]+[.][Gg][Gg][Uu][Ff]$ ]]; then
  printf '%s\n' 'error=unsafe_old_file'
  exit 2
fi

home="${HOME:?}"
roots=(
  "$home/.cache/huggingface/hub"
  "$home/.cache/local_llm/models"
  "$home/.cache/llama.cpp"
)
matches=()
seen_roots=''
for root in "${roots[@]}"; do
  [[ -d "$root" ]] || continue
  case ":$seen_roots:" in
    *":$root:"*) continue ;;
  esac
  seen_roots="${seen_roots}:$root"
  while IFS= read -r -d '' path; do
    if [[ "$(basename -- "$path")" == "$old_file" ]]; then
      matches+=("$path")
    fi
  done < <(find "$root" -type f -name "$old_file" -print0 2>/dev/null)
done

download_status=unknown
if [[ -z "$selected_file" ]]; then
  download_status=no_file
elif ! ensure_download_tool; then
  printf 'download_tool=python-urllib\n'
  printf 'download_start=%s:%s\n' "$new_repo" "$selected_file"
  if download_with_python; then
    download_status=success
  else
    download_status=failed
  fi
elif command -v huggingface-cli >/dev/null 2>&1; then
  printf 'download_tool=huggingface-cli\n'
  printf 'download_start=%s:%s\n' "$new_repo" "$selected_file"
  if huggingface-cli download "$new_repo" "$selected_file"; then
    download_status=success
  else
    download_status=failed
  fi
elif command -v hf >/dev/null 2>&1; then
  printf 'download_tool=hf\n'
  printf 'download_start=%s:%s\n' "$new_repo" "$selected_file"
  if hf download "$new_repo" "$selected_file"; then
    download_status=success
  else
    download_status=failed
  fi
else
  download_status=no_tool
fi

if [[ "$download_status" != success ]]; then
  printf 'deleted=none\n'
  printf 'delete_status=not_attempted\n'
  printf 'download_status=%s\n' "$download_status"
  exit 0
fi

case "${#matches[@]}" in
  0)
    printf 'deleted=none\n'
    printf 'delete_status=not_found\n'
    ;;
  1)
    rm -f -- "${matches[0]}"
    printf 'deleted=%s\n' "$old_file"
    printf 'delete_status=deleted\n'
    ;;
  *)
    printf 'deleted=none\n'
    printf 'delete_status=ambiguous\n'
    ;;
esac
printf 'download_status=%s\n' "$download_status"
REMOTE_REPLACE
  } | ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" bash -s 2>/dev/null
}

cmd_replace() {
  local old_file=''
  local new_repo=''
  local target=''
  local dry_run=false
  local yes=false
  local positional_count=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
          printf '%s\n' '--target requires remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      --dry-run)
        dry_run=true
        shift
        ;;
      --yes)
        yes=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown replace option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        positional_count=$((positional_count + 1))
        case "$positional_count" in
          1) old_file="$1" ;;
          2) new_repo="$1" ;;
          *)
            printf 'replace accepts two arguments, got extra argument: %s\n' "$1" >&2
            return 2
            ;;
        esac
        shift
        ;;
    esac
  done

  if [[ -z "$old_file" || -z "$new_repo" ]]; then
    printf '%s\n' 'Usage: model-manager replace <old-file> <new-repo> --target remote:<host> --dry-run|--yes' >&2
    return 2
  fi
  case "$old_file" in
    '' | */* | *..*)
      printf '%s\n' 'old-file must be a basename without / or ..' >&2
      return 2
      ;;
  esac
  if [[ ! "$old_file" =~ ^[A-Za-z0-9._+-]+[.][Gg][Gg][Uu][Ff]$ ]]; then
    printf '%s\n' 'old-file must be a safe GGUF basename matching [A-Za-z0-9._+-]+.gguf' >&2
    return 2
  fi
  if [[ "$dry_run" == "$yes" ]]; then
    printf '%s\n' 'replace requires exactly one of --dry-run or --yes' >&2
    return 2
  fi
  case "$target" in
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      if [[ "${target#remote:}" == -* ]]; then
        printf 'remote target host must not start with '\''-'\'': %s\n' "$target" >&2
        return 2
      fi
      ;;
    '')
      printf '%s\n' 'replace requires --target remote:<host>' >&2
      return 2
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      return 2
      ;;
  esac

  ensure_runs_dirs

  local dynamic_choice selected_quant selected_file action audit_file remote_output
  local delete_status deleted_file download_status line key value
  dynamic_choice="$(resolve_dynamic_quant_file "$new_repo" "$target")"
  selected_quant="$(printf '%s\n' "$dynamic_choice" | sed -n '1p')"
  selected_file="$(printf '%s\n' "$dynamic_choice" | sed -n '2p')"
  action='dry-run'
  if [[ "$yes" == true ]]; then
    action='replace'
  fi
  if [[ "$dry_run" == true ]]; then
    audit_file="$(write_replacement_audit "$old_file" "$new_repo" "$selected_quant" "$selected_file" "$target" "$action" planned planned planned)"
    printf 'Replacement dry-run\n'
    printf 'old_file=%s\n' "$old_file"
    printf 'new_repo=%s\n' "$new_repo"
    printf 'selected_quant=%s\n' "$selected_quant"
    printf 'selected_file=%s\n' "$selected_file"
    printf 'target=%s\n' "$target"
    printf 'would_delete_remote_basename=%s\n' "$old_file"
    printf 'would_download_repo=%s\n' "$new_repo"
    printf 'would_download_file=%s\n' "$selected_file"
    printf 'audit_file=%s\n' "$audit_file"
    return 0
  fi

  if ! remote_output="$(run_remote_replace "${target#remote:}" "$old_file" "$new_repo" "$selected_file" "$selected_quant")"; then
    printf 'remote replacement failed for %s\n' "$target" >&2
    return 1
  fi
  delete_status='unknown'
  deleted_file='none'
  download_status='unknown'
  while IFS= read -r line; do
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      deleted) deleted_file="$value" ;;
      delete_status) delete_status="$value" ;;
      download_status) download_status="$value" ;;
    esac
  done <<<"$remote_output"
  audit_file="$(write_replacement_audit "$old_file" "$new_repo" "$selected_quant" "$selected_file" "$target" "$action" "$delete_status" "$deleted_file" "$download_status")"

  if [[ "$delete_status" != deleted || "$deleted_file" != "$old_file" || "$download_status" != success ]]; then
    printf 'Replacement did not complete\n'
    printf 'old_file=%s\n' "$old_file"
    printf 'new_repo=%s\n' "$new_repo"
    printf 'selected_quant=%s\n' "$selected_quant"
    printf 'selected_file=%s\n' "$selected_file"
    printf 'target=%s\n' "$target"
    printf '%s\n' "$remote_output"
    printf 'audit_file=%s\n' "$audit_file"
    return 1
  fi

  printf 'Replacement complete\n'
  printf 'old_file=%s\n' "$old_file"
  printf 'new_repo=%s\n' "$new_repo"
  printf 'selected_quant=%s\n' "$selected_quant"
  printf 'selected_file=%s\n' "$selected_file"
  printf 'target=%s\n' "$target"
  printf '%s\n' "$remote_output"
  printf 'audit_file=%s\n' "$audit_file"
}

cmd_delete() {
  local repo=''
  local profile_pattern=''
  local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local dry_run=true
  local yes=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        [[ $# -ge 2 && "$2" != --* ]] || {
          printf '%s\n' '--target requires remote:<host>' >&2
          return 2
        }
        target="$2"
        shift 2
        ;;
      --profile)
        [[ $# -ge 2 && "$2" != --* ]] || {
          printf '%s\n' '--profile requires family:profile or family:*' >&2
          return 2
        }
        profile_pattern="$2"
        shift 2
        ;;
      --dry-run)
        dry_run=true
        shift
        ;;
      --yes)
        yes=true
        dry_run=false
        shift
        ;;
      -h | --help)
        printf '%s\n' 'Usage: model-manager delete <repo>|--profile family:profile --target remote:<host> [--dry-run|--yes]'
        return 0
        ;;
      --*)
        printf 'Unknown delete option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        if [[ -n "$repo" ]]; then
          printf 'delete accepts one repo, got extra argument: %s\n' "$1" >&2
          return 2
        fi
        repo="$1"
        shift
        ;;
    esac
  done

  if [[ -n "$repo" && -n "$profile_pattern" ]]; then
    printf '%s\n' 'delete accepts either a repo or --profile, not both' >&2
    return 2
  fi
  [[ -n "$repo" || -n "$profile_pattern" ]] || {
    printf '%s\n' 'delete requires a repo or --profile' >&2
    return 2
  }
  case "$target" in
    remote:*) ;;
    *)
      printf '%s\n' 'delete requires --target remote:<host>' >&2
      return 2
      ;;
  esac
  if [[ -z "${target#remote:}" || "${target#remote:}" == -* ]]; then
    printf 'invalid remote target: %s\n' "$target" >&2
    return 2
  fi

  ensure_runs_dirs
  if [[ -n "$profile_pattern" ]]; then
    cmd_delete_profile "$profile_pattern" "$target" "$dry_run" "$yes"
    return $?
  fi

  local alias
  alias="$(infer_alias "$repo")"
  printf 'Delete %s\n' "$([[ "$yes" == true ]] && printf 'result' || printf 'dry-run')"
  printf 'repo=%s\n' "$repo"
  printf 'target=%s\n' "$target"

  if [[ "$dry_run" == true ]]; then
    printf 'would_remove_selections_for_repo=%s\n' "$repo"
    printf 'would_remove_switcher_entries_for_repo=%s\n' "$repo"
    printf 'remote_cache_plan:\n'
    run_remote_delete_repo_cache "${target#remote:}" "$repo" plan || true
    return 0
  fi

  local removed_selections removed_switcher
  removed_selections="$(remove_selection_repo_entries "$repo")"
  removed_switcher="$(remove_switcher_repo_entries "$repo" "$alias")"
  printf 'removed_selection_count=%s\n' "$removed_selections"
  printf 'removed_switcher_count=%s\n' "$removed_switcher"
  printf 'remote_cache_delete:\n'
  run_remote_delete_repo_cache "${target#remote:}" "$repo" delete
}

cmd_delete_profile() {
  local profile_pattern="$1"
  local target="$2"
  local dry_run="$3"
  local yes="$4"
  local profiles_json="${LOCAL_LLM_PROFILES_JSON:-$repo_root/configs/profiles.json}"
  if [[ ! -f "$profiles_json" && -f "$HOME/.local/share/local_llm/config/profiles.json" ]]; then
    profiles_json="$HOME/.local/share/local_llm/config/profiles.json"
  fi

  [[ "$profile_pattern" == *:* ]] || {
    printf '%s\n' '--profile requires family:profile or family:*' >&2
    return 2
  }
  [[ -f "$profiles_json" ]] || {
    printf 'profiles JSON not found: %s\n' "$profiles_json" >&2
    return 1
  }

  local mode
  local family="${profile_pattern%%:*}"
  local wanted_profile="${profile_pattern#*:}"
  mode=plan
  if [[ "$yes" == true && "$dry_run" != true ]]; then
    mode=delete
  fi

  printf 'Delete profile %s\n' "$([[ "$mode" == delete ]] && printf 'result' || printf 'dry-run')"

  python3 - "$profiles_json" "$profile_pattern" "$mode" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
pattern = sys.argv[2]
mode = sys.argv[3]
family, wanted_profile = pattern.split(":", 1)
data = json.loads(path.read_text(encoding="utf-8"))
profiles = data.get("profiles")
if not isinstance(profiles, dict):
    raise SystemExit("profiles JSON missing profiles object")

matched = {}
remaining = {}
for key, value in profiles.items():
    if not isinstance(value, dict):
        continue
    key_family, sep, key_profile = key.partition(":")
    is_match = key_family == family and (wanted_profile == "*" or key_profile == wanted_profile)
    if is_match:
        matched[key] = value
    else:
        remaining[key] = value

if not matched:
    raise SystemExit(f"no profiles match: {pattern}")

repos = sorted({value.get("hf_repo") for value in matched.values() if value.get("hf_repo")})
print(f"profile_pattern={pattern}")
for key in sorted(matched):
    print(f"matched_profile={key} repo={matched[key].get('hf_repo', '')}")
for repo in repos:
    remaining_refs = sum(1 for value in remaining.values() if value.get("hf_repo") == repo)
    action = "keep" if remaining_refs else "delete"
    print(f"cache_action={action} repo={repo} remaining_refs={remaining_refs}")

if mode == "delete":
    for key in matched:
        profiles.pop(key, None)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"removed_profile_count={len(matched)}")
PY
  if [[ "$mode" == delete && "$wanted_profile" == '*' ]]; then
    local removed_switcher_count removed_oc_local_count
    removed_switcher_count="$(remove_switcher_family_entries "$family")"
    removed_oc_local_count="$(remove_oc_local_family_entries "$family")"
    printf 'removed_switcher_count=%s\n' "$removed_switcher_count"
    printf 'removed_launcher_family_count=%s\n' "$removed_oc_local_count"
  fi
}

infer_family() {
  local repo_lower
  repo_lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$repo_lower" in
    *qwen3-coder-next*)
      printf '%s\n' 'qwen-coder-next'
      ;;
    *qwen*coder*)
      printf '%s\n' 'qwen-coder'
      ;;
    *deepseek*)
      printf '%s\n' 'deepseek-r1'
      ;;
    *qwen*)
      printf '%s\n' 'qwen'
      ;;
    *gemma*)
      printf '%s\n' 'gemma'
      ;;
    *gpt-oss*)
      printf '%s\n' 'gpt-oss'
      ;;
    *)
      printf '%s\n' 'candidate'
      ;;
  esac
}

infer_alias() {
  local name
  name="${1##*/}"
  name="${name%-GGUF}"
  name="${name%-gguf}"
  printf '%s\n' "$name" | tr '[:upper:]' '[:lower:]'
}

infer_quant() {
  local repo_lower="${2:-}"
  repo_lower="$(printf '%s' "$repo_lower" | tr '[:upper:]' '[:lower:]')"
  if [[ "$repo_lower" == *qwen3-coder-next* ]]; then
    printf '%s\n' 'UD-TQ1_0'
    return 0
  fi
  local family="$1"
  case "$family" in
    qwen-coder | qwen | deepseek-r1)
      printf '%s\n' 'Q3_K_M'
      ;;
    gemma)
      printf '%s\n' 'UD-Q2_K_XL'
      ;;
    gpt-oss)
      printf '%s\n' 'UD-Q8_K_XL'
      ;;
    *)
      printf '%s\n' 'Q3_K_M'
      ;;
  esac
}

infer_hf_file() {
  local repo_lower
  repo_lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$repo_lower" in
    *qwen3-coder-next*)
      printf '%s\n' 'Qwen3-Coder-Next-UD-TQ1_0.gguf'
      ;;
    *)
      printf '\n'
      ;;
  esac
}

benchmark_hardware_json() {
  local target="$1"
  local vram=''
  case "$target" in
    remote:*)
      vram="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${target#remote:}" 'for f in /sys/class/drm/card*/device/mem_info_vram_total; do [ -r "$f" ] && cat "$f" && break; done' 2>/dev/null || true)"
      ;;
  esac
  python3 - "$target" "$vram" <<'PY'
import json
import sys

target, vram = sys.argv[1:]
try:
    vram_gb = int(vram) / 1073741824 if vram else 20.0
except ValueError:
    vram_gb = 20.0
print(json.dumps({"source": target, "vram_gb": vram_gb}, separators=(",", ":")))
PY
}

fetch_repo_tree_json() {
  local repo="$1"
  if [[ -n "${LOCAL_LLM_HF_TREE_FIXTURE:-}" ]]; then
    python3 - "$LOCAL_LLM_HF_TREE_FIXTURE" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(handle.read(), end="")
PY
    return 0
  fi
  local encoded_repo
  encoded_repo="$(
    python3 - "$repo" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe="/"))
PY
  )"
  curl -fsSL "https://huggingface.co/api/models/${encoded_repo}/tree/main" 2>/dev/null || printf '[]\n'
}

resolve_dynamic_quant_file() {
  local repo="$1"
  local target="$2"
  local tree_json hardware
  tree_json="$(fetch_repo_tree_json "$repo")"
  hardware="$(benchmark_hardware_json "$target")"
  python3 - "$repo" "$hardware" "$MODEL_FIT_SCRIPT" "$tree_json" <<'PY'
import json
import subprocess
import sys

repo, hardware, model_fit, tree_json = sys.argv[1:]
tree = json.loads(tree_json)
siblings = []
for item in tree if isinstance(tree, list) else []:
    if not isinstance(item, dict):
        continue
    path = item.get("path") or item.get("rfilename")
    size = item.get("size")
    if isinstance(path, str) and path.lower().endswith(".gguf") and isinstance(size, int | float):
        siblings.append({"rfilename": path, "size": size})
payload = [{"id": repo, "tags": ["gguf"], "siblings": siblings}]
ranked = subprocess.check_output(
    [sys.executable, model_fit, "--hardware-json", hardware, "--limit", "1", "--json"],
    input=json.dumps(payload),
    text=True,
)
candidate = json.loads(ranked)["candidates"][0]
print(candidate.get("best_quant") or "")
print(candidate.get("best_file") or "")
PY
}

run_remote_benchmark() {
  local host="$1"
  local repo="$2"
  local family="$3"
  local alias="$4"
  local profile="$5"
  local quant="$6"
  local hf_file="$7"
  local remote_dir="${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}"
  local port=8080
  local ctx="${8:-65536}"
  local batch="${9:-128}"
  local ubatch="${10:-$batch}"

  ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" bash -s -- "$remote_dir" "$repo" "$family" "$alias" "$profile" "$quant" "$hf_file" "$port" "$ctx" "$batch" "$ubatch" <<'REMOTE_BENCH'
set -euo pipefail

remote_dir="$1"
repo="$2"
family="$3"
alias="$4"
profile="$5"
quant="$6"
hf_file="$7"
port="$8"
ctx="$9"
batch="${10}"
ubatch="${11}"
ngl=999
server_pid=""
service_was_active=false
log_file="${TMPDIR:-/tmp}/local-llm-benchmark-${alias}-${profile}-$$.log"
response_file="${TMPDIR:-/tmp}/local-llm-benchmark-${alias}-${profile}-$$.json"
start_script=".local-llm-benchmark-${alias}.sh"

json_string() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

stop_server() {
  return 0
}

restore_service() {
  return 0
}

last_number_for() {
  local pattern="$1"
  local file="$2"
  awk -v pattern="$pattern" '$0 ~ pattern { for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+([.][0-9]+)?$/) value = $i } END { print value }' "$file"
}

last_tokens_for() {
  local pattern="$1"
  local file="$2"
  awk -v pattern="$pattern" '$0 ~ pattern { for (i = 1; i < NF; i++) if ($i == "/" && $(i + 1) ~ /^[0-9]+$/) value = $(i + 1) } END { print value }' "$file"
}

trap restore_service EXIT

cd "$remote_dir"
model_args=(-hf "${repo}:${quant}")
if [[ -n "$hf_file" ]]; then
  model_args=(-hf "$repo" --hf-file "$hf_file")
fi
server_cmd=(
  ./build/bin/llama-server
  "${model_args[@]}"
  --host 0.0.0.0
  --port "$port"
  -ngl "$ngl"
  -c "$ctx"
  --flash-attn on
  -ub "$ubatch"
  -b "$batch"
  --threads "$(nproc)"
  --prio 2
  --no-warmup
  --temp 0.6
  --top-p 0.95
  --top-k 20
  --min-p 0.0
  --presence-penalty 0.0
  --alias "$alias"
)
if [[ "$family" != gpt-oss && "$family" != deepseek-r1 ]]; then
  server_cmd+=(--reasoning off)
fi
command_text=""
for command_text_part in "${server_cmd[@]}"; do
  printf -v command_text_part '%q' "$command_text_part"
  command_text+="${command_text_part} "
done
command_text="${command_text% }"
{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' 'set -euo pipefail'
  printf '%s\n' 'profile="${1:-reliable}"'
  printf '%s\n' 'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *) echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac'
  printf 'exec'
  for command_text_part in "${server_cmd[@]}"; do
    printf ' %q' "$command_text_part"
  done
  printf '\n'
} >"$start_script"
chmod +x "$start_script"
cat >current-model.env.tmp <<EOF
REMOTE_SCRIPT=./$start_script
REMOTE_PROFILE=$profile
EOF
mv current-model.env.tmp current-model.env
: >"$log_file"
restart_started="$(date -Is)"
systemctl --user restart llama-server.service

load_status=timeout
for _ in $(seq 1 180); do
  if curl -fsS --max-time 5 "http://127.0.0.1:${port}/v1/models" 2>/dev/null | grep -F "$alias" >/dev/null; then
    load_status=success
    break
  fi
  if ! systemctl --user is-active --quiet llama-server.service >/dev/null 2>&1; then
    load_status=failed
    break
  fi
  sleep 2
done

if [[ "$load_status" == success ]]; then
  prompt='Write a deterministic benchmark response of exactly 32 numbered lines. Each line must contain one concise sentence about local inference performance, queueing, memory bandwidth, and token generation. Do not stop early.'
  request="{\"model\":$(json_string "$alias"),\"messages\":[{\"role\":\"user\",\"content\":$(json_string "$prompt")}],\"max_tokens\":512,\"temperature\":0}"
  if ! curl -fsS --max-time 300 "http://127.0.0.1:${port}/v1/chat/completions" -H 'Content-Type: application/json' -d "$request" >"$response_file" 2>>"$log_file"; then
    load_status=error
  fi
fi

journalctl --user -u llama-server.service --since "$restart_started" --no-pager >>"$log_file" 2>/dev/null || true
if grep -E 'hipMalloc failed|out of memory|OOM|cannot allocate memory|std::bad_alloc' "$log_file" >/dev/null 2>&1; then
  load_status=oom
fi

prompt_tok_s="$(last_number_for 'prompt eval time' "$log_file")"
decode_tok_s="$(last_number_for '(^|:)[[:space:]]+eval time' "$log_file")"
prompt_tokens="$(last_tokens_for 'prompt eval time' "$log_file")"
decode_tokens="$(last_tokens_for '(^|:)[[:space:]]+eval time' "$log_file")"
if [[ "$load_status" == success && ( -z "$decode_tokens" || "$decode_tokens" -lt 128 ) ]]; then
  load_status=too_short
fi
printf 'load_status=%s\n' "$load_status"
printf 'prompt_tok_s=%s\n' "$prompt_tok_s"
printf 'decode_tok_s=%s\n' "$decode_tok_s"
printf 'prompt_tokens=%s\n' "$prompt_tokens"
printf 'decode_tokens=%s\n' "$decode_tokens"
printf 'ctx=%s\n' "$ctx"
printf 'batch=%s\n' "$batch"
printf 'ubatch=%s\n' "$ubatch"
printf 'ngl=%s\n' "$ngl"
printf 'command=%s\n' "$command_text"
printf 'log_file=%s\n' "$log_file"
REMOTE_BENCH
}

cmd_discover() {
  local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local query='GGUF'
  local limit=8
  local json=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--target requires local or remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      --query)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--query requires text' >&2
          return 2
        fi
        query="$2"
        shift 2
        ;;
      --limit)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--limit requires a number' >&2
          return 2
        fi
        limit="$2"
        shift 2
        ;;
      --json)
        json=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown discover option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        query="$1"
        shift
        ;;
    esac
  done

  case "$limit" in
    '' | *[!0-9]*)
      printf 'invalid limit: %s\n' "$limit" >&2
      return 2
      ;;
  esac

  case "$target" in
    local) ;;
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      printf 'expected local or remote:<host>\n' >&2
      return 2
      ;;
  esac

  if [[ "$json" == true ]]; then
    local discovery_json
    case "$target" in
      local)
        discovery_json="$($MODEL_DISCOVERY_SCRIPT --local --query "$query" --limit "$limit" --json)"
        ;;
      remote:*)
        discovery_json="$($MODEL_DISCOVERY_SCRIPT --host "${target#remote:}" --query "$query" --limit "$limit" --json)"
        ;;
    esac
    python3 - "$target" "$query" "$limit" "$discovery_json" <<'PY'
import json
import sys

target, query, limit, discovery_json = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
payload = json.loads(discovery_json)
payload["target"] = target
payload["query"] = query
payload["limit"] = limit
print(json.dumps(payload, separators=(",", ":")))
PY
    return 0
  fi

  case "$target" in
    local)
      "$MODEL_DISCOVERY_SCRIPT" --local --query "$query" --limit "$limit"
      ;;
    remote:*)
      "$MODEL_DISCOVERY_SCRIPT" --host "${target#remote:}" --query "$query" --limit "$limit"
      ;;
  esac
}

cmd_select() {
  local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local repo=''
  local family=''
  local alias=''
  local purpose=''

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--target requires local or remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      --repo)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--repo requires a value' >&2
          return 2
        fi
        repo="$2"
        shift 2
        ;;
      --family)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--family requires a value' >&2
          return 2
        fi
        family="$2"
        shift 2
        ;;
      --alias)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--alias requires a value' >&2
          return 2
        fi
        alias="$2"
        shift 2
        ;;
      --purpose)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--purpose requires a value' >&2
          return 2
        fi
        purpose="$2"
        shift 2
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown select option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        repo="$1"
        shift
        ;;
    esac
  done

  if [[ -z "$repo" ]]; then
    printf '%s\n' 'select requires --repo' >&2
    return 2
  fi
  if [[ -z "$family" ]]; then
    family="$(infer_family "$repo")"
  fi
  if [[ -z "$alias" ]]; then
    alias="$(infer_alias "$repo")"
  fi

  case "$target" in
    local) ;;
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      printf 'expected local or remote:<host>\n' >&2
      return 2
      ;;
  esac

  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'python3 is required for selection JSON' >&2
    return 1
  fi

  ensure_runs_dirs
  local timestamp
  local safe_family
  local output_file
  local unique_suffix
  timestamp="$(date +%Y%m%d-%H%M%S)"
  safe_family="${family//[^A-Za-z0-9_.-]/-}"
  unique_suffix="$$"
  output_file="$runs_dir/selections/${timestamp}-${safe_family}-${unique_suffix}.json"
  while [[ -e "$output_file" ]]; do
    unique_suffix="${unique_suffix}x"
    output_file="$runs_dir/selections/${timestamp}-${safe_family}-${unique_suffix}.json"
  done

  python3 - "$output_file" "$repo" "$family" "$alias" "$target" "$purpose" <<'PY'
import json
import sys

output_file, repo, family, alias, target, purpose = sys.argv[1:]
selection = {"repo": repo, "family": family, "alias": alias, "target": target}
if purpose:
    selection["purpose"] = purpose
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(selection, handle, separators=(",", ":"))
    handle.write("\n")
PY

  printf 'Selected %s\n' "$repo"
  printf 'Wrote selection: %s\n' "$output_file"
}

cmd_benchmark() {
  local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
  local repo=''
  local family=''
  local alias=''
  local profiles='reliable'
  local -a profile_list=()
  local dry_run=false
  local record_only=false
  local quant=''
  local hf_file=''
  local full=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--target requires local or remote:<host>' >&2
          return 2
        fi
        target="$2"
        shift 2
        ;;
      --repo)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--repo requires a value' >&2
          return 2
        fi
        repo="$2"
        shift 2
        ;;
      --family)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--family requires a value' >&2
          return 2
        fi
        family="$2"
        shift 2
        ;;
      --alias)
        if [[ $# -lt 2 ]]; then
          printf '%s\n' '--alias requires a value' >&2
          return 2
        fi
        alias="$2"
        shift 2
        ;;
      --profiles)
        if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
          printf '%s\n' '--profiles requires a non-empty value' >&2
          return 2
        fi
        profiles="$2"
        shift 2
        ;;
      --quant)
        if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
          printf '%s\n' '--quant requires a non-empty value' >&2
          return 2
        fi
        quant="$2"
        shift 2
        ;;
      --hf-file)
        if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
          printf '%s\n' '--hf-file requires a non-empty value' >&2
          return 2
        fi
        hf_file="$2"
        shift 2
        ;;
      --dry-run)
        dry_run=true
        shift
        ;;
      --full)
        full=true
        shift
        ;;
      --record-only)
        record_only=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown benchmark option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        repo="$1"
        shift
        ;;
    esac
  done

  if [[ -z "$repo" ]]; then
    printf '%s\n' 'benchmark requires --repo' >&2
    return 2
  fi
  if [[ -z "$family" ]]; then
    family="$(infer_family "$repo")"
  fi
  if [[ -z "$alias" ]]; then
    alias="$(infer_alias "$repo")"
  fi
  if [[ -z "$quant" && -z "$hf_file" ]]; then
    dynamic_choice="$(resolve_dynamic_quant_file "$repo" "$target")"
    quant="$(printf '%s\n' "$dynamic_choice" | sed -n '1p')"
    hf_file="$(printf '%s\n' "$dynamic_choice" | sed -n '2p')"
  fi
  if [[ -z "$quant" ]]; then
    quant="$(infer_quant "$family" "$repo")"
  fi
  if [[ -z "$hf_file" ]]; then
    hf_file="$(infer_hf_file "$repo")"
  fi

  ensure_runs_dirs

  case "$profiles" in
    ,* | *, | *,,*)
      printf '%s\n' '--profiles contains an empty profile' >&2
      return 2
      ;;
  esac

  IFS=, read -r -a profile_list <<<"$profiles"
  local profile
  for profile in "${profile_list[@]}"; do
    if [[ -z "$profile" ]]; then
      printf '%s\n' '--profiles contains an empty profile' >&2
      return 2
    fi
    case "$profile" in
      *[!A-Za-z0-9_.-]*)
        printf 'invalid benchmark profile: %s\n' "$profile" >&2
        return 2
        ;;
    esac
  done

  case "$target" in
    local) ;;
    remote:*)
      if [[ -z "${target#remote:}" ]]; then
        printf 'remote target requires a host: %s\n' "$target" >&2
        return 2
      fi
      ;;
    *)
      printf 'invalid target: %s\n' "$target" >&2
      printf 'expected local or remote:<host>\n' >&2
      return 2
      ;;
  esac

  if [[ "$record_only" == true ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      printf '%s\n' 'python3 is required for benchmark JSON' >&2
      return 1
    fi

    local timestamp
    local result_timestamp
    local safe_family
    local safe_profile
    local output_file
    local unique_suffix
    timestamp="$(date +%Y%m%d-%H%M%S)"
    result_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    safe_family="${family//[^A-Za-z0-9_.-]/-}"
    for profile in "${profile_list[@]}"; do
      safe_profile="${profile//[^A-Za-z0-9_.-]/-}"
      unique_suffix="$$"
      output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
      while [[ -e "$output_file" ]]; do
        unique_suffix="${unique_suffix}x"
        output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
      done

      python3 - "$output_file" "$target" "$repo" "$family" "$alias" "$profile" "$result_timestamp" <<'PY'
import json
import sys

output_file, target, repo, family, alias, profile, timestamp = sys.argv[1:]
result = {
    "target": target,
    "repo": repo,
    "family": family,
    "alias": alias,
    "profile": profile,
    "ctx": None,
    "batch": None,
    "ubatch": None,
    "ngl": None,
    "load_status": "not_run",
    "prompt_tok_s": None,
    "decode_tok_s": None,
    "command": "",
    "timestamp": timestamp,
}
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(result, handle, separators=(",", ":"))
    handle.write("\n")
PY

      printf 'Wrote benchmark result: %s\n' "$output_file"
    done
    return 0
  fi

  if [[ "$dry_run" != true ]]; then
    case "$target" in
      remote:*) ;;
      *)
        printf '%s\n' 'benchmark execution currently requires a remote:<host> target; use --dry-run for a plan' >&2
        return 2
        ;;
    esac

    if [[ "$full" == true ]]; then
      local trials_tsv=''
      local -a trial_matrix=(
        'speed|32768|256|256'
        'speed|32768|128|128'
        'balanced|49152|128|128'
        'balanced|49152|64|64'
        'reliable|65536|128|128'
        'reliable|65536|64|64'
        'tiny|65536|64|64'
      )
      local trial_number=0
      local trial_total="${#trial_matrix[@]}"
      local trial_spec trial_profile trial_ctx trial_batch trial_ubatch
      local benchmark_output line key value
      local load_status prompt_tok_s decode_tok_s prompt_tokens decode_tokens ctx batch ubatch ngl command_text log_file
      printf 'Full benchmark start\n'
      printf 'repo=%s\n' "$repo"
      printf 'family=%s\n' "$family"
      printf 'alias=%s\n' "$alias"
      printf 'target=%s\n' "$target"
      printf 'quant=%s\n' "$quant"
      if [[ -n "$hf_file" ]]; then
        printf 'hf_file=%s\n' "$hf_file"
      fi
      printf 'trials=%s\n' "$trial_total"
      for trial_spec in "${trial_matrix[@]}"; do
        IFS='|' read -r trial_profile trial_ctx trial_batch trial_ubatch <<<"$trial_spec"
        trial_number=$((trial_number + 1))
        printf 'running trial=%s/%s profile=%s ctx=%s batch=%s ubatch=%s ngl=999\n' \
          "$trial_number" "$trial_total" "$trial_profile" "$trial_ctx" "$trial_batch" "$trial_ubatch"
        benchmark_output="$(run_remote_benchmark "${target#remote:}" "$repo" "$family" "$alias" "$trial_profile" "$quant" "$hf_file" "$trial_ctx" "$trial_batch" "$trial_ubatch")"
        load_status=''
        prompt_tok_s=''
        decode_tok_s=''
        prompt_tokens=''
        decode_tokens=''
        ctx=''
        batch=''
        ubatch=''
        ngl=''
        command_text=''
        log_file=''
        while IFS= read -r line; do
          key="${line%%=*}"
          value="${line#*=}"
          case "$key" in
            load_status) load_status="$value" ;;
            prompt_tok_s) prompt_tok_s="$value" ;;
            decode_tok_s) decode_tok_s="$value" ;;
            prompt_tokens) prompt_tokens="$value" ;;
            decode_tokens) decode_tokens="$value" ;;
            ctx) ctx="$value" ;;
            batch) batch="$value" ;;
            ubatch) ubatch="$value" ;;
            ngl) ngl="$value" ;;
            command) command_text="$value" ;;
            log_file) log_file="$value" ;;
          esac
        done <<<"$benchmark_output"
        trials_tsv+="${trial_number}"$'\t'"${trial_profile}"$'\t'"${ctx:-$trial_ctx}"$'\t'"${batch:-$trial_batch}"$'\t'"${ubatch:-$trial_ubatch}"$'\t'"${ngl:-999}"$'\t'"${load_status:-unknown}"$'\t'"${prompt_tok_s}"$'\t'"${decode_tok_s}"$'\t'"${prompt_tokens}"$'\t'"${decode_tokens}"$'\t'"${command_text}"$'\t'"${log_file}"$'\n'
        printf 'trial=%s profile=%s ctx=%s batch=%s ubatch=%s load_status=%s prompt_tok_s=%s decode_tok_s=%s prompt_tokens=%s decode_tokens=%s\n' \
          "$trial_number" "$trial_profile" "${ctx:-$trial_ctx}" "${batch:-$trial_batch}" "${ubatch:-$trial_ubatch}" "${load_status:-unknown}" "${prompt_tok_s:-null}" "${decode_tok_s:-null}" "${prompt_tokens:-null}" "${decode_tokens:-null}"
      done

      local timestamp result_timestamp safe_family output_file unique_suffix recommendations_output
      timestamp="$(date +%Y%m%d-%H%M%S)"
      result_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      safe_family="${family//[^A-Za-z0-9_.-]/-}"
      unique_suffix="$$"
      output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-full-${unique_suffix}.json"
      while [[ -e "$output_file" ]]; do
        unique_suffix="${unique_suffix}x"
        output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-full-${unique_suffix}.json"
      done

      recommendations_output="$(
        TRIALS_TSV="$trials_tsv" python3 - "$output_file" "$target" "$repo" "$family" "$alias" "$quant" "$hf_file" "$result_timestamp" <<'PY'
import json
import os
import sys

output_file, target, repo, family, alias, quant, hf_file, timestamp = sys.argv[1:]
raw = os.environ.get("TRIALS_TSV", "").splitlines()

def integer(value):
    return int(value) if value else None

def number(value):
    return float(value) if value else None

trials = []
for line in raw:
    fields = line.split("\t")
    if len(fields) != 13:
        continue
    (
        trial,
        profile,
        ctx,
        batch,
        ubatch,
        ngl,
        load_status,
        prompt_tok_s,
        decode_tok_s,
        prompt_tokens,
        decode_tokens,
        command,
        log_file,
    ) = fields
    trials.append({
        "trial": integer(trial),
        "profile": profile,
        "ctx": integer(ctx),
        "batch": integer(batch),
        "ubatch": integer(ubatch),
        "ngl": integer(ngl),
        "load_status": load_status,
        "prompt_tok_s": number(prompt_tok_s),
        "decode_tok_s": number(decode_tok_s),
        "prompt_tokens": integer(prompt_tokens),
        "decode_tokens": integer(decode_tokens),
        "command": command,
        "log_file": log_file,
    })

successful = [
    trial for trial in trials
    if trial["load_status"] == "success"
    and trial.get("decode_tok_s") is not None
    and (trial.get("decode_tokens") or 0) >= 128
]

def copy_trial(trial):
    return dict(trial) if trial else None

profile_priority = {"reliable": 4, "balanced": 3, "speed": 2, "tiny": 1}
fastest = max(successful, key=lambda trial: trial["decode_tok_s"], default=None)
reliable = max(
    successful,
    key=lambda trial: ((trial["ctx"] or 0), profile_priority.get(trial["profile"], 0), trial["decode_tok_s"] or 0),
    default=None,
)
long_enough = [trial for trial in successful if (trial.get("ctx") or 0) >= 49152]
best = max(
    long_enough or successful,
    key=lambda trial: ((trial["ctx"] or 0), profile_priority.get(trial["profile"], 0), trial["decode_tok_s"] or 0),
    default=None,
)
recommendations = {
    "fastest-usable": copy_trial(fastest),
    "reliable-long-context": copy_trial(reliable),
    "best-overall": copy_trial(best),
}
payload = {
    "mode": "full",
    "target": target,
    "repo": repo,
    "family": family,
    "alias": alias,
    "quant": quant,
    "hf_file": hf_file or None,
    "timestamp": timestamp,
    "trials": trials,
    "recommendations": recommendations,
}
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
    handle.write("\n")
for name, trial in recommendations.items():
    if trial:
        print(f"recommendation={name} profile={trial['profile']} ctx={trial['ctx']} batch={trial['batch']} ubatch={trial['ubatch']} decode_tok_s={trial['decode_tok_s']}")
    else:
        print(f"recommendation={name} none")
PY
      )"
      printf 'Full benchmark result\n'
      printf 'repo=%s\n' "$repo"
      printf 'family=%s\n' "$family"
      printf 'alias=%s\n' "$alias"
      printf 'target=%s\n' "$target"
      printf '%s\n' "$recommendations_output"
      printf 'result_file=%s\n' "$output_file"
      return 0
    fi

    local benchmark_output
    local load_status=''
    local prompt_tok_s=''
    local decode_tok_s=''
    local prompt_tokens=''
    local decode_tokens=''
    local ctx=''
    local batch=''
    local ubatch=''
    local ngl=''
    local command_text=''
    local log_file=''
    local line key value
    benchmark_output="$(run_remote_benchmark "${target#remote:}" "$repo" "$family" "$alias" "${profile_list[0]}" "$quant" "$hf_file")"
    while IFS= read -r line; do
      key="${line%%=*}"
      value="${line#*=}"
      case "$key" in
        load_status) load_status="$value" ;;
        prompt_tok_s) prompt_tok_s="$value" ;;
        decode_tok_s) decode_tok_s="$value" ;;
        prompt_tokens) prompt_tokens="$value" ;;
        decode_tokens) decode_tokens="$value" ;;
        ctx) ctx="$value" ;;
        batch) batch="$value" ;;
        ubatch) ubatch="$value" ;;
        ngl) ngl="$value" ;;
        command) command_text="$value" ;;
        log_file) log_file="$value" ;;
      esac
    done <<<"$benchmark_output"

    local timestamp result_timestamp safe_family safe_profile output_file unique_suffix
    timestamp="$(date +%Y%m%d-%H%M%S)"
    result_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    safe_family="${family//[^A-Za-z0-9_.-]/-}"
    safe_profile="${profile_list[0]//[^A-Za-z0-9_.-]/-}"
    unique_suffix="$$"
    output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
    while [[ -e "$output_file" ]]; do
      unique_suffix="${unique_suffix}x"
      output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
    done

    python3 - "$output_file" "$target" "$repo" "$family" "$alias" "${profile_list[0]}" "$ctx" "$batch" "$ubatch" "$ngl" "$load_status" "$prompt_tok_s" "$decode_tok_s" "$prompt_tokens" "$decode_tokens" "$command_text" "$result_timestamp" <<'PY'
import json
import sys

(
    output_file,
    target,
    repo,
    family,
    alias,
    profile,
    ctx,
    batch,
    ubatch,
    ngl,
    load_status,
    prompt_tok_s,
    decode_tok_s,
    prompt_tokens,
    decode_tokens,
    command,
    timestamp,
) = sys.argv[1:]

def integer(value):
    return int(value) if value else None

def number(value):
    return float(value) if value else None

result = {
    "target": target,
    "repo": repo,
    "family": family,
    "alias": alias,
    "profile": profile,
    "ctx": integer(ctx),
    "batch": integer(batch),
    "ubatch": integer(ubatch),
    "ngl": integer(ngl),
    "load_status": load_status or "unknown",
    "prompt_tok_s": number(prompt_tok_s),
    "decode_tok_s": number(decode_tok_s),
    "prompt_tokens": integer(prompt_tokens),
    "decode_tokens": integer(decode_tokens),
    "command": command,
    "timestamp": timestamp,
}
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(result, handle, separators=(",", ":"))
    handle.write("\n")
PY

    if [[ "$load_status" == success && -n "$prompt_tok_s" && -n "$decode_tok_s" && -n "$decode_tokens" && "$decode_tokens" -ge 128 ]]; then
      printf 'Benchmark result\n'
    else
      printf 'Benchmark did not complete\n'
    fi
    printf 'repo=%s\n' "$repo"
    printf 'family=%s\n' "$family"
    printf 'alias=%s\n' "$alias"
    printf 'profile=%s\n' "${profile_list[0]}"
    printf 'target=%s\n' "$target"
    printf 'load_status=%s\n' "${load_status:-unknown}"
    printf 'prompt_tok_s=%s\n' "${prompt_tok_s:-null}"
    printf 'decode_tok_s=%s\n' "${decode_tok_s:-null}"
    printf 'prompt_tokens=%s\n' "${prompt_tokens:-null}"
    printf 'decode_tokens=%s\n' "${decode_tokens:-null}"
    if [[ "$load_status" != success || -z "$prompt_tok_s" || -z "$decode_tok_s" || -z "$decode_tokens" || "$decode_tokens" -lt 128 ]]; then
      printf 'reason=%s\n' 'model did not become ready or did not emit throughput metrics'
    fi
    printf 'log_file=%s\n' "${log_file:-unknown}"
    printf 'result_file=%s\n' "$output_file"
    return 0
  fi

  printf 'Benchmark plan\n'
  printf 'repo=%s\n' "$repo"
  printf 'family=%s\n' "$family"
  printf 'alias=%s\n' "$alias"
  printf 'profiles=%s\n' "$profiles"
  printf 'quant=%s\n' "$quant"
  if [[ -n "$hf_file" ]]; then
    printf 'hf_file=%s\n' "$hf_file"
  fi
  printf 'target=%s\n' "$target"
}

cmd_accept() {
  local benchmark_file=''
  local dry_run=false
  local json_fields
  local repo
  local family
  local alias
  local target
  local profile
  local start_script
  local max_start=0
  local start_path
  local start_name
  local start_number
  local start_value

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        dry_run=true
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      --*)
        printf 'Unknown accept option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        if [[ -n "$benchmark_file" ]]; then
          printf 'accept accepts one benchmark JSON file, got extra argument: %s\n' "$1" >&2
          return 2
        fi
        benchmark_file="$1"
        shift
        ;;
    esac
  done

  if [[ -z "$benchmark_file" ]]; then
    printf '%s\n' 'accept requires a benchmark JSON file' >&2
    return 2
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'python3 is required to parse benchmark JSON' >&2
    return 1
  fi

  if ! json_fields="$(
    python3 - "$benchmark_file" <<'PY'
import json
import os
import sys

path = sys.argv[1]
if not os.path.exists(path):
    raise SystemExit(f"benchmark JSON not found: {path}")
if not os.path.isfile(path):
    raise SystemExit(f"benchmark JSON is not a file: {path}")
try:
    with open(path, encoding="utf-8") as handle:
        result = json.load(handle)
except OSError as exc:
    raise SystemExit(f"benchmark JSON is unreadable: {path}: {exc}") from exc
except json.JSONDecodeError as exc:
    raise SystemExit(f"benchmark JSON is invalid: {path}: {exc}") from exc

if not isinstance(result, dict):
    raise SystemExit("benchmark JSON must be an object")

mode = result.get("mode", "quick")
if mode == "full":
    recommendation = result.get("recommendations", {}).get("best-overall")
    if not isinstance(recommendation, dict):
        raise SystemExit("full benchmark JSON missing recommendations.best-overall")
    merged = dict(result)
    merged.update(recommendation)
    result = merged

required = ("repo", "family", "alias", "target", "profile")
for key in required:
    if key not in result:
        raise SystemExit(f"benchmark JSON missing required field: {key}")
    if not isinstance(result[key], str):
        raise SystemExit(f"benchmark JSON field must be a string: {key}")
    if any(ord(char) < 32 or ord(char) == 127 for char in result[key]):
        raise SystemExit(f"benchmark JSON field contains a control character: {key}")

if result.get("load_status") != "success":
    raise SystemExit(f"benchmark JSON load_status is not success: {result.get('load_status')}")
for key in ("ctx", "batch", "ubatch", "ngl"):
    if key in result and not isinstance(result[key], int):
        raise SystemExit(f"benchmark JSON field must be an integer: {key}")
for key in ("quant", "hf_file"):
    if key in result and result[key] is not None and not isinstance(result[key], str):
        raise SystemExit(f"benchmark JSON field must be a string: {key}")
values = [result[key] for key in required]
values.extend(str(result.get(key) or "") for key in ("ctx", "batch", "ubatch", "ngl", "quant", "hf_file"))
print("\t".join(values))
PY
  )"; then
    return 1
  fi

  local ctx batch ubatch ngl quant hf_file
  IFS=$'\t' read -r repo family alias target profile ctx batch ubatch ngl quant hf_file <<<"$json_fields"

  local existing_launcher
  existing_launcher="$(find_existing_launcher "$repo" "$alias")"
  if [[ -n "$existing_launcher" ]]; then
    local removed_selection_count
    removed_selection_count="$(remove_matching_selections "$repo" "$alias")"
    local switcher_status
    switcher_status="$(ensure_switcher_model "$(infer_family "$repo")" "${existing_launcher%% *}" "$alias" "${alias//-/ }")"
    printf 'Accepted benchmark already has launcher\n'
    printf 'repo=%s\n' "$repo"
    printf 'family=%s\n' "$family"
    printf 'alias=%s\n' "$alias"
    printf 'target=%s\n' "$target"
    printf 'profile=%s\n' "$profile"
    printf 'start_script=%s\n' "${existing_launcher%% *}"
    printf 'removed_selection_count=%s\n' "$removed_selection_count"
    printf 'switcher_status=%s\n' "$switcher_status"
    return 0
  fi

  shopt -s nullglob
  for start_path in "$repo_root"/scripts/start*.sh; do
    start_name="${start_path##*/}"
    start_number="${start_name#start}"
    start_number="${start_number%.sh}"
    if [[ -n "$start_number" && "$start_number" != *[!0-9]* ]]; then
      start_value=$((10#$start_number))
      if ((start_value > max_start)); then
        max_start="$start_value"
      fi
    fi
  done
  shopt -u nullglob
  start_script="${LOCAL_LLM_ACCEPT_START_SCRIPT:-scripts/start$((max_start + 1)).sh}"

  if [[ "$dry_run" == true ]]; then
    printf 'Accept plan\n'
    printf 'repo=%s\n' "$repo"
    printf 'family=%s\n' "$family"
    printf 'alias=%s\n' "$alias"
    printf 'target=%s\n' "$target"
    printf 'profile=%s\n' "$profile"
    printf 'Dry-run actions:\n'
    printf 'would create %s\n' "$start_script"
    printf 'would update scripts/oc-local\n'
    printf 'would update installer.sh\n'
    printf 'would update README.md\n'
    printf 'would update test_oc_local.sh\n'
    return 0
  fi

  if [[ -e "$repo_root/$start_script" ]]; then
    printf 'accept start script already exists: %s\n' "$start_script" >&2
    return 1
  fi
  if [[ ! -d "$repo_root/scripts" ]]; then
    printf '%s\n' 'accept must be run from a local_llm source checkout so it can create scripts/start*.sh' >&2
    return 1
  fi

  python3 - "$repo_root/$start_script" "$repo" "$alias" "$ctx" "$batch" "$ubatch" "$ngl" "$quant" "$hf_file" <<'PY'
import shlex
import sys

path, repo, alias, ctx, batch, ubatch, ngl, quant, hf_file = sys.argv[1:]
for name, value in {"ctx": ctx, "batch": batch, "ubatch": ubatch, "ngl": ngl}.items():
    if not value.isdigit():
        raise SystemExit(f"missing numeric {name}")
lines = [
    "#!/usr/bin/env bash",
    "set -euo pipefail",
    'profile="${1:-reliable}"',
    'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *) echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac',
    f"ctx={ctx}",
    f"batch={batch}",
    f"ubatch={ubatch}",
    f"ngl={ngl}",
    "exec ./build/bin/llama-server \\",
    f"  -hf {shlex.quote(repo)} \\",
]
if hf_file:
    lines.append(f"  --hf-file {shlex.quote(hf_file)} \\")
else:
    lines[-1] = f"  -hf {shlex.quote(repo + ':' + quant)} \\\\"
lines.extend([
    "  --host 0.0.0.0 \\",
    "  --port 8080 \\",
    '  -ngl "$ngl" \\',
    '  -c "$ctx" \\',
    "  --flash-attn on \\",
    '  -ub "$ubatch" \\',
    '  -b "$batch" \\',
    '  --threads "$(nproc)" \\',
    "  --prio 2 \\",
    "  --no-warmup \\",
    "  --temp 0.6 \\",
    "  --top-p 0.95 \\",
    "  --top-k 20 \\",
    "  --min-p 0.0 \\",
    "  --presence-penalty 0.0 \\",
    f"  --alias {shlex.quote(alias)} \\",
    "  --reasoning off",
])
with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines))
    handle.write("\n")
PY
  chmod +x "$repo_root/$start_script"
  local removed_selection_count
  removed_selection_count="$(remove_matching_selections "$repo" "$alias")"
  local switcher_status
  switcher_status="$(ensure_switcher_model "$(infer_family "$repo")" "$start_script" "$alias" "${alias//-/ }")"

  printf 'Accepted benchmark\n'
  printf 'repo=%s\n' "$repo"
  printf 'family=%s\n' "$family"
  printf 'alias=%s\n' "$alias"
  printf 'target=%s\n' "$target"
  printf 'profile=%s\n' "$profile"
  printf 'ctx=%s\n' "$ctx"
  printf 'batch=%s\n' "$batch"
  printf 'ubatch=%s\n' "$ubatch"
  printf 'ngl=%s\n' "$ngl"
  printf 'start_script=%s\n' "$start_script"
  printf 'removed_selection_count=%s\n' "$removed_selection_count"
  printf 'switcher_status=%s\n' "$switcher_status"
}

main() {
  local command_name="${1:-}"

  case "$command_name" in
    -h | --help | '')
      usage
      ;;
    status)
      cmd_status
      ;;
    list)
      cmd_list "${@:2}"
      ;;
    update)
      cmd_update "${@:2}"
      ;;
    replace)
      cmd_replace "${@:2}"
      ;;
    delete)
      cmd_delete "${@:2}"
      ;;
    discover)
      cmd_discover "${@:2}"
      ;;
    select)
      cmd_select "${@:2}"
      ;;
    benchmark)
      cmd_benchmark "${@:2}"
      ;;
    accept)
      cmd_accept "${@:2}"
      ;;
    *)
      printf 'Unknown command: %s\n\n' "$command_name" >&2
      usage >&2
      return 1
      ;;
  esac
}

main "$@"
