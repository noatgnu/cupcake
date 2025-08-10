#!/bin/bash


set -e

copy_previous

log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

log_cupcake "CUPCAKE stage prerun completed"