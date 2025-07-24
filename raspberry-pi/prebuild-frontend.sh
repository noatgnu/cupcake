#!/bin/bash

# CUPCAKE Frontend Pre-build Script
# Creates a pre-built Angular frontend that can be used in Pi image builds
# Works on both x86 and ARM64 platforms

set -e

# Configuration
FRONTEND_REPO="https://github.com/noatgnu/cupcake-ng.git"
BUILD_DIR="${BUILD_DIR:-./frontend-build}"
OUTPUT_DIR="${OUTPUT_DIR:-./frontend-dist}"
PI_HOSTNAME="${PI_HOSTNAME:-cupcake-pi.local}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# Detect platform
detect_platform() {
    local arch=$(uname -m)
    local os=$(uname -s)
    
    case "$arch" in
        x86_64)
            PLATFORM="x86_64"
            ;;
        aarch64|arm64)
            PLATFORM="arm64"
            ;;
        armv7l)
            PLATFORM="armv7"
            ;;
        *)
            PLATFORM="unknown"
            ;;
    esac
    
    info "Detected platform: $PLATFORM ($arch on $os)"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if git is available
    if ! command -v git &> /dev/null; then
        error "Git is required but not installed"
    fi
    
    # Check if we have Node.js or can install it
    if ! command -v node &> /dev/null; then
        warn "Node.js not found, will attempt to install"
        install_nodejs
    else
        local node_version=$(node --version | sed 's/v//')
        local major_version=$(echo $node_version | cut -d. -f1)
        
        if [ "$major_version" -lt 18 ]; then
            warn "Node.js version $node_version is too old (need 18+), will update"
            install_nodejs
        else
            info "Using Node.js version: $node_version"
        fi
    fi
    
    # Check if npm is available
    if ! command -v npm &> /dev/null; then
        error "npm is required but not installed"
    fi
    
    log "Prerequisites check completed"
}

# Install Node.js based on platform
install_nodejs() {
    log "Installing Node.js..."
    
    case "$PLATFORM" in
        x86_64)
            if command -v apt &> /dev/null; then
                # Debian/Ubuntu
                curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
                sudo apt-get install -y nodejs
            elif command -v yum &> /dev/null; then
                # RHEL/CentOS
                curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
                sudo yum install -y nodejs npm
            elif command -v brew &> /dev/null; then
                # macOS
                brew install node
            else
                error "Cannot install Node.js automatically on this system"
            fi
            ;;
        arm64|armv7)
            if command -v apt &> /dev/null; then
                # Raspberry Pi OS / Debian ARM
                curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
                sudo apt-get install -y nodejs
            else
                error "Cannot install Node.js automatically on ARM system without apt"
            fi
            ;;
        *)
            error "Unsupported platform for automatic Node.js installation"
            ;;
    esac
    
    info "Node.js installed successfully: $(node --version)"
}

# Clean up previous builds
cleanup_previous() {
    log "Cleaning up previous builds..."
    
    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
    
    if [ -d "$OUTPUT_DIR" ]; then
        rm -rf "$OUTPUT_DIR"
    fi
    
    log "Cleanup completed"
}

# Clone and prepare frontend source
prepare_frontend_source() {
    log "Preparing frontend source..."
    
    # Create build directory
    mkdir -p "$BUILD_DIR"
    
    # Clone the frontend repository
    info "Cloning CUPCAKE Angular frontend..."
    git clone "$FRONTEND_REPO" "$BUILD_DIR"
    
    cd "$BUILD_DIR"
    
    # Configure for Pi deployment
    info "Configuring frontend for Pi deployment (hostname: $PI_HOSTNAME)..."
    
    # Update environment files for Pi deployment
    if [ -f "src/environments/environment.ts" ]; then
        sed -i "s;https://cupcake.proteo.info;http://$PI_HOSTNAME;g" src/environments/environment.ts
        sed -i "s;http://localhost;http://$PI_HOSTNAME;g" src/environments/environment.ts
    fi
    
    if [ -f "src/environments/environment.prod.ts" ]; then
        sed -i "s;https://cupcake.proteo.info;http://$PI_HOSTNAME;g" src/environments/environment.prod.ts
        sed -i "s;http://localhost;http://$PI_HOSTNAME;g" src/environments/environment.prod.ts
    fi
    
    cd ..
    
    log "Frontend source prepared"
}

# Build the frontend
build_frontend() {
    log "Building Angular frontend..."
    
    cd "$BUILD_DIR"
    
    # Set Node.js memory options for different platforms
    case "$PLATFORM" in
        x86_64)
            # x86_64 can handle more memory
            export NODE_OPTIONS="--max-old-space-size=4096"
            ;;
        arm64)
            # ARM64 (Pi 5) can handle moderate memory
            export NODE_OPTIONS="--max-old-space-size=2048"
            ;;
        armv7)
            # ARMv7 (Pi 4) needs conservative memory settings
            export NODE_OPTIONS="--max-old-space-size=1024"
            ;;
        *)
            # Conservative default
            export NODE_OPTIONS="--max-old-space-size=1024"
            ;;
    esac
    
    info "Using Node.js memory limit: $NODE_OPTIONS"
    
    # Install dependencies
    info "Installing npm dependencies..."
    npm install --no-optional --production=false
    
    # Build the frontend
    info "Building production frontend (this may take several minutes)..."
    
    # Use different build strategies based on platform performance
    if [ "$PLATFORM" = "x86_64" ]; then
        # Fast x86 build with optimizations
        npm run build --prod --build-optimizer --aot
    else
        # ARM build with conservative settings
        npm run build --prod
    fi
    
    cd ..
    
    log "Frontend build completed successfully"
}

# Package the built frontend
package_frontend() {
    log "Packaging built frontend..."
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Check for built files
    local dist_dir=""
    if [ -d "$BUILD_DIR/dist/browser" ]; then
        dist_dir="$BUILD_DIR/dist/browser"
    elif [ -d "$BUILD_DIR/dist" ]; then
        dist_dir="$BUILD_DIR/dist"
    else
        error "Cannot find built frontend files in $BUILD_DIR/dist"
    fi
    
    # Copy built files
    info "Copying built files from $dist_dir to $OUTPUT_DIR..."
    cp -r "$dist_dir"/* "$OUTPUT_DIR/"
    
    # Create build info file
    cat > "$OUTPUT_DIR/.build-info" << EOF
# CUPCAKE Frontend Build Info
BUILD_DATE=$(date -Iseconds)
BUILD_PLATFORM=$PLATFORM
BUILD_HOST=$(hostname)
NODE_VERSION=$(node --version)
NPM_VERSION=$(npm --version)
PI_HOSTNAME=$PI_HOSTNAME
BUILD_DIR=$BUILD_DIR
OUTPUT_DIR=$OUTPUT_DIR
EOF
    
    # Calculate size
    local size_kb=$(du -sk "$OUTPUT_DIR" | cut -f1)
    local size_mb=$((size_kb / 1024))
    
    log "Frontend packaged successfully"
    info "Output size: ${size_mb}MB (${size_kb}KB)"
    info "Output location: $OUTPUT_DIR"
    
    # List key files
    info "Key files created:"
    ls -la "$OUTPUT_DIR" | head -10
    if [ $(ls -1 "$OUTPUT_DIR" | wc -l) -gt 10 ]; then
        info "... and $(( $(ls -1 "$OUTPUT_DIR" | wc -l) - 10 )) more files"
    fi
}

# Clean up build directory
cleanup_build() {
    if [ "$KEEP_BUILD_DIR" != "1" ]; then
        log "Cleaning up build directory..."
        rm -rf "$BUILD_DIR"
    else
        info "Keeping build directory: $BUILD_DIR"
    fi
}

# Show usage information
show_usage() {
    cat << EOF
CUPCAKE Frontend Pre-build Script

Usage: $0 [OPTIONS]

OPTIONS:
    -h, --help              Show this help message
    -o, --output-dir DIR    Output directory for built frontend (default: ./frontend-dist)
    -b, --build-dir DIR     Build directory (default: ./frontend-build)
    -H, --hostname HOST     Pi hostname for frontend config (default: cupcake-pi.local)
    -k, --keep-build        Keep build directory after completion
    -v, --verbose           Enable verbose output

ENVIRONMENT VARIABLES:
    BUILD_DIR               Build directory path
    OUTPUT_DIR              Output directory path  
    PI_HOSTNAME             Pi hostname for frontend configuration
    KEEP_BUILD_DIR          Set to "1" to keep build directory

EXAMPLES:
    # Basic build
    $0
    
    # Custom output directory
    $0 --output-dir /tmp/cupcake-frontend
    
    # Custom Pi hostname  
    $0 --hostname my-cupcake-pi.local
    
    # Keep build files for debugging
    $0 --keep-build

This script can be used standalone or called from other build scripts.
It automatically detects the platform and optimizes the build accordingly.
EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -o|--output-dir)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            -b|--build-dir)
                BUILD_DIR="$2"
                shift 2
                ;;
            -H|--hostname)
                PI_HOSTNAME="$2"
                shift 2
                ;;
            -k|--keep-build)
                KEEP_BUILD_DIR="1"
                shift
                ;;
            -v|--verbose)
                set -x
                shift
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done
}

# Main execution
main() {
    log "Starting CUPCAKE frontend pre-build process..."
    
    # Parse arguments
    parse_arguments "$@"
    
    # Main build steps
    detect_platform
    check_prerequisites
    cleanup_previous
    prepare_frontend_source
    build_frontend
    package_frontend
    cleanup_build
    
    log "Frontend pre-build completed successfully!"
    info "Built frontend available in: $OUTPUT_DIR"
    info "You can now use this in your Pi image build process"
    
    # Show how to use with main build script
    echo
    info "To use with the Pi image build script:"
    echo "  export USE_PREBUILT_FRONTEND=1"
    echo "  export PREBUILT_FRONTEND_DIR=\"$OUTPUT_DIR\""
    echo "  ./build-pi-image.sh pi5"
}

# Run main function with all arguments
main "$@"
