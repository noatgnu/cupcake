#!/bin/bash

# CUPCAKE Raspberry Pi 5 Image Builder
# Creates a custom Raspberry Pi OS image optimized for CUPCAKE deployment

set -e

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
    
    # Check for required packages
    local required_packages=("git" "docker.io" "qemu-user-static" "binfmt-support")
    for package in "${required_packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $package "; then
            warn "Installing missing package: $package"
            sudo apt-get update
            sudo apt-get install -y "$package"
        fi
    done
    
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
    cp -r "$CONFIG_DIR/pi-gen-config/"* "$PI_GEN_DIR/"
    
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
    log "Configuring pi-gen settings..."
    
    cat > "$PI_GEN_DIR/config" << EOF
# CUPCAKE Pi 5 Configuration
IMG_NAME="cupcake-pi5"
IMG_DATE="$(date +%Y-%m-%d)"
RELEASE="bookworm"
DEPLOY_COMPRESSION="zip"

# Pi 5 specific
PI_MODEL="5"
ARCH="arm64"

# Reduce image size
ENABLE_SSH=1
DISABLE_SPLASH=0
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
ENABLE_SSH=1

# Reduce GPU memory
GPU_MEM=16

# WiFi configuration (optional)
# WPA_ESSID="YourWiFiNetwork"
# WPA_PASSWORD="YourWiFiPassword"
# WPA_COUNTRY="US"
EOF
    
    log "pi-gen configuration completed"
}

# Create custom stage
create_custom_stage() {
    log "Creating custom CUPCAKE stage..."
    
    local stage_dir="$PI_GEN_DIR/stage-cupcake"
    
    # Create stage prerun script
    cat > "$stage_dir/prerun.sh" << 'EOF'
#!/bin/bash -e

# CUPCAKE Stage Prerun
if [ -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf" ]; then
    rm -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf"
fi
EOF
    chmod +x "$stage_dir/prerun.sh"
    
    # Create main setup
    mkdir -p "$stage_dir/01-cupcake"
    cat > "$stage_dir/01-cupcake/01-run.sh" << 'EOF'
#!/bin/bash -e

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

# Install Python and essential packages
apt-get install -y python3 python3-pip python3-venv python3-dev

# Install system dependencies for Python packages
apt-get install -y build-essential libpq-dev libffi-dev libssl-dev
apt-get install -y libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
apt-get install -y git curl wget unzip htop

# Install Node.js for frontend builds (optional)
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

# Clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

CHROOT_EOF

# Copy configuration files
cp -r files/* "${ROOTFS_DIR}/"

# Set permissions
chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"*

# Create cupcake user and directories
on_chroot << 'CHROOT_EOF'
# Create cupcake user if it doesn't exist
if ! id "cupcake" &>/dev/null; then
    useradd -m -s /bin/bash cupcake
    echo "cupcake:cupcake123" | chpasswd
    usermod -aG sudo cupcake
fi

# Create necessary directories
mkdir -p /var/log/cupcake
mkdir -p /var/lib/cupcake
mkdir -p /opt/cupcake/data
mkdir -p /opt/cupcake/backups

# Set ownership
chown -R cupcake:cupcake /opt/cupcake
chown -R cupcake:cupcake /var/log/cupcake
chown -R cupcake:cupcake /var/lib/cupcake

CHROOT_EOF

# Enable services
on_chroot << 'CHROOT_EOF'
# Enable SSH
systemctl enable ssh

# Configure and enable PostgreSQL
systemctl enable postgresql
systemctl enable redis-server
systemctl enable nginx

# Copy and enable CUPCAKE systemd services
cp /opt/cupcake/scripts/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable cupcake-setup.service

CHROOT_EOF

echo "CUPCAKE stage completed successfully"
EOF
    chmod +x "$stage_dir/01-cupcake/01-run.sh"
    
    log "Custom CUPCAKE stage created"
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
    if [[ -f "deploy/cupcake-pi5-$(date +%Y-%m-%d).img" ]]; then
        log "Image build completed successfully!"
        
        # Copy to build directory
        cp deploy/cupcake-pi5-* "../$BUILD_DIR/"
        
        info "Image location: $BUILD_DIR/cupcake-pi5-$(date +%Y-%m-%d).img"
    else
        error "Image build failed!"
    fi
    
    cd ..
}

# Create deployment package
create_deployment_package() {
    log "Creating deployment package..."
    
    local package_dir="$BUILD_DIR/cupcake-pi5-deployment"
    mkdir -p "$package_dir"
    
    # Copy README and documentation
    cp README.md "$package_dir/"
    
    # Copy configuration files for reference
    cp -r "$CONFIG_DIR" "$package_dir/"
    
    # Copy scripts for standalone use
    cp -r "$SCRIPTS_DIR" "$package_dir/"
    
    # Create deployment instructions
    cat > "$package_dir/DEPLOYMENT.md" << 'EOF'
# CUPCAKE Pi 5 Deployment Instructions

## 1. Flash Image to SD Card

### Using Raspberry Pi Imager (Recommended)
1. Download and install Raspberry Pi Imager
2. Select "Use custom image" and choose the .img file
3. Select your SD card
4. Configure SSH keys and WiFi if needed
5. Flash the image

### Using dd (Linux/macOS)
```bash
sudo dd if=cupcake-pi5-YYYY-MM-DD.img of=/dev/sdX bs=4M status=progress
```

## 2. Initial Boot and Setup

1. Insert SD card into Raspberry Pi 5
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
    tar -czf "cupcake-pi5-deployment-$(date +%Y-%m-%d).tar.gz" cupcake-pi5-deployment/
    cd ..
    
    log "Deployment package created: $BUILD_DIR/cupcake-pi5-deployment-$(date +%Y-%m-%d).tar.gz"
}

# Main execution
main() {
    log "Starting CUPCAKE Raspberry Pi 5 image build..."
    
    # Create necessary directories
    mkdir -p "$CONFIG_DIR" "$SCRIPTS_DIR" "$ASSETS_DIR" "$BUILD_DIR"
    
    check_prerequisites
    setup_pi_gen
    prepare_build
    configure_pi_gen
    create_custom_stage
    build_image
    create_deployment_package
    
    log "CUPCAKE Raspberry Pi 5 image build completed successfully!"
    log "Image location: $BUILD_DIR/cupcake-pi5-$(date +%Y-%m-%d).img"
    log "Deployment package: $BUILD_DIR/cupcake-pi5-deployment-$(date +%Y-%m-%d).tar.gz"
    
    echo ""
    echo -e "${GREEN}Next steps:${NC}"
    echo "1. Flash the image to an SD card (64GB+ recommended)"
    echo "2. Boot the Raspberry Pi 5"
    echo "3. SSH to cupcake@cupcake-pi.local (password: cupcake123)"
    echo "4. Run: sudo /opt/cupcake/setup.sh"
    echo "5. Access web interface at http://cupcake-pi.local"
    echo ""
    echo -e "${YELLOW}Note: Change default passwords immediately after first boot!${NC}"
}

# Execute main function
main "$@"