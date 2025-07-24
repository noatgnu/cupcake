#!/bin/bash

# CUPCAKE Pi Build - Pi Specifications
# Handles Pi model detection and configuration

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

detect_target_pi_specs() {
    info "Determining target Pi specifications for $PI_MODEL..."
    
    case "$PI_MODEL" in
        pi4)
            TARGET_RAM_MB=4096
            TARGET_CORES=4
            WHISPER_MODEL="base.en"
            WHISPER_THREADS=4
            IMAGE_SIZE="8G"
            ;;
        pi5)
            TARGET_RAM_MB=8192
            TARGET_CORES=4
            WHISPER_MODEL="small.en"
            WHISPER_THREADS=4
            IMAGE_SIZE="12G"
            ;;
        *)
            error "Unsupported Pi model: $PI_MODEL. Supported: pi4, pi5"
            ;;
    esac
    
    info "Target specs: $PI_MODEL with ${TARGET_RAM_MB}MB RAM, $TARGET_CORES cores"
    info "Whisper config: $WHISPER_MODEL model, $WHISPER_THREADS threads"
    info "Image size: $IMAGE_SIZE"
    
    # Export variables for use in other scripts
    export TARGET_RAM_MB TARGET_CORES WHISPER_MODEL WHISPER_THREADS IMAGE_SIZE
}