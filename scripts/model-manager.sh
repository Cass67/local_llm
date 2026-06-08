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

# Python backend for new simplified commands
MODEL_MANAGER_PY="$SCRIPT_DIR/model_manager"
if [[ ! -d "$MODEL_MANAGER_PY" ]]; then
	MODEL_MANAGER_PY="$repo_root/scripts/model_manager"
fi

runs_dir="${LOCAL_LLM_RUNS_DIR:-$HOME/.local/share/local_llm/runs}"
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
  list      Show installed and cached models
  update    Show cached model update suggestions
  replace   Replace a cached remote GGUF basename safely
  delete    Delete a repo from local metadata and remote GGUF cache
  discover   Find candidate models
  select     Select a candidate model (legacy — install replaces this)
  benchmark  Benchmark a selected model
  accept     Accept benchmark results
  deploy           Preview generated state deployment
  update-launcher  Regenerate launcher for an accepted model
  export           Export local model-manager state as JSON
  restore          Restore local model-manager state from JSON
  status           Show model-manager status

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

validate_launcher_write_target() {
	local path="$1"

	python3 - "$runs_dir" "$generated_launcher_dir" "$path" <<'PY'
import os
import pathlib
import sys

runs_dir = pathlib.Path(sys.argv[1])
launcher_dir = pathlib.Path(sys.argv[2])
target = pathlib.Path(sys.argv[3])


def fail(message):
    raise SystemExit(message)


if runs_dir.is_symlink():
    fail(f"model-manager refuses symlinked runs dir: {runs_dir}")

runs_abs = pathlib.Path(os.path.abspath(runs_dir))
launcher_abs = pathlib.Path(os.path.abspath(launcher_dir))
target_abs = pathlib.Path(os.path.abspath(target))
parent_abs = target_abs.parent

try:
    if os.path.commonpath([str(launcher_abs), str(target_abs)]) != str(launcher_abs):
        fail(f"model-manager launcher path must be under runs launchers dir: {target}")
except ValueError:
    fail(f"model-manager launcher path must be under runs launchers dir: {target}")

try:
    relative_parent = parent_abs.relative_to(runs_abs)
except ValueError:
    fail(f"model-manager launcher path must be under runs dir: {target}")

current = runs_abs
for component in relative_parent.parts:
    current = current / component
    if current.is_symlink():
        fail(f"model-manager refuses symlinked runs path component: {current}")
    if current.exists() and not current.is_dir():
        fail(f"model-manager launcher parent path is not a directory: {current}")

if target_abs.is_symlink():
    fail(f"model-manager refuses symlinked launcher file: {target}")

try:
    real_launcher_dir = launcher_abs.resolve(strict=False)
    real_target = target_abs.resolve(strict=False)
    if os.path.commonpath([str(real_launcher_dir), str(real_target)]) != str(real_launcher_dir):
        fail(f"model-manager launcher path escapes runs launchers dir: {target}")
except OSError as exc:
    fail(f"model-manager launcher path is invalid: {target}: {exc}")
PY
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

is_safe_generated_name() {
	local value="$1"
	[[ "$value" =~ ^[A-Za-z0-9_.-]+$ && "$value" != *..* && "$value" != -* ]]
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

print_bootstrap_plan() {
	local target="$1"

	printf 'Bootstrap plan\n'
	printf '==============\n'
	printf 'target=%s\n' "$target"
	printf 'runs_dir=%s\n' "$runs_dir"
	printf 'config=%s\n' "$runs_dir/bootstrap/config.json"
	printf 'next=model-manager discover --target %s\n' "$target"
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
import re
import shlex
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
	print_generated_launcher_inventory
}

print_generated_launcher_inventory() {
	local -a launcher_files=()

	if [[ -d "$generated_launcher_dir" ]]; then
		shopt -s nullglob
		launcher_files=("$generated_launcher_dir"/start*.sh)
		shopt -u nullglob
	fi

	((${#launcher_files[@]} > 0)) || return 0

	python3 - "${launcher_files[@]}" <<'PY'
import re
import shlex
import sys
from pathlib import Path


def infer_family(repo):
    name = repo.lower()
    if "qwen" in name and "coder" in name:
        return "qwen-coder"
    if "qwen" in name:
        return "qwen"
    if "gemma" in name:
        return "gemma"
    if "gpt-oss" in name:
        return "gpt-oss"
    if "deepseek" in name:
        return "deepseek-r1"
    return "generated"


for arg in sys.argv[1:]:
    path = Path(arg)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        continue

    metadata = {}
    for line in text.splitlines():
        if line.startswith("# local_llm_"):
            key, sep, value = line[2:].partition("=")
            if sep:
                metadata[key.removeprefix("local_llm_")] = value

    repo = metadata.get("repo") or ""
    alias = metadata.get("alias") or ""
    quant = metadata.get("hf_file") or metadata.get("quant") or ""
    family = metadata.get("family") or ""

    if not repo:
        match = re.search(r"^\s*-hf\s+(.+?)\s+\\$", text, re.MULTILINE)
        if match:
            try:
                tokens = shlex.split(match.group(1))
            except ValueError:
                tokens = []
            if tokens:
                repo = tokens[0]
                if ":" in repo:
                    repo, quant = repo.rsplit(":", 1)
    if not alias:
        match = re.search(r"^\s*--alias\s+(.+?)\s+\\$", text, re.MULTILINE)
        if match:
            try:
                tokens = shlex.split(match.group(1))
            except ValueError:
                tokens = []
            if tokens:
                alias = tokens[0]

    if not repo or not alias:
        continue
    if not family:
        family = infer_family(repo)

    parts = [f"launcher family={family}", f"repo={repo}", f"alias={alias}", f"remote_start={path}"]
    if quant:
        parts.append(f"quant={quant}")
    print(" ".join(parts))
PY
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
	: "$1" "$2"
	return 0
}

find_existing_accepted_launcher() {
	local repo="$1"
	local family="$2"
	local alias="$3"
	local metadata_file="$runs_dir/accepted/$family.json"

	[[ -f "$metadata_file" ]] || return 0
	reject_symlink_state_file "$metadata_file" || return 1
	python3 - "$metadata_file" "$repo" "$family" "$alias" "$generated_launcher_dir" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
repo, family, alias, launcher_dir = sys.argv[2:]

try:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"accepted metadata is invalid: {path}: {exc}") from exc

if not isinstance(data, dict):
    raise SystemExit(f"accepted metadata must be an object: {path}")

metadata_family = data.get("family") or family
if not isinstance(metadata_family, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", metadata_family) or ".." in metadata_family or metadata_family.startswith("-"):
    raise SystemExit(f"accepted metadata contains unsafe family: {path}")
if metadata_family != family:
    raise SystemExit(0)

metadata_repo = data.get("repo") or data.get("hf_repo")
metadata_alias = data.get("alias") or data.get("model_name")
if not isinstance(metadata_alias, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", metadata_alias) or ".." in metadata_alias or metadata_alias.startswith("-"):
    raise SystemExit(f"accepted metadata contains unsafe alias: {path}")
if metadata_repo != repo:
    raise SystemExit(0)
if metadata_alias != alias:
    raise SystemExit(
        f"accepted metadata alias mismatch for family {family}: "
        f"existing_alias={metadata_alias!s} requested_alias={alias}. "
        "Delete the existing accepted metadata before accepting a different alias."
    )

launcher_file = data.get("launcher_file")
if isinstance(launcher_file, str) and launcher_file:
    print(launcher_file)
    raise SystemExit(0)

remote_start = data.get("remote_start")
if isinstance(remote_start, str) and re.fullmatch(r"\./[A-Za-z0-9_.-]+\.sh", remote_start):
    print(str(pathlib.Path(launcher_dir) / pathlib.PurePosixPath(remote_start).name))
PY
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

update_existing_launcher_runtime() {
	local launcher_file="$1"
	local ctx="$2"
	local batch="$3"
	local ubatch="$4"
	local ngl="$5"
	local tensor_split="${6:-}"

	[[ -f "$launcher_file" && ! -L "$launcher_file" ]] || return 0
	python3 - "$launcher_file" "$ctx" "$batch" "$ubatch" "$ngl" "$tensor_split" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
ctx, batch, ubatch, ngl, tensor_split = sys.argv[2:]
for name, value in {"ctx": ctx, "batch": batch, "ubatch": ubatch, "ngl": ngl}.items():
    if not re.fullmatch(r"[0-9]+", value):
        raise SystemExit(f"invalid {name}")
if tensor_split and not re.fullmatch(r"[1-9][0-9]*(,[1-9][0-9]*)*", tensor_split):
    raise SystemExit("invalid tensor_split")
text = path.read_text(encoding="utf-8")
for name, value in (("ctx", ctx), ("batch", batch), ("ubatch", ubatch), ("ngl", ngl)):
    text = re.sub(rf"^{name}=[0-9]+$", f"{name}={value}", text, flags=re.MULTILINE)
if tensor_split:
    text = re.sub(
        r"--tensor-split [^ \\\n]+",
        f"--tensor-split {tensor_split}",
        text,
    )
path.write_text(text, encoding="utf-8")
PY
}

ensure_launcher_model_log_redirect() {
	local launcher_file="$1"

	[[ -f "$launcher_file" && ! -L "$launcher_file" ]] || return 0
	python3 - "$launcher_file" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
needle = "set -euo pipefail\n"
awk_filter = "!/stopping wait for next result due to should_stop condition/ && !/ref: https:\\/\\/github.com\\/ggml-org\\/llama.cpp\\/pull\\/22907/ && !/stop: cancel task/ && !/create_check/ && !/erased invalidated context checkpoint/ && !/creating new checkpoint during processing/ && !/forcing full prompt re-processing due to lack of cache data/ && !/slot print_timing:.*prompt processing/"
exec_line = f"exec > >(stdbuf -oL -eL awk '{awk_filter}' | tee \"$log_file\") 2>&1"
if "exec > >(stdbuf -oL -eL awk " in text:
    text = re.sub(r"^exec > >\(stdbuf -oL -eL awk '.*' \| tee \"\$log_file\"\) 2>&1$", exec_line, text, count=1, flags=re.MULTILINE)
elif 'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"' in text:
    text = text.replace('mkdir -p "$(dirname "$log_file")"\n', 'mkdir -p "$(dirname "$log_file")"\n' + exec_line + "\n", 1)
else:
    insert = (
        'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"\n'
        'mkdir -p "$(dirname "$log_file")"\n'
        f'{exec_line}\n'
    )
    if needle not in text:
        raise SystemExit(f"launcher is missing expected shell strict-mode line: {path}")
    text = text.replace(needle, needle + insert, 1)
path.write_text(text, encoding="utf-8")
PY
	chmod +x "$launcher_file"
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

write_accepted_metadata() {
	local repo="$1"
	local family="$2"
	local alias="$3"
	local launcher_file="$4"
	local profile="$5"
	local ctx="$6"
	local batch="$7"
	local ubatch="$8"
	local ngl="$9"
	local quant="${10}"
	local hf_file="${11}"
	local backend="${12:-}"
	local visible_devices="${13:-}"
	local split_mode="${14:-}"
	local tensor_split="${15:-}"
	local cache_type_k="${16:-}"
	local cache_type_v="${17:-}"
	local ctx_shift="${18:-}"
	local target="${19:-}"

	ensure_state_dir "$runs_dir/accepted" accepted || return 1
	python3 - "$runs_dir/accepted" "$repo" "$family" "$alias" "$launcher_file" "$profile" "$ctx" "$batch" "$ubatch" "$ngl" "$quant" "$hf_file" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$cache_type_k" "$cache_type_v" "$ctx_shift" "$target" <<'PY'
import json
import os
import pathlib
import re
import sys
from pathlib import Path

accepted_dir = Path(sys.argv[1])
repo, family, alias, launcher_file, profile, ctx, batch, ubatch, ngl, quant, hf_file, backend, visible_devices, split_mode, tensor_split, cache_type_k, cache_type_v, ctx_shift, target = sys.argv[2:]
if not re.fullmatch(r"[A-Za-z0-9_.-]+", family) or ".." in family or family.startswith("-"):
    raise SystemExit("model-manager refuses unsafe family")
if not re.fullmatch(r"[A-Za-z0-9_.-]+", alias) or ".." in alias or alias.startswith("-"):
    raise SystemExit("model-manager refuses unsafe alias")
for name, value in (("repo", repo), ("launcher_file", launcher_file), ("profile", profile), ("quant", quant), ("hf_file", hf_file), ("cache_type_k", cache_type_k), ("cache_type_v", cache_type_v), ("ctx_shift", ctx_shift), ("target", target)):
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SystemExit(f"accepted metadata field contains a control character: {name}")
    if name in {"cache_type_k", "cache_type_v"} and value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SystemExit(f"accepted metadata field contains an unsafe cache type: {name}")
path = accepted_dir / f"{family}.json"
remote_start = "./" + pathlib.PurePosixPath(launcher_file).name
if path.is_symlink():
    raise SystemExit(f"model-manager refuses symlinked state file: {path}")

def accepted_integer(name, value, *, minimum):
    if value == "":
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise SystemExit(f"accepted metadata field must be numeric: {name}")
    parsed = int(value)
    if parsed < minimum:
        if minimum == 1:
            raise SystemExit(f"accepted metadata field must be positive: {name}")
        raise SystemExit(f"accepted metadata field must be non-negative: {name}")
    return parsed

payload = {
    "repo": repo,
    "hf_repo": repo,
    "family": family,
    "alias": alias,
    "model_name": alias,
    "remote_start": remote_start,
    "launcher_file": launcher_file,
    "hf_file": hf_file,
    "quant": quant,
    "profile": profile,
    "reasoning": True,
    "config": {"reasoning": True},
}
for key, value, minimum in (("ctx", ctx, 1), ("batch", batch, 1), ("ubatch", ubatch, 1), ("ngl", ngl, 0)):
    parsed = accepted_integer(key, value, minimum=minimum)
    if parsed is not None:
        payload["config"][key] = parsed
if cache_type_k:
    payload["config"]["cache_type_k"] = cache_type_k
if cache_type_v:
    payload["config"]["cache_type_v"] = cache_type_v
if target:
    if not re.fullmatch(r"local|remote:[A-Za-z0-9_.:-]+", target):
        raise SystemExit("accepted metadata target must be local or remote:<host>")
    payload["target"] = target
if ctx_shift:
    if ctx_shift not in {"on", "true", "1", "off", "false", "0"} and not re.fullmatch(r"[0-9]+", ctx_shift):
        raise SystemExit("accepted metadata ctx_shift must be on/off or a non-negative integer")
    payload["config"]["ctx_shift"] = ctx_shift
if backend:
    if backend not in {"vulkan", "rocm"}:
        raise SystemExit("accepted metadata backend must be rocm or vulkan when set")
    if not re.fullmatch(r"[0-9]+(,[0-9]+)*", visible_devices):
        raise SystemExit("accepted metadata visible_devices must be comma-separated device indexes")
    if split_mode not in {"layer", "row"}:
        raise SystemExit("accepted metadata split_mode must be layer or row")
    if not re.fullmatch(r"[1-9][0-9]*(,[1-9][0-9]*)*", tensor_split):
        raise SystemExit("accepted metadata tensor_split must be comma-separated positive integers")
    if backend == "vulkan" and visible_devices == "0,1" and tensor_split == "44,1":
        tensor_split = "1,1"
    payload["config"].update({
        "backend": backend,
        "visible_devices": visible_devices,
        "split_mode": split_mode,
        "tensor_split": tensor_split,
    })

payload["profiles"] = {
    name: dict(payload["config"])
    for name in ("speed", "fastlong", "balanced", "reliable", "tiny")
}

with path.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(path)
PY
}

write_vulkan_equivalent_for_accepted() {
	local accepted_metadata_file="$1"

	python3 - "$accepted_metadata_file" <<'PY'
import json
import os
import pathlib
import re
import stat
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
if metadata_path.is_symlink() or not metadata_path.is_file():
    raise SystemExit(f"refusing unsafe accepted metadata path: {metadata_path}")
accepted = json.loads(metadata_path.read_text(encoding="utf-8"))
if not isinstance(accepted, dict):
    raise SystemExit("accepted metadata must be an object")

safe = re.compile(r"[A-Za-z0-9_.-]+")
def require_safe(name, value):
    if not isinstance(value, str) or not safe.fullmatch(value) or ".." in value or value.startswith("-"):
        raise SystemExit(f"unsafe {name}: {value!r}")
    return value

family = require_safe("family", accepted.get("family") or metadata_path.stem)
alias = require_safe("alias", accepted.get("alias") or accepted.get("model_name") or family)
profile = require_safe("profile", accepted.get("profile") or "reliable")
if family.endswith("-vulkan") or alias.endswith("-vulkan"):
    raise SystemExit("accepted metadata is already a Vulkan entry")

launcher_file = accepted.get("launcher_file")
if not isinstance(launcher_file, str):
    raise SystemExit("accepted metadata missing launcher_file")
launcher_path = Path(launcher_file)
if launcher_path.is_symlink() or not launcher_path.is_file():
    raise SystemExit(f"launcher file is missing or unsafe: {launcher_path}")
if launcher_path.name.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.-]+\.sh", launcher_path.name):
    raise SystemExit(f"unsafe launcher basename: {launcher_path.name}")

v_family = family + "-vulkan"
v_alias = alias + "-vulkan"
v_launcher_name = launcher_path.with_suffix("").name + "-vulkan.sh"
v_launcher_path = launcher_path.with_name(v_launcher_name)

text = launcher_path.read_text(encoding="utf-8")
text = text.replace(f"# local_llm_family={family}", f"# local_llm_family={v_family}")
text = text.replace(f"# local_llm_alias={alias}", f"# local_llm_alias={v_alias}")
text = re.sub(r"^export HIP_VISIBLE_DEVICES=.*\n", "", text, flags=re.MULTILINE)
text = re.sub(r"^export ROCR_VISIBLE_DEVICES=.*\n", "", text, flags=re.MULTILINE)
if "GGML_VK_VISIBLE_DEVICES" not in text:
    text = re.sub(r"(ngl=.*\n)", r"\1export GGML_VK_VISIBLE_DEVICES=0,1\n", text, count=1)
text = text.replace("exec ./build/bin/llama-server \\", "exec ./build-vulkan/bin/llama-server \\")
text = re.sub(r"(--alias\s+)([A-Za-z0-9_.-]+)(\s*\\)", rf"\1{v_alias}\3", text)
if "./build-vulkan/bin/llama-server" not in text:
    raise SystemExit("failed to rewrite launcher to Vulkan binary")

v_launcher_path.write_text(text, encoding="utf-8")
mode = launcher_path.stat().st_mode
v_launcher_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

v_accepted = dict(accepted)
v_accepted["family"] = v_family
v_accepted["alias"] = v_alias
v_accepted["model_name"] = v_alias
v_accepted["launcher_file"] = str(v_launcher_path)
v_accepted["remote_start"] = "./" + v_launcher_name
config = dict(v_accepted.get("config") or {})
config["backend"] = "vulkan"
config["visible_devices"] = config.get("visible_devices") or "0,1"
config["split_mode"] = config.get("split_mode") or "layer"
config["tensor_split"] = config.get("tensor_split") or "1,1"
v_accepted["config"] = config
v_metadata_path = metadata_path.with_name(v_family + ".json")
if v_metadata_path.is_symlink():
    raise SystemExit(f"refusing symlinked Vulkan metadata path: {v_metadata_path}")
v_metadata_path.write_text(json.dumps(v_accepted, indent=2, sort_keys=True) + "\n", encoding="utf-8")

bin_dir = Path.home() / ".local" / "bin"
oc_local = bin_dir / "oc-local"
if oc_local.exists() and not oc_local.is_symlink():
    bin_dir.mkdir(parents=True, exist_ok=True)
    shortcut = bin_dir / ("oc-" + v_family)
    shortcut.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"exec /bin/bash \"$HOME/.local/bin/oc-local\" {v_family} {profile} --remote \"${{OC_LOCAL_REMOTE_HOST:-ubt26}}\" \"$@\"\n",
        encoding="utf-8",
    )
    shortcut.chmod(0o755)
    print(f"vulkan_shortcut={shortcut}")
print(f"vulkan_launcher_file={v_launcher_path}")
print(f"vulkan_accepted_metadata_file={v_metadata_path}")
PY
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

infer_slug_from_repo() {
	local name
	name="${1##*/}"
	name="${name%-GGUF}"
	name="${name%-gguf}"
	printf '%s\n' "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//'
}

infer_benchmark_family() {
	local family
	family="$(infer_family "$1")"
	if [[ "$family" == candidate ]]; then
		infer_slug_from_repo "$1"
	else
		printf '%s\n' "$family"
	fi
}

infer_alias() {
	infer_slug_from_repo "$1"
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

run_remote_benchmark() {
	local host="$1"
	local repo="$2"
	local family="$3"
	local alias="$4"
	local profile="$5"
	local quant="$6"
	local hf_file="$7"
	local remote_dir="${OC_LOCAL_REMOTE_DIR:-~/llama.cpp}"
	local port=8080
	local ctx="${8:-131072}"
	local batch="${9:-4096}"
	local ubatch="${10:-256}"
	local backend="${11:-auto}"
	local visible_devices="${12:-}"
	local split_mode="${13:-}"
	local tensor_split="${14:-}"
	local responsive="${15:-false}"
	local cache_type_k="${16:-}"
	local cache_type_v="${17:-}"
	local ctx_shift="${18:-}"
	local empty_arg='__LOCAL_LLM_EMPTY__'

	ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" bash -s -- "$remote_dir" "$repo" "$family" "$alias" "$profile" "$quant" "${hf_file:-$empty_arg}" "$port" "$ctx" "$batch" "$ubatch" "$backend" "${visible_devices:-$empty_arg}" "${split_mode:-$empty_arg}" "${tensor_split:-$empty_arg}" "$responsive" "${cache_type_k:-$empty_arg}" "${cache_type_v:-$empty_arg}" "${ctx_shift:-$empty_arg}" <<'REMOTE_BENCH'
export PATH="$HOME/.local/bin:$PATH"
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
backend="${12}"
visible_devices="${13}"
split_mode="${14}"
tensor_split="${15}"
responsive="${16}"
cache_type_k="${17}"
cache_type_v="${18}"
ctx_shift="${19}"
for optional_name in hf_file visible_devices split_mode tensor_split cache_type_k cache_type_v ctx_shift; do
  if [[ "${!optional_name}" == '__LOCAL_LLM_EMPTY__' ]]; then
    printf -v "$optional_name" '%s' ''
  fi
done
ngl=999
server_pid=""
service_was_active=false
had_current_model_env=false
previous_current_model_env=""
if [[ "$remote_dir" == "~" || "$remote_dir" == \~/* ]]; then
  remote_dir="$HOME${remote_dir#\~}"
fi
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
  systemctl --user stop llama-server.service >/dev/null 2>&1 || true
  systemctl --user reset-failed llama-server.service >/dev/null 2>&1 || true
  pkill -u "$(id -u)" -f 'llama-server' >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    if ! pgrep -u "$(id -u)" -f 'llama-server' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
}

restore_service() {
  cd "$remote_dir" 2>/dev/null || return 0
  if [[ "$had_current_model_env" == true ]]; then
    printf '%s\n' "$previous_current_model_env" >current-model.env.tmp
    mv current-model.env.tmp current-model.env
    systemctl --user restart llama-server.service >/dev/null 2>&1 || true
  else
    rm -f current-model.env current-model.env.tmp
    systemctl --user stop llama-server.service >/dev/null 2>&1 || true
  fi
  if [[ -n "${start_script:-}" ]]; then
    rm -f -- "$start_script"
  fi
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
if [[ -f current-model.env ]]; then
  had_current_model_env=true
  previous_current_model_env="$(cat current-model.env)"
fi
if [[ "$responsive" == true ]]; then
  ctx=131072
  batch=4096
  ubatch=256
fi
if [[ "$backend" == rocm ]]; then
  backend=default
fi
if [[ "$backend" == auto ]]; then
  backend=default
  if [[ -x ./build-vulkan/bin/llama-server ]]; then
    vulkan_device_count="$(./build-vulkan/bin/llama-server --list-devices 2>/dev/null | grep -c '^  Vulkan[0-9]:' || true)"
    if [[ "$vulkan_device_count" =~ ^[0-9]+$ ]] && (( vulkan_device_count >= 2 )); then
      backend=vulkan
    fi
  fi
fi
if [[ "$backend" == vulkan ]]; then
  visible_devices="${visible_devices:-0,1}"
  split_mode="${split_mode:-layer}"
  tensor_split="${tensor_split:-1,1}"
  if [[ "$visible_devices" == "0,1" && "$tensor_split" == "44,1" ]]; then
    tensor_split="1,1"
  fi
  export GGML_VK_VISIBLE_DEVICES="$visible_devices"
elif [[ -n "$visible_devices" ]]; then
  split_mode="${split_mode:-row}"
  tensor_split="${tensor_split:-1,1}"
  export HIP_VISIBLE_DEVICES="$visible_devices"
  export ROCR_VISIBLE_DEVICES="$visible_devices"
fi
server_bin=./build/bin/llama-server
if [[ "$backend" == vulkan ]]; then
  server_bin=./build-vulkan/bin/llama-server
fi
model_args=(-hf "${repo}:${quant}")
if [[ -n "$hf_file" ]]; then
  model_args=(-hf "$repo" --hf-file "$hf_file")
fi
server_cmd=(
  "$server_bin"
  "${model_args[@]}"
  --host 0.0.0.0
  --port "$port"
  --timeout 1200
  --threads-http 2
  --parallel 1
  --no-cont-batching
  -ngl "$ngl"
)
if [[ "$backend" == vulkan && "$visible_devices" == "0,1" && "$tensor_split" == "44,1" ]]; then
  tensor_split="1,1"
fi
if [[ -n "$split_mode" || -n "$tensor_split" ]]; then
  server_cmd+=(--split-mode "$split_mode" --tensor-split "$tensor_split")
fi
case "$ctx_shift" in
  on | true | 1) server_cmd+=(--context-shift) ;;
  off | false | 0 | "") ;;
  *) server_cmd+=(--context-shift) ;;
esac
if [[ -n "$cache_type_k" ]]; then
  server_cmd+=(-ctk "$cache_type_k")
fi
if [[ -n "$cache_type_v" ]]; then
  server_cmd+=(-ctv "$cache_type_v")
fi
server_cmd+=(
  --cache-ram 16384
  --ctx-checkpoints 64
  --checkpoint-every-n-tokens 4096
  -c "$ctx"
  --flash-attn on
  -ub "$ubatch"
  -b "$batch"
  --threads "$(nproc)"
  --prio 2
  --no-warmup
)
if [[ "$responsive" == true ]]; then
  : # responsive mode is now baked into default server args
fi
sampler_temp="0.6"
sampler_top_p="0.95"
sampler_top_k="20"
if [[ "${family,,}" == gemma* || "${alias,,}" == gemma* || "${repo,,}" == *gemma* ]]; then
  sampler_temp="1.0"
  sampler_top_p="0.95"
  sampler_top_k="64"
fi
case "${repo,,} ${family,,} ${alias,,}" in
  *gemma-4-12b*) server_cmd+=(--no-mmproj) ;;
esac
server_cmd+=(
  --temp "$sampler_temp"
  --top-p "$sampler_top_p"
  --top-k "$sampler_top_k"
  --min-p 0.0
  --presence-penalty 0.0
  --alias "$alias"
)
server_cmd+=(--reasoning on)
command_text=""
if [[ "$backend" == vulkan ]]; then
  command_text="GGML_VK_VISIBLE_DEVICES=$visible_devices "
elif [[ -n "$visible_devices" ]]; then
  command_text="HIP_VISIBLE_DEVICES=$visible_devices ROCR_VISIBLE_DEVICES=$visible_devices "
fi
for command_text_part in "${server_cmd[@]}"; do
  printf -v command_text_part '%q' "$command_text_part"
  command_text+="${command_text_part} "
done
command_text="${command_text% }"
{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' 'set -euo pipefail'
  if [[ "$backend" == vulkan ]]; then
    printf 'export GGML_VK_VISIBLE_DEVICES=%q\n' "$visible_devices"
  elif [[ -n "$visible_devices" ]]; then
    printf 'export HIP_VISIBLE_DEVICES=%q\n' "$visible_devices"
    printf 'export ROCR_VISIBLE_DEVICES=%q\n' "$visible_devices"
  fi
  printf '%s\n' 'profile="${1:-reliable}"'
  printf '%s\n' 'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *) echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac'
  printf 'exec'
  for command_text_part in "${server_cmd[@]}"; do
    printf ' %q' "$command_text_part"
  done
  printf '\n'
} >"$start_script"
chmod +x "$start_script"
remote_script="./$start_script"
{
  printf 'REMOTE_SCRIPT=%q\n' "$remote_script"
  printf 'REMOTE_PROFILE=%q\n' "$profile"
} >current-model.env.tmp
mv current-model.env.tmp current-model.env
: >"$log_file"
restart_started="$(date -Is)"
stop_server
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
  prompt='You are running a local model benchmark. Read this checklist: cache reuse, prompt prefill, decode throughput, memory pressure, tool-use responsiveness, and service health. Reply with exactly one word: ok'
  request="{\"model\":$(json_string "$alias"),\"messages\":[{\"role\":\"user\",\"content\":$(json_string "$prompt")}],\"max_tokens\":128,\"temperature\":0}"
  if ! curl -fsS --max-time 180 "http://127.0.0.1:${port}/v1/chat/completions" -H 'Content-Type: application/json' -d "$request" >"$response_file" 2>>"$log_file"; then
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
if [[ "$load_status" == success ]]; then
  quality_status="$(python3 - "$prompt_tok_s" "$decode_tok_s" "$prompt_tokens" "$decode_tokens" <<'PY'
import sys
prompt_tps, decode_tps, prompt_tokens, decode_tokens = sys.argv[1:]

def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

ptps = number(prompt_tps)
dtps = number(decode_tps)
ptok = integer(prompt_tokens)
dtok = integer(decode_tokens)
if dtok is None or dtok < 64:
    print("too_short")
elif ptok is None or ptok < 48:
    print("prompt_probe_too_short")
elif ptps is None or ptps < 25.0:
    print("prompt_too_slow")
elif dtps is None or dtps < 4.5:
    print("decode_too_slow")
else:
    print("success")
PY
)"
  if [[ "$quality_status" != success ]]; then
    load_status="$quality_status"
  fi
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
if [[ -n "$cache_type_k" ]]; then
  printf 'cache_type_k=%s\n' "$cache_type_k"
fi
if [[ -n "$cache_type_v" ]]; then
  printf 'cache_type_v=%s\n' "$cache_type_v"
fi
if [[ -n "$visible_devices" ]]; then
  if [[ "$backend" == vulkan ]]; then
    printf 'backend=%s\n' "$backend"
  else
    printf 'backend=%s\n' rocm
  fi
  printf 'visible_devices=%s\n' "$visible_devices"
  printf 'split_mode=%s\n' "$split_mode"
  printf 'tensor_split=%s\n' "$tensor_split"
fi
if [[ -n "$ctx_shift" ]]; then
  printf 'ctx_shift=%s\n' "$ctx_shift"
fi
printf 'command=%s\n' "$command_text"
printf 'log_file=%s\n' "$log_file"
REMOTE_BENCH
}

cmd_discover() {
	local target
	target="$(default_target)"
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
	local target
	target="$(default_target)"
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
	reject_symlink_state_file "$output_file" || return 1

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
	local target
	target="$(default_target)"
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
	local backend='auto'
	local visible_devices=''
	local split_mode=''
	local tensor_split=''
	local responsive=false
	local cache_type_k=''
	local cache_type_v=''
	local ctx_shift=''
	local ctx_override=''
	local batch_override=''
	local ubatch_override=''

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
		--cache-type-k)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--cache-type-k requires a non-empty value' >&2
				return 2
			fi
			cache_type_k="$2"
			shift 2
			;;
		--cache-type-v)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--cache-type-v requires a non-empty value' >&2
				return 2
			fi
			cache_type_v="$2"
			shift 2
			;;
		--backend)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--backend requires auto, default, rocm, or vulkan' >&2
				return 2
			fi
			backend="$2"
			shift 2
			;;
		--visible-devices)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--visible-devices requires comma-separated device indexes' >&2
				return 2
			fi
			visible_devices="$2"
			shift 2
			;;
		--split-mode)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--split-mode requires layer or row' >&2
				return 2
			fi
			split_mode="$2"
			shift 2
			;;
		--tensor-split)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--tensor-split requires comma-separated positive integers' >&2
				return 2
			fi
			tensor_split="$2"
			shift 2
			;;
		--ctx)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--ctx requires a positive integer' >&2
				return 2
			fi
			ctx_override="$2"
			shift 2
			;;
		--batch)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--batch requires a positive integer' >&2
				return 2
			fi
			batch_override="$2"
			shift 2
			;;
		--ubatch)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--ubatch requires a positive integer' >&2
				return 2
			fi
			ubatch_override="$2"
			shift 2
			;;
		--ctx-shift)
			if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
				printf '%s\n' '--ctx-shift requires on, true, 1, off, false, 0, or a non-negative integer' >&2
				return 2
			fi
			ctx_shift="$2"
			shift 2
			;;
		--responsive)
			responsive=true
			shift
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
		family="$(infer_benchmark_family "$repo")"
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

	case "$backend" in
	auto | default | rocm | vulkan) ;;
	*)
		printf 'invalid benchmark backend: %s\n' "$backend" >&2
		return 2
		;;
	esac
	if [[ -n "$visible_devices" && ! "$visible_devices" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
		printf 'invalid visible devices: %s\n' "$visible_devices" >&2
		return 2
	fi
	if [[ -n "$split_mode" ]]; then
		case "$split_mode" in
		layer | row) ;;
		*)
			printf 'invalid split mode: %s\n' "$split_mode" >&2
			return 2
			;;
		esac
	fi
	if [[ -n "$tensor_split" && ! "$tensor_split" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]]; then
		printf 'invalid tensor split: %s\n' "$tensor_split" >&2
		return 2
	fi
	if [[ -n "$cache_type_k" && ! "$cache_type_k" =~ ^[A-Za-z0-9_.-]+$ ]]; then
		printf 'invalid cache type k: %s\n' "$cache_type_k" >&2
		return 2
	fi
	for numeric_override in ctx_override batch_override ubatch_override; do
		if [[ -n "${!numeric_override}" && ! "${!numeric_override}" =~ ^[1-9][0-9]*$ ]]; then
			printf 'invalid numeric benchmark override %s: %s\n' "$numeric_override" "${!numeric_override}" >&2
			return 2
		fi
	done
	if [[ -n "$cache_type_v" && ! "$cache_type_v" =~ ^[A-Za-z0-9_.-]+$ ]]; then
		printf 'invalid cache type v: %s\n' "$cache_type_v" >&2
		return 2
	fi
	if [[ -n "$ctx_shift" ]]; then
		case "$ctx_shift" in
		on | true | 1 | off | false | 0) ;;
		*[!0-9]*)
			printf 'invalid ctx shift: %s\n' "$ctx_shift" >&2
			return 2
			;;
		esac
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
			reject_symlink_state_file "$output_file" || return 1

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
				'speed|32768|4096|256'
				'balanced|49152|4096|256'
				'reliable|65536|4096|256'
				'tiny|65536|4096|256'
			)
			local trial_number=0
			local trial_total="${#trial_matrix[@]}"
			local trial_spec trial_profile trial_ctx trial_batch trial_ubatch
			local benchmark_output line key value
			local load_status prompt_tok_s decode_tok_s prompt_tokens decode_tokens ctx batch ubatch ngl result_cache_type_k result_cache_type_v command_text log_file
			printf 'Full benchmark start\n'
			printf 'repo=%s\n' "$repo"
			printf 'family=%s\n' "$family"
			printf 'alias=%s\n' "$alias"
			printf 'target=%s\n' "$target"
			printf 'quant=%s\n' "$quant"
			if [[ -n "$hf_file" ]]; then
				printf 'hf_file=%s\n' "$hf_file"
			fi
			if [[ -n "$cache_type_k" ]]; then
				printf 'cache_type_k=%s\n' "$cache_type_k"
			fi
			if [[ -n "$cache_type_v" ]]; then
				printf 'cache_type_v=%s\n' "$cache_type_v"
			fi
			printf 'trials=%s\n' "$trial_total"
			for trial_spec in "${trial_matrix[@]}"; do
				IFS='|' read -r trial_profile trial_ctx trial_batch trial_ubatch <<<"$trial_spec"
				trial_number=$((trial_number + 1))
				printf 'running trial=%s/%s profile=%s ctx=%s batch=%s ubatch=%s ngl=999\n' \
					"$trial_number" "$trial_total" "$trial_profile" "$trial_ctx" "$trial_batch" "$trial_ubatch"
				benchmark_output="$(run_remote_benchmark "${target#remote:}" "$repo" "$family" "$alias" "$trial_profile" "$quant" "$hf_file" "$trial_ctx" "$trial_batch" "$trial_ubatch" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$responsive" "$cache_type_k" "$cache_type_v" "$ctx_shift")"
				load_status=''
				prompt_tok_s=''
				decode_tok_s=''
				prompt_tokens=''
				decode_tokens=''
				ctx=''
				batch=''
				ubatch=''
				ngl=''
				result_cache_type_k=''
				result_cache_type_v=''
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
					cache_type_k) result_cache_type_k="$value" ;;
					cache_type_v) result_cache_type_v="$value" ;;
					command) command_text="$value" ;;
					log_file) log_file="$value" ;;
					esac
				done <<<"$benchmark_output"
				trials_tsv+="${trial_number}"$'\t'"${trial_profile}"$'\t'"${ctx:-$trial_ctx}"$'\t'"${batch:-$trial_batch}"$'\t'"${ubatch:-$trial_ubatch}"$'\t'"${ngl:-999}"$'\t'"${load_status:-unknown}"$'\t'"${prompt_tok_s}"$'\t'"${decode_tok_s}"$'\t'"${prompt_tokens}"$'\t'"${decode_tokens}"$'\t'"${result_cache_type_k:-$cache_type_k}"$'\t'"${result_cache_type_v:-$cache_type_v}"$'\t'"${command_text}"$'\t'"${log_file}"$'\n'
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
			reject_symlink_state_file "$output_file" || return 1

			recommendations_output="$(
				TRIALS_TSV="$trials_tsv" python3 - "$output_file" "$target" "$repo" "$family" "$alias" "$quant" "$hf_file" "$cache_type_k" "$cache_type_v" "$result_timestamp" <<'PY'
import json
import os
import sys

output_file, target, repo, family, alias, quant, hf_file, cache_type_k, cache_type_v, timestamp = sys.argv[1:]
raw = os.environ.get("TRIALS_TSV", "").splitlines()

def integer(value):
    return int(value) if value else None

def number(value):
    return float(value) if value else None

trials = []
for line in raw:
    fields = line.split("\t")
    if len(fields) != 15:
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
        trial_cache_type_k,
        trial_cache_type_v,
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
        "cache_type_k": trial_cache_type_k or None,
        "cache_type_v": trial_cache_type_v or None,
        "command": command,
        "log_file": log_file,
    })

successful = [
    trial for trial in trials
    if trial["load_status"] == "success"
    and trial.get("prompt_tok_s") is not None
    and trial.get("prompt_tok_s") >= 25.0
    and trial.get("decode_tok_s") is not None
    and trial.get("decode_tok_s") >= 4.5
    and (trial.get("prompt_tokens") or 0) >= 48
    and (trial.get("decode_tokens") or 0) >= 64
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
    "cache_type_k": cache_type_k or None,
    "cache_type_v": cache_type_v or None,
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
		local result_backend=''
		local result_visible_devices=''
		local result_split_mode=''
		local result_tensor_split=''
		local result_cache_type_k=''
		local result_cache_type_v=''
		local result_ctx_shift=''
		local line key value
		benchmark_output="$(run_remote_benchmark "${target#remote:}" "$repo" "$family" "$alias" "${profile_list[0]}" "$quant" "$hf_file" "$ctx_override" "$batch_override" "$ubatch_override" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$responsive" "$cache_type_k" "$cache_type_v" "$ctx_shift")"
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
			backend) result_backend="$value" ;;
			visible_devices) result_visible_devices="$value" ;;
			split_mode) result_split_mode="$value" ;;
			tensor_split) result_tensor_split="$value" ;;
			cache_type_k) result_cache_type_k="$value" ;;
			cache_type_v) result_cache_type_v="$value" ;;
			ctx_shift) result_ctx_shift="$value" ;;
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
		reject_symlink_state_file "$output_file" || return 1

		python3 - "$output_file" "$target" "$repo" "$family" "$alias" "${profile_list[0]}" "$ctx" "$batch" "$ubatch" "$ngl" "$load_status" "$prompt_tok_s" "$decode_tok_s" "$prompt_tokens" "$decode_tokens" "$command_text" "$result_timestamp" "$quant" "$hf_file" "$result_backend" "$result_visible_devices" "$result_split_mode" "$result_tensor_split" "${result_cache_type_k:-$cache_type_k}" "${result_cache_type_v:-$cache_type_v}" "${result_ctx_shift:-$ctx_shift}" <<'PY'
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
    quant,
    hf_file,
    backend,
    visible_devices,
    split_mode,
    tensor_split,
    cache_type_k,
    cache_type_v,
    ctx_shift,
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
    "quant": quant,
    "hf_file": hf_file,
    "cache_type_k": cache_type_k or None,
    "cache_type_v": cache_type_v or None,
    "ctx_shift": ctx_shift or None,
    "command": command,
    "timestamp": timestamp,
}
if backend:
    if backend == "vulkan" and visible_devices == "0,1" and tensor_split == "44,1":
        tensor_split = "1,1"
        if command:
            command = command.replace("--tensor-split 44,1", "--tensor-split 1,1")
            result["command"] = command
    result["backend"] = backend
    result["visible_devices"] = visible_devices
    result["split_mode"] = split_mode
    result["tensor_split"] = tensor_split
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(result, handle, separators=(",", ":"))
    handle.write("\n")
PY

		if [[ "$load_status" == success && -n "$prompt_tok_s" && -n "$decode_tok_s" && -n "$prompt_tokens" && -n "$decode_tokens" && "$prompt_tokens" -ge 48 && "$decode_tokens" -ge 64 ]]; then
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
		if [[ "$load_status" != success || -z "$prompt_tok_s" || -z "$decode_tok_s" || -z "$prompt_tokens" || -z "$decode_tokens" || "$prompt_tokens" -lt 48 || "$decode_tokens" -lt 64 ]]; then
			printf 'reason=%s\n' 'model did not become ready, was too slow, or did not emit enough throughput metrics'
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
	if [[ -n "$cache_type_k" ]]; then
		printf 'cache_type_k=%s\n' "$cache_type_k"
	fi
	if [[ -n "$cache_type_v" ]]; then
		printf 'cache_type_v=%s\n' "$cache_type_v"
	fi
	printf 'target=%s\n' "$target"
}

cmd_accept() {
	local benchmark_file=''
	local dry_run=false
	local create_vulkan=false
	local json_fields
	local repo
	local family
	local alias
	local target
	local profile
	local start_script
	local launcher_file
	local max_start=0
	local start_path
	local start_name
	local start_number
	local start_value
	local accepted_metadata_file

	while [[ $# -gt 0 ]]; do
		case "$1" in
		--dry-run)
			dry_run=true
			shift
			;;
		--vulkan)
			create_vulkan=true
			shift
			;;
		-h | --help)
			printf '%s\n' 'Usage: model-manager accept [--dry-run] [--vulkan] BENCHMARK.json'
			printf '%s\n' '  --vulkan  also create a Vulkan backend metadata/launcher/oc-* peer'
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
import re
import shlex
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

family = result["family"]
if not re.fullmatch(r"[A-Za-z0-9_.-]+", family) or ".." in family or family.startswith("-"):
    raise SystemExit("benchmark JSON field contains an unsafe family: family")
alias = result["alias"]
if not re.fullmatch(r"[A-Za-z0-9_.-]+", alias) or ".." in alias or alias.startswith("-"):
    raise SystemExit("benchmark JSON field contains an unsafe alias: alias")

def has_control_chars(value):
    return any(ord(char) < 32 or ord(char) == 127 for char in value)

if result.get("load_status") != "success":
    raise SystemExit(f"benchmark JSON load_status is not success: {result.get('load_status')}")
quality_checks = (
    ("prompt_tokens", 48, "integer"),
    ("decode_tokens", 64, "integer"),
    ("prompt_tok_s", 25.0, "number"),
    ("decode_tok_s", 4.5, "number"),
)
for key, minimum, kind in quality_checks:
    value = result.get(key)
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SystemExit(f"benchmark JSON field must be an integer: {key}")
    elif not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SystemExit(f"benchmark JSON field must be a number: {key}")
    if value < minimum:
        raise SystemExit(f"benchmark JSON field below acceptance threshold: {key}={value} < {minimum}")
for key, minimum in (("ctx", 1), ("batch", 1), ("ubatch", 1), ("ngl", 0)):
    if key in result and not isinstance(result[key], int):
        raise SystemExit(f"benchmark JSON field must be an integer: {key}")
    if key in result and isinstance(result[key], bool):
        raise SystemExit(f"benchmark JSON field must be an integer: {key}")
    if key in result and result[key] < minimum:
        if minimum == 1:
            raise SystemExit(f"benchmark JSON field must be a positive integer: {key}")
        raise SystemExit(f"benchmark JSON field must be a non-negative integer: {key}")
for key in ("quant", "hf_file", "cache_type_k", "cache_type_v"):
    if key in result and result[key] is not None and not isinstance(result[key], str):
        raise SystemExit(f"benchmark JSON field must be a string: {key}")
    if key in result and isinstance(result[key], str) and has_control_chars(result[key]):
        raise SystemExit(f"benchmark JSON field contains a control character: {key}")
    if key in ("cache_type_k", "cache_type_v") and isinstance(result.get(key), str):
        if result[key] and not re.fullmatch(r"[A-Za-z0-9_.-]+", result[key]):
            raise SystemExit(f"benchmark JSON field contains an unsafe cache type: {key}")

if not result.get("quant") or not result.get("hf_file"):
    command = result.get("command") or ""
    if isinstance(command, str) and command:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
        while parts and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[0]):
            parts.pop(0)
        for index, part in enumerate(parts):
            if part == "--hf-file" and index + 1 < len(parts) and not result.get("hf_file"):
                result["hf_file"] = parts[index + 1]
            if part == "-hf" and index + 1 < len(parts) and not result.get("quant"):
                _, sep, quant = parts[index + 1].partition(":")
                if sep:
                    result["quant"] = quant
backend = result.get("backend") or ""
visible_devices = result.get("visible_devices") or ""
split_mode = result.get("split_mode") or ""
tensor_split = result.get("tensor_split") or ""
ctx_shift = result.get("ctx_shift") or ""
if ctx_shift:
    if not isinstance(ctx_shift, str) or has_control_chars(ctx_shift):
        raise SystemExit("benchmark JSON ctx_shift must be a safe string")
    if ctx_shift not in {"on", "true", "1", "off", "false", "0"} and not re.fullmatch(r"[0-9]+", ctx_shift):
        raise SystemExit("benchmark JSON ctx_shift must be on/off or a non-negative integer")
if backend:
    if backend not in {"vulkan", "rocm"}:
        raise SystemExit("benchmark JSON backend must be rocm or vulkan when set")
    for key, value in (("visible_devices", visible_devices), ("split_mode", split_mode), ("tensor_split", tensor_split)):
        if not isinstance(value, str) or has_control_chars(value):
            raise SystemExit(f"benchmark JSON field must be a safe string: {key}")
    if not re.fullmatch(r"[0-9]+(,[0-9]+)*", visible_devices):
        raise SystemExit("benchmark JSON visible_devices must be comma-separated device indexes")
    if split_mode not in {"layer", "row"}:
        raise SystemExit("benchmark JSON split_mode must be layer or row")
    if not re.fullmatch(r"[1-9][0-9]*(,[1-9][0-9]*)*", tensor_split):
        raise SystemExit("benchmark JSON tensor_split must be comma-separated positive integers")
    if backend == "vulkan" and visible_devices == "0,1" and tensor_split == "44,1":
        tensor_split = "1,1"
        result["tensor_split"] = tensor_split
values = [result[key] for key in required]
values.extend(str(result.get(key) or "") for key in ("ctx", "batch", "ubatch", "ngl", "quant", "hf_file", "cache_type_k", "cache_type_v"))
values.extend([backend, visible_devices, split_mode, tensor_split, ctx_shift])
print("\x1f".join(values))
PY
	)"; then
		return 1
	fi

	local ctx batch ubatch ngl quant hf_file cache_type_k cache_type_v backend visible_devices split_mode tensor_split ctx_shift
	IFS=$'\x1f' read -r repo family alias target profile ctx batch ubatch ngl quant hf_file cache_type_k cache_type_v backend visible_devices split_mode tensor_split ctx_shift <<<"$json_fields"

	ensure_runs_dirs

	local existing_launcher
	existing_launcher="$(find_existing_accepted_launcher "$repo" "$family" "$alias")"
	if [[ -n "$existing_launcher" ]]; then
		if [[ "$dry_run" == true ]]; then
			printf 'Accept plan\n'
			printf 'repo=%s\n' "$repo"
			printf 'family=%s\n' "$family"
			printf 'alias=%s\n' "$alias"
			printf 'target=%s\n' "$target"
			printf 'profile=%s\n' "$profile"
			printf 'launcher_file=%s\n' "${existing_launcher%% *}"
			printf 'Dry-run actions:\n'
			printf 'would update accepted metadata under %s\n' "$runs_dir/accepted"
			if [[ "$create_vulkan" == true ]]; then
				printf 'would also create/update Vulkan equivalent metadata/launcher/shortcut\n'
			fi
			return 0
		fi
		local removed_selection_count
		removed_selection_count="$(remove_matching_selections "$repo" "$alias")"
		ensure_launcher_model_log_redirect "${existing_launcher%% *}"
		update_existing_launcher_runtime "${existing_launcher%% *}" "$ctx" "$batch" "$ubatch" "$ngl" "$tensor_split"
		accepted_metadata_file="$(write_accepted_metadata "$repo" "$family" "$alias" "${existing_launcher%% *}" "$profile" "$ctx" "$batch" "$ubatch" "$ngl" "$quant" "$hf_file" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$cache_type_k" "$cache_type_v" "$ctx_shift" "$target")"
		printf 'Accepted benchmark already has launcher\n'
		printf 'repo=%s\n' "$repo"
		printf 'family=%s\n' "$family"
		printf 'alias=%s\n' "$alias"
		printf 'target=%s\n' "$target"
		printf 'profile=%s\n' "$profile"
		printf 'start_script=%s\n' "${existing_launcher%% *}"
		printf 'accepted_metadata_file=%s\n' "$accepted_metadata_file"
		if [[ "$create_vulkan" == true ]]; then
			write_vulkan_equivalent_for_accepted "$accepted_metadata_file"
		fi
		printf 'removed_selection_count=%s\n' "$removed_selection_count"
		return 0
	fi

	shopt -s nullglob
	for start_path in "$repo_root"/scripts/start*.sh "$generated_launcher_dir"/start*.sh; do
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
	launcher_file="${LOCAL_LLM_ACCEPT_START_SCRIPT:-$generated_launcher_dir/start$((max_start + 1)).sh}"
	start_script="$launcher_file"

	if [[ "$dry_run" == true ]]; then
		printf 'Accept plan\n'
		printf 'repo=%s\n' "$repo"
		printf 'family=%s\n' "$family"
		printf 'alias=%s\n' "$alias"
		printf 'target=%s\n' "$target"
		printf 'profile=%s\n' "$profile"
		printf 'launcher_file=%s\n' "$launcher_file"
		printf 'Dry-run actions:\n'
		printf 'would create %s\n' "$launcher_file"
		printf 'would write accepted metadata under %s\n' "$runs_dir/accepted"
		if [[ "$create_vulkan" == true ]]; then
			printf 'would also create Vulkan equivalent metadata/launcher/shortcut\n'
		fi
		return 0
	fi

	validate_launcher_write_target "$launcher_file" || return 1
	if [[ -e "$launcher_file" ]]; then
		printf 'accept launcher already exists: %s\n' "$launcher_file" >&2
		return 1
	fi
	mkdir -p "${launcher_file%/*}"

	python3 - "$launcher_file" "$repo" "$family" "$alias" "$ctx" "$batch" "$ubatch" "$ngl" "$quant" "$hf_file" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$cache_type_k" "$cache_type_v" "$ctx_shift" <<'PY'
import shlex
import sys
import re

path, repo, family, alias, ctx, batch, ubatch, ngl, quant, hf_file, backend, visible_devices, split_mode, tensor_split, cache_type_k, cache_type_v, ctx_shift = sys.argv[1:]
for name, value in (("repo", repo), ("family", family), ("alias", alias), ("quant", quant), ("hf_file", hf_file), ("cache_type_k", cache_type_k), ("cache_type_v", cache_type_v)):
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SystemExit(f"launcher field contains a control character: {name}")
for name, value, minimum in (("ctx", ctx, 1), ("batch", batch, 1), ("ubatch", ubatch, 1), ("ngl", ngl, 0)):
    if not value.isdigit():
        raise SystemExit(f"missing numeric {name}")
    if int(value) < minimum:
        if minimum == 1:
            raise SystemExit(f"missing positive numeric {name}")
        raise SystemExit(f"missing non-negative numeric {name}")
if ctx_shift:
    if ctx_shift not in {"on", "true", "1", "off", "false", "0"} and not re.fullmatch(r"[0-9]+", ctx_shift):
        raise SystemExit("ctx_shift must be on/off or a non-negative integer")
if backend:
    if backend not in {"vulkan", "rocm"}:
        raise SystemExit("backend must be rocm or vulkan when set")
    if not re.fullmatch(r"[0-9]+(,[0-9]+)*", visible_devices):
        raise SystemExit("visible_devices must be comma-separated device indexes")
    if split_mode not in {"layer", "row"}:
        raise SystemExit("split_mode must be layer or row")
    if not re.fullmatch(r"[1-9][0-9]*(,[1-9][0-9]*)*", tensor_split):
        raise SystemExit("tensor_split must be comma-separated positive integers")
    if backend == "vulkan" and visible_devices == "0,1" and tensor_split == "44,1":
        tensor_split = "1,1"
awk_filter = "!/stopping wait for next result due to should_stop condition/ && !/ref: https:\\/\\/github.com\\/ggml-org\\/llama.cpp\\/pull\\/22907/ && !/stop: cancel task/ && !/create_check/ && !/erased invalidated context checkpoint/ && !/creating new checkpoint during processing/ && !/forcing full prompt re-processing due to lack of cache data/ && !/slot print_timing:.*prompt processing/"
lines = [
    "#!/usr/bin/env bash",
    f"# local_llm_repo={repo}",
    f"# local_llm_family={family}",
    f"# local_llm_alias={alias}",
    f"# local_llm_quant={quant}",
    f"# local_llm_hf_file={hf_file}",
    "set -euo pipefail",
    'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
    'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"',
    'mkdir -p "$(dirname "$log_file")"',
    f'exec > >(stdbuf -oL -eL awk {shlex.quote(awk_filter)} | tee "$log_file") 2>&1',
    'profile="${1:-reliable}"',
    'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *) echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac',
    f"ctx={ctx}",
    f"batch={batch}",
    f"ubatch={ubatch}",
    f"ngl={ngl}",
]
if backend == "vulkan":
    lines.append(f"export GGML_VK_VISIBLE_DEVICES={visible_devices}")
elif visible_devices:
    lines.append(f"export HIP_VISIBLE_DEVICES={visible_devices}")
    lines.append(f"export ROCR_VISIBLE_DEVICES={visible_devices}")
server_bin = "./build-vulkan/bin/llama-server" if backend == "vulkan" else "./build/bin/llama-server"
lines.extend([
    f"exec {server_bin} \\",
    f"  -hf {shlex.quote(repo)} \\",
])
if hf_file:
    lines.append(f"  --hf-file {shlex.quote(hf_file)} \\")
else:
    lines[-1] = f"  -hf {shlex.quote(repo + ':' + quant)} \\\\"
lines.extend([
    "  --host 0.0.0.0 \\",
    "  --port 8080 \\",
    "  --timeout 600 \\",
    "  --threads-http 2 \\",
    "  --parallel 1 \\",
    "  --no-cont-batching \\",
    '  -ngl "$ngl" \\',
])
if backend:
    lines.extend([
        f"  --split-mode {shlex.quote(split_mode)} \\",
        f"  --tensor-split {shlex.quote(tensor_split)} \\",
    ])
if ctx_shift and ctx_shift not in {"off", "false", "0"}:
    lines.append("  --context-shift \\")
if cache_type_k:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", cache_type_k):
        raise SystemExit("cache_type_k must be a safe llama.cpp cache type")
    lines.append(f"  -ctk {shlex.quote(cache_type_k)} \\")
if cache_type_v:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", cache_type_v):
        raise SystemExit("cache_type_v must be a safe llama.cpp cache type")
    lines.append(f"  -ctv {shlex.quote(cache_type_v)} \\")
sampler_temp = "0.6"
sampler_top_p = "0.95"
sampler_top_k = "20"
repo_family_alias_lower = f"{repo} {family} {alias}".lower()
if family.lower().startswith("gemma") or alias.lower().startswith("gemma") or "gemma" in repo.lower():
    sampler_temp = "1.0"
    sampler_top_p = "0.95"
    sampler_top_k = "64"
lines.extend([
    "  --cache-ram 16384 \\",
    "  --ctx-checkpoints 64 \\",
    "  --checkpoint-every-n-tokens 4096 \\",
    '  -c "$ctx" \\',
    "  --flash-attn on \\",
    '  -ub "$ubatch" \\',
    '  -b "$batch" \\',
])
if "gemma-4-12b" in repo_family_alias_lower:
    lines.append("  --no-mmproj \\")
lines.extend([
    '  --threads "$(nproc)" \\',
    "  --prio 2 \\",
    "  --no-warmup \\",
    f"  --temp {sampler_temp} \\",
    f"  --top-p {sampler_top_p} \\",
    f"  --top-k {sampler_top_k} \\",
    "  --min-p 0.0 \\",
    "  --presence-penalty 0.0 \\",
    f"  --alias {shlex.quote(alias)} \\",
    "  --reasoning on",
])
with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines))
    handle.write("\n")
PY
	chmod +x "$launcher_file"
	local removed_selection_count
	removed_selection_count="$(remove_matching_selections "$repo" "$alias")"
	accepted_metadata_file="$(write_accepted_metadata "$repo" "$family" "$alias" "$launcher_file" "$profile" "$ctx" "$batch" "$ubatch" "$ngl" "$quant" "$hf_file" "$backend" "$visible_devices" "$split_mode" "$tensor_split" "$cache_type_k" "$cache_type_v" "$ctx_shift" "$target")"

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
	printf 'launcher_file=%s\n' "$launcher_file"
	printf 'start_script=%s\n' "$start_script"
	printf 'accepted_metadata_file=%s\n' "$accepted_metadata_file"
	if [[ "$create_vulkan" == true ]]; then
		write_vulkan_equivalent_for_accepted "$accepted_metadata_file"
	fi
	printf 'removed_selection_count=%s\n' "$removed_selection_count"
}

cmd_deploy() {
	local target=''
	local dry_run=false
	local yes=false
	local remote_dir="${OC_LOCAL_REMOTE_DIR:-~/llama.cpp}"

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
			printf '%s\n' 'Usage: model-manager deploy --target remote:<host> [--dry-run|--yes]'
			return 0
			;;
		--*)
			printf 'Unknown deploy option: %s\n' "$1" >&2
			return 2
			;;
		*)
			printf 'deploy accepts options only, got: %s\n' "$1" >&2
			return 2
			;;
		esac
	done

	if [[ "$yes" == true && "$dry_run" == true ]]; then
		printf '%s\n' 'choose either --dry-run or --yes, not both' >&2
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
		printf '%s\n' 'deploy requires --target remote:<host>' >&2
		return 2
		;;
	*)
		printf '%s\n' 'deploy currently requires --target remote:<host>' >&2
		return 2
		;;
	esac
	if [[ ! "$target" =~ ^remote:[A-Za-z0-9_.:-]+$ ]]; then
		printf '%s\n' 'invalid target: use remote:<host> with letters, digits, dot, underscore, colon, and hyphen' >&2
		return 2
	fi

	local -a accepted_files=()
	if [[ -L "$runs_dir" ]]; then
		printf 'model-manager refuses symlinked runs dir: %s\n' "$runs_dir" >&2
		return 1
	fi
	if [[ -e "$runs_dir" && ! -d "$runs_dir" ]]; then
		printf 'model-manager state path is not a directory: %s\n' "$runs_dir" >&2
		return 1
	fi
	if [[ -L "$runs_dir/accepted" ]]; then
		printf 'model-manager refuses symlinked accepted dir: %s\n' "$runs_dir/accepted" >&2
		return 1
	fi
	if [[ -L "$generated_launcher_dir" ]]; then
		printf 'model-manager refuses symlinked launchers dir: %s\n' "$generated_launcher_dir" >&2
		return 1
	fi
	if [[ -d "$runs_dir/accepted" ]]; then
		shopt -s nullglob
		accepted_files=("$runs_dir"/accepted/*.json)
		shopt -u nullglob
	fi

	if ((${#accepted_files[@]} == 0)); then
		printf '%s\n' 'Nothing to deploy: no accepted models or generated launcher state found.'
		return 0
	fi

	local plan_rows
	if ! plan_rows="$(
		python3 - "$runs_dir" "$remote_dir" "${accepted_files[@]}" <<'PY'
import json
import pathlib
import re
import sys

runs_dir = pathlib.Path(sys.argv[1])
remote_dir = sys.argv[2].rstrip("/")
launcher_dir = runs_dir / "launchers"

def safe_basename(value, suffix):
    return (
        isinstance(value, str)
        and pathlib.PurePath(value).name == value
        and re.fullmatch(r"[A-Za-z0-9_.-]+" + re.escape(suffix), value)
        and ".." not in value
        and not value.startswith("-")
    )


def safe_label(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+", value)
        and ".." not in value
        and not value.startswith("-")
    )


def require_safe_label(accepted_file, field, value):
    if not safe_label(value):
        raise SystemExit(
            f"invalid accepted metadata: {accepted_file} {field} contains unsafe characters"
        )

for raw_path in sys.argv[3:]:
    path = pathlib.Path(raw_path)
    if path.is_symlink() or not safe_basename(path.name, ".json"):
        continue
    try:
        with path.open(encoding="utf-8") as handle:
            accepted = json.load(handle)
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(accepted, dict):
        continue
    remote_start = accepted.get("remote_start")
    launcher_name = None
    if isinstance(remote_start, str):
        match = re.fullmatch(r"\./([A-Za-z0-9_.-]+\.sh)", remote_start)
        if match and safe_basename(match.group(1), ".sh"):
            launcher_name = match.group(1)
    launcher_file = accepted.get("launcher_file")
    if not launcher_name and isinstance(launcher_file, str):
        candidate = pathlib.PurePath(launcher_file).name
        if safe_basename(candidate, ".sh"):
            launcher_name = candidate
    if not launcher_name:
        continue
    launcher_path = launcher_dir / launcher_name
    if launcher_path.is_symlink() or not launcher_path.is_file():
        continue
    family = accepted.get("family") or path.stem
    alias = accepted.get("alias") or accepted.get("model_name") or "unknown"
    profile = accepted.get("profile") or "reliable"
    require_safe_label(path.name, "family", family)
    require_safe_label(path.name, "alias", alias)
    require_safe_label(path.name, "profile", profile)
    if "model_name" in accepted:
        require_safe_label(path.name, "model_name", accepted.get("model_name"))
    mtime = path.stat().st_mtime
    print(f"accepted={path.name}\tfamily={family}\talias={alias}\tlauncher={launcher_path}\tremote={remote_dir}/{launcher_name}\tprofile={profile}\tmtime={mtime}")
PY
	)"; then
		printf '%s\n' 'deploy plan generation failed' >&2
		return 1
	fi

	if [[ -z "$plan_rows" ]]; then
		printf '%s\n' 'Nothing to deploy: no accepted models with generated launcher files found.'
		return 0
	fi

	local host="${target#remote:}"
	local support_dir="${LOCAL_LLM_SUPPORT_DIR:-}"
	if [[ -z "$support_dir" ]]; then
		if [[ -f "$repo_root/scripts/run-current-model.sh" ]]; then
			support_dir="$repo_root/scripts"
		else
			support_dir="${LOCAL_LLM_SHARE_DIR:-$HOME/.local/share/local_llm}/scripts"
		fi
	fi
	for support_file in run-current-model.sh local-llm-switcher.py Caddyfile.local-llm run-local-llm-caddy-container.sh local-llm-switcher.service opencode-web.service; do
		if [[ ! -f "$support_dir/$support_file" ]]; then
			printf 'deploy support file missing: %s\n' "$support_dir/$support_file" >&2
			return 1
		fi
	done

	local env_remote_dir="$remote_dir"
	local env_remote_dir_warning=false
	if [[ "$env_remote_dir" == "~" || "$env_remote_dir" == \~/* || "$env_remote_dir" != /* ]]; then
		env_remote_dir='/home/<user>/llama.cpp'
		env_remote_dir_warning=true
	fi
	printf 'Deploy plan\n'
	printf 'target=%s\n' "$target"
	printf 'remote_dir=%s\n' "$remote_dir"
	printf 'Generated launchers:\n'
	while IFS=$'\t' read -r accepted family alias launcher remote_path profile mtime; do
		printf '  %s %s %s\n' "$family" "$alias" "$accepted"
		printf '    copy launcher: %s -> %s:%s\n' "${launcher#launcher=}" "$host" "${remote_path#remote=}"
	done <<<"$plan_rows"
	printf 'OpenCode support files:\n'
	printf '  required env file: ~/.config/local_llm/opencode-web.env\n'
	printf "    OPENCODE_WEB_COMMAND='<replace-with-your-opencode-web-command> --host 127.0.0.1 --port 3002'\n"
	printf '  required env file: ~/.config/local_llm/local-llm-switcher.env\n'
	if [[ "$env_remote_dir_warning" == true ]]; then
		printf '    warning: replace /home/<user>/llama.cpp with the absolute path on the GPU host\n'
	fi
	printf '    LLAMA_DIR=%s\n' "$env_remote_dir"
	printf '    LOCAL_LLM_WEB_UPSTREAM=http://127.0.0.1:3002\n'
	printf '    LOCAL_LLM_INJECT_TARGET=opencode\n'
	printf '  copy support: %s/run-current-model.sh -> %s:%s/run-current-model.sh\n' "$support_dir" "$host" "$remote_dir"
	printf '  copy support: %s/local-llm-switcher.py -> %s:%s/local-llm-switcher.py\n' "$support_dir" "$host" "$remote_dir"
	printf '  copy support: %s/Caddyfile.local-llm -> %s:%s/Caddyfile.local-llm\n' "$support_dir" "$host" "$remote_dir"
	printf '  copy support: %s/run-local-llm-caddy-container.sh -> %s:%s/run-local-llm-caddy-container.sh\n' "$support_dir" "$host" "$remote_dir"
	printf '  copy service: %s/local-llm-switcher.service -> %s:~/.config/systemd/user/local-llm-switcher.service\n' "$support_dir" "$host"
	printf '  copy service: %s/opencode-web.service -> %s:~/.config/systemd/user/opencode-web.service\n' "$support_dir" "$host"
	if [[ "$dry_run" == true ]]; then
		printf '%s\n' 'Dry-run only: no files copied.'
		return 0
	fi

	if [[ ! "$remote_dir" =~ ^(~|/)?[A-Za-z0-9_./-]+$ ]]; then
		printf 'invalid remote dir: %s\n' "$remote_dir" >&2
		return 2
	fi

	local q_remote_dir
	printf -v q_remote_dir '%q' "$remote_dir"
	ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" "mkdir -p $q_remote_dir ~/.config/systemd/user ~/.config/local_llm" || return 1

	local current_launcher=''
	local current_profile='reliable'
	local current_mtime='-1'
	local launcher_path launcher_name remote_path profile_value mtime_value
	while IFS=$'\t' read -r accepted family alias launcher remote_path profile mtime; do
		launcher_path="${launcher#launcher=}"
		launcher_name="${remote_path##*/}"
		profile_value="${profile#profile=}"
		mtime_value="${mtime#mtime=}"
		scp "$launcher_path" "$host:$remote_dir/$launcher_name" || return 1
		if python3 - "$mtime_value" "$current_mtime" <<'PY'; then
import sys
raise SystemExit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)
PY
			current_launcher="$launcher_name"
			current_profile="$profile_value"
			current_mtime="$mtime_value"
		fi
	done <<<"$plan_rows"

	scp "$support_dir/run-current-model.sh" "$host:$remote_dir/run-current-model.sh" || return 1
	scp "$support_dir/local-llm-switcher.py" "$host:$remote_dir/local-llm-switcher.py" || return 1
	scp "$support_dir/Caddyfile.local-llm" "$host:$remote_dir/Caddyfile.local-llm" || return 1
	scp "$support_dir/run-local-llm-caddy-container.sh" "$host:$remote_dir/run-local-llm-caddy-container.sh" || return 1
	scp "$support_dir/local-llm-switcher.service" "$host:~/.config/systemd/user/local-llm-switcher.service" || return 1
	scp "$support_dir/opencode-web.service" "$host:~/.config/systemd/user/opencode-web.service" || return 1

	if [[ -z "$current_launcher" ]]; then
		printf '%s\n' 'deploy could not determine current launcher' >&2
		return 1
	fi
	ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" "cd $q_remote_dir && chmod +x *.sh local-llm-switcher.py 2>/dev/null || true; { printf '%s\\n' 'REMOTE_SCRIPT=./$current_launcher'; printf '%s\\n' 'REMOTE_PROFILE=$current_profile'; } > current-model.env; systemctl --user restart llama-server.service" || return 1
	printf 'Deploy complete\n'
	printf 'target=%s\n' "$target"
	printf 'current=%s profile=%s\n' "$current_launcher" "$current_profile"
}

cmd_update_launcher() {
	local family=""
	local yes=false
	local dry_run=false

	while [[ $# -gt 0 ]]; do
		case "$1" in
		--family)
			if [[ $# -lt 2 || -z "$2" ]]; then
				printf '%s\n' '--family requires a family name' >&2
				return 2
			fi
			family="$2"
			shift 2
			;;
		--yes)
			yes=true
			shift
			;;
		--dry-run)
			dry_run=true
			shift
			;;
		-h | --help)
			printf '%s\n' 'Usage: model-manager update-launcher --family <family> [--dry-run|--yes]'
			return 0
			;;
		--*)
			printf 'Unknown update-launcher option: %s\n' "$1" >&2
			return 2
			;;
		*)
			printf 'update-launcher accepts options only, got: %s\n' "$1" >&2
			return 2
			;;
		esac
	done

	if [[ -z "$family" ]]; then
		printf '%s\n' 'update-launcher requires --family <family>' >&2
		return 2
	fi

	if [[ "$yes" == true && "$dry_run" == true ]]; then
		printf '%s\n' 'choose either --dry-run or --yes, not both' >&2
		return 2
	fi

	local metadata_file="$runs_dir/accepted/$family.json"
	if [[ ! -f "$metadata_file" ]]; then
		printf 'accepted metadata not found for family: %s\n' "$family"
		return 1
	fi

	# Use Python to regenerate launcher from accepted metadata
	python3 - "$metadata_file" "$generated_launcher_dir" "$dry_run" "$yes" <<'PY'
import json
import pathlib
import re
import shlex
import sys

metadata_path = pathlib.Path(sys.argv[1])
launcher_dir = pathlib.Path(sys.argv[2])
dry_run = sys.argv[3] == "true"
yes = sys.argv[4] == "true"

if metadata_path.is_symlink():
    print("refuses symlinked accepted file", file=sys.stderr)
    sys.exit(1)

with metadata_path.open(encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    print("accepted metadata must be an object", file=sys.stderr)
    sys.exit(1)

family = data.get("family") or metadata_path.stem
alias = data.get("alias") or data.get("model_name") or "unknown"
repo = data.get("repo") or data.get("hf_repo")
quant = data.get("quant", "")
hf_file = data.get("hf_file", "")
config = data.get("config") or {}
ctx = str(config.get("ctx", "131072"))
batch = str(config.get("batch", "4096"))
ubatch = str(config.get("ubatch", "256"))
ngl = str(config.get("ngl", "999"))
backend = str(config.get("backend", ""))
visible_devices = str(config.get("visible_devices", ""))
split_mode = str(config.get("split_mode", "layer"))
tensor_split = str(config.get("tensor_split", "1,1"))
cache_type_k = str(config.get("cache_type_k", ""))
cache_type_v = str(config.get("cache_type_v", ""))
ctx_shift = str(config.get("ctx_shift", ""))
reasoning = config.get("reasoning", True)

# Validate basics
for name, value in (("repo", repo), ("family", family), ("alias", alias), ("quant", quant), ("hf_file", hf_file)):
    if value and any(ord(c) < 32 or ord(c) == 127 for c in str(value)):
        print(f"unsafe character in {name}", file=sys.stderr)
        sys.exit(1)

for name, value, minimum in (("ctx", ctx, 1), ("batch", batch, 1), ("ubatch", ubatch, 1), ("ngl", ngl, 0)):
    if not str(value).isdigit():
        print(f"missing numeric {name}", file=sys.stderr)
        sys.exit(1)
    if int(value) < minimum:
        print(f"{name} too small", file=sys.stderr)
        sys.exit(1)

# Determine launcher file
launcher_name = f"start_{family}.sh"
launcher_path = launcher_dir / launcher_name

if launcher_path.is_symlink():
    print("refuses symlinked launcher", file=sys.stderr)
    sys.exit(1)

# Build awk filter
awk_filter = "!/stopping wait for next result due to should_stop condition/ && !/ref: https:\\\/\\\/github.com\\\/ggml-org\\\/llama.cpp\\\/pull\\\/22907/ && !/stop: cancel task/ && !/create_check/ && !/erased invalidated context checkpoint/ && !/creating new checkpoint during processing/ && !/forcing full prompt re-processing due to lack of cache data/ && !/slot print_timing:.*prompt processing/"

lines = [
    "#!/usr/bin/env bash",
    f"# local_llm_repo={repo}",
    f"# local_llm_family={family}",
    f"# local_llm_alias={alias}",
    f"# local_llm_quant={quant}",
    f"# local_llm_hf_file={hf_file}",
    "set -euo pipefail",
    'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
    'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"',
    'mkdir -p "$(dirname "$log_file")"',
    f'exec > >(stdbuf -oL -eL awk {shlex.quote(awk_filter)} | tee "$log_file") 2>&1',
    'profile="${1:-reliable}"',
    'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *) echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac',
    f"ctx={ctx}",
    f"batch={batch}",
    f"ubatch={ubatch}",
    f"ngl={ngl}",
]

if backend == "vulkan":
    lines.append(f"export GGML_VK_VISIBLE_DEVICES={visible_devices}")
elif visible_devices:
    lines.append(f"export HIP_VISIBLE_DEVICES={visible_devices}")
    lines.append(f"export ROCR_VISIBLE_DEVICES={visible_devices}")

server_bin = "./build-vulkan/bin/llama-server" if backend == "vulkan" else "./build/bin/llama-server"

lines.extend([
    f"exec {server_bin} \\",
    f"  -hf {shlex.quote(repo)} \\",
])
if hf_file:
    lines.append(f"  --hf-file {shlex.quote(hf_file)} \\")
else:
    lines.append(f"  -hf {shlex.quote(repo + ':' + quant)} \\")

lines.extend([
    "  --host 0.0.0.0 \\",
    "  --port 8080 \\",
    "  --timeout 600 \\",
    "  --threads-http 2 \\",
    "  --parallel 1 \\",
    "  --no-cont-batching \\",
    '  -ngl "$ngl" \\','
])
if backend:
    lines.extend([
        f"  --split-mode {shlex.quote(split_mode)} \\",
        f"  --tensor-split {shlex.quote(tensor_split)} \\",
    ])
if ctx_shift and ctx_shift not in {"off", "false", "0"}:
    lines.append("  --context-shift \\")
if cache_type_k:
    lines.append(f"  -ctk {shlex.quote(cache_type_k)} \\")
if cache_type_v:
    lines.append(f"  -ctv {shlex.quote(cache_type_v)} \\")

sampler_temp = "0.6"
sampler_top_p = "0.95"
sampler_top_k = "20"
repo_family_alias_lower = f"{repo} {family} {alias}".lower()
if family.lower().startswith("gemma") or alias.lower().startswith("gemma") or "gemma" in repo.lower():
    sampler_temp = "1.0"
    sampler_top_p = "0.95"
    sampler_top_k = "64"

lines.extend([
    "  --cache-ram 16384 \\",
    "  --ctx-checkpoints 64 \\",
    "  --checkpoint-every-n-tokens 4096 \\",
    '  -c "$ctx" \\','
    "  --flash-attn on \\",
    '  -ub "$ubatch" \\','
    '  -b "$batch" \\','
])
if "gemma-4-12b" in repo_family_alias_lower:
    lines.append("  --no-mmproj \\")

lines.extend([
    '  --threads "$(nproc)" \\','
    "  --prio 2 \\",
    "  --no-warmup \\",
    f"  --temp {sampler_temp} \\",
    f"  --top-p {sampler_top_p} \\",
    f"  --top-k {sampler_top_k} \\",
    "  --min-p 0.0 \\",
    "  --presence-penalty 0.0 \\",
    f"  --alias {shlex.quote(alias)} \\",
])

reasoning_flag = "on" if reasoning else "off"
lines.append(f"  --reasoning {reasoning_flag}")

content = "\n".join(lines) + "\n"

if dry_run:
    print("dry-run: would update launcher:")
    print(f"  {launcher_path}")
    print("content preview:")
    for line in lines[:10]:
        print(f"  {line}")
    print("  ...")
else:
    launcher_dir.mkdir(parents=True, exist_ok=True)
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"updated launcher: {launcher_path}")
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
		if [[ -d "$MODEL_MANAGER_PY" ]]; then
			python3 -m scripts.model_manager status
		else
			cmd_status
		fi
		;;
	list)
		# Delegates to Python backend (reads both new and legacy state)
		if [[ -d "$MODEL_MANAGER_PY" ]]; then
			python3 -m scripts.model_manager list
		else
			cmd_list "${@:2}"
		fi
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
	deploy)
		cmd_deploy "${@:2}"
		;;
	update-launcher)
		cmd_update_launcher "${@:2}"
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
