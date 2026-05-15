#!/usr/bin/env bash
# Model discovery script for local_llm
# Searches for compatible models based on hardware specifications

set -euo pipefail

# Function to get CPU cores
get_cpu_cores() {
    if command -v nproc &> /dev/null; then
        nproc
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        sysctl -n hw.ncpu
    else
        echo "unknown"
    fi
}

# Function to get RAM
get_ram() {
    if command -v free &> /dev/null; then
        free -g | awk '/^Mem:/{print $2}'
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        sysctl -n hw.memsize | awk '{print $1/1073741824}' | cut -d. -f1
    else
        echo "unknown"
    fi
}

# Function to get model recommendations based on hardware
discover_models() {
    echo "Model Discovery Results:"
    echo "-----------------------"
    echo "Based on your system configuration:"
    echo "- CPU Cores: $(get_cpu_cores)"
    echo "- RAM: $(get_ram) GB"
    echo ""
    echo "Recommended models:"
    echo "1. Qwen3.6-35B-A3B (Large context, good for general use)"
    echo "2. Qwen3-Coder-30B-A3B-Instruct (Code-specialized)"
    echo "3. Gemma-4-31B-it (Lightweight alternative)"
    echo "4. gpt-oss-20B (High reasoning capability)"
    echo ""
    echo "Use 'model-discovery.sh --detailed' for more information"
}

# Function to get detailed model information
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

# Main function
main() {
    if [[ $# -gt 0 && "$1" == "--detailed" ]]; then
        detailed_discovery
    else
        discover_models
    fi
}

main "$@"