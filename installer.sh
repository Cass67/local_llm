#!/usr/bin/env bash
# Enhanced installer for local_llm project
# Integrates new discovery and update features

set -euo pipefail

echo "Installing local_llm client components with enhanced features..."

# Check if we're in the correct directory
if [[ ! -f "scripts/oc-local" ]]; then
    echo "Error: This script must be run from the local_llm project directory"
    exit 1
fi

# Ensure ~/.local/bin exists
mkdir -p ~/.local/bin

# Install the main oc-local script
echo "Installing oc-local script..."
install -m 0755 scripts/oc-local ~/.local/bin/oc-local

# Create symlinks for all profile combinations
echo "Creating symlinks for all command combinations..."

# Create basic profile symlinks
for profile in speed fastlong balanced reliable tiny; do
    ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-${profile}
done

# Create family-profile symlinks
for family in qwen qwen-coder gemma gemma-vision gpt-oss deepseek-r1; do
    for profile in speed fastlong balanced reliable tiny; do
        ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-${family}-${profile}
    done
done

# Create additional convenience symlinks
for profile in speed fastlong balanced reliable tiny; do
    ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-coder-${profile}
done

# Create family-specific symlinks for common commands
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen-coder
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-coder
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-code

# Install new enhancement scripts
echo "Installing enhancement scripts..."
install -m 0755 scripts/hardware-analyzer.sh ~/.local/bin/hardware-analyzer
install -m 0755 scripts/model-discovery.sh ~/.local/bin/model-discovery
install -m 0755 scripts/update-manager.sh ~/.local/bin/update-manager

echo "Installation complete!"
echo ""
echo "Enhanced features installed:"
echo "- hardware-analyzer: System capability detection"
echo "- model-discovery: Model recommendation system"
echo "- update-manager: Update management"
echo ""
echo "To use the installed commands, you need to add ~/.local/bin to your PATH:"
echo "  export PATH=~/.local/bin:\$PATH"
echo ""
echo "You can now use commands like:"
echo "  oc-qwen-reliable --lean"
echo "  oc-gemma-vision-reliable --lean"
echo "  oc-qwen-coder-fastlong --lean"
echo ""
echo "Enhanced functionality:"
echo "  hardware-analyzer"
echo "  model-discovery"
echo "  model-discovery --detailed"
echo "  update-manager"
echo ""
echo "Note: The oc-local script is installed at ~/.local/bin/oc-local"