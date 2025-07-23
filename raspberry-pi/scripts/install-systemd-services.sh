#!/bin/bash
set -e

echo "=== Installing CUPCAKE systemd services ==="

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
CONFIG_DIR="$SCRIPT_DIR/../config"

# Copy systemd service files
echo "Installing systemd service files..."
cp "$CONFIG_DIR/systemd/"*.service /etc/systemd/system/

# Enable all CUPCAKE services
echo "Enabling CUPCAKE services..."
systemctl enable cupcake-setup.service
systemctl enable cupcake-web.service
systemctl enable cupcake-transcribe.service
systemctl enable cupcake-export.service
systemctl enable cupcake-import.service
systemctl enable cupcake-maintenance.service
systemctl enable cupcake-ocr.service

echo "=== Systemd services installed and enabled ==="
