#!/usr/bin/env bash
# Bring a bare Ubuntu host to the point where deploy.sh can run.
#
#   scripts/bootstrap-host.sh            # check only (default, read-only)
#   scripts/bootstrap-host.sh --install  # install what is missing
#
# Checks are read-only and safe on a live box. --install is idempotent: apt is
# given -y, the docker CLI plugins are only fetched when absent, and group and
# module edits are no-ops when already applied.
#
# What this CANNOT do, because the values or state live outside git -- see
# docs/RECOVERY.md: .env secrets, the Cloudflare tunnel ingress (dashboard-only),
# the model cache on /mnt/hfcache, and the agent auth.json credentials.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="check"
[[ "${1:-}" == "--install" ]] && MODE="install"

# Pinned to what ubt26 runs today; override to move them.
COMPOSE_VERSION="${COMPOSE_VERSION:-v5.1.4}"
BUILDX_VERSION="${BUILDX_VERSION:-v0.30.0}"

APT_PACKAGES=(
  docker.io git curl jq rsync python3 nodejs npm
  lm-sensors ca-certificates
  # Diagnostics only: the runners carry their own ROCm userspace in-image.
  rocminfo rocm-smi
)
# nct6775 drives the chassis fans (ubt26-airflowd), corsair_psu the PSU telemetry
# (scripts/ubt26-psu-mon). Both load fine at runtime but are lost on reboot
# unless persisted -- corsair_psu was missing from modules-load.d on ubt26.
MODULES=(nct6775 corsair_psu)
GROUPS_NEEDED=(docker video render)

MISSING=0
ok() { printf '  \033[32mok\033[0m       %s\n' "$1"; }
miss() {
  printf '  \033[31mMISSING\033[0m  %s\n' "$1"
  MISSING=$((MISSING + 1))
}

need_root() {
  if [[ $EUID -ne 0 ]] && ! command -v sudo >/dev/null; then
    echo "need root or sudo for --install" >&2
    exit 1
  fi
}
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

echo "== apt packages =="
for p in "${APT_PACKAGES[@]}"; do
  if dpkg -s "$p" >/dev/null 2>&1; then ok "$p"; else
    miss "$p"
    if [[ $MODE == install ]]; then
      need_root
      $SUDO apt-get update -qq
      $SUDO apt-get install -y "$p"
    fi
  fi
done

echo "== docker CLI plugins (not apt-provided) =="
PLUGIN_DIR="$HOME/.docker/cli-plugins"
install_plugin() {
  local name="$1" url="$2"
  mkdir -p "$PLUGIN_DIR"
  curl -fsSL -o "$PLUGIN_DIR/$name" "$url"
  chmod +x "$PLUGIN_DIR/$name"
}
ARCH="$(uname -m)"
for plug in compose buildx; do
  if [[ -x "$PLUGIN_DIR/docker-$plug" ]]; then ok "docker-$plug"; else
    miss "docker-$plug (hand-installed binary, apt will not restore it)"
    if [[ $MODE == install ]]; then
      case "$plug" in
        compose) install_plugin docker-compose \
          "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" ;;
        buildx) install_plugin docker-buildx \
          "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64" ;;
      esac
    fi
  fi
done

echo "== cloudflared =="
if command -v cloudflared >/dev/null; then ok "cloudflared"; else
  miss "cloudflared (needs Cloudflare's apt repo; tunnel ingress is dashboard-managed)"
fi

echo "== group membership ($USER) =="
for g in "${GROUPS_NEEDED[@]}"; do
  if id -nG "$USER" | tr ' ' '\n' | grep -qx "$g"; then ok "$g"; else
    miss "$g"
    if [[ $MODE == install ]]; then
      need_root
      $SUDO usermod -aG "$g" "$USER"
      echo "     (log out and back in for '$g' to take effect)"
    fi
  fi
done

echo "== kernel modules persisted =="
for m in "${MODULES[@]}"; do
  if grep -rqx "$m" /etc/modules-load.d/ 2>/dev/null; then ok "$m"; else
    miss "$m (not in modules-load.d; lost on reboot)"
    if [[ $MODE == install ]]; then
      need_root
      echo "$m" | $SUDO tee -a /etc/modules-load.d/local-llm.conf >/dev/null
      $SUDO modprobe "$m" || true
    fi
  fi
done

echo "== GPU visible =="
if [[ -e /dev/kfd && -d /dev/dri ]]; then ok "/dev/kfd and /dev/dri present"; else
  miss "/dev/kfd or /dev/dri (amdgpu not loaded)"
fi

echo "== case-fan daemon =="
if systemctl is-enabled ubt26-airflowd >/dev/null 2>&1; then ok "ubt26-airflowd enabled"; else
  miss "ubt26-airflowd not installed"
  if [[ $MODE == install ]]; then
    need_root
    $SUDO install -m 0755 "$REPO_DIR/scripts/ubt26-airflowd" /usr/local/sbin/ubt26-airflowd
    $SUDO install -m 0644 "$REPO_DIR/scripts/ubt26-airflowd.service" /etc/systemd/system/
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now ubt26-airflowd
  fi
fi

echo "== repo-side state =="
if [[ -f "$REPO_DIR/.env" ]]; then
  ok ".env present"
else
  miss ".env (secrets -- see docs/RECOVERY.md, values are not in git)"
fi

echo
if [[ $MISSING -eq 0 ]]; then
  echo "All checks passed. Next: scripts/state-init.sh, scripts/agents-init.sh, then ./deploy.sh"
else
  echo "$MISSING item(s) missing."
  [[ $MODE == check ]] && echo "Re-run with --install to fix what is automatable."
  exit 1
fi
