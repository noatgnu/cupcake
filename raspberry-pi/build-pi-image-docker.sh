#!/bin/bash

# CUPCAKE Raspberry Pi Image Builder (Docker Version)
# Creates a custom Raspberry Pi OS image optimized for CUPCAKE deployment using Docker

set -e

# Default values
PI_MODEL="${1:-pi5}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"

# Script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUPCAKE_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
DOCKER_IMAGE_NAME="cupcake-pi-builder"
DOCKER_TAG="latest"
CONTAINER_NAME="cupcake-pi-build-$(date +%s)"

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

# Validate inputs
validate_inputs() {
    if [[ "$PI_MODEL" != "pi4" && "$PI_MODEL" != "pi5" ]]; then
        error "PI_MODEL must be 'pi4' or 'pi5'"
    fi
    
    if [[ "$ENABLE_SSH" != "0" && "$ENABLE_SSH" != "1" ]]; then
        error "ENABLE_SSH must be '0' or '1'"
    fi
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if Docker is installed and running
    if ! command -v docker &> /dev/null; then
        error "Docker is required but not installed. Please install Docker first."
    fi
    
    if ! docker info &> /dev/null; then
        error "Docker daemon is not running. Please start Docker first."
    fi
    
    # Check and install binfmt-support if needed on host
    if command -v apt-get &> /dev/null; then
        if ! dpkg -l | grep -q "^ii  binfmt-support "; then
            log "Installing binfmt-support package on host..."
            sudo apt-get update
            sudo apt-get install -y binfmt-support
        fi
        
        # Ensure binfmt-support is available on host
        if systemctl list-unit-files | grep -q "binfmt-support.service"; then
            sudo systemctl restart binfmt-support || warn "Could not restart binfmt-support service"
        else
            warn "binfmt-support service not available, binfmt should work via kernel module"
        fi
    fi
    
    # Check available disk space (need at least 10GB for Docker build)
    local available_space=$(df "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 10485760 ]]; then # 10GB in KB
        error "Need at least 10GB free disk space for Docker image building"
    fi
    
    log "Prerequisites check completed"
}

# Build Docker image
build_docker_image() {
    log "Building Docker image for pi-gen..."
    
    # Check if image already exists
    if docker images | grep -q "$DOCKER_IMAGE_NAME.*$DOCKER_TAG"; then
        info "Docker image $DOCKER_IMAGE_NAME:$DOCKER_TAG already exists"
        read -p "Rebuild the Docker image? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Using existing Docker image"
            return 0
        fi
    fi
    
    # Build the Docker image
    info "Building Docker image (this may take 10-15 minutes)..."
    cd "$SCRIPT_DIR"
    
    docker build \
        -f Dockerfile.pi-builder \
        -t "$DOCKER_IMAGE_NAME:$DOCKER_TAG" \
        . || error "Failed to build Docker image"
    
    log "Docker image built successfully"
}

# Create build script for container
create_container_build_script() {
    log "Creating container build script..."
    
    cat > "$SCRIPT_DIR/container-build.sh" << 'EOF'
#!/bin/bash
set -e

# Parse arguments passed from host
PI_MODEL="$1"
IMAGE_VERSION="$2"
ENABLE_SSH="$3"

echo "Starting CUPCAKE Pi $PI_MODEL image build in container..."
echo "Image Version: $IMAGE_VERSION"
echo "SSH Enabled: $ENABLE_SSH"

# Setup binfmt_misc inside the container
echo "Setting up binfmt_misc in container..."

# Load binfmt_misc module (should inherit from host but ensure it's available)
modprobe binfmt_misc 2>/dev/null || echo "binfmt_misc module already loaded"

# Check if binfmt_misc is mounted
if [[ ! -d "/proc/sys/fs/binfmt_misc" ]]; then
    echo "Mounting binfmt_misc in container..."
    mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || {
        echo "ERROR: Failed to mount binfmt_misc in container"
        exit 1
    }
fi

# Register qemu interpreters in container
echo "Registering ARM interpreters in container..."
if [[ -f "/usr/bin/qemu-aarch64-static" ]]; then
    # Register aarch64 interpreter
    if [[ ! -f "/proc/sys/fs/binfmt_misc/qemu-aarch64" ]]; then
        echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:CF' > /proc/sys/fs/binfmt_misc/register 2>/dev/null || echo "Could not register qemu-aarch64"
    fi
fi

if [[ -f "/usr/bin/qemu-arm-static" ]]; then
    # Register arm interpreter  
    if [[ ! -f "/proc/sys/fs/binfmt_misc/qemu-arm" ]]; then
        echo ':qemu-arm:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-arm-static:CF' > /proc/sys/fs/binfmt_misc/register 2>/dev/null || echo "Could not register qemu-arm"
    fi
fi

# Show final status
echo "Container binfmt_misc status:"
cat /proc/sys/fs/binfmt_misc/status 2>/dev/null || echo "status file not readable"
echo "Registered interpreters:"
ls -la /proc/sys/fs/binfmt_misc/ | grep -E "(qemu|arm|aarch64)" || echo "No ARM interpreters found"

# Change to pi-gen directory
cd /build/pi-gen

# Clean any previous builds
if [[ -d "work" ]]; then
    echo "Cleaning previous build..."
    sudo rm -rf work deploy || true
fi

# Configure pi-gen
echo "Configuring pi-gen for $PI_MODEL..."

# Set Pi model specific values
if [[ "$PI_MODEL" == "pi4" ]]; then
    PI_MODEL_NUM="4"
    GPU_MEM="64"
    HOSTNAME="cupcake-pi4"
else
    PI_MODEL_NUM="5"
    GPU_MEM="128"
    HOSTNAME="cupcake-pi5"
fi

cat > config << EOC
# CUPCAKE $PI_MODEL Configuration
IMG_NAME="cupcake-$PI_MODEL-$IMAGE_VERSION"
IMG_DATE="$(date +%Y-%m-%d)"
RELEASE="bookworm"
DEPLOY_COMPRESSION="none"

# Pi model specific
PI_MODEL="$PI_MODEL_NUM"
ARCH="arm64"

# Basic settings
ENABLE_SSH=$ENABLE_SSH
DISABLE_SPLASH=1
DISABLE_FIRST_BOOT_USER_RENAME=1

# Custom stages
STAGE_LIST="stage0 stage1 stage2 stage-cupcake"

# Locale settings
TIMEZONE_DEFAULT="UTC"
KEYBOARD_KEYMAP="us"
KEYBOARD_LAYOUT="English (US)"

# User configuration
FIRST_USER_NAME="cupcake"
FIRST_USER_PASS="cupcake123"
HOSTNAME="$HOSTNAME"

# GPU memory allocation
GPU_MEM=$GPU_MEM
EOC

# Create custom CUPCAKE stage
echo "Creating custom CUPCAKE stage..."
STAGE_DIR="stage-cupcake"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Create stage prerun script
cat > "$STAGE_DIR/prerun.sh" << 'PRERUN_EOF'
#!/bin/bash -e

# CUPCAKE Stage Prerun
if [ -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf" ]; then
    rm -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf"
fi
PRERUN_EOF
chmod +x "$STAGE_DIR/prerun.sh"

# Create main cupcake setup stage
mkdir -p "$STAGE_DIR/01-cupcake/files"

# Create cupcake directories in the stage
mkdir -p "$STAGE_DIR/01-cupcake/files/opt/cupcake"/{scripts,src,data,logs,backup,media,config,assets,frontend}
mkdir -p "$STAGE_DIR/01-cupcake/files/var/log/cupcake"
mkdir -p "$STAGE_DIR/01-cupcake/files/var/lib/cupcake"

# Copy CUPCAKE source code from mounted volume
echo "Copying CUPCAKE source code..."
if [[ -d "/build/cupcake-src" ]]; then
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='.git' \
              --exclude='.github' \
              --exclude='.idea' \
              --exclude='.claude' \
              --exclude='node_modules' \
              --exclude='venv' \
              --exclude='env' \
              --exclude='.env' \
              --exclude='build' \
              --exclude='dist' \
              --exclude='raspberry-pi' \
              --exclude='pi-deployment' \
              --exclude='tests' \
              --exclude='test_*' \
              --exclude='*_test.py' \
              --exclude='*.md' \
              --exclude='*.MD' \
              --exclude='README*' \
              --exclude='*.adoc' \
              --exclude='*.svg' \
              --exclude='docker-compose*.yml' \
              --exclude='captain-definition*' \
              --exclude='Dockerfile*' \
              --exclude='dockerfiles' \
              --exclude='ansible-playbooks' \
              --exclude='*.zip' \
              --exclude='*.tar.gz' \
              --exclude='*.tar' \
              --exclude='*.rar' \
              --exclude='*.7z' \
              --exclude='backups' \
              --exclude='temp_extract' \
              --exclude='data2' \
              --exclude='test_*' \
              --exclude='*test*' \
              --exclude='staticfiles' \
              --exclude='media' \
              --exclude='*.lock' \
              --exclude='.dockerignore' \
              --exclude='.gitignore' \
              --exclude='install_cupcake*.sh' \
              --exclude='build-multiarch.sh' \
              --exclude='turnserver*' \
              --exclude='cron' \
              --exclude='models' \
              /build/cupcake-src/ "$STAGE_DIR/01-cupcake/files/opt/cupcake/src/"
else
    echo "Warning: No CUPCAKE source found at /build/cupcake-src"
fi

# Create the main setup script
cat > "$STAGE_DIR/01-cupcake/01-run.sh" << 'SETUP_EOF'
#!/bin/bash -e

# Copy configuration files first
if [ -d "files" ]; then
    cp -r files/* "${ROOTFS_DIR}/"
fi

# Install system packages and build frontend
on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive

# Update package list
apt-get update

# Install PostgreSQL
apt-get install -y postgresql postgresql-contrib postgresql-client

# Install Redis
apt-get install -y redis-server

# Install Nginx
apt-get install -y nginx

# Install Python and essential packages for native deployment
apt-get install -y python3 python3-pip python3-venv python3-dev

# Install system dependencies for Python packages
apt-get install -y build-essential libpq-dev libffi-dev libssl-dev
apt-get install -y libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
apt-get install -y git curl wget unzip htop nvme-cli

# Install Node.js for frontend builds
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Build CUPCAKE Angular frontend
echo "Building CUPCAKE Angular frontend..."
cd /tmp
git clone https://github.com/noatgnu/cupcake-ng.git
cd cupcake-ng

# Configure for Pi deployment
HOSTNAME_VAR=""
if [[ "$PI_MODEL" == "pi4" ]]; then
    HOSTNAME_VAR="cupcake-pi4.local"
else
    HOSTNAME_VAR="cupcake-pi5.local"
fi

sed -i "s;https://cupcake.proteo.info;http://$HOSTNAME_VAR;g" src/environments/environment.ts
sed -i "s;http://localhost;http://$HOSTNAME_VAR;g" src/environments/environment.ts

# Install dependencies and build
npm install
npm run build

# Copy built frontend to nginx directory
mkdir -p /opt/cupcake/frontend
cp -r dist/browser/* /opt/cupcake/frontend/

# Clean up build directory
cd /
rm -rf /tmp/cupcake-ng

# Clean up packages
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

CHROOT_EOF

# Set permissions after copying files
if [ -d "${ROOTFS_DIR}/opt/cupcake/scripts" ]; then
    chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"*
fi

# Create cupcake user and directories
on_chroot << 'USER_EOF'
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

# Set ownership
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

USER_EOF

echo "CUPCAKE stage completed successfully"
SETUP_EOF
chmod +x "$STAGE_DIR/01-cupcake/01-run.sh"

# Create boot configuration stage
mkdir -p "$STAGE_DIR/02-boot-config"

cat > "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'BOOT_EOF'
#!/bin/bash -e

# Add Pi model specific optimizations to boot config
if [ -f "${ROOTFS_DIR}/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
elif [ -f "${ROOTFS_DIR}/boot/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/config.txt"
else
    echo "Creating boot config file..."
    mkdir -p "${ROOTFS_DIR}/boot/firmware"
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
fi

BOOT_EOF

# Add Pi-specific boot configurations
if [[ "$PI_MODEL" == "pi4" ]]; then
    cat >> "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'PI4_BOOT_EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTCONFIG_EOF'

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
BOOTCONFIG_EOF
PI4_BOOT_EOF
else
    cat >> "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'PI5_BOOT_EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTCONFIG_EOF'

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
BOOTCONFIG_EOF
PI5_BOOT_EOF
fi

chmod +x "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh"

# Start the build
echo "Starting pi-gen build process..."
echo "This will take 1-3 hours depending on your system..."

sudo ./build.sh

# Check if build was successful and copy to output
if [[ -f "deploy/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img" ]]; then
    echo "Build completed successfully!"
    cp deploy/cupcake-${PI_MODEL}-*.img /build/output/
    echo "Image copied to output directory"
    ls -la /build/output/
else
    echo "Build failed! Checking deploy directory..."
    ls -la deploy/ || echo "Deploy directory not found"
    exit 1
fi
EOF

    chmod +x "$SCRIPT_DIR/container-build.sh"
    log "Container build script created"
}

# Run the build in Docker container
run_docker_build() {
    log "Starting Docker-based Pi image build..."
    
    # Create output directory
    mkdir -p "$SCRIPT_DIR/output"
    
    info "Running build container (this will take 1-3 hours)..."
    
    # Run the build container with privileged access 
    # Note: Container inherits host's kernel and binfmt_misc setup
    docker run \
        --rm \
        --privileged \
        --name "$CONTAINER_NAME" \
        -v "$CUPCAKE_ROOT:/build/cupcake-src:ro" \
        -v "$SCRIPT_DIR/container-build.sh:/build/container-build.sh:ro" \
        -v "$SCRIPT_DIR/output:/build/output:rw" \
        "$DOCKER_IMAGE_NAME:$DOCKER_TAG" \
        /build/container-build.sh "$PI_MODEL" "$IMAGE_VERSION" "$ENABLE_SSH"
    
    log "Docker build completed"
}

# Compress and finalize image
finalize_image() {
    log "Finalizing image..."
    
    local image_file="$SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
    
    if [[ -f "$image_file" ]]; then
        info "Compressing image..."
        cd "$SCRIPT_DIR/output"
        
        # Compress with xz
        xz -9 -T 0 "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
        
        # Generate checksum
        sha256sum "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz" > "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
        
        log "Image finalized:"
        log "  Image: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz"
        log "  Checksum: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
    else
        error "Image file not found: $image_file"
    fi
}

# Cleanup function
cleanup() {
    log "Cleaning up temporary files..."
    
    # Remove container build script
    rm -f "$SCRIPT_DIR/container-build.sh"
    
    # Stop and remove container if it exists
    if docker ps -a | grep -q "$CONTAINER_NAME"; then
        docker rm -f "$CONTAINER_NAME" &>/dev/null || true
    fi
}

# Show usage
show_usage() {
    echo "Usage: $0 [pi4|pi5] [version] [enable_ssh]"
    echo ""
    echo "Arguments:"
    echo "  pi_model     - Raspberry Pi model: 'pi4' or 'pi5' (default: pi5)"
    echo "  version      - Image version tag (default: current date)"
    echo "  enable_ssh   - Enable SSH: '1' or '0' (default: 1)"
    echo ""
    echo "Examples:"
    echo "  $0                          # Build Pi 5 image with defaults"
    echo "  $0 pi4                      # Build Pi 4 image"
    echo "  $0 pi5 v1.0.0               # Build Pi 5 image with version v1.0.0"
    echo "  $0 pi4 v1.0.0 0             # Build Pi 4 image with SSH disabled"
    echo ""
    echo "Requirements:"
    echo "  - Docker installed and running"
    echo "  - At least 10GB free disk space"
    echo "  - Privileged Docker access (for pi-gen)"
}

# Main execution
main() {
    log "Starting CUPCAKE Raspberry Pi $PI_MODEL Docker image build..."
    info "Pi Model: $PI_MODEL"
    info "Image Version: $IMAGE_VERSION"
    info "SSH Enabled: $ENABLE_SSH"
    info "Build Directory: $SCRIPT_DIR"
    
    # CRITICAL: Load binfmt_misc IMMEDIATELY on host system
    log "Loading binfmt_misc kernel module on host (required for pi-gen)..."
    sudo modprobe binfmt_misc || warn "Could not load binfmt_misc module"
    
    # Mount binfmt_misc filesystem on host
    if [[ ! -d "/proc/sys/fs/binfmt_misc" ]] || ! mount | grep -q binfmt_misc; then
        log "Mounting binfmt_misc filesystem on host..."
        sudo mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || error "CRITICAL: Failed to mount binfmt_misc on host"
    fi
    
    # Verify it's working on host
    if [[ ! -f "/proc/sys/fs/binfmt_misc/status" ]]; then
        error "CRITICAL: binfmt_misc not properly mounted on host - Docker pi-gen will fail"
    fi
    
    info "Host binfmt_misc status: $(cat /proc/sys/fs/binfmt_misc/status 2>/dev/null || echo 'unknown')"
    
    # Set up cleanup trap
    trap cleanup EXIT
    
    validate_inputs
    check_prerequisites
    build_docker_image
    create_container_build_script
    run_docker_build
    finalize_image
    
    log "CUPCAKE Raspberry Pi $PI_MODEL Docker image build completed successfully!"
    
    echo ""
    echo -e "${GREEN}Build Results:${NC}"
    echo "📦 Image: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz"
    echo "🔐 Checksum: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo "1. Flash the image to an SD card (64GB+ recommended)"
    echo "2. Boot the Raspberry Pi ${PI_MODEL^^}"
    echo "3. SSH to cupcake@cupcake-${PI_MODEL}.local (password: cupcake123)"
    echo "4. Access web interface at http://cupcake-${PI_MODEL}.local"
    echo ""
    echo -e "${YELLOW}Security Note: Change default passwords immediately after first boot!${NC}"
}

# Check if help is requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_usage
    exit 0
fi

# Execute main function
main "$@"