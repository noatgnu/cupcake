#!/bin/bash

# Install dependencies for traditional CUPCAKE Pi 5 image building

set -e

echo "=== Installing CUPCAKE Traditional Build Dependencies ==="

# Check if running on a supported system
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "Warning: This script is designed for Linux systems"
    echo "For other systems, use Docker or a Linux VM"
fi

# Update package lists
echo "Updating package lists..."
sudo apt-get update

# Install required packages
echo "Installing build dependencies..."
sudo apt-get install -y \
    qemu-user-static \
    binfmt-support \
    debootstrap \
    parted \
    kpartx \
    dosfstools \
    rsync \
    wget \
    curl \
    git \
    pv \
    xz-utils

# Enable ARM64 emulation
echo "Configuring ARM64 emulation..."
sudo systemctl enable qemu-binfmt-static
sudo systemctl start qemu-binfmt-static

# Test emulation
if [ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    echo "✅ ARM64 emulation configured successfully"
else
    echo "⚠️  ARM64 emulation may need manual configuration"
    echo "Run: sudo systemctl restart qemu-binfmt-static"
fi

echo ""
echo "=== Installation Complete ==="
echo "You can now run: sudo ./build-cupcake-image.sh"
echo ""
echo "Or test the setup with: ./test-build-approach.sh"