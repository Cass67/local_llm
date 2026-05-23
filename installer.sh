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
  find "$BIN_DIR" -maxdepth 1 \( -name "oc-speed" -o -name "oc-fastlong" -o -name "oc-balanced" -o -name "oc-reliable" -o -name "oc-tiny" -o -name "oc-qwen-*" -o -name "oc-qwen-coder-*" -o -name "oc-gemma-*" -o -name "oc-gpt-oss-*" -o -name "oc-deepseek-r1-*" -o -name "oc-coder-*" \) -exec rm -f {} + 2>/dev/null || true

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
  ./installer.sh -p /Users/cass/.local/bin/localllm
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

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$RUNS_DIR"

# Copy core scripts (overwrite existing)
echo "Installing core scripts..."
install -m 0755 "$REPO_ROOT/scripts/oc-local" "$BIN_DIR/oc-local"
install -m 0755 "$REPO_ROOT/scripts/lib.sh" "$BIN_DIR/lib.sh"
install -m 0755 "$REPO_ROOT/scripts/model-manager.sh" "$BIN_DIR/model-manager"
install -m 0755 "$REPO_ROOT/scripts/model-discovery.sh" "$BIN_DIR/model-discovery"
install -m 0755 "$REPO_ROOT/scripts/model-fit.py" "$BIN_DIR/model-fit.py"
install -m 0755 "$REPO_ROOT/scripts/update-manager.sh" "$BIN_DIR/update-manager"
install -m 0755 "$REPO_ROOT/scripts/hardware-analyzer.sh" "$BIN_DIR/hardware-analyzer"

# Copy configs (overwrite existing)
echo "Installing configuration..."
if [[ -f "$REPO_ROOT/configs/profiles.json" ]]; then
  cp -f "$REPO_ROOT/configs/profiles.json" "$CONFIG_DIR/profiles.json"
fi
if [[ -f "$REPO_ROOT/configs/candidates.json" ]]; then
  cp -f "$REPO_ROOT/configs/candidates.json" "$CONFIG_DIR/candidates.json"
fi

# Create convenience wrapper scripts (no symlinks)
echo "Installing convenience commands..."

# Remove wrappers for families that were removed after benchmarking.
rm -f "$BIN_DIR"/oc-glm-hauhau \
  "$BIN_DIR"/oc-glm-hauhau-speed \
  "$BIN_DIR"/oc-glm-hauhau-fastlong \
  "$BIN_DIR"/oc-glm-hauhau-balanced \
  "$BIN_DIR"/oc-glm-hauhau-reliable \
  "$BIN_DIR"/oc-glm-hauhau-tiny

# Basic profile wrappers: oc-speed, etc.
for profile in speed fastlong balanced reliable tiny; do
  local_name="oc-${profile}"
  # Never overwrite the main oc-local binary
  if [[ "$local_name" == "oc-local" ]]; then
    continue
  fi

  rm -f "$BIN_DIR/$local_name"
  cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen "$profile" "\$@"
EOF
  chmod +x "$BIN_DIR/$local_name"
done

# Family-profile wrappers: oc-qwen-reliable, etc.
# Skip if the resulting name would be "oc-local"
for family in qwen qwen-hauhau qwen-27b-hauhau gemma-hauhau qwen-27b qwen-opus qwen-heretic qwen-coder qwen-coder-next gemma gpt-oss deepseek-r1; do
  for profile in speed fastlong balanced reliable tiny; do
    local_name="oc-${family}-${profile}"
    if [[ "$local_name" != "oc-local" ]]; then
      rm -f "$BIN_DIR/$local_name"
      cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" "$family" "$profile" "\$@"
EOF
      chmod +x "$BIN_DIR/$local_name"
    fi
  done
done

local_name="oc-qwen-hauhau"
rm -f "$BIN_DIR/$local_name"
cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-hauhau reliable "\$@"
EOF
chmod +x "$BIN_DIR/$local_name"

for family in qwen-27b-hauhau gemma-hauhau; do
  local_name="oc-${family}"
  rm -f "$BIN_DIR/$local_name"
  cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" "$family" reliable "\$@"
EOF
  chmod +x "$BIN_DIR/$local_name"
done

# Session-resume shortcut for the HauhauCS aggressive model.
local_name="oc-qwen-hauhau-ses-2009"
rm -f "$BIN_DIR/$local_name"
cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-hauhau reliable "\$@" --lean -s ses_2009bfccfffeEVdvBAajurVOi4
EOF
chmod +x "$BIN_DIR/$local_name"

# MTP-visible wrappers: oc-qwen-mtp, oc-qwen-27b-mtp, oc-qwen-opus-mtp, oc-qwen-heretic-mtp.
for family in qwen qwen-27b qwen-opus qwen-heretic; do
  for profile in speed fastlong balanced reliable tiny; do
    local_name="oc-${family}-mtp-${profile}"
    rm -f "$BIN_DIR/$local_name"
    cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" "$family" "$profile" "\$@"
EOF
    chmod +x "$BIN_DIR/$local_name"
  done

  local_name="oc-${family}-mtp"
  rm -f "$BIN_DIR/$local_name"
  cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" "$family" reliable "\$@"
EOF
  chmod +x "$BIN_DIR/$local_name"
done

# Coder convenience wrappers
for profile in speed fastlong balanced reliable tiny; do
  local_name="oc-coder-${profile}"
  # Safety: never overwrite main oc-local binary
  if [[ "$local_name" == "oc-local" ]]; then
    continue
  fi

  rm -f "$BIN_DIR/$local_name"
  cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-coder "$profile" "\$@"
EOF
  chmod +x "$BIN_DIR/$local_name"
done

# Coder Next convenience wrappers
for profile in speed fastlong balanced reliable tiny; do
  local_name="oc-coder-next-${profile}"
  rm -f "$BIN_DIR/$local_name"
  cat >"$BIN_DIR/$local_name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-coder-next "$profile" "\$@"
EOF
  chmod +x "$BIN_DIR/$local_name"
done

# Family-specific convenience wrappers (avoid overwriting oc-local)
for name in oc-qwen-coder oc-coder oc-code; do
  # Safety: never overwrite main oc-local binary
  if [[ "$name" == "oc-local" ]]; then
    continue
  fi

  rm -f "$BIN_DIR/$name"
  cat >"$BIN_DIR/$name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-coder reliable "\$@"
EOF
  chmod +x "$BIN_DIR/$name"
done

for name in oc-qwen-coder-next oc-coder-next; do
  rm -f "$BIN_DIR/$name"
  cat >"$BIN_DIR/$name" <<EOF
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/oc-local" qwen-coder-next reliable "\$@"
EOF
  chmod +x "$BIN_DIR/$name"
done

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
echo "  oc-local qwen reliable --lean"
echo "  oc-qwen-reliable --lean"
echo "  hardware-analyzer"
echo "  model-discovery"
echo "  update-manager"
