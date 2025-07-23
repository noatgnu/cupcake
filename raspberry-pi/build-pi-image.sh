#!/bin/bash

# CUPCAKE Raspberry Pi Image Builder
# Creates a custom Raspberry Pi OS image optimized for CUPCAKE deployment

set -e

# Parse command line arguments
PI_MODEL="${1:-pi5}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"

# Validate Pi model
if [[ "$PI_MODEL" != "pi4" && "$PI_MODEL" != "pi5" ]]; then
    echo "Error: PI_MODEL must be 'pi4' or 'pi5'"
    echo "Usage: $0 [pi4|pi5] [version] [enable_ssh]"
    echo "Example: $0 pi5 v1.0.0 1"
    exit 1
fi

# Configuration
PI_GEN_DIR="./pi-gen"
CUPCAKE_DIR="$(dirname "$(readlink -f "$0")")/.."
BUILD_DIR="./build"
CONFIG_DIR="./config"
SCRIPTS_DIR="./scripts"
ASSETS_DIR="./assets"

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
    
    # Clean and create stage directory
    rm -rf "$stage_dir"
    mkdir -p "$stage_dir"
    
    # Create stage prerun script
    cat > "$stage_dir/prerun.sh" << 'EOF'
#!/bin/bash -e

# CUPCAKE Stage Prerun
if [ -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf" ]; then
    rm -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf"
fi
EOF
    chmod +x "$stage_dir/prerun.sh"
    
    # Create main cupcake setup stage
    mkdir -p "$stage_dir/01-cupcake/files"
    
    # Copy system configuration files if they exist
    if [[ -d "$CONFIG_DIR/system" ]]; then
        info "Copying system configuration files..."
        cp -r "$CONFIG_DIR/system/"* "$stage_dir/01-cupcake/files/"
    fi
    
    # Create cupcake directories in the stage
    mkdir -p "$stage_dir/01-cupcake/files/opt/cupcake"/{scripts,src,data,logs,backup,media,config,assets}
    mkdir -p "$stage_dir/01-cupcake/files/var/log/cupcake"
    mkdir -p "$stage_dir/01-cupcake/files/var/lib/cupcake"
    
    # Copy existing raspberry-pi scripts if they exist
    if [[ -d "$SCRIPTS_DIR" ]]; then
        info "Copying deployment scripts..."
        cp -r "$SCRIPTS_DIR/"* "$stage_dir/01-cupcake/files/opt/cupcake/scripts/"
        chmod +x "$stage_dir/01-cupcake/files/opt/cupcake/scripts/"*
    fi
    
    # Copy existing configuration if it exists
    if [[ -d "$CONFIG_DIR/nginx" ]]; then
        cp -r "$CONFIG_DIR/nginx" "$stage_dir/01-cupcake/files/opt/cupcake/config/"
    fi
    if [[ -d "$CONFIG_DIR/postgresql" ]]; then
        cp -r "$CONFIG_DIR/postgresql" "$stage_dir/01-cupcake/files/opt/cupcake/config/"
    fi
    
    # Copy assets if they exist
    if [[ -d "$ASSETS_DIR" ]]; then
        info "Copying assets..."
        cp -r "$ASSETS_DIR/"* "$stage_dir/01-cupcake/files/opt/cupcake/assets/" 2>/dev/null || true
    fi
    
    # Copy CUPCAKE source code
    info "Copying CUPCAKE source code..."
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
              "$CUPCAKE_DIR/" "$stage_dir/01-cupcake/files/opt/cupcake/src/"
    
    # Create the main setup script
    cat > "$stage_dir/01-cupcake/01-run.sh" << 'EOF'
#!/bin/bash -e

# Ensure ROOTFS_DIR is set and exists
if [ -z "${ROOTFS_DIR}" ]; then
    echo "Error: ROOTFS_DIR is not set"
    exit 1
fi

echo "Setting up CUPCAKE in ${ROOTFS_DIR}"

# Copy configuration files first
if [ -d "files" ] && [ -n "${ROOTFS_DIR}" ]; then
    echo "Copying files to ${ROOTFS_DIR}"
    # Ensure target directory exists
    mkdir -p "${ROOTFS_DIR}"
    # Copy files with proper error checking
    find files -type f -exec cp --parents {} "${ROOTFS_DIR}/" \; 2>/dev/null || {
        echo "Warning: Some files could not be copied"
        # Try alternative copy method
        if [ -d "files" ]; then
            cd files
            tar -cf - . | (cd "${ROOTFS_DIR}" && tar -xf -)
            cd ..
        fi
    }
fi

# Install system packages
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

# Configure for Pi deployment (use generic Pi hostname)
sed -i 's;https://cupcake.proteo.info;http://cupcake-pi.local;g' src/environments/environment.ts
sed -i 's;http://localhost;http://cupcake-pi.local;g' src/environments/environment.ts

# Install dependencies and build
npm install
npm run build

# Copy built frontend to nginx directory
mkdir -p /opt/cupcake/frontend
cp -r dist/browser/* /opt/cupcake/frontend/
chown -R cupcake:cupcake /opt/cupcake/frontend

# Clean up build directory
cd /
rm -rf /tmp/cupcake-ng

# Clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

CHROOT_EOF

# Set permissions after copying files
if [ -d "${ROOTFS_DIR}/opt/cupcake/scripts" ]; then
    chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"*
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

CHROOT_EOF

echo "CUPCAKE stage completed successfully"
EOF
    chmod +x "$stage_dir/01-cupcake/01-run.sh"
    
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

# Build the image
build_image() {
    log "Starting image build process..."
    
    cd "$PI_GEN_DIR"
    
    # Clean previous builds
    if [[ -d "work" ]]; then
        info "Cleaning previous build..."
        sudo rm -rf work
    fi
    
    if [[ -d "deploy" ]]; then
        sudo rm -rf deploy
    fi
    
    # Start build
    info "Building Raspberry Pi image (this may take 1-2 hours)..."
    sudo ./build.sh
    
    # Check if build was successful
    local expected_image="deploy/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
    if [[ -f "$expected_image" ]]; then
        log "Image build completed successfully!"
        
        # Copy to build directory
        cp deploy/cupcake-${PI_MODEL}-* "../$BUILD_DIR/"
        
        info "Image location: $BUILD_DIR/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
    else
        error "Image build failed! Expected: $expected_image"
        ls -la deploy/ || true
    fi
    
    cd ..
}

# Create deployment package
create_deployment_package() {
    log "Creating deployment package..."
    
    local package_dir="$BUILD_DIR/cupcake-${PI_MODEL}-deployment"
    mkdir -p "$package_dir"
    
    # Copy README and documentation
    cp README.md "$package_dir/"
    
    # Copy configuration files for reference
    cp -r "$CONFIG_DIR" "$package_dir/"
    
    # Copy scripts for standalone use
    cp -r "$SCRIPTS_DIR" "$package_dir/"
    
    # Create deployment instructions
    cat > "$package_dir/DEPLOYMENT.md" << EOF
# CUPCAKE $PI_MODEL Deployment Instructions

## 1. Flash Image to SD Card

### Using Raspberry Pi Imager (Recommended)
1. Download and install Raspberry Pi Imager
2. Select "Use custom image" and choose the .img file
3. Select your SD card
4. Configure SSH keys and WiFi if needed
5. Flash the image

### Using dd (Linux/macOS)
\`\`\`bash
sudo dd if=cupcake-$PI_MODEL-$IMAGE_VERSION.img of=/dev/sdX bs=4M status=progress
\`\`\`

## 2. Initial Boot and Setup

1. Insert SD card into Raspberry Pi ${PI_MODEL^^}
2. Connect ethernet cable (recommended)
3. Power on the Pi
4. Wait for initial boot (2-3 minutes)

## 3. Access and Configuration

### SSH Access
```bash
ssh cupcake@cupcake-pi.local
# Default password: cupcake123 (change immediately)
```

### Initial Setup
```bash
sudo /opt/cupcake/setup.sh
```

## 4. Web Access

Once setup is complete:
- Web Interface: http://cupcake-pi.local
- Admin Panel: http://cupcake-pi.local/admin

## 5. Monitoring

Check system status:
```bash
sudo systemctl status cupcake-*
htop
```

## Troubleshooting

- Check logs: `journalctl -u cupcake-web`
- System resources: `df -h && free -h`
- Network issues: `ip addr show`
EOF
    
    # Create archive
    cd "$BUILD_DIR"
    tar -czf "cupcake-${PI_MODEL}-deployment-${IMAGE_VERSION}.tar.gz" "cupcake-${PI_MODEL}-deployment/"
    cd ..
    
    log "Deployment package created: $BUILD_DIR/cupcake-${PI_MODEL}-deployment-${IMAGE_VERSION}.tar.gz"
}

# Main execution
main() {
    log "Starting CUPCAKE Raspberry Pi $PI_MODEL image build..."
    info "Pi Model: $PI_MODEL"
    info "Image Version: $IMAGE_VERSION"
    info "SSH Enabled: $ENABLE_SSH"
    
    # CRITICAL: Load binfmt_misc FIRST THING before any other operations
    log "Loading binfmt_misc kernel module (required for pi-gen)..."
    sudo modprobe binfmt_misc || warn "Could not load binfmt_misc module"
    
    # Mount binfmt_misc filesystem immediately
    if [[ ! -d "/proc/sys/fs/binfmt_misc" ]] || ! mount | grep -q binfmt_misc; then
        log "Mounting binfmt_misc filesystem..."
        sudo mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || error "CRITICAL: Failed to mount binfmt_misc - pi-gen will fail"
    fi
    
    # Verify it's actually working
    if [[ ! -f "/proc/sys/fs/binfmt_misc/status" ]]; then
        error "CRITICAL: binfmt_misc not properly mounted - pi-gen will fail"
    fi
    
    info "binfmt_misc status: $(cat /proc/sys/fs/binfmt_misc/status 2>/dev/null || echo 'unknown')"
    
    # Use system's qemu-user-static registration
    log "Configuring qemu-user-static for pi-gen..."
    if [ -f /usr/lib/binfmt.d/qemu-aarch64-static.conf ]; then
        sudo systemd-binfmt --reload /usr/lib/binfmt.d/qemu-aarch64-static.conf 2>/dev/null || true
    fi
    
    # Alternative: use update-binfmts if available
    if command -v update-binfmts &>/dev/null; then
        sudo update-binfmts --enable qemu-aarch64 2>/dev/null || true
        sudo update-binfmts --enable qemu-arm 2>/dev/null || true
    fi
    
    # Show what's registered
    info "Registered binfmt interpreters:"
    ls -la /proc/sys/fs/binfmt_misc/ | grep -E "(qemu|arm|aarch64)" || warn "No ARM interpreters found"
    
    # Test if ARM emulation is working
    if command -v qemu-aarch64-static &>/dev/null; then
        log "Testing ARM64 emulation..."
        if echo "int main(){return 42;}" | gcc -x c - -o /tmp/test_arm64 -static 2>/dev/null; then
            if qemu-aarch64-static /tmp/test_arm64 2>/dev/null; then
                info "ARM64 emulation test: PASSED"
            else
                warn "ARM64 emulation test: FAILED"
            fi
            rm -f /tmp/test_arm64
        fi
    fi
    
    # Create necessary directories
    mkdir -p "$CONFIG_DIR" "$SCRIPTS_DIR" "$ASSETS_DIR" "$BUILD_DIR"
    
    check_prerequisites
    setup_pi_gen
    prepare_build
    configure_pi_gen
    create_custom_stage
    build_image
    create_deployment_package
    
    log "CUPCAKE Raspberry Pi $PI_MODEL image build completed successfully!"
    log "Image location: $BUILD_DIR/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
    log "Deployment package: $BUILD_DIR/cupcake-${PI_MODEL}-deployment-${IMAGE_VERSION}.tar.gz"
    
    echo ""
    echo -e "${GREEN}Next steps:${NC}"
    echo "1. Flash the image to an SD card (64GB+ recommended for production)"
    echo "2. Boot the Raspberry Pi ${PI_MODEL^^}"
    echo "3. SSH to cupcake@cupcake-pi.local (password: cupcake123)"
    echo "4. Run: sudo /opt/cupcake/setup.sh"
    echo "5. Access web interface at http://cupcake-pi.local"
    echo ""
    echo -e "${GREEN}Frontend Features:${NC}"
    echo "• Angular frontend built and included"
    echo "• Configured for Pi deployment with .local hostnames"
    echo "• No separate frontend deployment needed"
    echo ""
    echo -e "${YELLOW}Note: Change default passwords immediately after first boot!${NC}"
}

# Execute main function
main "$@"