#!/bin/bash

# Docker-based CUPCAKE Pi 5 Image Builder Host Script
# Builds CUPCAKE image using Docker for maximum portability

set -e

echo "=== Docker CUPCAKE Pi 5 Image Builder ==="

# Configuration
DOCKER_IMAGE="cupcake-pi5-builder"
BUILD_CONTAINER="cupcake-build-$(date +%s)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[HOST]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# Check dependencies
check_docker() {
    log "Checking Docker availability..."
    
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
    fi
    
    if ! docker info &> /dev/null; then
        error "Docker daemon is not running or not accessible. Try: sudo systemctl start docker"
    fi
    
    # Check if user can run docker without sudo
    if ! docker ps &> /dev/null; then
        warn "Docker requires sudo. You may need to add your user to docker group:"
        warn "sudo usermod -aG docker \$USER && newgrp docker"
    fi
    
    log "Docker is available and working"
}

# Create necessary directories
setup_directories() {
    log "Setting up build directories..."
    
    mkdir -p "$OUTPUT_DIR"
    mkdir -p "$SCRIPT_DIR/build-scripts"
    mkdir -p "$SCRIPT_DIR/config"
    
    # Copy system detection script if it exists
    if [ -f "$SCRIPT_DIR/../rpi-image-gen/scripts/detect-system-capabilities.py" ]; then
        cp "$SCRIPT_DIR/../rpi-image-gen/scripts/detect-system-capabilities.py" "$SCRIPT_DIR/config/"
        log "Copied system detection script"
    fi
    
    info "Output directory: $OUTPUT_DIR"
}

# Build the Docker image
build_docker_image() {
    log "Building Docker image for CUPCAKE Pi 5 builder..."
    
    cd "$SCRIPT_DIR"
    
    # Build the builder image
    docker build -f Dockerfile.cupcake-builder -t "$DOCKER_IMAGE" .
    
    log "Docker builder image created: $DOCKER_IMAGE"
}

# Run the build in container
run_build() {
    log "Starting CUPCAKE Pi 5 image build in Docker container..."
    
    local docker_args=(
        "--name" "$BUILD_CONTAINER"
        "--rm"
        "--privileged"
        "--cap-add=SYS_ADMIN"
        "--cap-add=MKNOD"
        "--device=/dev/loop-control:/dev/loop-control"
        "-v" "$OUTPUT_DIR:/build/output"
        "-v" "/dev:/dev"
        "--tmpfs" "/tmp:exec,size=4G"
    )
    
    # Add loop devices if they exist
    for i in {0..7}; do
        if [ -e "/dev/loop$i" ]; then
            docker_args+=("--device=/dev/loop$i:/dev/loop$i")
        fi
    done
    
    info "Starting Docker container: $BUILD_CONTAINER"
    info "This may take 30-90 minutes depending on system performance..."
    info "Container will download ~2GB base image and build complete CUPCAKE stack"
    
    # Run the build
    docker run "${docker_args[@]}" "$DOCKER_IMAGE"
    
    log "Docker build completed"
}

# Test the build
test_build() {
    log "Testing Docker build environment..."
    
    # Quick test run to verify container works
    docker run --rm --privileged "$DOCKER_IMAGE" /bin/bash -c "
        echo '=== Docker Build Environment Test ==='
        echo 'OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d\"\\\"\" -f2)'
        echo 'Architecture: $(uname -m)'
        echo 'RAM: $(free -h | awk \"NR==2{print \\$2}\")'
        echo 'Disk: $(df -h /build | awk \"NR==2{print \\$4}\")'
        echo 'ARM64 emulation: $([ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && echo \"Available\" || echo \"Not configured\")'
        echo 'Required tools:'
        for tool in wget curl git debootstrap parted losetup qemu-aarch64-static; do
            if command -v \$tool >/dev/null 2>&1; then
                echo \"  ✓ \$tool\"
            else
                echo \"  ✗ \$tool (missing)\"
            fi
        done
        echo '=== Test completed ==='
    "
}

# Clean up
cleanup() {
    log "Cleaning up Docker resources..."
    
    # Remove stopped containers
    if docker ps -a --format "{{.Names}}" | grep -q "cupcake-build"; then
        docker rm $(docker ps -a --format "{{.Names}}" | grep "cupcake-build") 2>/dev/null || true
    fi
    
    # Optional: Remove builder image (uncomment to save space)
    # docker rmi "$DOCKER_IMAGE" 2>/dev/null || true
    
    log "Cleanup completed"
}

# Show usage
usage() {
    echo "Docker CUPCAKE Pi 5 Image Builder"
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  build     - Build CUPCAKE Pi 5 image (default)"
    echo "  test      - Test Docker build environment"
    echo "  clean     - Clean up Docker resources"
    echo "  rebuild   - Rebuild Docker image and build CUPCAKE image"
    echo ""
    echo "Examples:"
    echo "  $0                # Build CUPCAKE image"
    echo "  $0 test          # Test environment"
    echo "  $0 rebuild       # Force rebuild of Docker image"
}

# Main function
main() {
    local command=${1:-build}
    
    case "$command" in
        "build")
            log "Building CUPCAKE Pi 5 image using Docker..."
            check_docker
            setup_directories
            
            # Build Docker image if it doesn't exist
            if ! docker image inspect "$DOCKER_IMAGE" &> /dev/null; then
                build_docker_image
            else
                log "Docker builder image already exists"
            fi
            
            run_build
            
            echo ""
            echo "=== Build Summary ==="
            if [ -d "$OUTPUT_DIR" ] && [ "$(ls -A "$OUTPUT_DIR" 2>/dev/null)" ]; then
                echo "✅ Build completed successfully"
                echo "📁 Output files:"
                ls -lh "$OUTPUT_DIR"/ | grep -E "\\.img$" || echo "No .img files found"
                echo ""
                echo "To flash to SD card:"
                echo "  sudo dd if=$OUTPUT_DIR/cupcake-pi5-docker-*.img of=/dev/sdX bs=4M status=progress"
                echo "  or use Raspberry Pi Imager with 'Use Custom'"
            else
                echo "❌ Build may have failed - no output files found"
                exit 1
            fi
            ;;
            
        "test")
            log "Testing Docker build environment..."
            check_docker
            setup_directories
            
            if ! docker image inspect "$DOCKER_IMAGE" &> /dev/null; then
                build_docker_image
            fi
            
            test_build
            ;;
            
        "clean")
            cleanup
            ;;
            
        "rebuild")
            log "Rebuilding Docker image and building CUPCAKE image..."
            check_docker
            setup_directories
            
            # Force rebuild of Docker image
            docker rmi "$DOCKER_IMAGE" 2>/dev/null || true
            build_docker_image
            run_build
            ;;
            
        *)
            usage
            exit 1
            ;;
    esac
}

# Handle interrupts
trap cleanup INT TERM

# Run main function
main "$@"