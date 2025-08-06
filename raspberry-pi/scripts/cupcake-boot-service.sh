#!/bin/bash
set -e

# CUPCAKE Boot Service Script
# This script runs as a systemd service to verify services and create ready flag
# It assumes systemd dependencies already started the required services

echo "[$(date)] CUPCAKE Boot Service - Verifying services and creating ready flag..."

# Wait for services to be fully ready (with longer timeouts for boot conditions)
echo "[$(date)] Waiting for services to be ready..."

# Function to wait for a service to be active
wait_for_service() {
    local service=$1
    local max_wait=${2:-120}  # Default 2 minutes for boot conditions
    local count=0
    
    echo "[$(date)] Waiting for $service to be active..."
    while [ $count -lt $max_wait ]; do
        if systemctl is-active --quiet "$service" 2>/dev/null; then
            echo "[$(date)] ✓ $service is active"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    
    echo "[$(date)] ERROR: $service failed to become active within ${max_wait} seconds"
    systemctl status "$service" --no-pager || true
    return 1
}

# Wait for essential services (systemd should have started these via dependencies)
wait_for_service "postgresql" 180
wait_for_service "redis-server" 60

# Test nginx configuration and wait for it
echo "[$(date)] Testing nginx configuration..."
nginx -t || {
    echo "[$(date)] ERROR: Nginx configuration test failed"
    nginx -T 2>&1 | tail -20 || true
    exit 1
}

wait_for_service "nginx" 60

# Wait for CUPCAKE services
wait_for_service "cupcake-web" 120
wait_for_service "cupcake-worker" 60

# Final verification that all services are running
echo "[$(date)] Final verification of all services..."
for service in postgresql redis-server nginx cupcake-web cupcake-worker; do
    if ! systemctl is-active --quiet "$service"; then
        echo "[$(date)] ERROR: Service $service is not running"
        systemctl status "$service" --no-pager || true
        exit 1
    else
        echo "[$(date)] ✓ $service is running"
    fi
done

# Create ready flag
echo "[$(date)] Creating ready flag..."
touch /tmp/cupcake-ready

echo "[$(date)] CUPCAKE boot service completed successfully - all services verified and ready flag created"