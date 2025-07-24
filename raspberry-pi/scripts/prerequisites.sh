#!/bin/bash

# CUPCAKE Pi Build - Prerequisites Check
# Verifies system requirements and dependencies

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

check_prerequisites() {
    log "Checking build prerequisites..."
    
    # Check if Docker is available and running
    if ! command -v docker &> /dev/null; then
        error "Docker is required but not installed. Please install Docker first."
    fi
    
    if ! docker info &> /dev/null; then
        error "Docker is not running. Please start Docker daemon."
    fi
    
    info "✓ Docker is available and running"
    
    # Check available disk space (need at least 10GB free)
    local available_space_kb=$(df . | tail -1 | awk '{print $4}')
    local available_space_gb=$((available_space_kb / 1024 / 1024))
    
    if [ "$available_space_gb" -lt 10 ]; then
        error "Insufficient disk space. Need at least 10GB free, have ${available_space_gb}GB"
    fi
    
    info "✓ Sufficient disk space available (${available_space_gb}GB)"
    
    # Check if required tools are available
    local missing_tools=()
    
    for tool in git curl unzip; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        error "Missing required tools: ${missing_tools[*]}. Please install them first."
    fi
    
    info "✓ All required tools are available"
    
    # Check if we can run ARM emulation
    if ! docker run --rm --privileged multiarch/qemu-user-static --reset -p yes &> /dev/null; then
        warn "Failed to setup ARM emulation - may affect build process"
    else
        info "✓ ARM emulation setup successful"
    fi
    
    log "Prerequisites check completed successfully"
}