#!/bin/bash


set -e

FRONTEND_REPO="https://github.com/noatgnu/cupcake-ng.git"
BUILD_DIR="${BUILD_DIR:-./frontend-build}"
OUTPUT_DIR="${OUTPUT_DIR:-./frontend-dist}"
PI_HOSTNAME="${PI_HOSTNAME:-cupcake-pi.local}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' 
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

check_prerequisites() {
    log "Checking prerequisites..."
    
    if ! command -v git &> /dev/null; then
        error "Git is required but not installed"
    fi
    
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
    
    if ! command -v npm &> /dev/null; then
        error "npm is required but not installed"
    fi
    
    log "Prerequisites check completed"
}

install_nodejs() {
    log "Installing Node.js..."
    
    case "$PLATFORM" in
        x86_64)
            if command -v apt &> /dev/null; then
                curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
                sudo apt-get install -y nodejs
            elif command -v yum &> /dev/null; then
                curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
                sudo yum install -y nodejs npm
            elif command -v brew &> /dev/null; then
                brew install node
            else
                error "Cannot install Node.js automatically on this system"
            fi
            ;;
        arm64|armv7)
            if command -v apt &> /dev/null; then
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

prepare_frontend_source() {
    log "Preparing frontend source..."
    
    mkdir -p "$BUILD_DIR"
    
    info "Cloning CUPCAKE Angular frontend..."
    git clone "$FRONTEND_REPO" "$BUILD_DIR"
    
    cd "$BUILD_DIR"
    
    info "Configuring frontend for Pi deployment (hostname: $PI_HOSTNAME)..."
    
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

build_frontend() {
    log "Building Angular frontend..."
    
    cd "$BUILD_DIR"
    
    case "$PLATFORM" in
        x86_64)
            export NODE_OPTIONS="--max-old-space-size=4096"
            ;;
        arm64)
            export NODE_OPTIONS="--max-old-space-size=2048"
            ;;
        armv7)
            export NODE_OPTIONS="--max-old-space-size=1024"
            ;;
        *)
            export NODE_OPTIONS="--max-old-space-size=1024"
            ;;
    esac
    
    info "Using Node.js memory limit: $NODE_OPTIONS"
    
    info "Installing npm dependencies..."
    npm install --no-optional --production=false
    
        info "Building production frontend (this may take several minutes)..."
    
    if [ "$PLATFORM" = "x86_64" ]; then
        npm run build --prod --build-optimizer --aot
    else
        npm run build --prod
    fi
    
    cd ..
    
    log "Frontend build completed successfully"
}

package_frontend() {
    log "Packaging built frontend..."
    
    mkdir -p "$OUTPUT_DIR"
    
    local dist_dir=""
    if [ -d "$BUILD_DIR/dist/browser" ]; then
        dist_dir="$BUILD_DIR/dist/browser"
    elif [ -d "$BUILD_DIR/dist" ]; then
        dist_dir="$BUILD_DIR/dist"
    else
        error "Cannot find built frontend files in $BUILD_DIR/dist"
    fi
    
    info "Copying built files from $dist_dir to $OUTPUT_DIR..."
    cp -r "$dist_dir"/* "$OUTPUT_DIR/"
    
    cat > "$OUTPUT_DIR/.build-info" << EOF
BUILD_DATE=$(date -Iseconds)
BUILD_PLATFORM=$PLATFORM
BUILD_HOST=$(hostname)
NODE_VERSION=$(node --version)
NPM_VERSION=$(npm --version)
PI_HOSTNAME=$PI_HOSTNAME
BUILD_DIR=$BUILD_DIR
OUTPUT_DIR=$OUTPUT_DIR
EOF
    
    local size_kb=$(du -sk "$OUTPUT_DIR" | cut -f1)
    local size_mb=$((size_kb / 1024))
    
    log "Frontend packaged successfully"
    info "Output size: ${size_mb}MB (${size_kb}KB)"
    info "Output location: $OUTPUT_DIR"
    
    info "Key files created:"
    ls -la "$OUTPUT_DIR" | head -10
    if [ $(ls -1 "$OUTPUT_DIR" | wc -l) -gt 10 ]; then
        info "... and $(( $(ls -1 "$OUTPUT_DIR" | wc -l) - 10 )) more files"
    fi
}

cleanup_build() {
    if [ "$KEEP_BUILD_DIR" != "1" ]; then
        log "Cleaning up build directory..."
        rm -rf "$BUILD_DIR"
    else
        info "Keeping build directory: $BUILD_DIR"
    fi
}

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
    $0
    
    $0 --output-dir /tmp/cupcake-frontend
    
    $0 --hostname my-cupcake-pi.local
    
    $0 --keep-build

This script can be used standalone or called from other build scripts.
It automatically detects the platform and optimizes the build accordingly.
EOF
}

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

main() {
    log "Starting CUPCAKE frontend pre-build process..."
    
    parse_arguments "$@"
    
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
    
    echo
    info "To use with the Pi image build script:"
    echo "  export USE_PREBUILT_FRONTEND=1"
    echo "  export PREBUILT_FRONTEND_DIR=\"$OUTPUT_DIR\""
    echo "  ./build-pi-image.sh pi5"
}

main "$@"
