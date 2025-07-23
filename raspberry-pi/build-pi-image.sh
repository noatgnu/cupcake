#!/bin/bash

# CUPCAKE Raspberry Pi Image Builder
# Creates a custom Raspberry Pi OS image optimized for CUPCAKE deployment

set -e

# Parse command line arguments
PI_MODEL="${1:-pi5}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"

# Version and metadata
VERSION="1.0.0"
BUILD_DATE=$(date -Iseconds)

# Validate Pi model
if [[ "$PI_MODEL" != "pi4" && "$PI_MODEL" != "pi5" ]]; then
    echo "Error: PI_MODEL must be 'pi4' or 'pi5'"
    echo "Usage: $0 [pi4|pi5] [version] [enable_ssh]"
    echo "Example: $0 pi5 v1.0.0 1"
    exit 1
fi

# Auto-detect build directory with sufficient space (from native version)
detect_build_dir() {
    local required_gb=20
    local best_dir=""
    local max_space=0

    # Check potential directories in order of preference
    local dirs=("/build" "/opt/build" "/home/$USER/build" "/tmp/build")

    for dir in "${dirs[@]}"; do
        if [ -d "$(dirname "$dir")" ]; then
            local available_gb=$(df "$(dirname "$dir")" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}')
            if [ "$available_gb" -gt "$max_space" ]; then
                max_space=$available_gb
                best_dir=$dir
            fi
        fi
    done

    # Find the mount point with most free space if none above work
    if [ "$max_space" -lt "$required_gb" ]; then
        best_dir=$(df -h | grep -E '^/dev' | awk '{print $6 " " int($4)}' | sort -k2 -nr | head -1 | cut -d' ' -f1)/cupcake-build
        max_space=$(df "$best_dir" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}' || echo 0)
    fi

    if [ "$max_space" -lt "$required_gb" ]; then
        error "Need at least ${required_gb}GB free space. Found ${max_space}GB at $best_dir"
        error "Free up space or add external storage"
    fi

    echo "$best_dir"
}


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

# Detect target Pi specifications for optimization (from native version)
detect_target_pi_specs() {
    log "Determining target Pi specifications for $PI_MODEL..."

    # Set Pi model specific values
    if [[ "$PI_MODEL" == "pi4" ]]; then
        PI_MODEL_NUM="4"
        PI_RAM_MB="4096"  # Assume 4GB Pi 4 for optimal build
        PI_CORES="4"
        GPU_MEM="64"
        HOSTNAME="cupcake-pi4"
        IMG_SIZE="8G"
        WHISPER_MODEL="base.en"
        WHISPER_THREADS="4"
    else
        PI_MODEL_NUM="5"
        PI_RAM_MB="8192"  # Assume 8GB Pi 5 for optimal build
        PI_CORES="4"
        GPU_MEM="128"
        HOSTNAME="cupcake-pi5"
        IMG_SIZE="10G"
        WHISPER_MODEL="small.en"
        WHISPER_THREADS="6"
    fi

    info "Target specs: $PI_MODEL with ${PI_RAM_MB}MB RAM, $PI_CORES cores"
    info "Whisper config: $WHISPER_MODEL model, $WHISPER_THREADS threads"
    info "Image size: $IMG_SIZE"
}

# Configuration with smart detection
BUILD_DIR=$(detect_build_dir)
PI_GEN_DIR="$BUILD_DIR/pi-gen"
CUPCAKE_DIR="$(dirname "$(readlink -f "$0")")/.."
CONFIG_DIR="./config"
SCRIPTS_DIR="./scripts"
ASSETS_DIR="./assets"

# Initialize target specs
detect_target_pi_specs

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if running on Debian/Ubuntu
    if ! command -v apt &> /dev/null; then
        error "This script requires a Debian/Ubuntu system with apt package manager"
    fi
    
    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root"
    fi
    
    # Install pi-gen dependencies
    log "Installing pi-gen dependencies..."
    sudo apt-get update
    sudo apt-get install -y \
        qemu-user-static \
        debootstrap git \
        parted kpartx fdisk gdisk \
        dosfstools e2fsprogs \
        zip xz-utils \
        python3 python3-pip \
        binfmt-support \
        rsync \
        quilt \
        libarchive-tools \
        arch-test \
        coreutils \
        zerofree \
        tar \
        whois \
        grep \
        libcap2-bin \
        xxd \
        file \
        kmod \
        bc \
        pigz
    
    # Install binfmt-support and enable it
    if ! dpkg -l | grep -q "^ii  binfmt-support "; then
        log "Installing binfmt-support package..."
        sudo apt-get install -y binfmt-support
    fi
    
    # Enable binfmt support service if available
    if systemctl list-unit-files | grep -q "binfmt-support.service"; then
        sudo systemctl enable binfmt-support || warn "Could not enable binfmt-support service"
        sudo systemctl start binfmt-support || warn "Could not start binfmt-support service"
    fi
    
    # Check available disk space (need at least 8GB)
    local available_space=$(df . | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 8388608 ]]; then # 8GB in KB
        error "Need at least 8GB free disk space for image building"
    fi
    
    log "Prerequisites check completed"
}

# Setup pi-gen
setup_pi_gen() {
    log "Setting up pi-gen..."
    
    if [[ ! -d "$PI_GEN_DIR" ]]; then
        info "Cloning pi-gen repository..."
        git clone https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
    else
        info "Updating pi-gen repository..."
        cd "$PI_GEN_DIR"
        git pull origin master
        cd ..
    fi
    
    # Copy our custom configuration
    cp -r "$CONFIG_DIR/pi-gen-config/"* "$PI_GEN_DIR/" 2>/dev/null || true
    
    log "pi-gen setup completed"
}

# Prepare build environment
prepare_build() {
    log "Preparing build environment..."
    
    # Create build directory
    mkdir -p "$BUILD_DIR"
    
    # Create custom stage for CUPCAKE
    local stage_dir="$PI_GEN_DIR/stage-cupcake"
    mkdir -p "$stage_dir"
    
    # Copy stage configuration
    cp "$CONFIG_DIR/pi-gen-config/stage-cupcake/"* "$stage_dir/" 2>/dev/null || true
    
    # Create files directory for custom files
    local files_dir="$stage_dir/01-cupcake/files"
    mkdir -p "$files_dir"
    
    # Copy system configuration files
    info "Copying system configuration files..."
    cp -r "$CONFIG_DIR/system/"* "$files_dir/"
    
    # Copy scripts
    info "Copying deployment scripts..."
    mkdir -p "$files_dir/opt/cupcake/scripts"
    cp "$SCRIPTS_DIR/"* "$files_dir/opt/cupcake/scripts/"
    chmod +x "$files_dir/opt/cupcake/scripts/"*
    
    # Copy config files (systemd services, etc.)
    info "Copying configuration files..."
    mkdir -p "$files_dir/opt/cupcake/config"
    cp -r "$CONFIG_DIR/"* "$files_dir/opt/cupcake/config/" 2>/dev/null || true

    # Ensure NVMe setup script is executable
    chmod +x "$files_dir/opt/cupcake/scripts/setup-nvme.sh"
    
    # Copy CUPCAKE source code
    info "Copying CUPCAKE source code..."
    mkdir -p "$files_dir/opt/cupcake/src"
    
    # Copy essential CUPCAKE files (excluding development files)
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='.git' \
              --exclude='node_modules' \
              --exclude='venv' \
              --exclude='env' \
              --exclude='.env' \
              --exclude='build' \
              --exclude='dist' \
              --exclude='raspberry-pi' \
              "$CUPCAKE_DIR/" "$files_dir/opt/cupcake/src/"
    
    # Copy assets
    info "Copying assets..."
    cp -r "$ASSETS_DIR/"* "$files_dir/opt/cupcake/assets/" 2>/dev/null || true
    
    log "Build environment prepared"
}

# Configure pi-gen settings
configure_pi_gen() {
    log "Configuring pi-gen settings for $PI_MODEL..."
    
    # Set Pi model specific values
    local pi_model_num=""
    local gpu_mem=""
    local hostname=""
    
    if [[ "$PI_MODEL" == "pi4" ]]; then
        pi_model_num="4"
        gpu_mem="64"
        hostname="cupcake-pi4"
    else
        pi_model_num="5"
        gpu_mem="128"
        hostname="cupcake-pi5"
    fi
    
    cat > "$PI_GEN_DIR/config" << EOF
# CUPCAKE $PI_MODEL Configuration
IMG_NAME="cupcake-$PI_MODEL-$IMAGE_VERSION"
IMG_DATE="$(date +%Y-%m-%d)"
RELEASE="bookworm"
DEPLOY_COMPRESSION="xz"

# Pi model specific
PI_MODEL="$pi_model_num"
ARCH="arm64"

# Basic settings
ENABLE_SSH=$ENABLE_SSH
DISABLE_SPLASH=1
DISABLE_FIRST_BOOT_USER_RENAME=1

# Custom stages
STAGE_LIST="stage0 stage1 stage2 stage-cupcake"

# Skip stages we don't need
SKIP_IMAGES="stage0,stage1"

# Locale settings
TIMEZONE_DEFAULT="UTC"
KEYBOARD_KEYMAP="us"
KEYBOARD_LAYOUT="English (US)"

# User configuration
FIRST_USER_NAME="cupcake"
FIRST_USER_PASS="cupcake123"  # Will be changed during setup
HOSTNAME="$hostname"

# GPU memory allocation
GPU_MEM=$gpu_mem

# WiFi configuration (optional)
# WPA_ESSID="YourWiFiNetwork"
# WPA_PASSWORD="YourWiFiPassword"
# WPA_COUNTRY="US"
EOF
    
    log "pi-gen configuration completed for $PI_MODEL"
}

# Create custom stage
create_custom_stage() {
    log "Creating custom CUPCAKE stage..."
    
    local stage_dir="$PI_GEN_DIR/stage-cupcake"
    
    # The stage directory should already exist from prepare_build, but ensure it's clean
    rm -rf "$stage_dir/01-cupcake"
    mkdir -p "$stage_dir/01-cupcake"

    # Create stage prerun script
    cat > "$stage_dir/prerun.sh" << 'EOF'
#!/bin/bash -e

# CUPCAKE Stage Prerun
if [ -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf" ]; then
    rm -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf"
fi
EOF
    chmod +x "$stage_dir/prerun.sh"
    
    # Create the main setup script that uses our modular scripts
    cat > "$stage_dir/01-cupcake/01-run.sh" << 'EOF'
#!/bin/bash -e

# Ensure ROOTFS_DIR is set and exists
if [ -z "${ROOTFS_DIR}" ]; then
    echo "Error: ROOTFS_DIR is not set"
    exit 1
fi

echo "Setting up CUPCAKE in ${ROOTFS_DIR}"

# Copy all files from the prepare_build stage
if [ -d "files" ] && [ -n "${ROOTFS_DIR}" ]; then
    echo "Copying files to ${ROOTFS_DIR}"
    mkdir -p "${ROOTFS_DIR}"
    find files -type f -exec cp --parents {} "${ROOTFS_DIR}/" \; 2>/dev/null || {
        echo "Warning: Some files could not be copied"
        if [ -d "files" ]; then
            cd files
            tar -cf - . | (cd "${ROOTFS_DIR}" && tar -xf -)
            cd ..
        fi
    }
fi

# Run the modular installation script
on_chroot << 'CHROOT_EOF'
bash /opt/cupcake/scripts/install-cupcake.sh
CHROOT_EOF

echo "CUPCAKE stage completed successfully"

EOF

    chmod +x "$stage_dir/01-cupcake/01-run.sh"

    log "Custom CUPCAKE stage created"
}

# Main build execution
main() {
    log "Starting CUPCAKE Pi image build for $PI_MODEL..."

    # Main build steps
    check_prerequisites
    setup_pi_gen
    prepare_build
    configure_pi_gen
    create_custom_stage

    # Run pi-gen build
    log "Starting pi-gen build process..."
    cd "$PI_GEN_DIR"

    # Run the build
    sudo ./build.sh

    log "Pi image build completed successfully!"
    log "Output images available in: $PI_GEN_DIR/deploy/"

    # List generated images
    if [ -d "$PI_GEN_DIR/deploy" ]; then
        info "Generated images:"
        ls -la "$PI_GEN_DIR/deploy/"*.img* 2>/dev/null || true
        ls -la "$PI_GEN_DIR/deploy/"*.zip 2>/dev/null || true
    fi
}

# Run main build process
main "$@"
