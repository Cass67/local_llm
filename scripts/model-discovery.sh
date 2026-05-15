#!/usr/bin/env bash
# model-discovery.sh - search for compatible models based on hardware.
# Delegates lifecycle to model-manager.sh and uses lib.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

MODEL_MANAGER="$SCRIPT_DIR/model-manager.sh"

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
    sysctl -n hw.memsize | awk '{print $1/1073741824}' | cut -d. -f1
  else
    echo "unknown"
  fi
}

discover_models() {
  echo "Model Discovery Results:"
  echo "-----------------------"
  echo "Based on your system configuration:"
  echo "- CPU Cores: $(get_cpu_cores)"
  echo "- RAM: $(get_ram) GB"
  echo ""
  echo "Recommended model families (see profiles in profiles.json):"
  echo "- qwen: general-purpose"
  echo "- qwen-coder: code-specialized"
  echo "- gemma: lightweight alternative"
  echo "- gpt-oss: high reasoning capability"
  echo ""
  echo "To discover new candidate models for a family, run:"
  echo "  model-manager.sh discover <family>"
}

detailed_discovery() {
  echo "Detailed Model Information:"
  echo "---------------------------"
  echo "Qwen3.6-35B-A3B:"
  echo "  - Context: 65k tokens"
  echo "  - Recommended quantization: UD-Q3_K_XL"
  echo "  - VRAM requirement: ~16GB (with full offload)"
  echo ""
  echo "Qwen3-Coder-30B-A3B-Instruct:"
  echo "  - Context: 65k tokens"
  echo "  - Recommended quantization: UD-Q3_K_XL"
  echo "  - VRAM requirement: ~16GB (with full offload)"
  echo ""
  echo "Gemma-4-31B-it:"
  echo "  - Context: 65k tokens"
  echo "  - Recommended quantization: UD-Q2_K_XL"
  echo "  - VRAM requirement: ~12GB (with full offload)"
  echo ""
  echo "gpt-oss-20B:"
  echo "  - Context: 131k tokens"
  echo "  - Recommended quantization: UD-Q8_K_XL"
  echo "  - VRAM requirement: ~20GB (with full offload)"
}

main() {
  if [[ $# -gt 0 && "$1" == "--detailed" ]]; then
    detailed_discovery
  else
    discover_models
  fi
}

main "$@"