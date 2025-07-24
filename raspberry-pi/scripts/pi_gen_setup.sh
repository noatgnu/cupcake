#!/bin/bash

# CUPCAKE Pi Build - Pi-gen Setup and Configuration
# Handles pi-gen repository setup and configuration

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

# Build directory detection
detect_build_dir() {
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    
    # Try different possible locations
    if [ -d "$script_dir" ]; then
        BUILD_BASE_DIR="$script_dir"
    elif [ -d "/home/runner/build" ]; then
        BUILD_BASE_DIR="/home/runner/build"
    elif [ -d "$HOME/build" ]; then
        BUILD_BASE_DIR="$HOME/build"
    else
        BUILD_BASE_DIR="$(pwd)/build"
    fi
    
    PI_GEN_DIR="$BUILD_BASE_DIR/pi-gen"
    CONFIG_DIR="$(dirname "$script_dir")"
    
    info "Build directory: $BUILD_BASE_DIR"
    info "Pi-gen directory: $PI_GEN_DIR"
    info "Config directory: $CONFIG_DIR"
    
    # Export for use in other scripts
    export BUILD_BASE_DIR PI_GEN_DIR CONFIG_DIR
}

setup_pi_gen() {
    log "Setting up pi-gen repository..."
    
    # Create build directory
    mkdir -p "$BUILD_BASE_DIR"
    cd "$BUILD_BASE_DIR"
    
    # Clone or update pi-gen
    if [ ! -d "$PI_GEN_DIR" ]; then
        log "Cloning pi-gen repository..."
        git clone https://github.com/RPi-Distro/pi-gen.git
    else
        log "Updating existing pi-gen repository..."
        cd "$PI_GEN_DIR"
        git fetch origin
        git reset --hard origin/master
        cd "$BUILD_BASE_DIR"
    fi
    
    log "Pi-gen repository ready"
}

prepare_build() {
    log "Preparing build environment..."
    
    # Ensure pi-gen directory exists
    if [ ! -d "$PI_GEN_DIR" ]; then
        error "Pi-gen directory not found: $PI_GEN_DIR"
    fi
    
    cd "$PI_GEN_DIR"
    
    # Clean any previous builds
    log "Cleaning previous build artifacts..."
    sudo docker system prune -f 2>/dev/null || true
    rm -rf work/ deploy/ || true
    
    log "Build environment prepared"
}

configure_pi_gen() {
    log "Configuring pi-gen build parameters..."
    
    cd "$PI_GEN_DIR"
    
    # Create pi-gen config file
    cat > config <<EOF
IMG_NAME=cupcake-${PI_MODEL}-${IMAGE_VERSION}
RELEASE=bookworm
DEPLOY_COMPRESSION=xz
LOCALE_DEFAULT=en_US.UTF-8
TARGET_HOSTNAME=${HOSTNAME:-cupcake-pi}
KEYBOARD_KEYMAP=us
KEYBOARD_LAYOUT="English (US)"
TIMEZONE_DEFAULT=UTC
FIRST_USER_NAME=${DEFAULT_USER:-cupcake}
FIRST_USER_PASS=${DEFAULT_PASSWORD:-cupcake123}
WPA_ESSID="${WIFI_SSID:-}"
WPA_PASSWORD="${WIFI_PASSWORD:-}"
WPA_COUNTRY=US
ENABLE_SSH=${ENABLE_SSH:-1}
PUBKEY_SSH_FIRST_USER=""
PUBKEY_ONLY_SSH=0

# Build optimizations
WORK_DIR=$PI_GEN_DIR/work
DEPLOY_DIR=$PI_GEN_DIR/deploy
LOG_FILE=$PI_GEN_DIR/build.log

# Stage configuration
SKIP_IMAGES="4,5"
STAGE_LIST="stage0,stage1,stage2,stage-cupcake"

# Docker build settings
USE_DOCKER=1
PRESERVE_CONTAINER=0
CONTAINER_NAME=cupcake_pi_build
DOCKER_BASE_IMAGE=debian:bookworm

# Performance settings
PARALLEL_JOBS=\$(nproc)
EOF
    
    # Set executable permissions on scripts
    chmod +x build-docker.sh || chmod +x build.sh
    
    log "Pi-gen configuration completed"
}