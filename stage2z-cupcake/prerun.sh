#!/bin/bash -e

# Pi-gen prerun script for CUPCAKE stage
# This script runs before the stage execution

# Use copy_previous instead of validating ROOTFS_DIR
copy_previous

log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

log_cupcake "CUPCAKE stage prerun completed"