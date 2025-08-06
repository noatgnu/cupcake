#!/bin/bash
set -e

# CUPCAKE Service Enabler Script
# This script runs on every boot to ensure all CUPCAKE services are running

echo "[$(date)] Ensuring CUPCAKE services are running..."

# Enable all CUPCAKE services (idempotent)
systemctl enable postgresql redis-server nginx cupcake-web cupcake-worker 2>/dev/null || true

# Start essential services with timeout and error checking
echo "[$(date)] Starting PostgreSQL..."
timeout 30 systemctl start postgresql || {
    echo "[$(date)] ERROR: PostgreSQL failed to start"
    systemctl status postgresql --no-pager || true
    exit 1
}

echo "[$(date)] Starting Redis..."
timeout 30 systemctl start redis-server || {
    echo "[$(date)] ERROR: Redis failed to start"
    systemctl status redis-server --no-pager || true
    exit 1
}

# Create cupcake-ready flag before testing nginx (required for nginx config)
echo "[$(date)] Creating temporary ready flag for nginx startup..."
touch /tmp/cupcake-ready

# Test nginx configuration before starting
echo "[$(date)] Testing nginx configuration..."
nginx -t || {
    echo "[$(date)] ERROR: Nginx configuration test failed"
    nginx -T 2>&1 | tail -20 || true
    rm -f /tmp/cupcake-ready
    exit 1
}

# Start nginx with timeout
echo "[$(date)] Starting nginx..."
timeout 30 systemctl start nginx || {
    echo "[$(date)] ERROR: Nginx failed to start"
    systemctl status nginx --no-pager || true
    journalctl -u nginx --no-pager -n 20 || true
    rm -f /tmp/cupcake-ready
    exit 1
}

# Start CUPCAKE services with timeout
echo "[$(date)] Starting CUPCAKE web service..."
timeout 30 systemctl start cupcake-web || {
    echo "[$(date)] ERROR: CUPCAKE web service failed to start"
    systemctl status cupcake-web --no-pager || true
    journalctl -u cupcake-web --no-pager -n 10 || true
    exit 1
}

echo "[$(date)] Starting CUPCAKE worker service..."
timeout 30 systemctl start cupcake-worker || {
    echo "[$(date)] ERROR: CUPCAKE worker service failed to start"
    systemctl status cupcake-worker --no-pager || true
    journalctl -u cupcake-worker --no-pager -n 10 || true
    exit 1
}

# Verify all services are actually running
echo "[$(date)] Verifying services are running..."
for service in postgresql redis-server nginx cupcake-web cupcake-worker; do
    if ! systemctl is-active --quiet "$service"; then
        echo "[$(date)] ERROR: Service $service is not running"
        systemctl status "$service" --no-pager || true
        exit 1
    else
        echo "[$(date)] ✓ $service is running"
    fi
done

# Create ready flag in /tmp (gets cleared on each boot)
touch /tmp/cupcake-ready

echo "[$(date)] CUPCAKE services are running and ready"
