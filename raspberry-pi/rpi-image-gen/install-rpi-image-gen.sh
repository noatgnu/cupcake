#!/bin/bash

# Install rpi-image-gen (Raspberry Pi Foundation's official image generation tool)
# This script downloads and installs rpi-image-gen for building custom Pi images

set -e

echo "=== Installing rpi-image-gen ==="

# Check if running on a supported system
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "Warning: rpi-image-gen is designed for Linux systems"
    echo "You may want to use Docker or a Linux VM"
fi

# Create temporary directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "Downloading rpi-image-gen from GitHub..."
git clone https://github.com/raspberrypi/rpi-image-gen.git
cd rpi-image-gen

echo "Installing system dependencies..."
# Update package list
sudo apt-get update

# Install required packages for rpi-image-gen
sudo apt-get install -y \
    git \
    build-essential \
    debootstrap \
    qemu-user-static \
    binfmt-support \
    parted \
    kpartx \
    python3 \
    python3-pip \
    python3-yaml \
    dosfstools \
    zip \
    unzip

# Install Python dependencies
pip3 install --user pyyaml

echo "Building rpi-image-gen..."
# Make the script executable
chmod +x rpi-image-gen

# Test installation
echo "Testing rpi-image-gen installation..."
if ./rpi-image-gen --help > /dev/null 2>&1; then
    echo "✅ rpi-image-gen installed successfully"
else
    echo "❌ rpi-image-gen installation test failed"
    exit 1
fi

# Install to system PATH
echo "Installing rpi-image-gen to /usr/local/bin..."
sudo cp rpi-image-gen /usr/local/bin/
sudo chmod +x /usr/local/bin/rpi-image-gen

# Clean up
cd /
rm -rf "$TEMP_DIR"

echo "=== Installation completed ==="
echo "rpi-image-gen is now available in your PATH"
echo "You can now run: rpi-image-gen --help"
echo ""
echo "To build the CUPCAKE Pi 5 image:"
echo "cd $(dirname "$0")"
echo "./build-image.sh"