#!/usr/bin/env bash
# shellcheck disable=SC1091
# hardware-analyzer.sh - detect system capabilities for model selection.
# Uses lib.sh for shared utilities and logging.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_SH_SCRIPT_DIR="$SCRIPT_DIR" source "$SCRIPT_DIR/lib.sh"

get_gpu_memory() {
  if command -v rocminfo &>/dev/null; then
    rocminfo 2>/dev/null | grep -i "memory" | head -1 | awk '{print $1}' || echo "unknown"
  else
    echo "unknown"
  fi
}

get_cpu_info() {
  if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    nproc
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    sysctl -n hw.ncpu
  else
    echo "unknown"
  fi
}

get_ram_info() {
  if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    free -g | awk '/^Mem:/{print $2}'
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    sysctl -n hw.memsize | awk '{print $1/1073741824}' | cut -d. -f1
  else
    echo "unknown"
  fi
}

main() {
  echo "Hardware Analysis Results:"
  echo "------------------------"
  echo "CPU Cores: $(get_cpu_info)"
  echo "Available RAM: $(get_ram_info) GB"
  echo "GPU Memory: $(get_gpu_memory)"
  echo ""
  echo "System Architecture: $(uname -m)"
  echo "Operating System: $(uname -s)"
}

main
