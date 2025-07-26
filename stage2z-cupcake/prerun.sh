#!/bin/bash

# Pi-gen prerun script for CUPCAKE stage
# This script runs before the stage execution

# Set strict error handling inside the script
set -e

# Use copy_previous instead of validating ROOTFS_DIR
copy_previous

log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

log_cupcake "CUPCAKE stage prerun completed"