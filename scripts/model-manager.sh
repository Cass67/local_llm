#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
# Single source of truth for profiles: the state dir the backend writes to.
PROFILES_JSON="${LOCAL_LLM_PROFILES_JSON:-${LOCAL_LLM_STATE_DIR:-$HOME/.local/share/local_llm}/profiles.json}"
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

# Python backend for new simplified commands
MODEL_MANAGER_PY="$SCRIPT_DIR/model_manager"
if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
  MODEL_MANAGER_PY="$repo_root/scripts/model_manager"
fi

if [[ -z "${LOCAL_LLM_RUNS_DIR:-}" && -n "${LOCAL_LLM_STATE_DIR:-}" ]]; then
  runs_dir="$LOCAL_LLM_STATE_DIR/runs"
else
  runs_dir="${LOCAL_LLM_RUNS_DIR:-$HOME/.local/share/local_llm/runs}"
fi
export LOCAL_LLM_RUNS_DIR="$runs_dir"
generated_launcher_dir="$runs_dir/launchers"

default_target() {
  # Env override
  if [[ -n "${OC_LOCAL_REMOTE_HOST:-}" ]]; then
    printf 'remote:%s\n' "$OC_LOCAL_REMOTE_HOST"
    return 0
  fi
  # Read from saved config (new: runs/config.json, legacy: runs/bootstrap/config.json)
  if [[ -f "$runs_dir/config.json" ]]; then
    local target
    target="$(python3 -c "import json; print(json.load(open('$runs_dir/config.json'))['target'])" 2>/dev/null)" || true
    if [[ -n "$target" ]]; then
      printf '%s\n' "$target"
      return 0
    fi
  fi
  if [[ -f "$runs_dir/bootstrap/config.json" ]]; then
    local target
    target="$(python3 -c "import json; print(json.load(open('$runs_dir/bootstrap/config.json'))['target'])" 2>/dev/null)" || true
    if [[ -n "$target" ]]; then
      printf '%s\n' "$target"
      return 0
    fi
  fi
  printf 'local\n'
}

usage() {
  cat <<'EOF'
Usage: model-manager <command> [options]

Simplified workflow:
  init      Set target once (replaces bootstrap)
  search    Search and score models (use with install)
  install   Install a model by index from search results

Full commands:
  bootstrap Bootstrap first-run model-manager state (legacy)
  list      Show accepted models
  accept    Accept a benchmark result and record model metadata
  update    Show cached model update suggestions
  replace   Replace a cached remote GGUF basename safely
  delete    Delete a repo from local metadata and remote GGUF cache
  export    Export local model-manager state as JSON
  restore   Restore local model-manager state from JSON
  status    Show model-manager status
  tui       Launch the terminal UI

Options:
  -h, --help  Show this help
EOF
  printf '\nRepository: %s\n' "$repo_root"
}

ensure_state_dir() {
  local dir="$1"
  local label="$2"

  if [[ -L "$dir" ]]; then
    printf 'model-manager refuses symlinked %s dir: %s\n' "$label" "$dir" >&2
    return 1
  fi
  if [[ -e "$dir" && ! -d "$dir" ]]; then
    printf 'model-manager state path is not a directory: %s\n' "$dir" >&2
    return 1
  fi
  mkdir -p "$dir"
  if [[ -L "$dir" ]]; then
    printf 'model-manager refuses symlinked %s dir: %s\n' "$label" "$dir" >&2
    return 1
  fi
}

reject_symlink_state_file() {
  local path="$1"

  if [[ -L "$path" ]]; then
    printf 'model-manager refuses symlinked state file: %s\n' "$path" >&2
    return 1
  fi
}

ensure_runs_dirs() {
  ensure_state_dir "$runs_dir" runs || return 1
  ensure_state_dir "$runs_dir/candidates" candidates || return 1
  ensure_state_dir "$runs_dir/selections" selections || return 1
  ensure_state_dir "$runs_dir/benchmarks" benchmarks || return 1
  ensure_state_dir "$runs_dir/replacements" replacements || return 1
  ensure_state_dir "$runs_dir/accepted" accepted || return 1
  ensure_state_dir "$generated_launcher_dir" launchers || return 1
}

print_bootstrap_plan() {
  local target="$1"

  printf 'Bootstrap plan\n'
  printf '==============\n'
  printf 'target=%s\n' "$target"
  printf 'runs_dir=%s\n' "$runs_dir"
  printf 'config=%s\n' "$runs_dir/bootstrap/config.json"
  printf 'next=model-manager search --target %s\n' "$target"
}

cmd_bootstrap() {
  local target
  target="$(default_target)"
  local dry_run=false
  local yes=false

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
        printf 'Unknown bootstrap option: %s\n' "$1" >&2
        return 2
        ;;
      *)
        printf 'Unexpected bootstrap argument: %s\n' "$1" >&2
        return 2
        ;;
    esac
  done

  if [[ "$dry_run" == true && "$yes" == true ]]; then
    printf '%s\n' 'choose either --dry-run or --yes, not both' >&2
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
      printf 'expected local or remote:<host>\n' >&2
      return 2
      ;;
  esac
  if [[ ! "$target" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    printf '%s\n' 'invalid target: use only letters, digits, dot, underscore, colon, and hyphen' >&2
    return 2
  fi

  print_bootstrap_plan "$target"

  if [[ "$yes" == true ]]; then
    ensure_state_dir "$runs_dir" runs || return 1
    ensure_state_dir "$runs_dir/bootstrap" bootstrap || return 1
    reject_symlink_state_file "$runs_dir/bootstrap/config.json" || return 1
    python3 - "$runs_dir/bootstrap/config.json" "$target" <<'PY'
import datetime
import json
import sys

path, target = sys.argv[1], sys.argv[2]
payload = {
    "target": target,
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
    printf 'wrote=%s\n' "$runs_dir/bootstrap/config.json"
  elif [[ "$dry_run" != true ]]; then
    printf 'hint=rerun with --yes to write bootstrap config\n'
  fi
}

cmd_export() {
  if (($# > 0)); then
    printf 'export accepts no arguments\n' >&2
    return 2
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'python3 is required to export model-manager state' >&2
    return 1
  fi
  if [[ -L "$runs_dir" ]]; then
    printf 'export refuses symlinked runs dir: %s\n' "$runs_dir" >&2
    return 1
  fi

  python3 - "$runs_dir" <<'PY'
import json
import os
import pathlib
import re
import stat
import sys

runs_dir = pathlib.Path(sys.argv[1])
runs_dir_resolved = runs_dir.resolve()
secret_re = re.compile(r"(token|secret|password|cookie|authorization|api[_-]?key|auth)", re.IGNORECASE)


def scrub(value):
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if not secret_re.search(str(key))}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def read_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return scrub(value)


def safe_file_name(path, suffix):
    name = path.name
    if name in {"", ".", ".."} or name != pathlib.PurePath(name).name:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+" + re.escape(suffix), name))


payload = {"version": 1}
bootstrap_dir = runs_dir / "bootstrap"
bootstrap_path = runs_dir / "bootstrap" / "config.json"
if bootstrap_dir.is_dir() and not bootstrap_dir.is_symlink() and bootstrap_path.is_file() and not bootstrap_path.is_symlink():
    try:
        bootstrap_resolved = bootstrap_path.resolve()
        bootstrap_within_runs = os.path.commonpath([str(runs_dir_resolved), str(bootstrap_resolved)]) == str(runs_dir_resolved)
    except OSError:
        bootstrap_within_runs = False
    if bootstrap_within_runs:
        bootstrap = read_json(bootstrap_path)
        if isinstance(bootstrap, dict):
            payload["bootstrap"] = bootstrap

accepted = {}
accepted_dir = runs_dir / "accepted"
if accepted_dir.is_dir() and not accepted_dir.is_symlink():
    for path in sorted(accepted_dir.glob("*.json")):
        if path.is_symlink():
            continue
        if not safe_file_name(path, ".json"):
            continue
        value = read_json(path)
        if isinstance(value, dict):
            accepted[path.name] = value
payload["accepted"] = accepted

launchers = {}
launcher_dir = runs_dir / "launchers"
if launcher_dir.is_dir() and not launcher_dir.is_symlink():
    for path in sorted(launcher_dir.glob("*.sh")):
        if path.is_symlink():
            continue
        if not safe_file_name(path, ".sh"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode
        except OSError:
            continue
        if secret_re.search(content):
            launchers[path.name] = {"omitted": "secret-like content"}
            continue
        launchers[path.name] = {
            "content": content,
            "executable": bool(mode & stat.S_IXUSR),
        }
payload["launchers"] = launchers

json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
}

cmd_restore() {
  local backup_file="${1:-}"
  if [[ -z "$backup_file" || $# -ne 1 ]]; then
    printf 'restore requires one backup JSON file\n' >&2
    return 2
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'python3 is required to restore model-manager state' >&2
    return 1
  fi

  python3 - "$runs_dir" "$backup_file" <<'PY'
import json
import os
import pathlib
import re
import sys

runs_dir_input = pathlib.Path(sys.argv[1])
backup_file = pathlib.Path(sys.argv[2])
secret_re = re.compile(r"(token|secret|password|cookie|authorization|api[_-]?key|auth)", re.IGNORECASE)


def fail(message):
    raise SystemExit(message)


if runs_dir_input.is_symlink():
    fail(f"restore refuses symlinked runs dir: {runs_dir_input}")
runs_dir = pathlib.Path(os.path.abspath(runs_dir_input))


def safe_name(name, suffix, label):
    if not isinstance(name, str):
        fail(f"unsafe {label} name")
    if name in {"", ".", ".."} or pathlib.PurePosixPath(name).name != name or pathlib.PurePath(name).name != name:
        fail(f"unsafe {label} name: {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+" + re.escape(suffix), name):
        fail(f"unsafe {label} name: {name!r}")
    return name


def target_path(parent, name):
    path = runs_dir / parent / name
    allowed = runs_dir / parent
    try:
        if os.path.commonpath([str(allowed), str(path)]) != str(allowed):
            fail(f"restore path escapes runs dir: {name!r}")
    except ValueError:
        fail(f"restore path escapes runs dir: {name!r}")
    return path


def validate_runs_write_target(path, file_label):
    path = pathlib.Path(os.path.abspath(path))
    try:
        relative_parent = path.parent.relative_to(runs_dir)
    except ValueError:
        fail(f"restore path escapes runs dir: {path}")

    current = runs_dir
    for component in relative_parent.parts:
        current = current / component
        if current.is_symlink():
            fail(f"restore refuses symlinked runs path component: {current}")
        if current.exists() and not current.is_dir():
            fail(f"restore target parent is not a directory: {current}")
    if path.is_symlink():
        fail(f"restore refuses symlinked {file_label} file: {path}")

    try:
        real_runs = runs_dir.resolve(strict=False)
        real_path = path.resolve(strict=False)
        if os.path.commonpath([str(real_runs), str(real_path)]) != str(real_runs):
            fail(f"restore path escapes runs dir: {path}")
    except OSError as exc:
        fail(f"restore path is invalid: {path}: {exc}")


def validate_restore_dir(parent):
    path = runs_dir / parent
    if path.is_symlink():
        fail(f"restore refuses symlinked {parent} dir")
    if path.exists() and not path.is_dir():
        fail(f"restore target is not a directory: {parent}")
    real_runs = runs_dir.resolve(strict=False)
    resolved = path.resolve()
    if os.path.commonpath([str(real_runs), str(resolved)]) != str(real_runs):
        fail(f"restore dir escapes runs dir: {parent}")


def validate_no_secret_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if secret_re.search(str(key)):
                fail("backup contains secret-like key")
            validate_no_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            validate_no_secret_keys(item)


def normalize_accepted_integer(value, label, *, minimum):
    if isinstance(value, bool):
        fail(f"accepted config field must be an integer: {label}")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        parsed = int(value)
    else:
        fail(f"accepted config field must be an integer: {label}")
    if parsed < minimum:
        if minimum == 1:
            fail(f"accepted config field must be a positive integer: {label}")
        fail(f"accepted config field must be a non-negative integer: {label}")
    return parsed


def normalize_accepted_numeric_fields(entry, entry_name, container_name, container):
    if not isinstance(container, dict):
        fail(f"accepted {container_name} must be an object: {entry_name}")
    for key in ("ctx", "context", "batch", "ubatch"):
        if key in container:
            container[key] = normalize_accepted_integer(container[key], f"{entry_name} {container_name}.{key}", minimum=1)
    if "ngl" in container:
        container["ngl"] = normalize_accepted_integer(container["ngl"], f"{entry_name} {container_name}.ngl", minimum=0)


def has_control_chars(value):
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def safe_generated_basename(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", value)) and ".." not in value and not value.startswith("-")


def validate_safe_identifier(value, label, entry_name):
    if not isinstance(value, str) or not safe_generated_basename(value):
        fail(f"accepted {label} must be safe: {entry_name}")


def validate_no_control_chars(value, label, entry_name, *, require_nonempty=False):
    if not isinstance(value, str):
        fail(f"accepted {label} must be a string: {entry_name}")
    if require_nonempty and not value:
        fail(f"accepted {label} must be nonempty: {entry_name}")
    if has_control_chars(value):
        fail(f"accepted {label} must not contain control characters: {entry_name}")


def validate_remote_start(value, entry_name):
    if not isinstance(value, str):
        fail(f"accepted remote_start must be a safe relative launcher path: {entry_name}")
    match = re.fullmatch(r"\./([A-Za-z0-9_.-]+\.sh)", value)
    if not match or not safe_generated_basename(match.group(1)):
        fail(f"accepted remote_start must be a safe relative launcher path: {entry_name}")
    return match.group(1)


def validate_accepted_entry(entry_name, value):
    launcher_basename = None
    if "family" in value:
        validate_safe_identifier(value["family"], "family", entry_name)
    for key in ("alias", "model_name"):
        if key in value:
            validate_safe_identifier(value[key], key, entry_name)
    if "repo" not in value:
        fail(f"accepted repo must be nonempty: {entry_name}")
    for key in ("repo", "hf_repo"):
        if key in value:
            validate_no_control_chars(value[key], key, entry_name, require_nonempty=True)
    for key in ("hf_file", "quant"):
        if key in value:
            validate_no_control_chars(value[key], key, entry_name)
    if "remote_start" in value:
        launcher_basename = validate_remote_start(value["remote_start"], entry_name)
    if "launcher_file" in value:
        launcher_file = value["launcher_file"]
        validate_no_control_chars(launcher_file, "launcher_file", entry_name, require_nonempty=True)
        launcher_file_basename = pathlib.PurePath(launcher_file).name
        if not launcher_basename:
            launcher_basename = validate_remote_start("./" + launcher_file_basename, entry_name)
        if launcher_file_basename != launcher_basename:
            fail(f"accepted launcher_file must match remote_start basename: {entry_name}")
        value["launcher_file"] = str(runs_dir / "launchers" / launcher_basename)
    config = value.get("config")
    if config is not None:
        normalize_accepted_numeric_fields(value, entry_name, "config", config)
    profiles = value.get("profiles")
    if profiles is not None:
        if not isinstance(profiles, dict):
            fail(f"accepted profiles must be an object: {entry_name}")
        for profile_name, profile_config in profiles.items():
            if not isinstance(profile_name, str):
                fail(f"accepted profile name must be a string: {entry_name}")
            normalize_accepted_numeric_fields(value, entry_name, f"profiles.{profile_name}", profile_config)


try:
    with backup_file.open(encoding="utf-8") as handle:
        payload = json.load(handle)
except OSError as exc:
    fail(f"backup JSON is unreadable: {exc}")
except json.JSONDecodeError as exc:
    fail(f"backup JSON is invalid: {exc}")

if not isinstance(payload, dict):
    fail("backup JSON must be an object")
if payload.get("version") != 1:
    fail("backup JSON has unsupported version")
validate_no_secret_keys(payload)
validate_restore_dir("bootstrap")
validate_restore_dir("accepted")
validate_restore_dir("launchers")

bootstrap = payload.get("bootstrap")
bootstrap_write = None
if bootstrap is not None:
    if not isinstance(bootstrap, dict):
        fail("bootstrap must be an object")
    bootstrap_write = (target_path("bootstrap", "config.json"), bootstrap)

accepted = payload.get("accepted", {})
if not isinstance(accepted, dict):
    fail("accepted must be an object")
accepted_writes = []
for name, value in sorted(accepted.items()):
    name = safe_name(name, ".json", "accepted")
    if not isinstance(value, dict):
        fail(f"accepted entry must be an object: {name}")
    validate_accepted_entry(name, value)
    accepted_writes.append((target_path("accepted", name), value))

launchers = payload.get("launchers", {})
if not isinstance(launchers, dict):
    fail("launchers must be an object")
launcher_writes = []
for name, value in sorted(launchers.items()):
    name = safe_name(name, ".sh", "launcher")
    if not isinstance(value, dict):
        fail(f"launcher entry must be an object: {name}")
    content = value.get("content")
    if content is None:
        continue
    if not isinstance(content, str):
        fail(f"launcher content must be a string: {name}")
    if secret_re.search(content):
        fail(f"launcher contains secret-like content: {name}")
    executable = value.get("executable", True)
    if not isinstance(executable, bool):
        fail(f"launcher executable must be a boolean: {name}")
    launcher_writes.append((target_path("launchers", name), content, executable))

if bootstrap_write is not None:
    validate_runs_write_target(bootstrap_write[0], "state")
for path, _value in accepted_writes:
    validate_runs_write_target(path, "state")
for path, _content, _executable in launcher_writes:
    validate_runs_write_target(path, "launcher")

if bootstrap_write is not None:
    path, value = bootstrap_write
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")

for path, value in accepted_writes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")

for path, content, executable in launcher_writes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(0o755 if executable else 0o644)

print(f"restored={runs_dir}")
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

find_accepted_metadata_by_repo() {
  local repo="$1"
  python3 - "$runs_dir/accepted" "$repo" <<'PY'
import json
import pathlib
import sys

accepted_dir = pathlib.Path(sys.argv[1])
repo = sys.argv[2]
for path in sorted(accepted_dir.glob("*.json")):
    if path.name == "default.json" or path.is_symlink():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if isinstance(data, dict) and data.get("repo") == repo:
        family = data.get("family") or path.stem
        launcher_file = data.get("launcher_file") or ""
        alias = data.get("alias") or data.get("model_name") or ""
        print(f"family={family}")
        print(f"launcher_file={launcher_file}")
        print(f"alias={alias}")
        raise SystemExit(0)
PY
}

remove_accepted_metadata_by_family() {
  local family="$1"
  local accepted_file="$runs_dir/accepted/$family.json"
  if [[ -f "$accepted_file" && ! -L "$accepted_file" ]]; then
    rm -f -- "$accepted_file"
    printf '1\n'
  else
    printf '0\n'
  fi
}

remove_accepted_default_if_matches() {
  local family="$1"
  local default_file="$runs_dir/accepted/default.json"
  [[ -f "$default_file" && ! -L "$default_file" ]] || return 0
  python3 - "$default_file" "$family" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
family = sys.argv[2]
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)
if isinstance(data, dict) and data.get("family") == family:
    path.unlink()
PY
}

run_remote_delete_repo_cache() {
  local host="$1"
  local repo="$2"
  local mode="$3"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" python3 - "$repo" "$mode" <<'PY'
import json
import os
import re
import shutil
import subprocess
import sys

repo, mode = sys.argv[1:]
home = os.path.expanduser("~")
hf_root = os.path.join(home, ".cache", "huggingface", "hub")
file_roots = [
    os.path.join(home, ".cache", "local_llm", "models"),
    os.path.join(home, ".cache", "llama.cpp"),
]
deleted = 0
planned = 0
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo):
    raise SystemExit("remote delete requires a Hugging Face repo id like owner/model")

repo_cache_name = "models--" + repo.replace("/", "--")
repo_cache_path = os.path.join(hf_root, repo_cache_name)
if os.path.isdir(repo_cache_path):
    hf_root_real = os.path.realpath(hf_root)
    repo_cache_real = os.path.realpath(repo_cache_path)
    if os.path.dirname(repo_cache_real) != hf_root_real:
        raise SystemExit("refusing to delete cache path outside Hugging Face hub root")
    if os.path.basename(repo_cache_real) != repo_cache_name:
        raise SystemExit("refusing to delete unexpected Hugging Face cache basename")
    if os.path.islink(repo_cache_path):
        raise SystemExit("refusing to delete symlinked Hugging Face cache directory")
    planned += 1
    print(json.dumps({"repo": repo, "kind": "hf_repo_cache", "path": repo_cache_path, "action": mode}, separators=(",", ":")))
    if mode == "delete":
        try:
            shutil.rmtree(repo_cache_path)
        except PermissionError:
            subprocess.run(["sudo", "rm", "-rf", "--", repo_cache_path], check=True)
        deleted += 1

for root in file_roots:
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
            print(json.dumps({"repo": found_repo, "kind": "gguf_file", "file": name, "path": path, "action": mode}, separators=(",", ":")))
            if mode == "delete":
                try:
                    os.remove(path)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-f", "--", path], check=True)
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

cmd_update() {
  local target
  target="$(default_target)"
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
  reject_symlink_state_file "$output_file" || return 1

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
  local target
  target="$(default_target)"
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

  local removed_selections removed_switcher meta_info family launcher_file removed_accepted
  meta_info="$(find_accepted_metadata_by_repo "$repo")"
  family=""
  launcher_file=""
  if [[ -n "$meta_info" ]]; then
    family="$(printf '%s\n' "$meta_info" | awk -F= '$1=="family"{print $2; exit}')"
    launcher_file="$(printf '%s\n' "$meta_info" | awk -F= '$1=="launcher_file"{print $2; exit}')"
  fi
  removed_selections="$(remove_selection_repo_entries "$repo")"
  removed_switcher="$(remove_switcher_repo_entries "$repo" "$alias")"
  removed_accepted=0
  if [[ -n "$family" ]]; then
    removed_accepted="$(remove_accepted_metadata_by_family "$family")"
    remove_accepted_default_if_matches "$family"
    remove_switcher_family_entries "$family" >/dev/null || true
    remove_oc_local_family_entries "$family" >/dev/null || true
    if [[ -n "$launcher_file" && -f "$launcher_file" && ! -L "$launcher_file" ]]; then
      rm -f -- "$launcher_file"
    fi
  fi
  printf 'removed_selection_count=%s\n' "$removed_selections"
  printf 'removed_switcher_count=%s\n' "$removed_switcher"
  printf 'removed_accepted_count=%s\n' "$removed_accepted"
  printf 'remote_cache_delete:\n'
  run_remote_delete_repo_cache "${target#remote:}" "$repo" delete
}

cmd_delete_profile() {
  local profile_pattern="$1"
  local target="$2"
  local dry_run="$3"
  local yes="$4"
  local profiles_json="$PROFILES_JSON"

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

infer_slug_from_repo() {
  local name
  name="${1##*/}"
  name="${name%-GGUF}"
  name="${name%-gguf}"
  printf '%s\n' "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//'
}

infer_alias() {
  infer_slug_from_repo "$1"
}

benchmark_hardware_json() {
  local target="$1"
  local vram=''
  case "$target" in
    remote:*)
      vram="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${target#remote:}" 'total=0; for f in /sys/class/drm/card*/device/mem_info_vram_total; do [ -r "$f" ] && total=$((total + $(cat "$f"))); done; [ "$total" -gt 0 ] && echo "$total"' 2>/dev/null || true)"
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

main() {
  local command_name="${1:-}"

  case "$command_name" in
    -h | --help | '')
      usage
      ;;
    init)
      # New simplified init — delegates to Python backend
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager init "${@:2}"
      ;;
    search)
      # Delegates to Python backend
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager search "${@:2}"
      ;;
    install)
      # New simplified install — delegates to Python backend
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager install "${@:2}"
      ;;
    bootstrap)
      cmd_bootstrap "${@:2}"
      ;;
    status)
      # Delegates to Python backend (reads both new and legacy state)
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager status "${@:2}"
      ;;
    list)
      # Delegates to Python backend (reads both new and legacy state)
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager list "${@:2}"
      ;;
    accept)
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager accept "${@:2}"
      ;;
    update)
      cmd_update "${@:2}"
      ;;
    replace)
      cmd_replace "${@:2}"
      ;;
    delete)
      # Use bash implementation: full purge supports repo, profiles, remote cache, launchers.
      cmd_delete "${@:2}"
      ;;
    export)
      cmd_export "${@:2}"
      ;;
    restore)
      cmd_restore "${@:2}"
      ;;
    tui)
      # Launch interactive TUI
      if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
        printf 'Python backend not found at %s\n' "$MODEL_MANAGER_PY" >&2
        return 1
      fi
      python3 -m scripts.model_manager tui
      ;;
    *)
      printf 'Unknown command: %s\n\n' "$command_name" >&2
      usage >&2
      return 1
      ;;
  esac
}

main "$@"
