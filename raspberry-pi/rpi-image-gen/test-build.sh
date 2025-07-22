#!/bin/bash

# Test script for CUPCAKE Pi 5 image configuration
# This script validates the configuration without building the full image

set -e

echo "=== CUPCAKE Pi 5 Configuration Test ==="

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/cupcake-pi5-config.cfg"

echo "Script directory: $SCRIPT_DIR"
echo "Config file: $CONFIG_FILE"

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Configuration file not found: $CONFIG_FILE"
    exit 1
else
    echo "✅ Configuration file found"
fi

# Check configuration file structure
echo -e "\n=== Configuration File Content ==="
if [ -r "$CONFIG_FILE" ]; then
    echo "✅ Configuration file is readable"
    
    # Check for required sections
    echo -e "\n--- Checking required sections ---"
    sections=("device" "image" "sys" "cupcake")
    for section in "${sections[@]}"; do
        if grep -q "^\[$section\]" "$CONFIG_FILE"; then
            echo "✅ Section [$section] found"
        else
            echo "❌ Section [$section] missing"
        fi
    done
    
    # Show key configuration values
    echo -e "\n--- Key Configuration Values ---"
    echo "Image name: $(grep '^image_name' "$CONFIG_FILE" | cut -d'=' -f2 | xargs)"
    echo "Architecture: $(grep '^architecture' "$CONFIG_FILE" | cut -d'=' -f2 | xargs)"
    echo "Default user: $(grep '^default_user' "$CONFIG_FILE" | cut -d'=' -f2 | xargs)"
    echo "Collections: $(grep '^collections' "$CONFIG_FILE" | cut -d'=' -f2 | xargs)"
else
    echo "❌ Configuration file is not readable"
    exit 1
fi

# Check supporting files
echo -e "\n=== Supporting Files Check ==="

# Check collections
if [ -d "${SCRIPT_DIR}/collections" ]; then
    echo "✅ Collections directory found"
    if [ -f "${SCRIPT_DIR}/collections/cupcake-packages.yaml" ]; then
        echo "✅ CUPCAKE packages collection found"
    else
        echo "❌ CUPCAKE packages collection missing"
    fi
else
    echo "❌ Collections directory missing"
fi

# Check hooks
if [ -d "${SCRIPT_DIR}/hooks" ]; then
    echo "✅ Hooks directory found"
    hook_count=$(ls "${SCRIPT_DIR}/hooks"/*.sh 2>/dev/null | wc -l)
    echo "✅ Found $hook_count hook scripts"
    
    # List hooks
    echo "--- Available hooks ---"
    ls -1 "${SCRIPT_DIR}/hooks"/*.sh 2>/dev/null | sort | while read hook; do
        echo "  $(basename "$hook")"
    done
else
    echo "❌ Hooks directory missing"
fi

# Check scripts
if [ -d "${SCRIPT_DIR}/scripts" ]; then
    echo "✅ Scripts directory found"
    if [ -f "${SCRIPT_DIR}/scripts/detect-system-capabilities.py" ]; then
        echo "✅ System capability detection script found"
    else
        echo "❌ System capability detection script missing"
    fi
else
    echo "❌ Scripts directory missing"
fi

# Check overlays
if [ -d "${SCRIPT_DIR}/overlays" ]; then
    echo "✅ Overlays directory found"
else
    echo "⚠️  Overlays directory not found (optional)"
fi

# Validate build script
if [ -f "${SCRIPT_DIR}/build-image.sh" ]; then
    echo "✅ Build script found"
    if [ -x "${SCRIPT_DIR}/build-image.sh" ]; then
        echo "✅ Build script is executable"
    else
        echo "❌ Build script is not executable"
    fi
else
    echo "❌ Build script missing"
fi

echo -e "\n=== Configuration Test Summary ==="
echo "Configuration file: $CONFIG_FILE"
echo "Directory structure validated"
echo "Ready for rpi-image-gen build"

# Show suggested build command
echo -e "\n=== Suggested Build Command ==="
echo "cd $SCRIPT_DIR"
echo "./build-image.sh"
echo ""
echo "Or manually:"
echo "rpi-image-gen -c cupcake-pi5-config.cfg -D . -o images --verbose"