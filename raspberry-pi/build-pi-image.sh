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

    # Check potential directories in order of preference (updated for GitHub Actions)
    local dirs=("$HOME/build" "/tmp/build" "./build" "/opt/build")

    for dir in "${dirs[@]}"; do
        local parent_dir=$(dirname "$dir")
        if [ -d "$parent_dir" ] && [ -w "$parent_dir" ]; then
            local available_gb=$(df "$parent_dir" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}')
            if [ "$available_gb" -gt "$max_space" ]; then
                max_space=$available_gb
                best_dir=$dir
            fi
        fi
    done

    # If no suitable directory found, use current directory
    if [ -z "$best_dir" ] || [ "$max_space" -lt "$required_gb" ]; then
        best_dir="./cupcake-build"
        max_space=$(df . 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}' || echo 0)
    fi

    if [ "$max_space" -lt "$required_gb" ]; then
        warn "Only ${max_space}GB available, but ${required_gb}GB recommended"
        warn "Build may fail if space runs out"
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

# Custom stages - ensure our stage runs after stage2
STAGE_LIST="stage0 stage1 stage2 stage-cupcake"

# Set work directory for pi-gen
WORK_DIR="${BUILD_DIR}/pi-gen/work"

# Only export image after our custom stage
SKIP_IMAGES="stage0,stage1,stage2"

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
    
    # Create clean stage directory
    rm -rf "$stage_dir"
    mkdir -p "$stage_dir/00-install-cupcake"
    local files_dir="$stage_dir/00-install-cupcake/files"
    mkdir -p "$files_dir"
    
    # Copy stage configuration if it exists
    if [ -d "$CONFIG_DIR/pi-gen-config/stage-cupcake" ]; then
        cp "$CONFIG_DIR/pi-gen-config/stage-cupcake/"* "$stage_dir/" 2>/dev/null || true
    fi
    
    # Ensure stage control files exist (these control pi-gen behavior)
    # EXPORT_IMAGE tells pi-gen to create an image after this stage
    touch "$stage_dir/EXPORT_IMAGE"
    
    # Ensure we have all required pi-gen stage files
    # EXPORT_IMAGE already created above
    
    # Create SKIP file to ensure stage isn't skipped
    if [ ! -f "$stage_dir/SKIP" ]; then
        # Don't create SKIP file - we want this stage to run
        :
    fi
    
    # Create stage info file
    cat > "$stage_dir/STAGE_INFO" << 'EOF'
# CUPCAKE Installation Stage
# Installs CUPCAKE LIMS on Raspberry Pi OS
# Depends on: stage2 (base system)
EOF
    
    # Copy system configuration files if they exist
    if [ -d "$CONFIG_DIR/system" ]; then
        info "Copying system configuration files..."
        cp -r "$CONFIG_DIR/system/"* "$files_dir/" 2>/dev/null || true
    else
        warn "System config directory not found: $CONFIG_DIR/system"
    fi
    
    # Copy scripts if they exist
    if [ -d "$SCRIPTS_DIR" ]; then
        info "Copying deployment scripts..."
        mkdir -p "$files_dir/opt/cupcake/scripts"
        cp "$SCRIPTS_DIR/"* "$files_dir/opt/cupcake/scripts/" 2>/dev/null || true
        chmod +x "$files_dir/opt/cupcake/scripts/"* 2>/dev/null || true
    else
        warn "Scripts directory not found: $SCRIPTS_DIR"
        mkdir -p "$files_dir/opt/cupcake/scripts"
    fi
    
    # Copy config files (systemd services, etc.) if they exist
    if [ -d "$CONFIG_DIR" ]; then
        info "Copying configuration files..."
        mkdir -p "$files_dir/opt/cupcake/config"
        cp -r "$CONFIG_DIR/"* "$files_dir/opt/cupcake/config/" 2>/dev/null || true
    else
        warn "Config directory not found: $CONFIG_DIR"
        mkdir -p "$files_dir/opt/cupcake/config"
    fi
    
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
    
    # Copy assets if they exist
    if [ -d "$ASSETS_DIR" ]; then
        info "Copying assets..."
        mkdir -p "$files_dir/opt/cupcake/assets"
        cp -r "$ASSETS_DIR/"* "$files_dir/opt/cupcake/assets/" 2>/dev/null || true
    else
        warn "Assets directory not found: $ASSETS_DIR"
        mkdir -p "$files_dir/opt/cupcake/assets"
    fi
    
    log "Stage files prepared"

    # Create stage prerun script - this copies rootfs from previous stage
    cat > "$stage_dir/prerun.sh" << 'EOF'
#!/bin/bash -e

# CUPCAKE Stage Prerun - copy rootfs from previous stage if it doesn't exist
# This is the standard pi-gen pattern used by all official stages

if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi

echo "CUPCAKE stage prerun completed - rootfs ready"
EOF
    chmod +x "$stage_dir/prerun.sh"
    
    # Create the main setup script - this runs in pi-gen context
    cat > "$stage_dir/00-install-cupcake/01-run.sh" << 'EOF'
#!/bin/bash -e

# Logging functions for pi-gen stage context
log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

warn() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1"
}

error() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1"
    exit 1
}

info() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# At this point, pi-gen should have set up ROOTFS_DIR properly via prerun.sh
log "Starting CUPCAKE installation..."
log "ROOTFS_DIR: ${ROOTFS_DIR}"

# Basic validation that we're in the right context
if [ -z "${ROOTFS_DIR}" ]; then
    error "ROOTFS_DIR not set - this script must run within pi-gen context"
fi

if [ ! -d "${ROOTFS_DIR}" ]; then
    error "ROOTFS_DIR does not exist: ${ROOTFS_DIR} - prerun.sh script didn't work correctly"
fi

log "ROOTFS_DIR validated: ${ROOTFS_DIR}"

# Copy configuration files from the files directory
if [ -d "files" ]; then
    log "Copying configuration files..."
    info "Files directory structure:"
    find files -type f | head -10
    
    # Check if files directory has content
    if [ "$(ls -A files 2>/dev/null)" ]; then
        cp -r files/* "${ROOTFS_DIR}/" || {
            error "Failed to copy files to ${ROOTFS_DIR}"
        }
        log "Successfully copied configuration files"
    else
        info "Files directory is empty, nothing to copy"
    fi
else
    info "No files directory found, skipping file copy"
    info "This is normal if no system configuration files need to be copied"
fi

# Install system packages in chroot
log "Installing system packages..."
on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive

# Update package list
apt-get update

# Install core system packages
apt-get install -y \
    postgresql postgresql-contrib postgresql-client \
    redis-server \
    nginx \
    python3 python3-pip python3-venv python3-dev \
    build-essential libpq-dev libffi-dev libssl-dev \
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    git curl wget unzip htop nvme-cli \
    supervisor

log "System packages installed successfully"
CHROOT_EOF

# Frontend setup - use pre-built or build from source
setup_frontend() {
    log "Setting up frontend..."
    
    # Ensure ROOTFS_DIR is available for frontend setup
    if [ -z "${ROOTFS_DIR}" ]; then
        error "ROOTFS_DIR is not set in frontend setup"
    fi
    
    local frontend_source=""
    local use_prebuilt=false
    
    # Check for pre-built frontend in various locations
    local prebuilt_locations=(
        "${PREBUILT_FRONTEND_DIR}"                    # Custom environment variable
        "../raspberry-pi/frontend-dist"               # GitHub Actions location
        "./frontend-dist"                             # Local build location
        "../frontend-dist"                            # Parent directory
    )
    
    for location in "${prebuilt_locations[@]}"; do
        if [ -n "$location" ] && [ -d "$location" ] && [ "$(ls -A "$location" 2>/dev/null)" ]; then
            frontend_source="$location"
            use_prebuilt=true
            break
        fi
    done
    
    # Force pre-build if USE_PREBUILT_FRONTEND is set but no pre-built frontend found
    if [ "${USE_PREBUILT_FRONTEND}" = "1" ] && [ "$use_prebuilt" = false ]; then
        warn "USE_PREBUILT_FRONTEND=1 but no pre-built frontend found"
        info "Attempting to pre-build frontend using prebuild-frontend.sh..."
        
        # Try to run the pre-build script
        if [ -f "./prebuild-frontend.sh" ]; then
            ./prebuild-frontend.sh --hostname "$HOSTNAME" --output-dir "./frontend-dist"
            if [ -d "./frontend-dist" ]; then
                frontend_source="./frontend-dist"
                use_prebuilt=true
                log "Successfully pre-built frontend"
            else
                warn "Pre-build script completed but no output found"
            fi
        else
            warn "prebuild-frontend.sh not found, will build in QEMU"
        fi
    fi
    
    if [ "$use_prebuilt" = true ]; then
        log "Using pre-built frontend from: $frontend_source"
        
        # Copy pre-built frontend directly to the target directory
        mkdir -p "${ROOTFS_DIR}/opt/cupcake/frontend"
        cp -r "$frontend_source"/* "${ROOTFS_DIR}/opt/cupcake/frontend/"
        
        # Create build info in the target
        if [ -f "$frontend_source/.build-info" ]; then
            cp "$frontend_source/.build-info" "${ROOTFS_DIR}/opt/cupcake/frontend/"
            info "Frontend build info:"
            cat "$frontend_source/.build-info" | grep -E "(BUILD_DATE|BUILD_PLATFORM|NODE_VERSION)" || true
        fi
        
        # Just clean up apt cache (no Node.js build needed)
        on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive

# Clean up apt cache
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Pre-built frontend integration completed"
CHROOT_EOF
        
        log "Pre-built frontend integration completed"
    else
        warn "Building frontend from source in QEMU (this will be slow)..."
        on_chroot << 'CHROOT_EOF'
# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "Node.js installed, version: $(node --version)"

# Build CUPCAKE Angular frontend
echo "Building CUPCAKE Angular frontend..."
cd /tmp
git clone https://github.com/noatgnu/cupcake-ng.git
cd cupcake-ng

# Configure for Pi deployment (use Pi's hostname)
sed -i 's;https://cupcake.proteo.info;http://cupcake-pi.local;g' src/environments/environment.ts
sed -i 's;http://localhost;http://cupcake-pi.local;g' src/environments/environment.ts

# Install dependencies and build (with increased memory for Pi build)
export NODE_OPTIONS="--max-old-space-size=1024"
npm install --no-optional
npm run build --prod

# Copy built frontend to nginx directory
mkdir -p /opt/cupcake/frontend
cp -r dist/browser/* /opt/cupcake/frontend/

# Clean up build directory
cd /
rm -rf /tmp/cupcake-ng

# Clean up apt cache
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Frontend build completed"
CHROOT_EOF
        
        log "QEMU frontend build completed"
    fi
}

# Call the frontend setup function
setup_frontend

# Set permissions after copying files
if [ -n "${ROOTFS_DIR}" ] && [ -d "${ROOTFS_DIR}/opt/cupcake/scripts" ]; then
    log "Setting script permissions..."
    chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"* || warn "Failed to set script permissions"
else
    warn "Cannot set script permissions - ROOTFS_DIR not set or scripts directory not found"
fi

# Create cupcake user and directories
on_chroot << 'CHROOT_EOF'
# Create cupcake user if it doesn't exist
if ! id "cupcake" &>/dev/null; then
    useradd -m -s /bin/bash cupcake
    echo "cupcake:cupcake123" | chpasswd
    usermod -aG sudo cupcake
fi

# Create required directories
mkdir -p /var/log/cupcake
mkdir -p /var/lib/cupcake
mkdir -p /opt/cupcake/{data,logs,backup,media}

# Set ownership (including frontend files)
chown -R cupcake:cupcake /opt/cupcake
chown -R cupcake:cupcake /var/log/cupcake
chown -R cupcake:cupcake /var/lib/cupcake

# Enable services
systemctl enable ssh
systemctl enable postgresql
systemctl enable redis-server
systemctl enable nginx

# Enable cupcake setup service if it exists
if [ -f "/etc/systemd/system/cupcake-setup.service" ]; then
    systemctl enable cupcake-setup.service
fi

CHROOT_EOF

log "CUPCAKE stage completed successfully"
EOF

    chmod +x "$stage_dir/00-install-cupcake/01-run.sh"
    
    # Create boot configuration stage
    mkdir -p "$stage_dir/02-boot-config"
    
    cat > "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
#!/bin/bash -e

# Add Pi model specific optimizations to boot config
# Check which boot path exists
if [ -f "${ROOTFS_DIR}/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
elif [ -f "${ROOTFS_DIR}/boot/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/config.txt"
else
    echo "Creating boot config file..."
    mkdir -p "${ROOTFS_DIR}/boot/firmware"
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
fi

EOF

    # Add Pi-specific boot configurations
    if [[ "$PI_MODEL" == "pi4" ]]; then
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTEOF'

# CUPCAKE Pi 4 Optimizations
arm_64bit=1
dtparam=arm_freq=2000
dtparam=over_voltage=2
gpu_mem=64

# Enable NVMe support
dtparam=pciex1
dtoverlay=pcie-32bit-dma

# Disable unused interfaces
dtparam=audio=off
camera_auto_detect=0
display_auto_detect=0

# Memory optimizations
disable_splash=1
boot_delay=0
BOOTEOF
EOF
    else
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTEOF'

# CUPCAKE Pi 5 Optimizations
arm_64bit=1
dtparam=arm_freq=2400
dtparam=over_voltage=2
gpu_mem=128

# Enable PCIe Gen 3 for NVMe
dtparam=pciex1_gen=3
dtoverlay=pcie-32bit-dma

# Pi 5 specific optimizations
dtparam=i2c_arm=off
dtparam=spi=off

# Disable unused interfaces
dtparam=audio=off
camera_auto_detect=0
display_auto_detect=0

# Memory and performance optimizations
disable_splash=1
boot_delay=0
arm_boost=1
BOOTEOF
EOF
    fi
    
    chmod +x "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh"

    log "Custom CUPCAKE stage created with $PI_MODEL optimizations"
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

    # Run pi-gen build using Docker (official recommended approach)
    log "Starting pi-gen Docker build process..."
    cd "$PI_GEN_DIR"

    # Use Docker build approach like official pi-gen-action
    # This avoids QEMU timing issues and rootfs setup problems by:
    # 1. Running pi-gen in controlled Docker environment  
    # 2. Proper isolation between host and build environment
    # 3. Consistent chroot/mount behavior across different hosts
    # 4. Official recommended approach for automated builds
    log "Using Docker-based pi-gen build (resolves QEMU/timing issues)"
    
    # Set Docker build options for better reliability
    export PRESERVE_CONTAINER=0
    export CONTINUE=0
    
    # Run the Docker-based build
    sudo ./build-docker.sh

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
