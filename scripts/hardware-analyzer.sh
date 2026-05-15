#!/usr/bin/env bash
# Hardware analyzer for local_llm system
# Detects system capabilities for model selection

set -euo pipefail

# Function to get GPU memory (ROCm example)
get_gpu_memory() {
    if command -v rocminfo &> /dev/null; then
        # Get total GPU memory from ROCm
        rocminfo | grep -i "memory" | head -1 | awk '{print $1}' 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

# Function to get CPU info
get_cpu_info() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        nproc
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        sysctl -n hw.ncpu
    else
        echo "unknown"
    fi
}

# Function to get available RAM
get_ram_info() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        free -g | awk '/^Mem:/{print $2}'
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        sysctl -n hw.memsize | awk '{print $1/1073741824}' | cut -d. -f1
    else
        echo "unknown"
    fi
}

# Main function
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