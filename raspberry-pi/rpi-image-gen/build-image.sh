#!/bin/bash

# CUPCAKE Pi 5 Image Builder using rpi-image-gen
# This script builds a custom Raspberry Pi OS image with CUPCAKE pre-installed

set -e

echo "=== CUPCAKE Pi 5 Image Builder ==="

# Check if rpi-image-gen is available
if ! command -v rpi-image-gen &> /dev/null; then
    echo "rpi-image-gen not found. Please install it first:"
    echo "git clone https://github.com/raspberrypi/rpi-image-gen.git"
    echo "cd rpi-image-gen && sudo ./bootstrap && sudo ./build.sh"
    exit 1
fi

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/cupcake-pi5-config.cfg"

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE"
    exit 1
fi

# Create output directory
OUTPUT_DIR="${SCRIPT_DIR}/images"
mkdir -p "$OUTPUT_DIR"

echo "Building CUPCAKE Pi 5 image..."
echo "Config file: $CONFIG_FILE"
echo "Output directory: $OUTPUT_DIR"
echo "Script directory: $SCRIPT_DIR"

# Build the image with proper directory specification
# Note: rpi-image-gen expects to be run from within its own directory
# We need to copy our config files to the rpi-image-gen directory

# Check if we're in the rpi-image-gen directory
if [ ! -f "build.sh" ] || [ ! -f "rpi-image-gen" ]; then
    echo "Error: This script must be run from within the rpi-image-gen repository directory"
    echo "Please:"
    echo "1. Clone rpi-image-gen: git clone https://github.com/raspberrypi/rpi-image-gen.git"
    echo "2. Copy CUPCAKE files: cp -r /path/to/cupcake/raspberry-pi/rpi-image-gen/* rpi-image-gen/"
    echo "3. Run from rpi-image-gen directory: cd rpi-image-gen && ./build-cupcake-image.sh"
    exit 1
fi

# Build with the proper rpi-image-gen command structure
./build.sh -c "$(basename "$CONFIG_FILE")"

echo "=== Build completed ==="
echo "Image files should be in: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR" || echo "No output files found"