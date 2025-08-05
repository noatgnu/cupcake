#!/bin/bash
set -e

# CUPCAKE Service Enabler Script
# This script runs on every boot to ensure all CUPCAKE services are running

echo "[$(date)] Ensuring CUPCAKE services are running..."

# Enable all CUPCAKE services (idempotent)
systemctl enable postgresql redis-server nginx cupcake-web cupcake-worker 2>/dev/null || true

# Start essential services
systemctl start postgresql
systemctl start redis-server

# Start web services
systemctl start nginx
systemctl start cupcake-web
systemctl start cupcake-worker

# Create ready flag in /tmp (gets cleared on each boot)
touch /tmp/cupcake-ready

echo "[$(date)] CUPCAKE services are running and ready"
