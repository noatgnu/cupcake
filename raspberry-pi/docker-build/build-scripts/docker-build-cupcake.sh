#!/bin/bash

# Docker-based CUPCAKE Pi 5 Image Builder
# Builds a complete CUPCAKE image inside a Docker container

set -e

echo "=== Docker CUPCAKE Pi 5 Image Builder ==="

# Configuration
IMG_NAME="cupcake-pi5-docker-$(date +%Y%m%d-%H%M).img"
IMG_SIZE="8G"
MOUNT_DIR="/tmp/cupcake-pi5-build"
LOOP_DEVICE=""
BUILD_DIR="/build"
OUTPUT_DIR="/build/output"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Cleanup function
cleanup() {
    log "Cleaning up..."
    if [ -n "$LOOP_DEVICE" ] && [ -e "$LOOP_DEVICE" ]; then
        sudo umount "${LOOP_DEVICE}p1" 2>/dev/null || true
        sudo umount "${LOOP_DEVICE}p2" 2>/dev/null || true
        sudo losetup -d "$LOOP_DEVICE" 2>/dev/null || true
    fi
    
    if [ -d "$MOUNT_DIR" ]; then
        sudo umount "$MOUNT_DIR/boot" 2>/dev/null || true
        sudo umount "$MOUNT_DIR" 2>/dev/null || true
        sudo rm -rf "$MOUNT_DIR" 2>/dev/null || true
    fi
}

trap cleanup EXIT

# Check environment
check_environment() {
    log "Checking Docker build environment..."
    
    info "Container OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
    info "Architecture: $(uname -m)"
    info "Available RAM: $(free -h | awk 'NR==2{print $2}')"
    info "Available disk: $(df -h $BUILD_DIR | awk 'NR==2{print $4}')"
    
    # Check ARM64 emulation
    if [ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
        log "ARM64 emulation available"
    else
        warn "ARM64 emulation not detected, attempting to enable..."
        sudo update-binfmts --enable qemu-aarch64 || warn "Could not enable ARM64 emulation"
    fi
    
    # Check for required tools
    local required_tools=("wget" "parted" "losetup" "debootstrap" "qemu-aarch64-static")
    for tool in "${required_tools[@]}"; do
        if command -v "$tool" >/dev/null 2>&1; then
            info "✓ $tool available"
        else
            error "✗ $tool not found"
        fi
    done
}

# Download base Raspberry Pi OS image
download_base_image() {
    log "Downloading base Raspberry Pi OS image..."
    
    cd "$BUILD_DIR"
    
    # Use known working Raspberry Pi OS ARM64 image URL provided by user
    local image_url="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz"
    local image_file="2025-05-13-raspios-bookworm-arm64-lite.img.xz"
    
    if [ ! -f "raspios-lite-arm64.img" ]; then
        log "Downloading Raspberry Pi OS Lite ARM64 (2025-05-13 Bookworm)..."
        
        log "URL: $image_url"
        
        # Try download with retries
        local max_retries=3
        local retry=1
        
        while [ $retry -le $max_retries ]; do
            if wget --progress=bar:force -O "$image_file" "$image_url"; then
                break
            else
                warn "Download attempt $retry failed"
                if [ $retry -eq $max_retries ]; then
                    error "Failed to download after $max_retries attempts"
                fi
                retry=$((retry + 1))
                sleep 10
            fi
        done
        
        log "Extracting image..."
        xz -d "$image_file"
        mv "${image_file%.xz}" raspios-lite-arm64.img
        
        info "Base image ready: $(du -h raspios-lite-arm64.img | cut -f1)"
    else
        log "Base image already exists"
    fi
}

# Prepare image for modification
prepare_image() {
    log "Preparing CUPCAKE image..."
    
    # Copy base image to our target
    cp raspios-lite-arm64.img "$IMG_NAME"
    
    # Expand image size for CUPCAKE
    log "Expanding image to $IMG_SIZE..."
    dd if=/dev/zero bs=1M count=4096 >> "$IMG_NAME" 2>/dev/null
    
    # Setup loop device
    LOOP_DEVICE=$(sudo losetup --show -fP "$IMG_NAME")
    log "Using loop device: $LOOP_DEVICE"
    
    # Resize root partition
    log "Resizing root partition..."
    
    # First, resize the partition table
    sudo parted "$LOOP_DEVICE" resizepart 2 100% || warn "Partition resize may have failed"
    
    # Wait for kernel to recognize the new partition size
    sudo partprobe "$LOOP_DEVICE" || true
    sleep 2
    
    # Force filesystem check and resize
    log "Checking and resizing filesystem..."
    sudo e2fsck -f -y "${LOOP_DEVICE}p2" || warn "Filesystem check completed with warnings"
    sudo resize2fs "${LOOP_DEVICE}p2" || {
        warn "Standard resize failed, trying alternative approach..."
        # Alternative: Use fdisk to recreate partition
        echo -e "d\n2\nn\np\n2\n\n\ny\nw" | sudo fdisk "$LOOP_DEVICE" || warn "Fdisk partition recreation failed"
        sudo partprobe "$LOOP_DEVICE" || true
        sleep 2
        sudo e2fsck -f -y "${LOOP_DEVICE}p2" || warn "Second filesystem check completed"
        sudo resize2fs "${LOOP_DEVICE}p2" || error "Failed to resize filesystem after partition recreation"
    }
    
    log "Image prepared successfully"
}

# Mount image for modification
mount_image() {
    log "Mounting image for modification..."
    
    sudo mkdir -p "$MOUNT_DIR"
    
    # Mount root and boot partitions
    sudo mount "${LOOP_DEVICE}p2" "$MOUNT_DIR"
    sudo mount "${LOOP_DEVICE}p1" "$MOUNT_DIR/boot"
    
    # Enable ARM64 emulation in chroot
    sudo cp /usr/bin/qemu-aarch64-static "$MOUNT_DIR/usr/bin/"
    
    log "Image mounted at $MOUNT_DIR"
}

# Update system and install base packages
install_base_system() {
    log "Installing base system packages..."
    
    # Update package database
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get upgrade -y
    "
    
    # Install essential packages
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y \\
            curl wget git vim nano htop tree \\
            build-essential cmake pkg-config \\
            python3 python3-pip python3-venv python3-dev \\
            nodejs npm \\
            postgresql-14 postgresql-client-14 postgresql-contrib-14 \\
            redis-server redis-tools \\
            nginx \\
            ffmpeg libavcodec-extra \\
            fail2ban ufw \\
            nvme-cli smartmontools hdparm \\
            libopenblas-dev \\
            systemd-timesyncd
    "
    
    log "Base system packages installed"
}

# Set up CUPCAKE user and environment
setup_cupcake_environment() {
    log "Setting up CUPCAKE environment..."
    
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        # Create cupcake user
        useradd -m -s /bin/bash cupcake
        usermod -aG sudo cupcake
        echo 'cupcake ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers.d/cupcake
        
        # Create CUPCAKE directories
        mkdir -p /opt/cupcake/{scripts,config,logs}
        mkdir -p /var/lib/cupcake
        mkdir -p /var/log/cupcake
        mkdir -p /opt/whisper.cpp
        
        # Set ownership
        chown -R cupcake:cupcake /opt/cupcake /var/lib/cupcake /var/log/cupcake
    "
    
    log "CUPCAKE environment created"
}

# Install Python dependencies
install_python_environment() {
    log "Installing Python environment for CUPCAKE..."
    
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        # Upgrade pip
        python3 -m pip install --upgrade pip setuptools wheel
        
        # Install CUPCAKE Python dependencies
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
            psutil \\
            numpy \\
            pandas
    "
    
    log "Python environment configured"
}

# Build and configure Whisper.cpp
install_whisper() {
    log "Building Whisper.cpp for speech recognition..."
    
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        cd /opt/whisper.cpp
        git clone https://github.com/ggerganov/whisper.cpp.git .
        
        # Download appropriate models for Pi 5
        echo 'Downloading Whisper models...'
        ./models/download-ggml-model.sh tiny.en
        ./models/download-ggml-model.sh base.en  
        ./models/download-ggml-model.sh small.en
        
        # Build Whisper.cpp optimized for ARM64
        echo 'Building Whisper.cpp...'
        cmake -B build \\
            -DWHISPER_OPENBLAS=ON \\
            -DWHISPER_NO_AVX=ON \\
            -DWHISPER_NO_AVX2=ON
        cmake --build build --config Release -j \$(nproc)
        
        # Verify build
        if [ -f build/bin/main ]; then
            echo 'Whisper.cpp built successfully'
            ./build/bin/main --help > /dev/null && echo 'Whisper.cpp test passed'
        else
            echo 'ERROR: Whisper.cpp build failed'
            exit 1
        fi
        
        # Set permissions
        chown -R cupcake:cupcake /opt/whisper.cpp
    "
    
    log "Whisper.cpp installation completed"
}

# Configure system services
configure_services() {
    log "Configuring system services..."
    
    # Configure PostgreSQL
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable postgresql
        
        # Configure PostgreSQL for Pi 5
        echo 'shared_buffers = 256MB' >> /etc/postgresql/14/main/postgresql.conf
        echo 'work_mem = 8MB' >> /etc/postgresql/14/main/postgresql.conf
        echo 'effective_cache_size = 1GB' >> /etc/postgresql/14/main/postgresql.conf
        
        # Start PostgreSQL to create database
        service postgresql start
        
        # Create CUPCAKE database and user
        sudo -u postgres createuser cupcake
        sudo -u postgres createdb cupcake_db -O cupcake
        sudo -u postgres psql -c \"ALTER USER cupcake WITH PASSWORD 'cupcake123';\"
        
        service postgresql stop
    "
    
    # Configure Redis
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable redis-server
        
        # Optimize Redis for Pi 5
        echo 'maxmemory 512mb' >> /etc/redis/redis.conf
        echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf
        echo 'save 900 1' >> /etc/redis/redis.conf
        echo 'save 300 10' >> /etc/redis/redis.conf
    "
    
    # Configure Nginx
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable nginx
        
        # Create CUPCAKE nginx configuration
        cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
    
    location /static/ {
        alias /opt/cupcake/staticfiles/;
        expires 30d;
    }
    
    location /media/ {
        alias /opt/cupcake/media/;
        expires 7d;
    }
}
EOF
        
        ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
    "
    
    # Configure firewall
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable ufw
        ufw --force enable
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow ssh
        ufw allow 80/tcp
        ufw allow 443/tcp
    "
    
    log "System services configured"
}

# Install system capability detection
install_system_detection() {
    log "Installing system capability detection..."
    
    # Copy system detection script
    if [ -f "$BUILD_DIR/config/detect-system-capabilities.py" ]; then
        sudo cp "$BUILD_DIR/config/detect-system-capabilities.py" "$MOUNT_DIR/opt/cupcake/scripts/"
    else
        # Create a simplified version
        sudo tee "$MOUNT_DIR/opt/cupcake/scripts/detect-system-capabilities.py" > /dev/null << 'EOF'
#!/usr/bin/env python3
"""
CUPCAKE System Capability Detection for Pi 5
"""
import os
import json

def detect_system_tier():
    try:
        with open('/proc/meminfo', 'r') as f:
            mem_line = f.readline()
            mem_kb = int(mem_line.split()[1])
            mem_mb = mem_kb // 1024
    except:
        mem_mb = 2048  # Default
    
    cpu_count = os.cpu_count() or 4
    
    if mem_mb < 2048:
        return 'low'
    elif mem_mb < 4096:
        return 'medium'
    else:
        return 'high'

def get_whisper_config():
    tier = detect_system_tier()
    
    configs = {
        'low': {
            'model': 'ggml-tiny.en.bin',
            'threads': 2
        },
        'medium': {
            'model': 'ggml-base.en.bin', 
            'threads': 4
        },
        'high': {
            'model': 'ggml-small.en.bin',
            'threads': 6
        }
    }
    
    config = configs[tier]
    config.update({
        'binary_path': '/opt/whisper.cpp/build/bin/main',
        'model_path': f"/opt/whisper.cpp/models/{config['model']}",
        'system_tier': tier
    })
    
    return config

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == 'tier':
            print(detect_system_tier())
        elif sys.argv[1] == 'whisper':
            print(json.dumps(get_whisper_config(), indent=2))
        elif sys.argv[1] == 'generate':
            # Generate config files
            os.makedirs('/opt/cupcake/config', exist_ok=True)
            
            config = get_whisper_config()
            
            # Generate environment file
            with open('/opt/cupcake/config/cupcake.env', 'w') as f:
                f.write(f"WHISPERCPP_PATH={config['binary_path']}\n")
                f.write(f"WHISPERCPP_DEFAULT_MODEL={config['model_path']}\n")
                f.write(f"WHISPERCPP_THREAD_COUNT={config['threads']}\n")
            
            # Generate system info
            with open('/opt/cupcake/config/system-info.json', 'w') as f:
                json.dump({'system_tier': config['system_tier'], 'whisper_config': config}, f, indent=2)
            
            print("Configuration generated in /opt/cupcake/config/")
    else:
        config = get_whisper_config()
        print(f"System tier: {config['system_tier']}")
        print(f"Whisper model: {config['model']}")
        print(f"Threads: {config['threads']}")
EOF
    fi
    
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        chmod +x /opt/cupcake/scripts/detect-system-capabilities.py
        ln -sf /opt/cupcake/scripts/detect-system-capabilities.py /usr/local/bin/cupcake-config
        
        # Create systemd service for system configuration
        cat > /etc/systemd/system/cupcake-system-config.service << 'EOF'
[Unit]
Description=CUPCAKE System Configuration
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/detect-system-capabilities.py generate
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl enable cupcake-system-config.service
    "
    
    log "System detection installed"
}

# Configure Pi 5 specific optimizations
configure_pi5_optimizations() {
    log "Configuring Pi 5 specific optimizations..."
    
    # Update boot configuration
    sudo tee -a "$MOUNT_DIR/boot/config.txt" > /dev/null << 'EOF'

# CUPCAKE Pi 5 Optimizations
arm_64bit=1
gpu_mem=128

# NVMe SSD Support
dtparam=pcie_gen=3
dtoverlay=nvme

# Performance optimizations
over_voltage=2
arm_freq=2400

# Hardware detection
camera_auto_detect=1
display_auto_detect=1

# Memory optimization
gpu_mem_1024=128
EOF

    # Create first-boot setup script
    sudo tee "$MOUNT_DIR/opt/cupcake/scripts/first-boot-setup.sh" > /dev/null << 'EOF'
#!/bin/bash
# CUPCAKE First Boot Setup

echo "=== CUPCAKE First Boot Setup ==="

# Generate system configuration
/opt/cupcake/scripts/detect-system-capabilities.py generate

# Optimize for NVMe if present
if [ -e /dev/nvme0n1 ]; then
    echo "NVMe drive detected, applying optimizations..."
    echo mq-deadline > /sys/block/nvme0n1/queue/scheduler || true
    echo 32 > /sys/block/nvme0n1/queue/nr_requests || true
fi

echo "First boot setup completed"
echo "CUPCAKE system ready for configuration"
EOF

    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        chmod +x /opt/cupcake/scripts/first-boot-setup.sh
        
        # Create systemd service for first boot
        cat > /etc/systemd/system/cupcake-first-boot.service << 'EOF'
[Unit]
Description=CUPCAKE First Boot Setup
After=cupcake-system-config.service
Wants=cupcake-system-config.service

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/first-boot-setup.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl enable cupcake-first-boot.service
    "
    
    log "Pi 5 optimizations configured"
}

# Create user documentation
create_documentation() {
    log "Creating user documentation..."
    
    sudo tee "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt" > /dev/null << 'EOF'
=== CUPCAKE Raspberry Pi 5 Image (Docker Build) ===

This image was built using Docker containerization for consistency and reliability.

INSTALLED COMPONENTS:
✓ Python 3 with CUPCAKE dependencies
✓ PostgreSQL 14 (optimized for Pi 5)
✓ Redis cache server
✓ Nginx web server with CUPCAKE configuration
✓ Whisper.cpp speech recognition (auto-configured)
✓ System capability detection and optimization

FIRST BOOT SETUP:
The system automatically:
1. Detects Pi 5 hardware capabilities
2. Configures Whisper.cpp with optimal model (tiny/base/small)
3. Applies NVMe optimizations if SSD detected
4. Sets up environment variables for CUPCAKE

DEFAULT CREDENTIALS:
- User: cupcake (no password - set on first boot!)
- PostgreSQL: cupcake / cupcake123
- Database: cupcake_db

GETTING STARTED:
1. Set password: sudo passwd cupcake
2. Configure network (if not using Ethernet)
3. Clone CUPCAKE: git clone https://github.com/noatgnu/cupcake.git
4. Follow CUPCAKE installation documentation

SYSTEM MANAGEMENT:
- System info: cupcake-config
- Whisper config: cupcake-config whisper  
- System tier: cupcake-config tier

TROUBLESHOOTING:
- Check services: systemctl status postgresql redis nginx
- View logs: journalctl -u cupcake-system-config
- Test Whisper: /opt/whisper.cpp/build/bin/main --help

Built with Docker for consistency and reliability.
For support: https://github.com/noatgnu/cupcake
EOF

    sudo chown cupcake:cupcake "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt"
    
    log "Documentation created"
}

# Finalize image
finalize_image() {
    log "Finalizing CUPCAKE image..."
    
    # Remove ARM64 emulation binary
    sudo rm -f "$MOUNT_DIR/usr/bin/qemu-aarch64-static"
    
    # Clean up package cache
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        apt-get clean
        rm -rf /var/lib/apt/lists/*
        rm -rf /tmp/* /var/tmp/*
    "
    
    # Unmount filesystem
    sudo umount "$MOUNT_DIR/boot"
    sudo umount "$MOUNT_DIR"
    
    # Detach loop device
    sudo losetup -d "$LOOP_DEVICE"
    LOOP_DEVICE=""
    
    # Move to output directory
    mv "$IMG_NAME" "$OUTPUT_DIR/"
    
    log "Image finalized: $OUTPUT_DIR/$IMG_NAME"
}

# Main build process
main() {
    local start_time=$(date +%s)
    
    log "Starting Docker-based CUPCAKE Pi 5 image build..."
    info "Build started at: $(date)"
    
    check_environment
    download_base_image
    prepare_image
    mount_image
    install_base_system
    setup_cupcake_environment
    install_python_environment
    install_whisper
    configure_services
    install_system_detection
    configure_pi5_optimizations
    create_documentation
    finalize_image
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local hours=$((duration / 3600))
    local minutes=$(((duration % 3600) / 60))
    
    log "Build completed successfully!"
    info "Build time: ${hours}h ${minutes}m"
    info "Output: $OUTPUT_DIR/$IMG_NAME"
    info "Size: $(du -h "$OUTPUT_DIR/$IMG_NAME" | cut -f1)"
    
    echo ""
    echo "=== CUPCAKE Pi 5 Image Ready ==="
    echo "📁 Image: $OUTPUT_DIR/$IMG_NAME"
    echo "💿 Flash with: sudo dd if=$OUTPUT_DIR/$IMG_NAME of=/dev/sdX bs=4M status=progress"
    echo "🖥️  Or use Raspberry Pi Imager with 'Use Custom' option"
    echo ""
    echo "First boot:"
    echo "1. Set password: sudo passwd cupcake"
    echo "2. Clone CUPCAKE: git clone https://github.com/noatgnu/cupcake.git"
    echo "3. Follow CUPCAKE installation guide"
}

# Run main build process
main "$@"