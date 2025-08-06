#!/bin/bash
# CUPCAKE Web Server Setup Hook
# Calls the main nginx setup script for consistency

set -e

echo ">>> CUPCAKE: Setting up web server..."

# Use the main nginx setup script for consistent configuration
if [ -f /opt/cupcake/scripts/setup-nginx.sh ]; then
    echo ">>> Using main nginx setup script..."
    cd /opt/cupcake/scripts
    chmod +x ./setup-nginx.sh
    ./setup-nginx.sh
    echo ">>> CUPCAKE: Web server setup completed via setup-nginx.sh"
else
    echo ">>> ERROR: Main nginx setup script not found at /opt/cupcake/scripts/setup-nginx.sh"
    echo ">>> Please ensure the cupcake scripts are properly installed"
    exit 1
fi

echo ">>> CUPCAKE: Web server setup completed successfully"