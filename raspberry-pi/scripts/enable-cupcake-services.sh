#!/bin/bash
set -e

# CUPCAKE Service Enabler Script
# This script runs on first boot to enable all CUPCAKE services

# Flag to prevent running multiple times
FIRSTBOOT_FLAG="/opt/cupcake/services-enabled"
if [ -f "$FIRSTBOOT_FLAG" ]; then
    exit 0
fi

echo "[$(date)] Enabling CUPCAKE services on first boot..."

# Enable all CUPCAKE services
systemctl enable postgresql
systemctl enable redis-server
systemctl enable nginx
systemctl enable cupcake-web
systemctl enable cupcake-worker

# Start essential services
systemctl start postgresql
systemctl start redis-server

# Start web services
systemctl start nginx
systemctl start cupcake-web
systemctl start cupcake-worker

# Mark services as enabled (this creates the ready flag for nginx)
echo "Services enabled at: $(date)" > "$FIRSTBOOT_FLAG"

echo "[$(date)] CUPCAKE services enabled and started successfully"