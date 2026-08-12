#!/usr/bin/env bash
# Standalone installer for local_llm project.
# After install, all components live under ~/.local/bin and
# ~/.local/share/local_llm, with no dependency on the repo.

set -euo pipefail

PREFIX=""
UNINSTALL=false
SHOW_HELP=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p | --prefix)
      PREFIX="$2"
      shift 2
      ;;
    -u | --uninstall)
      UNINSTALL=true
      shift
      ;;
    -h | --help)
      SHOW_HELP=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

BIN_DIR="${PREFIX:-${LOCAL_LLM_BIN_DIR:-$HOME/.local/bin}}"
SHARE_DIR="${LOCAL_LLM_SHARE_DIR:-$HOME/.local/share/local_llm}"
CONFIG_DIR="$SHARE_DIR/config"
RUNS_DIR="$SHARE_DIR/runs"
WRAPPER_MARKER="# local_llm generated wrapper"

is_legacy_local_llm_wrapper() {
  case "$1" in
    oc-speed | oc-fastlong | oc-balanced | oc-reliable | oc-tiny | \
      oc-qwen-speed | oc-qwen-fastlong | oc-qwen-balanced | oc-qwen-reliable | oc-qwen-tiny | \
      oc-qwen-coder-speed | oc-qwen-coder-fastlong | oc-qwen-coder-balanced | oc-qwen-coder-reliable | oc-qwen-coder-tiny | \
      oc-gemma-speed | oc-gemma-fastlong | oc-gemma-balanced | oc-gemma-reliable | oc-gemma-tiny | \
      oc-gpt-oss-speed | oc-gpt-oss-fastlong | oc-gpt-oss-balanced | oc-gpt-oss-reliable | oc-gpt-oss-tiny | \
      oc-deepseek-r1-speed | oc-deepseek-r1-fastlong | oc-deepseek-r1-balanced | oc-deepseek-r1-reliable | oc-deepseek-r1-tiny | \
      oc-coder-speed | oc-coder-fastlong | oc-coder-balanced | oc-coder-reliable | oc-coder-tiny)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

remove_generated_wrappers() {
  local wrapper
  local wrapper_name
  local symlink_target

  [[ -d "$BIN_DIR" ]] || return 0

  # Remove legacy generated/convenience wrappers before rebuilding from accepted state.
  for wrapper in "$BIN_DIR"/oc-*; do
    [[ -e "$wrapper" && "${wrapper##*/}" != "oc-local" ]] || continue
    wrapper_name="${wrapper##*/}"
    if [[ -L "$wrapper" ]]; then
      symlink_target="$(readlink "$wrapper")"
      [[ "${symlink_target##*/}" == "oc-local" ]] || continue
      rm -f "$wrapper"
    elif [[ -f "$wrapper" ]] && grep -qxF "$WRAPPER_MARKER" "$wrapper"; then
      rm -f "$wrapper"
    elif is_legacy_local_llm_wrapper "$wrapper_name"; then
      rm -f "$wrapper"
    fi
  done
}

if [[ "$UNINSTALL" == true ]]; then
  echo "Uninstalling local_llm..."

  # Remove core binaries
  rm -f "$BIN_DIR"/oc-local \
    "$BIN_DIR"/lib.sh \
    "$BIN_DIR"/model-manager \
    "$BIN_DIR"/model-discovery \
    "$BIN_DIR"/update-manager \
    "$BIN_DIR"/hardware-analyzer \
    "$BIN_DIR"/oc-qwen-coder \
    "$BIN_DIR"/oc-coder \
    "$BIN_DIR"/oc-code

  # Remove convenience wrappers by pattern
  remove_generated_wrappers

  # Remove share directory
  rm -rf "$SHARE_DIR"

  # If we installed into a dedicated prefix dir, remove it if empty
  if [[ -d "$BIN_DIR" && "$BIN_DIR" != "$HOME/.local/bin" ]]; then
    rmdir "$BIN_DIR" 2>/dev/null || true
  fi

  echo "Uninstall complete."
  exit 0
fi

if [[ "$SHOW_HELP" == true ]]; then
  cat <<'HELP'
Usage:
  ./installer.sh [-p PREFIX]              Install local_llm
  ./installer.sh -u                        Uninstall local_llm
  ./installer.sh --uninstall               Uninstall local_llm

Options:
  -p, --prefix PATH   Install binaries into PATH (default: ~/.local/bin)

Examples:
  ./installer.sh
  ./installer.sh -p ~/.local/bin/localllm
HELP
  exit 0
fi

echo "Installing local_llm as standalone app..."

# Installer is expected to run from repo root.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$REPO_ROOT/scripts/oc-local" ]]; then
  echo "Error: This script must be run from the local_llm project directory"
  exit 1
fi

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$RUNS_DIR" "$SHARE_DIR/scripts"

# Copy core scripts (overwrite existing)
echo "Installing core scripts..."
install -m 0755 "$REPO_ROOT/scripts/oc-local" "$BIN_DIR/oc-local"
install -m 0755 "$REPO_ROOT/scripts/model-manager.sh" "$BIN_DIR/model-manager"
install -m 0755 "$REPO_ROOT/scripts/model-discovery.sh" "$BIN_DIR/model-discovery"
install -m 0755 "$REPO_ROOT/scripts/model-fit.py" "$BIN_DIR/model-fit.py"
install -m 0755 "$REPO_ROOT/scripts/update-manager.sh" "$BIN_DIR/update-manager"
install -m 0755 "$REPO_ROOT/scripts/hardware-analyzer.sh" "$BIN_DIR/hardware-analyzer"

# Copy deploy support files (overwrite existing)
install -m 0755 "$REPO_ROOT/scripts/run-current-model.sh" "$SHARE_DIR/scripts/run-current-model.sh"
install -m 0755 "$REPO_ROOT/scripts/local-llm-switcher.py" "$SHARE_DIR/scripts/local-llm-switcher.py"
install -m 0644 "$REPO_ROOT/scripts/Caddyfile.local-llm" "$SHARE_DIR/scripts/Caddyfile.local-llm"
install -m 0755 "$REPO_ROOT/scripts/run-local-llm-caddy-container.sh" "$SHARE_DIR/scripts/run-local-llm-caddy-container.sh"
install -m 0644 "$REPO_ROOT/scripts/local-llm-switcher.service" "$SHARE_DIR/scripts/local-llm-switcher.service"
install -m 0644 "$REPO_ROOT/scripts/opencode-web.service" "$SHARE_DIR/scripts/opencode-web.service"

# Copy configs (overwrite existing)
echo "Installing configuration..."
# Profiles are the single source of truth and live in the state dir; the repo has no
# seed copy and the installer must never overwrite them. Migrate the legacy config-dir
# location once, then bootstrap an empty file for a fresh install.
if [[ ! -f "$SHARE_DIR/profiles.json" && -f "$CONFIG_DIR/profiles.json" ]]; then
  mv "$CONFIG_DIR/profiles.json" "$SHARE_DIR/profiles.json"
fi
if [[ ! -f "$SHARE_DIR/profiles.json" ]]; then
  printf '{\n  "families": {},\n  "profiles": {}\n}\n' >"$SHARE_DIR/profiles.json"
fi
if [[ -f "$REPO_ROOT/configs/candidates.json" ]]; then
  cp -f "$REPO_ROOT/configs/candidates.json" "$CONFIG_DIR/candidates.json"
fi

# Create convenience wrapper scripts only for accepted generated state.
echo "Installing generated convenience commands..."
remove_generated_wrappers

create_wrapper() {
  local name="$1"
  local family="$2"
  local profile="$3"
  local remote_host="${4:-}"

  [[ "$name" != "oc-local" ]] || return 0
  rm -f "$BIN_DIR/$name"
  cat >"$BIN_DIR/$name" <<EOF
#!/usr/bin/env bash
$WRAPPER_MARKER
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
EOF
  if [[ -n "$remote_host" ]]; then
    cat >>"$BIN_DIR/$name" <<EOF
remote_host="\${OC_LOCAL_REMOTE_HOST:-$remote_host}"
export OC_LOCAL_BASE_URL="\${OC_LOCAL_BASE_URL:-http://\$remote_host:8080/v1}"
exec "\$SCRIPT_DIR/oc-local" "$family" "$profile" --remote "\$remote_host" "\$@"
EOF
  else
    cat >>"$BIN_DIR/$name" <<EOF
exec "\$SCRIPT_DIR/oc-local" "$family" "$profile" "\$@"
EOF
  fi
  chmod +x "$BIN_DIR/$name"
}

if [[ -d "$RUNS_DIR/accepted" ]]; then
  while IFS=$'\t' read -r family profile remote_host; do
    [[ -n "$family" && -n "$profile" ]] || continue
    create_wrapper "oc-${family}-${profile}" "$family" "$profile" "$remote_host"
    if [[ "$profile" == "reliable" ]]; then
      create_wrapper "oc-${family}" "$family" "$profile" "$remote_host"
    fi
  done < <(
    python3 - "$RUNS_DIR/accepted" <<'PY'
import json
import pathlib
import re
import sys

accepted_dir = pathlib.Path(sys.argv[1])
safe = re.compile(r"^[A-Za-z0-9_.-]+$")
for path in sorted(accepted_dir.glob("*.json")):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(data, dict):
        continue
    family = data.get("family") or path.stem
    profiles = []
    target = data.get("target") or ""
    remote_host = ""
    if isinstance(target, str) and target.startswith("remote:"):
        remote_host = target.split(":", 1)[1]
    if remote_host and (not safe.fullmatch(remote_host) or ".." in remote_host):
        remote_host = ""
    if isinstance(data.get("profile"), str):
        profiles.append(data["profile"])
    if isinstance(data.get("profiles"), dict):
        profiles.extend(key for key in data["profiles"] if isinstance(key, str))
    for profile in sorted(set(profiles)):
        if safe.fullmatch(family) and safe.fullmatch(profile) and ".." not in family + profile:
            print(f"{family}\t{profile}\t{remote_host}")
PY
  )
fi

echo "Installation complete!"
echo ""
echo "Installed paths:"
echo "  Binaries:  $BIN_DIR"
echo "  Config:    $CONFIG_DIR"
echo "  Run data:  $RUNS_DIR"
echo ""
echo "To use commands, ensure ~/.local/bin is in your PATH:"
echo "  export PATH=~/.local/bin:\$PATH"
echo ""
echo "Examples:"
echo "  oc-local <family> <profile> --lean"
echo "  hardware-analyzer"
echo "  model-discovery"
echo "  update-manager"
