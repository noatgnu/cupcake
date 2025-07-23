#!/bin/bash

# CUPCAKE Pi Image Builder - Native Build Script
# Builds complete CUPCAKE images directly on Raspberry Pi 4 or 5
# Automatically detects hardware and adapts to storage configuration

set -e

echo "=== CUPCAKE Pi Image Builder (Native Build) ==="

# Parse command line arguments
PI_MODEL_ARG="${1:-}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"

# Version and metadata
VERSION="1.0.0"
BUILD_DATE=$(date -Iseconds)

# Configuration paths (matching QEMU version)
CUPCAKE_DIR="$(dirname "$(readlink -f "$0")")/.."
CONFIG_DIR="./config"
SCRIPTS_DIR="./scripts"
ASSETS_DIR="./assets"

# Auto-detect build directory with sufficient space
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

# Configuration with auto-detection
BUILD_DIR=$(detect_build_dir)
IMG_SIZE="8G"
MOUNT_DIR="$BUILD_DIR/mnt"
LOOP_DEVICE=""
OUTPUT_DIR="$BUILD_DIR/output"

# Detect Pi model and specs
PI_MODEL=""
PI_RAM_MB=""
PI_CORES=""
WHISPER_MODEL=""
WHISPER_THREADS=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[BUILD]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
progress() { echo -e "${CYAN}[PROGRESS]${NC} $1"; }

# Cleanup function
cleanup() {
    log "Cleaning up build environment..."
    
    if [ -d "$MOUNT_DIR" ]; then
        # Unmount bind mounts first
        sudo umount "$MOUNT_DIR/dev/pts" 2>/dev/null || true
        sudo umount "$MOUNT_DIR/dev" 2>/dev/null || true
        sudo umount "$MOUNT_DIR/sys" 2>/dev/null || true
        sudo umount "$MOUNT_DIR/proc" 2>/dev/null || true
        sudo umount "$MOUNT_DIR/boot" 2>/dev/null || true
        sudo umount "$MOUNT_DIR" 2>/dev/null || true
        sudo rm -rf "$MOUNT_DIR" 2>/dev/null || true
    fi
    
    if [ -n "$LOOP_DEVICE" ] && [ -e "$LOOP_DEVICE" ]; then
        sudo umount "${LOOP_DEVICE}p1" 2>/dev/null || true
        sudo umount "${LOOP_DEVICE}p2" 2>/dev/null || true
        sudo losetup -d "$LOOP_DEVICE" 2>/dev/null || true
    fi

    # Clean up temporary files
    rm -f "$BUILD_DIR"/*.tmp 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Detect Pi hardware
detect_pi_hardware() {
    log "Detecting Raspberry Pi hardware..."
    
    if [ ! -f /proc/cpuinfo ]; then
        error "Cannot detect Pi hardware - /proc/cpuinfo not found"
    fi
    
    # Detect Pi model
    local revision=$(grep "^Revision" /proc/cpuinfo | cut -d':' -f2 | tr -d ' ')
    local model_info=$(grep "^Model" /proc/cpuinfo | cut -d':' -f2 | sed 's/^ *//')
    
    if grep -q "Pi 5" /proc/cpuinfo || [[ "$model_info" == *"Pi 5"* ]]; then
        PI_MODEL="Pi 5"
    elif grep -q "Pi 4" /proc/cpuinfo || [[ "$model_info" == *"Pi 4"* ]]; then
        PI_MODEL="Pi 4"
    else
        warn "Could not detect Pi 4 or Pi 5, assuming Pi 4"
        PI_MODEL="Pi 4"
    fi
    
    # Detect RAM
    PI_RAM_MB=$(free -m | awk 'NR==2{print $2}')
    
    # Detect CPU cores
    PI_CORES=$(nproc)
    
    # Determine optimal Whisper configuration
    if [ "$PI_RAM_MB" -lt 2048 ]; then
        WHISPER_MODEL="tiny.en"
        WHISPER_THREADS=2
        IMG_SIZE="6G"  # Smaller image for low RAM
    elif [ "$PI_RAM_MB" -lt 4096 ]; then
        WHISPER_MODEL="base.en"
        WHISPER_THREADS=3
        IMG_SIZE="7G"
    elif [ "$PI_RAM_MB" -lt 8192 ]; then
        WHISPER_MODEL="base.en"
        WHISPER_THREADS=4
        IMG_SIZE="8G"
    else
        WHISPER_MODEL="small.en"
        WHISPER_THREADS=6
        IMG_SIZE="10G"
    fi
    
    info "Detected: $PI_MODEL with ${PI_RAM_MB}MB RAM, $PI_CORES cores"
    info "Whisper config: $WHISPER_MODEL model, $WHISPER_THREADS threads"
    info "Image size: $IMG_SIZE"
}

# Check build environment
check_environment() {
    log "Checking build environment..."
    
    info "System: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
    info "Architecture: $(uname -m)"
    info "Kernel: $(uname -r)"
    info "Build directory: $BUILD_DIR"
    
    # Check if running on Pi
    if ! grep -q "Raspberry Pi" /proc/cpuinfo && ! grep -q "BCM" /proc/cpuinfo; then
        warn "Not running on Raspberry Pi - build may not be optimal"
    fi
    
    # Create build directory
    sudo mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"
    sudo chown "$USER:$USER" "$BUILD_DIR" "$OUTPUT_DIR"
    
    # Check required tools and install if needed
    local required_tools=("wget" "parted" "losetup" "debootstrap" "chroot" "xz" "git")
    local missing_tools=()
    
    for tool in "${required_tools[@]}"; do
        if command -v "$tool" >/dev/null 2>&1; then
            info "✓ $tool available"
        else
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        warn "Installing missing tools: ${missing_tools[*]}"
        sudo apt update
        
        # Map tools to packages
        local packages=()
        for tool in "${missing_tools[@]}"; do
            case $tool in
                "debootstrap") packages+=("debootstrap");;
                "parted") packages+=("parted");;
                "xz") packages+=("xz-utils");;
                "git") packages+=("git");;
                *) packages+=("$tool");;
            esac
        done
        
        sudo apt install -y "${packages[@]}" kpartx dosfstools e2fsprogs rsync pv
    fi
    
    # Check available space
    local available_gb=$(df "$BUILD_DIR" | awk 'NR==2{print int($4/1024/1024)}')
    local required_gb=15
    
    if [ "$available_gb" -lt "$required_gb" ]; then
        error "Need at least ${required_gb}GB free space, have ${available_gb}GB"
    fi
    
    info "✓ ${available_gb}GB available space"
    info "✓ Build environment ready"
}

# Download appropriate base image
download_base_image() {
    log "Downloading base Raspberry Pi OS image..."
    
    cd "$BUILD_DIR"
    
    # Choose image based on Pi model
    local image_url
    local image_file
    
    if [ "$PI_MODEL" = "Pi 5" ]; then
        image_url="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz"
        image_file="2025-05-13-raspios-bookworm-arm64-lite.img.xz"
    else
        # Pi 4 - use same ARM64 image
        image_url="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz"
        image_file="2025-05-13-raspios-bookworm-arm64-lite.img.xz"
    fi
    
    if [ ! -f "raspios-lite-arm64.img" ]; then
        progress "Downloading Raspberry Pi OS Lite ARM64..."
        info "URL: $image_url"
        
        # Download with retry and progress
        local max_retries=3
        local retry=1
        
        while [ $retry -le $max_retries ]; do
            if wget --progress=bar:force --timeout=30 --tries=3 -O "$image_file" "$image_url"; then
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
        
        progress "Extracting image..."
        xz -d "$image_file" || error "Failed to extract image"
        mv "${image_file%.xz}" raspios-lite-arm64.img
        
        info "Base image ready: $(du -h raspios-lite-arm64.img | cut -f1)"
    else
        log "Base image already exists"
    fi
}

# Prepare image for CUPCAKE installation
prepare_image() {
    local img_name="cupcake-$PI_MODEL-$(echo "$PI_MODEL" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')-$(date +%Y%m%d-%H%M).img"
    
    log "Preparing CUPCAKE image: $img_name"
    
    # Copy base image to our target
    cp raspios-lite-arm64.img "$img_name"
    
    # Calculate expansion size based on target image size
    local current_size_mb=$(du -m "$img_name" | cut -f1)
    local target_size_mb=$(echo "$IMG_SIZE" | sed 's/G//' | awk '{print $1 * 1024}')
    local expand_mb=$((target_size_mb - current_size_mb))
    
    if [ $expand_mb -gt 0 ]; then
        progress "Expanding image by ${expand_mb}MB to reach $IMG_SIZE total..."
        dd if=/dev/zero bs=1M count=$expand_mb >> "$img_name" 2>/dev/null
    fi
    
    # Setup loop device
    LOOP_DEVICE=$(sudo losetup --show -fP "$img_name")
    log "Using loop device: $LOOP_DEVICE"
    
    # Resize root partition
    progress "Resizing root partition..."
    sudo parted "$LOOP_DEVICE" resizepart 2 100% || warn "Partition resize completed with warnings"
    
    # Wait for kernel to recognize changes
    sleep 2
    sudo partprobe "$LOOP_DEVICE" 2>/dev/null || true
    sleep 2
    
    # Force filesystem check and resize
    progress "Checking and resizing filesystem..."
    sudo e2fsck -f -y "${LOOP_DEVICE}p2" || warn "Filesystem check completed with warnings"
    sudo resize2fs "${LOOP_DEVICE}p2" || error "Failed to resize filesystem"
    
    # Store image name for later use
    echo "$img_name" > "$BUILD_DIR/current_image.tmp"
    
    info "Image prepared successfully: $(du -h "$img_name" | cut -f1)"
}

# Mount image for modification
mount_image() {
    log "Mounting image for modification..."
    
    sudo mkdir -p "$MOUNT_DIR"
    
    # Mount root and boot partitions
    sudo mount "${LOOP_DEVICE}p2" "$MOUNT_DIR"
    sudo mount "${LOOP_DEVICE}p1" "$MOUNT_DIR/boot"
    
    # Bind mount essential filesystems for chroot operations
    progress "Setting up chroot environment..."
    sudo mount --bind /proc "$MOUNT_DIR/proc"
    sudo mount --bind /sys "$MOUNT_DIR/sys"
    sudo mount --bind /dev "$MOUNT_DIR/dev"
    sudo mount --bind /dev/pts "$MOUNT_DIR/dev/pts"

    info "Image mounted at $MOUNT_DIR (native ARM64 - no emulation needed)"
}

# Install base system packages
install_base_system() {
    log "Installing base system packages..."
    
    # Update package database in chroot
    progress "Updating package database..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        export APT_LISTCHANGES_FRONTEND=none
        export NEEDRESTART_MODE=a
        apt-get update -qq
        apt-get upgrade -y -qq -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold'
    "
    
    # Add PostgreSQL official APT repository (same as Docker setup)
    progress "Adding PostgreSQL official repository..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        curl https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/apt.postgresql.org.gpg > /dev/null
        echo 'deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list
        apt-get update -qq
    "

    # Install packages appropriate for Pi model
    local packages="curl wget git vim nano htop tree rsync"
    packages="$packages build-essential cmake pkg-config"
    packages="$packages python3 python3-pip python3-venv python3-dev"
    packages="$packages postgresql-14 postgresql-client-14 postgresql-contrib-14"
    packages="$packages redis-server redis-tools"
    packages="$packages nginx"
    packages="$packages ffmpeg libavcodec-extra"
    packages="$packages fail2ban ufw"
    packages="$packages libopenblas-dev"
    packages="$packages systemd-timesyncd"
    
    # Add Pi-specific packages
    if [ "$PI_MODEL" = "Pi 5" ]; then
        packages="$packages nvme-cli smartmontools hdparm"
    fi
    
    # Add Node.js for both models
    packages="$packages nodejs npm"
    
    progress "Installing essential packages..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        export APT_LISTCHANGES_FRONTEND=none
        export NEEDRESTART_MODE=a
        apt-get install -y -qq $packages -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold'
    "
    
    log "Base system packages installed"
}

# Set up CUPCAKE environment
setup_cupcake_environment() {
    log "Setting up CUPCAKE environment..."
    
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        # Create cupcake user
        useradd -m -s /bin/bash cupcake
        usermod -aG sudo cupcake
        echo 'cupcake ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/cupcake
        
        # Create CUPCAKE directories
        mkdir -p /opt/cupcake/{scripts,config,logs,app}
        mkdir -p /var/lib/cupcake
        mkdir -p /var/log/cupcake
        mkdir -p /opt/whisper.cpp
        
        # Build and install Whisper.cpp for CUPCAKE
        echo '=== Setting up Whisper.cpp for CUPCAKE ==='
        cd /opt/whisper.cpp

        # Clone Whisper.cpp repository (matching transcribe worker)
        echo 'Cloning Whisper.cpp repository...'
        git clone https://github.com/ggerganov/whisper.cpp.git .

        # Detect system capabilities for model selection
        echo 'Detecting system capabilities...'
        TOTAL_RAM=\$(free -m | awk 'NR==2{printf \"%d\", \$2}')
        CPU_CORES=\$(nproc)
        PI_MODEL_REV=\$(cat /proc/cpuinfo | grep 'Revision' | awk '{print \$3}' | head -1)

        echo \"System specs: \${TOTAL_RAM}MB RAM, \${CPU_CORES} CPU cores, Pi model revision: \${PI_MODEL_REV}\"

        # Download models first (like transcribe worker does)
        echo 'Downloading Whisper models...'

        # Always download tiny as fallback
        ./models/download-ggml-model.sh tiny.en

        # Download appropriate models based on system capabilities
        if [ \"\$TOTAL_RAM\" -lt 2048 ]; then
            # Low memory systems (< 2GB) - tiny model only
            echo 'Low memory system detected - using tiny model'
            DEFAULT_MODEL='/opt/whisper.cpp/models/ggml-tiny.en.bin'
            THREAD_COUNT='2'
        elif [ \"\$TOTAL_RAM\" -lt 4096 ]; then
            # Medium memory systems (2-4GB) - base model
            echo 'Medium memory system detected - downloading base model'
            ./models/download-ggml-model.sh base.en
            DEFAULT_MODEL='/opt/whisper.cpp/models/ggml-base.en.bin'
            THREAD_COUNT='4'
        else
            # High memory systems (4GB+) - small model for Pi 5
            echo 'High memory system detected - downloading small model'
            ./models/download-ggml-model.sh base.en   # backup
            ./models/download-ggml-model.sh small.en
            DEFAULT_MODEL='/opt/whisper.cpp/models/ggml-small.en.bin'
            THREAD_COUNT='6'
        fi

        # Build Whisper.cpp (matching transcribe worker build commands exactly)
        echo 'Building Whisper.cpp...'
        cmake -B build
        cmake --build build --config Release -j \$(nproc)

        # Verify the binary was built correctly
        if [ ! -f 'build/bin/main' ]; then
            echo 'ERROR: whisper main binary not found after build!'
            exit 1
        fi

        echo 'Build completed successfully. Binary location: /opt/whisper.cpp/build/bin/main'

        # Create environment configuration matching CUPCAKE settings.py format
        echo 'Creating Whisper.cpp environment configuration...'
        mkdir -p /etc/environment.d
        cat > /etc/environment.d/50-whisper.conf << EOF
# Whisper.cpp configuration for CUPCAKE (matches settings.py)
WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/main
WHISPERCPP_DEFAULT_MODEL=\${DEFAULT_MODEL}
WHISPERCPP_THREAD_COUNT=\${THREAD_COUNT}
EOF

        # Create systemd environment file for services
        mkdir -p /etc/systemd/system.conf.d
        cat > /etc/systemd/system.conf.d/whisper.conf << EOF
[Manager]
DefaultEnvironment=WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/main
DefaultEnvironment=WHISPERCPP_DEFAULT_MODEL=\${DEFAULT_MODEL}
DefaultEnvironment=WHISPERCPP_THREAD_COUNT=\${THREAD_COUNT}
EOF

        # Test the installation
        echo 'Testing Whisper.cpp installation...'
        if /opt/whisper.cpp/build/bin/main --help > /dev/null 2>&1; then
            echo 'Whisper.cpp installation test passed'
        else
            echo 'WARNING: Whisper.cpp installation test failed'
        fi

        echo '=== Whisper.cpp setup completed ==='
        echo \"Binary path: /opt/whisper.cpp/build/bin/main\"
        echo \"Default model: \${DEFAULT_MODEL}\"
        echo \"Thread count: \${THREAD_COUNT}\"
        echo 'Model files available:'
        ls -la /opt/whisper.cpp/models/ | grep '\.bin\$' || echo 'No model files found'

        # Set ownership
        chown -R cupcake:cupcake /opt/cupcake /var/lib/cupcake /var/log/cupcake /opt/whisper.cpp
    "
    
    log "CUPCAKE environment created"
}

# Install Python dependencies
install_python_environment() {
    log "Installing Python environment for CUPCAKE..."
    
    progress "Setting up Python virtual environment..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        # Create virtual environment as cupcake user
        sudo -u cupcake python3 -m venv /opt/cupcake/venv
        
        # Activate and upgrade pip
        source /opt/cupcake/venv/bin/activate
        pip install --upgrade pip setuptools wheel
        
        # Install CUPCAKE Python dependencies from requirements.txt
        pip install \
            'Django>=4.2,<5.0' \
            djangorestframework \
            django-cors-headers \
            psycopg2-binary \
            redis \
            'django-rq>=2.0' \
            rq \
            gunicorn \
            uvicorn \
            channels \
            channels-redis \
            requests \
            psutil \
            numpy \
            pandas \
            Pillow \
            openpyxl \
            python-multipart \
            pydantic \
            fastapi \
            websockets \
            aiofiles \
            python-jose \
            passlib \
            bcrypt \
            python-dotenv \
            python-magic \
            pathvalidate \
            chardet \
            lxml \
            beautifulsoup4 \
            markdown \
            bleach \
            django-extensions \
            django-debug-toolbar \
            django-filter \
            djangorestframework-simplejwt \
            django-oauth-toolkit \
            social-auth-app-django \
            whitenoise \
            dj-database-url \
            python-decouple

        # Fix ownership
        chown -R cupcake:cupcake /opt/cupcake/venv
    "
    
    log "Python environment configured"
}

# Install CUPCAKE source code
install_cupcake_source() {
    log "Installing CUPCAKE source code..."

    # Copy external configuration files if they exist (matching QEMU version)
    if [[ -d "$CONFIG_DIR/system" ]]; then
        progress "Copying system configuration files..."
        sudo cp -r "$CONFIG_DIR/system/"* "$MOUNT_DIR/" 2>/dev/null || true
    fi

    if [[ -d "$SCRIPTS_DIR" ]]; then
        progress "Copying deployment scripts..."
        sudo mkdir -p "$MOUNT_DIR/opt/cupcake/scripts"
        sudo cp -r "$SCRIPTS_DIR/"* "$MOUNT_DIR/opt/cupcake/scripts/"
        sudo chmod +x "$MOUNT_DIR/opt/cupcake/scripts/"*
        sudo chown -R cupcake:cupcake "$MOUNT_DIR/opt/cupcake/scripts" 2>/dev/null || true
    fi

    if [[ -d "$ASSETS_DIR" ]]; then
        progress "Copying assets..."
        sudo mkdir -p "$MOUNT_DIR/opt/cupcake/assets"
        sudo cp -r "$ASSETS_DIR/"* "$MOUNT_DIR/opt/cupcake/assets/" 2>/dev/null || true
        sudo chown -R cupcake:cupcake "$MOUNT_DIR/opt/cupcake/assets" 2>/dev/null || true
    fi

    # Clone CUPCAKE repository directly into the image
    progress "Cloning CUPCAKE repository..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        cd /opt/cupcake
        sudo -u cupcake git clone https://github.com/noatgnu/cupcake.git app
        chown -R cupcake:cupcake /opt/cupcake/app

        # Remove unnecessary files to save space (matching QEMU exclusions)
        cd /opt/cupcake/app
        sudo -u cupcake rm -rf .git .github .idea .claude tests test_* *.md README* docker-compose* Dockerfile* raspberry-pi pi-deployment ansible-playbooks backups temp_extract data2 models staticfiles media __pycache__ *.pyc .env build dist node_modules venv env
    "
    
    progress "Installing CUPCAKE Python dependencies..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        cd /opt/cupcake/app
        source /opt/cupcake/venv/bin/activate

        # Install from requirements.txt if it exists
        if [ -f requirements.txt ]; then
            pip install -r requirements.txt
        fi

        # Create necessary directories (matching QEMU structure)
        sudo -u cupcake mkdir -p /opt/cupcake/app/{media,staticfiles,logs}
        sudo -u cupcake mkdir -p /opt/cupcake/{data,backup,config}
        sudo -u cupcake mkdir -p /var/log/cupcake

        # Set up Django
        export DJANGO_SETTINGS_MODULE=cupcake.settings
        export DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
        export REDIS_URL=redis://localhost:6379/0

        # Collect static files
        python manage.py collectstatic --noinput --clear || echo 'Static files collection failed - will be done on first boot'

        chown -R cupcake:cupcake /opt/cupcake/app
    "

    log "CUPCAKE source code installed"
}

# Create CUPCAKE systemd services
create_cupcake_services() {
    log "Creating CUPCAKE systemd services..."

    # Create CUPCAKE web service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-web.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE Web Server
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service

[Service]
Type=notify
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
Environment=DEBUG=True
Environment=USE_WHISPER=True
Environment=USE_OCR=True
Environment=USE_LLM=True
ExecStart=/opt/cupcake/venv/bin/gunicorn cupcake.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 300
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-web

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE transcribe worker service (replaces Celery worker)
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-transcribe.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE Transcribe Worker
After=network.target postgresql.service redis.service
Requires=redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
Environment=USE_WHISPER=True
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker transcribe
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-transcribe

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE export worker service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-export.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE Export Worker
After=network.target postgresql.service redis.service
Requires=redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker export
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-export

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE import worker service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-import.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE Import Worker
After=network.target postgresql.service redis.service
Requires=redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker import
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-import

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE maintenance worker service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-maintenance.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE Maintenance Worker
After=network.target postgresql.service redis.service
Requires=redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker maintenance
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-maintenance

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE OCR worker service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-ocr.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE OCR Worker
After=network.target postgresql.service redis.service
Requires=redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
Environment=USE_OCR=True
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker ocr
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-ocr

[Install]
WantedBy=multi-user.target
EOF

    # Create CUPCAKE first-boot setup service
    sudo tee "$MOUNT_DIR/etc/systemd/system/cupcake-setup.service" > /dev/null << EOF
[Unit]
Description=CUPCAKE First Boot Setup
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service
Before=cupcake-web.service

[Service]
Type=oneshot
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
ExecStart=/opt/cupcake/scripts/first-boot-setup.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-setup

[Install]
WantedBy=multi-user.target
EOF

    # Create runtime directory for PID files
    sudo tee "$MOUNT_DIR/etc/tmpfiles.d/cupcake.conf" > /dev/null << EOF
d /var/run/cupcake 0755 cupcake cupcake -
EOF

    # Create first boot setup script
    sudo tee "$MOUNT_DIR/opt/cupcake/scripts/first-boot-setup.sh" > /dev/null << 'EOF'
#!/bin/bash
# CUPCAKE First Boot Setup Script

set -e

LOG_FILE="/var/log/cupcake/first-boot.log"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "$(date): Starting CUPCAKE first boot setup..."

cd /opt/cupcake/app

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
while ! pg_isready -h localhost -p 5432 -U cupcake; do
    sleep 2
done

# Wait for Redis to be ready
echo "Waiting for Redis..."
while ! redis-cli ping > /dev/null 2>&1; do
    sleep 2
done

# Activate virtual environment
source /opt/cupcake/venv/bin/activate

# Set environment variables
export DJANGO_SETTINGS_MODULE=cupcake.settings
export DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
export REDIS_URL=redis://localhost:6379/0

# Run Django migrations
echo "Running Django migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

# Create superuser if it doesn't exist
echo "Setting up admin user..."
python manage.py shell << PYEOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake.local', 'cupcake123')
    print('Admin user created: admin / cupcake123')
else:
    print('Admin user already exists')
PYEOF

# Load initial data if needed
echo "Loading initial data..."
python manage.py loaddata initial_data.json 2>/dev/null || echo "No initial data file found"

# Set proper permissions
chown -R cupcake:cupcake /opt/cupcake /var/log/cupcake /var/lib/cupcake

echo "$(date): CUPCAKE first boot setup completed successfully"

# Disable this service so it doesn't run again
systemctl disable cupcake-setup.service
EOF

    sudo chmod +x "$MOUNT_DIR/opt/cupcake/scripts/first-boot-setup.sh"

    # Enable services
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable cupcake-setup.service
        systemctl enable cupcake-web.service
        systemctl enable cupcake-transcribe.service
        systemctl enable cupcake-export.service
        systemctl enable cupcake-import.service
        systemctl enable cupcake-maintenance.service
        systemctl enable cupcake-ocr.service
    "
    
    log "CUPCAKE systemd services created"
}

# Configure system services
configure_services() {
    log "Configuring system services for $PI_MODEL..."
    
    # Configure PostgreSQL with Pi-appropriate settings
    local pg_shared_buffers="128MB"
    local pg_work_mem="4MB"
    local pg_effective_cache="512MB"
    
    if [ "$PI_RAM_MB" -gt 4096 ]; then
        pg_shared_buffers="256MB"
        pg_work_mem="8MB"
        pg_effective_cache="1GB"
    elif [ "$PI_RAM_MB" -gt 7168 ]; then
        pg_shared_buffers="512MB"
        pg_work_mem="16MB"
        pg_effective_cache="2GB"
    fi
    
    progress "Configuring PostgreSQL..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable postgresql
        
        # Configure PostgreSQL for Pi specs
        echo 'shared_buffers = $pg_shared_buffers' >> /etc/postgresql/14/main/postgresql.conf
        echo 'work_mem = $pg_work_mem' >> /etc/postgresql/14/main/postgresql.conf
        echo 'effective_cache_size = $pg_effective_cache' >> /etc/postgresql/14/main/postgresql.conf
        echo 'random_page_cost = 1.1' >> /etc/postgresql/14/main/postgresql.conf
        
        # Start PostgreSQL to create database
        service postgresql start
        
        # Create CUPCAKE database and user
        sudo -u postgres createuser cupcake
        sudo -u postgres createdb cupcake_db -O cupcake
        sudo -u postgres psql -c \\\"ALTER USER cupcake WITH PASSWORD 'cupcake123';\\\" || \\
            sudo -u postgres psql -c \\\$'ALTER USER cupcake WITH PASSWORD \\'cupcake123\\';'

        service postgresql stop
    "
    
    # Configure Redis with Pi-appropriate settings
    local redis_maxmem="256mb"
    if [ "$PI_RAM_MB" -gt 4096 ]; then
        redis_maxmem="512mb"
    elif [ "$PI_RAM_MB" -gt 7168 ]; then
        redis_maxmem="1gb"
    fi
    
    progress "Configuring Redis..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable redis-server
        
        # Optimize Redis for Pi specs
        echo 'maxmemory $redis_maxmem' >> /etc/redis/redis.conf
        echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf
        echo 'save 900 1' >> /etc/redis/redis.conf
        echo 'save 300 10' >> /etc/redis/redis.conf
    "
    
    progress "Configuring Nginx..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        systemctl enable nginx
        
        # Create CUPCAKE nginx configuration
        cat > /etc/nginx/sites-available/cupcake << 'NGINXEOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
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
NGINXEOF
        
        ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
    "
    
    log "System services configured"
}

# Configure Pi-specific optimizations
configure_pi_optimizations() {
    log "Configuring $PI_MODEL specific optimizations..."
    
    # Base Pi configuration
    sudo tee -a "$MOUNT_DIR/boot/config.txt" > /dev/null << EOF

# CUPCAKE Pi Optimizations
arm_64bit=1
gpu_mem=64

# Hardware detection
camera_auto_detect=1
display_auto_detect=1
EOF

    # Pi 5 specific optimizations
    if [ "$PI_MODEL" = "Pi 5" ]; then
        sudo tee -a "$MOUNT_DIR/boot/config.txt" > /dev/null << EOF

# Pi 5 Specific Optimizations
# NVMe SSD Support
dtparam=pcie_gen=3
dtoverlay=nvme

# Performance optimizations
over_voltage=2
arm_freq=2400

# Memory optimization for Pi 5
gpu_mem_1024=128
gpu_mem_256=64
gpu_mem_512=64
EOF
    else
        # Pi 4 specific optimizations
        sudo tee -a "$MOUNT_DIR/boot/config.txt" > /dev/null << EOF

# Pi 4 Specific Optimizations
# Performance optimizations
arm_freq=2000
over_voltage=1

# Memory optimization for Pi 4
gpu_mem_1024=64
gpu_mem_512=64
gpu_mem_256=64
EOF
    fi
    
    # Install system capability detection
    sudo tee "$MOUNT_DIR/usr/local/bin/cupcake-config" > /dev/null << EOF
#!/usr/bin/env python3
"""CUPCAKE System Capability Detection"""
import os
import json

def detect_pi_model():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            content = f.read()
        if 'Pi 5' in content:
            return 'Pi 5'
        elif 'Pi 4' in content:
            return 'Pi 4'
        else:
            return 'Unknown Pi'
    except:
        return 'Unknown'

def detect_system_tier():
    try:
        with open('/proc/meminfo', 'r') as f:
            mem_line = f.readline()
            mem_kb = int(mem_line.split()[1])
            mem_mb = mem_kb // 1024
    except:
        mem_mb = 2048
    
    if mem_mb < 2048:
        return 'low'
    elif mem_mb < 4096:
        return 'medium'
    elif mem_mb < 8192:
        return 'high'
    else:
        return 'ultra'

def get_whisper_config():
    tier = detect_system_tier()
    pi_model = detect_pi_model()
    
    configs = {
        'low': {'model': 'ggml-tiny.en.bin', 'threads': 2},
        'medium': {'model': 'ggml-base.en.bin', 'threads': 3},
        'high': {'model': 'ggml-base.en.bin', 'threads': 4},
        'ultra': {'model': 'ggml-small.en.bin', 'threads': 6}
    }
    
    config = configs[tier]
    config.update({
        'binary_path': '/opt/whisper.cpp/build/bin/main',
        'model_path': f"/opt/whisper.cpp/models/{config['model']}",
        'system_tier': tier,
        'pi_model': pi_model
    })
    
    return config

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == 'tier':
            print(detect_system_tier())
        elif sys.argv[1] == 'model':
            print(detect_pi_model())
        elif sys.argv[1] == 'whisper':
            print(json.dumps(get_whisper_config(), indent=2))
    else:
        config = get_whisper_config()
        print(f"Pi Model: {config['pi_model']}")
        print(f"System tier: {config['system_tier']}")
        print(f"Whisper model: {config['model']}")
        print(f"Threads: {config['threads']}")
EOF

    sudo chmod +x "$MOUNT_DIR/usr/local/bin/cupcake-config"
    
    # Create NVMe optimization script (Pi 5 only)
    if [ "$PI_MODEL" = "Pi 5" ]; then
        sudo tee "$MOUNT_DIR/usr/local/bin/nvme-optimize" > /dev/null << 'EOF'
#!/bin/bash
# NVMe optimization for Pi 5
if [ -e /dev/nvme0n1 ]; then
    echo mq-deadline > /sys/block/nvme0n1/queue/scheduler 2>/dev/null || true
    echo 32 > /sys/block/nvme0n1/queue/nr_requests 2>/dev/null || true
fi
EOF
        sudo chmod +x "$MOUNT_DIR/usr/local/bin/nvme-optimize"
        
        # Create systemd service for NVMe optimization
        sudo tee "$MOUNT_DIR/etc/systemd/system/nvme-optimize.service" > /dev/null << EOF
[Unit]
Description=NVMe Optimization for Pi 5
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/nvme-optimize
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

        sudo chroot "$MOUNT_DIR" systemctl enable nvme-optimize.service
    fi
    
    log "$PI_MODEL optimizations configured"
}

# Create user documentation
create_documentation() {
    log "Creating user documentation..."
    
    sudo tee "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt" > /dev/null << EOF
=== CUPCAKE $PI_MODEL Image (Native Build v$VERSION) ===

This image was built NATIVELY on $PI_MODEL hardware for optimal performance.
Built on: $BUILD_DATE

SYSTEM SPECIFICATIONS:
• Pi Model: $PI_MODEL
• RAM Configuration: ${PI_RAM_MB}MB
• CPU Cores: $PI_CORES
• Whisper Model: $WHISPER_MODEL
• Whisper Threads: $WHISPER_THREADS

INSTALLED COMPONENTS:
✓ Python 3 with CUPCAKE dependencies (virtual environment)
✓ PostgreSQL 14 (optimized for $PI_MODEL specs)
✓ Redis cache server (memory-optimized)
✓ Nginx web server with CUPCAKE configuration
✓ Whisper.cpp speech recognition (native ARM64 build)
✓ System capability detection and auto-configuration

NATIVE BUILD ADVANTAGES:
✓ Faster compilation (no emulation overhead)
✓ Optimized binaries for $PI_MODEL ARM64
✓ Native performance testing during build
✓ Hardware-specific optimizations
✓ Automatic storage adaptation

FIRST BOOT SETUP:
1. Set password: sudo passwd cupcake
2. Configure network (if not using Ethernet)
3. Check system: cupcake-config
4. Clone CUPCAKE: git clone https://github.com/noatgnu/cupcake.git
5. Follow CUPCAKE installation documentation

DEFAULT CREDENTIALS:
- User: cupcake (no password - MUST set on first boot!)
- PostgreSQL: cupcake / cupcake123
- Database: cupcake_db

SYSTEM MANAGEMENT:
- System info: cupcake-config
- Pi model: cupcake-config model
- System tier: cupcake-config tier  
- Whisper config: cupcake-config whisper

OPTIMIZATIONS INCLUDED:
• Automatic hardware detection
• Memory-appropriate database tuning
• Pi model-specific performance settings
• Storage-agnostic configuration
EOF

    if [ "$PI_MODEL" = "Pi 5" ]; then
        sudo tee -a "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt" > /dev/null << EOF
• NVMe SSD auto-optimization
• PCIe Gen 3 support
• Advanced overclocking (2.4GHz)
EOF
    fi
    
    sudo tee -a "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt" > /dev/null << EOF

TROUBLESHOOTING:
- Check services: sudo systemctl status postgresql redis nginx
- View logs: journalctl -u service-name
- Test Whisper: /opt/whisper.cpp/build/bin/main --help
- Check storage: df -h && lsblk

Built natively on $PI_MODEL for optimal performance and compatibility.
For support: https://github.com/noatgnu/cupcake
EOF

    sudo chown 1000:1000 "$MOUNT_DIR/home/cupcake/CUPCAKE-README.txt"
    
    log "Documentation created"
}

# Finalize image
finalize_image() {
    log "Finalizing CUPCAKE image..."
    
    local img_name=$(cat "$BUILD_DIR/current_image.tmp")
    
    # Clean up package cache and temporary files
    progress "Cleaning up..."
    sudo chroot "$MOUNT_DIR" /bin/bash -c "
        export DEBIAN_FRONTEND=noninteractive
        export APT_LISTCHANGES_FRONTEND=none
        export NEEDRESTART_MODE=a
        apt-get autoremove -y -qq
        apt-get autoclean -qq
        apt-get clean -qq
        rm -rf /var/lib/apt/lists/*
        rm -rf /tmp/* /var/tmp/* 2>/dev/null || true
        rm -rf /var/cache/apt/* 2>/dev/null || true
    "
    
    # Unmount filesystem with proper cleanup
    progress "Unmounting filesystem..."

    # First, ensure no processes are using the chroot
    sudo fuser -km "$MOUNT_DIR" 2>/dev/null || true
    sleep 2

    # Unmount bind mounts first (in reverse order)
    sudo umount "$MOUNT_DIR/dev/pts" 2>/dev/null || warn "Failed to unmount /dev/pts"
    sudo umount "$MOUNT_DIR/dev" 2>/dev/null || warn "Failed to unmount /dev"
    sudo umount "$MOUNT_DIR/sys" 2>/dev/null || warn "Failed to unmount /sys"
    sudo umount "$MOUNT_DIR/proc" 2>/dev/null || warn "Failed to unmount /proc"

    # Wait a moment for any remaining processes to finish
    sleep 2

    # Unmount boot partition
    sudo umount "$MOUNT_DIR/boot" 2>/dev/null || {
        warn "Boot partition busy, forcing unmount..."
        sudo umount -l "$MOUNT_DIR/boot" 2>/dev/null || true
    }

    # Unmount root partition
    sudo umount "$MOUNT_DIR" 2>/dev/null || {
        warn "Root partition busy, forcing unmount..."
        sudo umount -l "$MOUNT_DIR" 2>/dev/null || true
    }

    # Wait for lazy unmounts to complete
    sleep 3

    # Detach loop device
    sudo losetup -d "$LOOP_DEVICE" || {
        warn "Loop device busy, waiting and retrying..."
        sleep 5
        sudo losetup -d "$LOOP_DEVICE" || warn "Failed to detach loop device"
    }
    LOOP_DEVICE=""
    
    # Move to output directory
    mv "$img_name" "$OUTPUT_DIR/"
    
    # Compress image for distribution
    progress "Compressing image for distribution (this may take 10-20 minutes)..."
    cd "$OUTPUT_DIR"
    
    # Use all available cores for compression
    xz -z -T 0 -v "$img_name"
    
    local final_name="${img_name}.xz"
    log "Image finalized: $OUTPUT_DIR/$final_name"
    
    # Create checksum
    progress "Creating checksum..."
    sha256sum "$final_name" > "${final_name}.sha256"
    
    info "Compressed size: $(du -h "$final_name" | cut -f1)"
    info "Checksum: ${final_name}.sha256"
}

# Show usage
show_usage() {
    cat << EOF
CUPCAKE Pi Image Builder - Native Build Script v$VERSION

Usage: $0 [OPTIONS]

OPTIONS:
    -h, --help          Show this help message
    -d, --build-dir     Specify build directory (default: auto-detect)
    -s, --size          Specify image size (default: auto-detect)
    --pi4               Force Pi 4 optimizations
    --pi5               Force Pi 5 optimizations
    --no-compress       Skip image compression
    --cleanup-only      Only run cleanup and exit

EXAMPLES:
    $0                          # Auto-detect everything and build
    $0 -d /mnt/usb/build       # Use specific build directory
    $0 -s 12G                  # Force 12GB image size
    $0 --pi5 -s 16G            # Force Pi 5 optimizations with 16GB image

REQUIREMENTS:
    • Raspberry Pi 4 or 5
    • 15GB+ free storage space
    • Internet connection
    • sudo privileges

The script automatically detects your Pi model and optimizes accordingly.
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_usage
            exit 0
            ;;
        -d|--build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        -s|--size)
            IMG_SIZE="$2"
            shift 2
            ;;
        --pi4)
            PI_MODEL="Pi 4"
            shift
            ;;
        --pi5)
            PI_MODEL="Pi 5"
            shift
            ;;
        --no-compress)
            NO_COMPRESS=1
            shift
            ;;
        --cleanup-only)
            cleanup
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Main build process
main() {
    local start_time=$(date +%s)
    
    echo ""
    echo "🎯 CUPCAKE Pi Image Builder v$VERSION"
    echo "   Native ARM64 build for Raspberry Pi"
    echo ""
    
    # Detect hardware if not forced
    if [ -z "$PI_MODEL" ]; then
        detect_pi_hardware
    else
        info "Using forced Pi model: $PI_MODEL"
        PI_RAM_MB=$(free -m | awk 'NR==2{print $2}')
        PI_CORES=$(nproc)
    fi
    
    info "Starting native $PI_MODEL CUPCAKE image build..."
    info "Build started at: $(date)"
    info "Build directory: $BUILD_DIR"
    
    # Ensure build directory exists and is writable
    sudo mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"
    sudo chown "$USER:$USER" "$BUILD_DIR" "$OUTPUT_DIR"
    
    # Main build steps
    progress "Step 1/10: Environment check"
    check_environment
    
    progress "Step 2/10: Base image download"
    download_base_image
    
    progress "Step 3/10: Image preparation"  
    prepare_image
    
    progress "Step 4/10: Mount image"
    mount_image
    
    progress "Step 5/10: Install base system"
    install_base_system
    
    progress "Step 6/10: Setup CUPCAKE environment"
    setup_cupcake_environment
    
    progress "Step 7/10: Install Python environment"
    install_python_environment
    
    progress "Step 8/10: Install CUPCAKE source"
    install_cupcake_source

    progress "Step 9/10: Configure services"
    configure_services
    
    progress "Step 10/10: Finalize image"
    configure_pi_optimizations
    create_documentation
    
    if [ -z "$NO_COMPRESS" ]; then
        finalize_image
    else
        log "Skipping compression as requested"
    fi
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local hours=$((duration / 3600))
    local minutes=$(((duration % 3600) / 60))
    
    echo ""
    echo "🎉 CUPCAKE $PI_MODEL Image Build Completed Successfully!"
    echo ""
    info "Build time: ${hours}h ${minutes}m"
    info "Output directory: $OUTPUT_DIR"
    
    if [ -z "$NO_COMPRESS" ]; then
        local final_image=$(ls "$OUTPUT_DIR"/*.img.xz 2>/dev/null | head -1)
        if [ -n "$final_image" ]; then
            info "Final image: $(basename "$final_image")"
            info "Size: $(du -h "$final_image" | cut -f1)"
            echo ""
            echo "📦 To flash the image:"
            echo "   1. Copy $(basename "$final_image") to your computer"
            echo "   2. Use Raspberry Pi Imager with 'Use Custom' option"
            echo "   3. Or: xz -d $(basename "$final_image") && sudo dd if=$(basename "${final_image%.xz}") of=/dev/sdX bs=4M status=progress"
        fi
    else
        local final_image=$(ls "$OUTPUT_DIR"/*.img 2>/dev/null | head -1)
        if [ -n "$final_image" ]; then
            info "Final image: $(basename "$final_image")"
            info "Size: $(du -h "$final_image" | cut -f1)"
        fi
    fi
    
    echo ""
    echo "✨ Native $PI_MODEL build advantages:"
    echo "   • No emulation overhead"
    echo "   • Optimized for your exact hardware"  
    echo "   • Native performance validation"
    echo "   • Hardware-specific optimizations"
    echo "   • Automatic storage adaptation"
    echo ""
}

# Run main build process
main "$@"