#!/bin/bash

# Traditional CUPCAKE Pi 5 Image Builder
# This script builds a complete CUPCAKE image using standard Linux tools
# without relying on rpi-image-gen

set -e

echo "=== CUPCAKE Pi 5 Traditional Image Builder ==="

# Configuration
IMG_NAME="cupcake-pi5-$(date +%Y%m%d).img"
IMG_SIZE="8G"
MOUNT_DIR="/tmp/cupcake-pi5-build"
LOOP_DEVICE=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

cleanup() {
    if [ -n "$LOOP_DEVICE" ] && [ -e "$LOOP_DEVICE" ]; then
        log "Cleaning up loop device $LOOP_DEVICE"
        sudo umount "${LOOP_DEVICE}p1" 2>/dev/null || true
        sudo umount "${LOOP_DEVICE}p2" 2>/dev/null || true
        sudo losetup -d "$LOOP_DEVICE" 2>/dev/null || true
    fi
    
    if [ -d "$MOUNT_DIR" ]; then
        sudo umount "$MOUNT_DIR/boot" 2>/dev/null || true
        sudo umount "$MOUNT_DIR" 2>/dev/null || true
        sudo rmdir "$MOUNT_DIR" 2>/dev/null || true
    fi
}

# Set trap for cleanup
trap cleanup EXIT

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    error "This script must be run with sudo"
fi

# Check dependencies
check_dependencies() {
    log "Checking dependencies..."
    local deps=(
        "qemu-user-static"
        "debootstrap" 
        "parted"
        "kpartx"
        "dosfstools"
        "rsync"
        "wget"
        "curl"
        "git"
    )
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null && ! dpkg -l | grep -q "^ii.*$dep"; then
            error "Missing dependency: $dep. Please install with: apt-get install $dep"
        fi
    done
    log "All dependencies satisfied"
}

# Download base Raspberry Pi OS image
download_base_image() {
    log "Downloading base Raspberry Pi OS Lite image..."
    
    local base_url="https://downloads.raspberrypi.org/raspios_lite_arm64/images"
    local latest_dir=$(curl -s "$base_url/" | grep -o 'raspios_lite_arm64-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' | tail -1)
    local image_file="${latest_dir}.img.xz"
    local image_url="${base_url}/${latest_dir}/${image_file}"
    
    if [ ! -f "raspios-lite-arm64.img" ]; then
        log "Downloading from: $image_url"
        wget -O "$image_file" "$image_url"
        
        log "Extracting image..."
        xz -d "$image_file"
        mv "${image_file%.xz}" raspios-lite-arm64.img
    else
        log "Base image already exists"
    fi
}

# Resize image for CUPCAKE installation
resize_image() {
    log "Creating CUPCAKE image with size $IMG_SIZE..."
    
    # Copy base image to our target image
    cp raspios-lite-arm64.img "$IMG_NAME"
    
    # Resize image file
    dd if=/dev/zero bs=1M count=4096 >> "$IMG_NAME"
    
    # Setup loop device
    LOOP_DEVICE=$(losetup --show -fP "$IMG_NAME")
    log "Using loop device: $LOOP_DEVICE"
    
    # Resize partition
    parted "$LOOP_DEVICE" resizepart 2 100%
    e2fsck -f "${LOOP_DEVICE}p2"
    resize2fs "${LOOP_DEVICE}p2"
}

# Mount the image
mount_image() {
    log "Mounting image..."
    mkdir -p "$MOUNT_DIR"
    mount "${LOOP_DEVICE}p2" "$MOUNT_DIR"
    mount "${LOOP_DEVICE}p1" "$MOUNT_DIR/boot"
    
    # Enable arm64 emulation
    cp /usr/bin/qemu-aarch64-static "$MOUNT_DIR/usr/bin/"
}

# Install system updates and basic packages
install_system_packages() {
    log "Installing system packages..."
    
    # Update package lists
    chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get upgrade -y
    "
    
    # Install base packages
    chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y \\
            curl wget git vim nano htop \\
            build-essential cmake pkg-config \\
            python3 python3-pip python3-venv python3-dev \\
            nodejs npm \\
            postgresql-14 postgresql-client-14 postgresql-contrib-14 \\
            redis-server redis-tools \\
            nginx \\
            ffmpeg libavcodec-extra \\
            fail2ban ufw \\
            nvme-cli smartmontools hdparm \\
            libopenblas-dev
    "
}

# Create CUPCAKE user and directories
setup_cupcake_user() {
    log "Setting up CUPCAKE user and directories..."
    
    chroot "$MOUNT_DIR" /bin/bash -c "
        # Create cupcake user
        useradd -m -s /bin/bash cupcake
        usermod -aG sudo cupcake
        
        # Create directories
        mkdir -p /opt/cupcake/{scripts,config}
        mkdir -p /var/lib/cupcake
        mkdir -p /var/log/cupcake
        mkdir -p /opt/whisper.cpp
        
        # Set ownership
        chown -R cupcake:cupcake /opt/cupcake /var/lib/cupcake /var/log/cupcake
    "
}

# Install Python dependencies
install_python_deps() {
    log "Installing Python dependencies..."
    
    chroot "$MOUNT_DIR" /bin/bash -c "
        pip3 install --upgrade pip setuptools wheel
        pip3 install \\
            Django>=4.2,<5.0 \\
            djangorestframework \\
            django-cors-headers \\
            psycopg2-binary \\
            redis \\
            celery \\
            gunicorn \\
            uvicorn \\
            channels \\
            channels-redis \\
            requests \\
            psutil
    "
}

# Build and install Whisper.cpp
install_whisper() {
    log "Building Whisper.cpp..."
    
    chroot "$MOUNT_DIR" /bin/bash -c "
        cd /opt/whisper.cpp
        git clone https://github.com/ggerganov/whisper.cpp.git .
        
        # Download models based on expected Pi 5 performance
        ./models/download-ggml-model.sh tiny.en
        ./models/download-ggml-model.sh base.en
        ./models/download-ggml-model.sh small.en
        
        # Build Whisper.cpp
        cmake -B build
        cmake --build build --config Release -j \$(nproc)
        
        # Set permissions
        chown -R cupcake:cupcake /opt/whisper.cpp
    "
}

# Configure system services
configure_services() {
    log "Configuring system services..."
    
    # Configure PostgreSQL
    chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable postgresql
        
        # Create CUPCAKE database and user
        sudo -u postgres createuser cupcake
        sudo -u postgres createdb cupcake_db -O cupcake
        sudo -u postgres psql -c \"ALTER USER cupcake WITH PASSWORD 'cupcake123';\"
    "
    
    # Configure Redis
    chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable redis-server
        
        # Configure Redis for CUPCAKE
        echo 'maxmemory 256mb' >> /etc/redis/redis.conf
        echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf
    "
    
    # Configure Nginx
    chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable nginx
        
        # Create basic CUPCAKE nginx config
        cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /static/ {
        alias /opt/cupcake/staticfiles/;
    }
    
    location /media/ {
        alias /opt/cupcake/media/;
    }
}
EOF
        
        ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
    "
    
    # Configure firewall
    chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable ufw
        ufw --force enable
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow ssh
        ufw allow 80
        ufw allow 443
    "
}

# Install system capability detection
install_system_detection() {
    log "Installing system capability detection..."
    
    # Copy our system detection script
    cp "$SCRIPT_DIR/../rpi-image-gen/scripts/detect-system-capabilities.py" "$MOUNT_DIR/opt/cupcake/scripts/"
    
    chroot "$MOUNT_DIR" /bin/bash -c "
        chmod +x /opt/cupcake/scripts/detect-system-capabilities.py
        
        # Create system configuration service
        cat > /etc/systemd/system/cupcake-system-config.service << 'EOF'
[Unit]
Description=CUPCAKE System Configuration
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/detect-system-capabilities.py generate /opt/cupcake/config
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl enable cupcake-system-config.service
        
        # Create management script
        ln -sf /opt/cupcake/scripts/detect-system-capabilities.py /usr/local/bin/cupcake-config
    "
}

# Configure Pi 5 optimizations
configure_pi5_optimizations() {
    log "Configuring Pi 5 specific optimizations..."
    
    # Update config.txt for Pi 5
    cat >> "$MOUNT_DIR/boot/config.txt" << EOF

# Pi 5 CUPCAKE Optimizations
arm_64bit=1
gpu_mem=128

# NVMe SSD Support and Optimization
dtparam=pcie_gen=3
dtoverlay=nvme

# Performance optimizations
over_voltage=2
arm_freq=2400

# Enable camera and display auto-detect
camera_auto_detect=1
display_auto_detect=1
EOF

    # Create NVMe optimization script
    cat > "$MOUNT_DIR/opt/cupcake/scripts/optimize-nvme.sh" << 'EOF'
#!/bin/bash
# NVMe SSD optimization for Pi 5

# Check if NVMe drive exists
if [ -e /dev/nvme0n1 ]; then
    echo "NVMe drive detected, applying optimizations..."
    
    # Set scheduler to mq-deadline for NVMe
    echo mq-deadline > /sys/block/nvme0n1/queue/scheduler
    
    # Increase queue depth
    echo 32 > /sys/block/nvme0n1/queue/nr_requests
    
    # Enable write cache
    hdparm -W1 /dev/nvme0n1
    
    echo "NVMe optimizations applied"
else
    echo "No NVMe drive detected"
fi
EOF

    chroot "$MOUNT_DIR" /bin/bash -c "
        chmod +x /opt/cupcake/scripts/optimize-nvme.sh
        
        # Create systemd service for NVMe optimization
        cat > /etc/systemd/system/cupcake-nvme-optimize.service << 'EOF'
[Unit]
Description=CUPCAKE NVMe Optimization
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/optimize-nvme.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl enable cupcake-nvme-optimize.service
    "
}

# Create first boot setup script
create_setup_script() {
    log "Creating first boot setup script..."
    
    cat > "$MOUNT_DIR/opt/cupcake/scripts/first-boot-setup.sh" << 'EOF'
#!/bin/bash
# CUPCAKE First Boot Setup Script

set -e

echo "=== CUPCAKE First Boot Setup ==="

# Detect system capabilities and generate config
/opt/cupcake/scripts/detect-system-capabilities.py generate /opt/cupcake/config

# Apply system optimizations based on detected hardware
if [ -f /opt/cupcake/config/system-info.json ]; then
    echo "Applying hardware-specific optimizations..."
    
    # Extract system tier
    TIER=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['system_tier'])")
    echo "Detected system tier: $TIER"
    
    # Configure Whisper.cpp based on system tier
    if [ -f /opt/cupcake/config/cupcake.env ]; then
        # Source the environment variables
        set -a
        source /opt/cupcake/config/cupcake.env
        set +a
        
        echo "Whisper.cpp configured for $TIER system"
        echo "Model: $WHISPERCPP_DEFAULT_MODEL"
        echo "Threads: $WHISPERCPP_THREAD_COUNT"
    fi
fi

echo "=== First boot setup completed ==="
echo "System is ready for CUPCAKE installation"
echo ""
echo "Next steps:"
echo "1. Clone CUPCAKE repository"
echo "2. Configure Django settings"
echo "3. Run database migrations"
echo "4. Start CUPCAKE services"
EOF

    chroot "$MOUNT_DIR" /bin/bash -c "
        chmod +x /opt/cupcake/scripts/first-boot-setup.sh
        
        # Create systemd service for first boot setup
        cat > /etc/systemd/system/cupcake-first-boot.service << 'EOF'
[Unit]
Description=CUPCAKE First Boot Setup
After=network.target cupcake-system-config.service
Wants=cupcake-system-config.service

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/first-boot-setup.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl enable cupcake-first-boot.service
    "
}

# Create README for the image
create_image_readme() {
    log "Creating image documentation..."
    
    cat > "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt" << 'EOF'
=== CUPCAKE Raspberry Pi 5 Image ===

This image contains a pre-configured Raspberry Pi 5 system optimized for CUPCAKE laboratory management software.

INSTALLED COMPONENTS:
- Python 3.11 with CUPCAKE dependencies
- PostgreSQL 14 database
- Redis cache server
- Nginx web server
- Whisper.cpp speech recognition (auto-configured)
- System capability detection and optimization

FIRST BOOT:
The system will automatically:
1. Detect hardware capabilities
2. Configure Whisper.cpp with optimal model
3. Apply system-specific optimizations
4. Set up environment variables

DEFAULT CREDENTIALS:
- User: cupcake (no password set - configure on first boot)
- PostgreSQL: cupcake/cupcake123
- Database: cupcake_db

NEXT STEPS:
1. Set password: sudo passwd cupcake
2. Configure network settings
3. Clone CUPCAKE: git clone https://github.com/noatgnu/cupcake.git
4. Follow CUPCAKE installation guide

SYSTEM MANAGEMENT:
- Check system config: cupcake-config detect
- View system info: cupcake-config info
- Test Whisper: cupcake-config test

For support, visit: https://github.com/noatgnu/cupcake
EOF

    chown cupcake:cupcake "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt"
}

# Main build process
main() {
    log "Starting CUPCAKE Pi 5 image build..."
    
    check_dependencies
    download_base_image
    resize_image
    mount_image
    
    install_system_packages
    setup_cupcake_user
    install_python_deps
    install_whisper
    configure_services
    install_system_detection
    configure_pi5_optimizations
    create_setup_script
    create_image_readme
    
    # Cleanup
    log "Cleaning up..."
    rm -f "$MOUNT_DIR/usr/bin/qemu-aarch64-static"
    
    # Unmount
    umount "$MOUNT_DIR/boot"
    umount "$MOUNT_DIR"
    losetup -d "$LOOP_DEVICE"
    
    log "Build completed successfully!"
    log "Image file: $IMG_NAME"
    log "Size: $(du -h "$IMG_NAME" | cut -f1)"
    
    echo ""
    echo "To flash to SD card:"
    echo "  sudo dd if=$IMG_NAME of=/dev/sdX bs=4M status=progress"
    echo "  or use Raspberry Pi Imager with 'Use Custom' option"
}

# Run main function
main "$@"