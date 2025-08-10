#!/bin/bash







set -e


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"


source "$SCRIPTS_DIR/logging.sh"
source "$SCRIPTS_DIR/pi_specs.sh"
source "$SCRIPTS_DIR/prerequisites.sh"
source "$SCRIPTS_DIR/pi_gen_setup.sh"
source "$SCRIPTS_DIR/frontend_setup.sh"
source "$SCRIPTS_DIR/ssl_setup.sh"
source "$SCRIPTS_DIR/stage_creator.sh"


DEFAULT_USER="${DEFAULT_USER:-cupcake}"
DEFAULT_PASSWORD="${DEFAULT_PASSWORD:-cupcake123}"
IMAGE_VERSION="${2:-latest}"
ENABLE_SSH="${3:-1}"
WIFI_SSID="${4:-}"
WIFI_PASSWORD="${5:-}"


export PI_MODEL="$1"
export IMAGE_VERSION
export ENABLE_SSH
export WIFI_SSID
export WIFI_PASSWORD
export DEFAULT_USER
export DEFAULT_PASSWORD


if [ $
    error "Usage: $0 <pi_model> [image_version] [enable_ssh] [wifi_ssid] [wifi_password]"
fi

if [ "$PI_MODEL" != "pi4" ] && [ "$PI_MODEL" != "pi5" ]; then
    error "Supported Pi models: pi4, pi5. Got: $PI_MODEL"
fi


case "$PI_MODEL" in
    pi4)
        HOSTNAME="cupcake-pi4"
        ;;
    pi5)
        HOSTNAME="cupcake-pi5"
        ;;
esac

export HOSTNAME

main() {
    log "Starting CUPCAKE Pi image build for $PI_MODEL..."
    log "Image version: $IMAGE_VERSION"
    log "SSH enabled: $ENABLE_SSH"
    
    
    detect_build_dir
    detect_target_pi_specs
    check_prerequisites
    
    
    setup_pi_gen
    prepare_build
    configure_pi_gen
    
    
    create_custom_stage
    
    
    run_pi_gen_build
    
    
    post_build_processing
    
    log "CUPCAKE Pi image build completed successfully!"
    info "Image location: $PI_GEN_DIR/deploy/"
    info "Look for: cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz"
}

run_pi_gen_build() {
    log "Starting pi-gen Docker build process..."
    
    cd "$PI_GEN_DIR"
    
    
    export DOCKER_BUILDKIT=1
    
    
    if [ -f "$CONFIG_DIR/raspberry-pi/build-docker-cupcake.sh" ]; then
        log "Using custom CUPCAKE Docker build method (Bookworm-based)..."
        timeout 7200 "$CONFIG_DIR/raspberry-pi/build-docker-cupcake.sh" 2>&1 | tee build-output.log
    elif [ -f "./build-docker.sh" ]; then
        log "Falling back to official Docker build method..."
        timeout 7200 ./build-docker.sh 2>&1 | tee build-output.log
    else
        error "Neither custom nor official build-docker.sh found"
    fi
    
    
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        error "Pi-gen build failed. Check build-output.log for details."
    fi
    
    log "Pi-gen build completed successfully"
}

post_build_processing() {
    log "Processing build results..."
    
    cd "$PI_GEN_DIR"
    
    
    local image_file
    if ls deploy/*cupcake-${PI_MODEL}*.img 1> /dev/null 2>&1; then
        image_file=$(ls deploy/*cupcake-${PI_MODEL}*.img | head -1)
        log "Found built image: $(basename "$image_file")"
    else
        error "No image file found in deploy directory"
    fi
    
    
    log "Compressing image with xz..."
    if [ ! -f "${image_file}.xz" ]; then
        xz -9 -T 0 "$image_file"
        log "Image compressed successfully"
    else
        log "Image already compressed"
    fi
    
    
    log "Generating checksums..."
    cd deploy
    for file in *.xz; do
        if [ -f "$file" ]; then
            sha256sum "$file" > "${file}.sha256"
            log "Checksum generated for $file"
        fi
    done
    
    
    display_build_summary
}

display_build_summary() {
    log "Build Summary:"
    echo "========================================"
    echo "Pi Model: $PI_MODEL"
    echo "Image Version: $IMAGE_VERSION"
    echo "Hostname: $HOSTNAME.local"
    echo "SSH Enabled: $ENABLE_SSH"
    echo "Default User: $DEFAULT_USER"
    echo "Build Directory: $PI_GEN_DIR"
    echo "========================================"
    
    
    if [ -d "$PI_GEN_DIR/deploy" ]; then
        echo "Built Files:"
        ls -lh "$PI_GEN_DIR/deploy/"*.{img,xz,sha256} 2>/dev/null || echo "No files found"
    fi
    
    echo "========================================"
    info "CUPCAKE Pi image ready for deployment!"
    info "Flash with Raspberry Pi Imager and configure via advanced options"
    info "Default credentials: $DEFAULT_USER / $DEFAULT_PASSWORD"
    info "Web interface: http://$HOSTNAME.local"
    info "Admin panel: http://$HOSTNAME.local/admin"
    echo "========================================"
}


cleanup() {
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        error "Build failed with exit code $exit_code"
        
        
        if [ -f "$PI_GEN_DIR/build-output.log" ]; then
            echo "Recent log entries:"
            tail -20 "$PI_GEN_DIR/build-output.log" || true
        fi
    fi
    
    
    log "Cleaning up temporary files..."
    
    exit $exit_code
}


trap cleanup EXIT


main "$@"