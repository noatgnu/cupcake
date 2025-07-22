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
rpi-image-gen \
    -c "$CONFIG_FILE" \
    -D "$SCRIPT_DIR" \
    -o "$OUTPUT_DIR" \
    --verbose

echo "=== Build completed ==="
echo "Image files should be in: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR" || echo "No output files found"