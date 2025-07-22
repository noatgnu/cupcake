#!/bin/bash
# CUPCAKE Image Builder for rpi-image-gen
# Builds custom Raspberry Pi OS image with CUPCAKE pre-installed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RPI_IMAGE_GEN_DIR="$HOME/rpi-image-gen"
CUPCAKE_CONFIG_DIR="$SCRIPT_DIR"

echo "CUPCAKE Raspberry Pi 5 Image Builder"
echo "==================================="

# Check if rpi-image-gen is available
if [ ! -d "$RPI_IMAGE_GEN_DIR" ]; then
    echo "rpi-image-gen not found. Cloning from GitHub..."
    cd "$HOME"
    git clone https://github.com/raspberrypi/rpi-image-gen.git
    cd rpi-image-gen
    
    echo "Installing dependencies..."
    sudo ./install_deps.sh
else
    echo "Using existing rpi-image-gen at $RPI_IMAGE_GEN_DIR"
    cd "$RPI_IMAGE_GEN_DIR"
fi

# Copy CUPCAKE configuration files
echo "Copying CUPCAKE configuration..."
cp -r "$CUPCAKE_CONFIG_DIR"/* ./

# Make hooks executable
chmod +x hooks/*.sh
chmod +x overlays/cupcake/opt/cupcake/scripts/*.sh

# Check if running on supported architecture
if [ "$(uname -m)" != "aarch64" ]; then
    echo "WARNING: Building on non-ARM64 architecture may be slow"
    echo "For best performance, build on a Raspberry Pi with 64-bit OS"
fi

# Build the image
echo "Building CUPCAKE image (this may take 30-60 minutes)..."
echo "Progress will be shown below:"
echo

./build.sh -c cupcake-pi5-config.ini

# Check if build was successful
if [ -f "work/cupcake-pi5/artefacts/cupcake-pi5.img" ]; then
    echo
    echo "✓ CUPCAKE image built successfully!"
    echo
    echo "Image location: $RPI_IMAGE_GEN_DIR/work/cupcake-pi5/artefacts/cupcake-pi5.img"
    echo "Image size: $(du -h work/cupcake-pi5/artefacts/cupcake-pi5.img | cut -f1)"
    echo
    echo "Next steps:"
    echo "1. Flash the image to an SD card or NVMe SSD using Raspberry Pi Imager"
    echo "2. Boot your Pi 5 with the image"
    echo "3. Connect via SSH using: ssh cupcake@<pi-ip-address>"
    echo "4. Run deployment script: sudo /opt/cupcake/scripts/deploy-cupcake.sh"
    echo "5. Set up SSL: sudo /opt/cupcake/scripts/setup-ssl.sh your-domain.com"
    echo
    echo "Default login:"
    echo "  Username: cupcake"
    echo "  Password: changeme123"
    echo "  (Change this immediately after first boot!)"
    echo
    echo "Hardware recommendations:"
    echo "  - Raspberry Pi 5 8GB"
    echo "  - NVMe SSD via M.2 HAT for production"
    echo "  - Active cooling for continuous operation"
    echo "  - Quality power supply (27W+ recommended)"
else
    echo
    echo "✗ Image build failed!"
    echo "Check the build output above for errors."
    exit 1
fi