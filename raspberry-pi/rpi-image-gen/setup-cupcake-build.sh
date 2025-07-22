#!/bin/bash

# Setup script for CUPCAKE Pi 5 image building with rpi-image-gen
# This script sets up the rpi-image-gen environment and copies CUPCAKE configuration

set -e

echo "=== CUPCAKE Pi 5 Image Build Setup ==="

# Get the directory where this script is located
CUPCAKE_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(pwd)"

echo "CUPCAKE config directory: $CUPCAKE_CONFIG_DIR"
echo "Current working directory: $WORK_DIR"

# Check if rpi-image-gen is already cloned
if [ -d "rpi-image-gen" ]; then
    echo "✅ rpi-image-gen directory already exists"
else
    echo "📥 Cloning rpi-image-gen repository..."
    git clone https://github.com/raspberrypi/rpi-image-gen.git
fi

cd rpi-image-gen

# Install dependencies if needed
if [ ! -f ".deps_installed" ]; then
    echo "📦 Installing rpi-image-gen dependencies..."
    sudo ./install_deps.sh
    touch .deps_installed
    echo "✅ Dependencies installed"
else
    echo "✅ Dependencies already installed"
fi

# Copy CUPCAKE configuration files
echo "📋 Copying CUPCAKE configuration files..."

# Copy main config file
cp "$CUPCAKE_CONFIG_DIR/cupcake-pi5-config.cfg" .
echo "✅ Copied cupcake-pi5-config.cfg"

# Copy collections
if [ -d "$CUPCAKE_CONFIG_DIR/collections" ]; then
    cp -r "$CUPCAKE_CONFIG_DIR/collections" .
    echo "✅ Copied collections directory"
fi

# Copy hooks
if [ -d "$CUPCAKE_CONFIG_DIR/hooks" ]; then
    cp -r "$CUPCAKE_CONFIG_DIR/hooks" .
    echo "✅ Copied hooks directory"
fi

# Copy scripts
if [ -d "$CUPCAKE_CONFIG_DIR/scripts" ]; then
    cp -r "$CUPCAKE_CONFIG_DIR/scripts" .
    echo "✅ Copied scripts directory"
fi

# Copy overlays if they exist
if [ -d "$CUPCAKE_CONFIG_DIR/overlays" ]; then
    cp -r "$CUPCAKE_CONFIG_DIR/overlays" .
    echo "✅ Copied overlays directory"
fi

# Make scripts executable
find hooks/ -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
find scripts/ -name "*.py" -exec chmod +x {} \; 2>/dev/null || true

echo "=== Setup completed successfully ==="
echo "📂 Location: $(pwd)"
echo "🔧 Configuration: cupcake-pi5-config.cfg"
echo ""
echo "To build the CUPCAKE Pi 5 image:"
echo "  ./build.sh -c cupcake-pi5-config.cfg"
echo ""
echo "Or test the build:"
echo "  ./build.sh -c cupcake-pi5-config.cfg --dry-run"