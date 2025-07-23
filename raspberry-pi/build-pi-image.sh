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

# Add PostgreSQL official APT repository (same as Docker setup)
curl https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/apt.postgresql.org.gpg > /dev/null
echo 'deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list
apt-get update

# Install PostgreSQL 14
apt-get install -y postgresql-14 postgresql-client-14 postgresql-contrib-14

# Install Redis
apt-get install -y redis-server redis-tools

# Install Nginx
apt-get install -y nginx

# Install Python and essential packages
apt-get install -y python3 python3-pip python3-venv python3-dev

# Install system dependencies for Python packages
apt-get install -y build-essential libpq-dev libffi-dev libssl-dev
apt-get install -y libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
apt-get install -y git curl wget unzip htop nvme-cli cmake pkg-config
apt-get install -y ffmpeg libavcodec-extra fail2ban ufw libopenblas-dev

# Install Node.js for frontend builds
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs npm

# Create cupcake user and setup directories
useradd -m -s /bin/bash cupcake
usermod -aG sudo cupcake
echo 'cupcake ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/cupcake

# Create CUPCAKE directories
mkdir -p /opt/cupcake/{scripts,config,logs,app,venv,data,backup,assets}
mkdir -p /var/lib/cupcake
mkdir -p /var/log/cupcake
mkdir -p /opt/whisper.cpp

# Build and install Whisper.cpp for CUPCAKE
echo "=== Setting up Whisper.cpp for CUPCAKE Pi ${PI_MODEL_NUM} ==="
cd /opt/whisper.cpp

# Clone Whisper.cpp repository (matching transcribe worker)
echo "Cloning Whisper.cpp repository..."
git clone https://github.com/ggerganov/whisper.cpp.git .

# Detect system capabilities for model selection
echo "Detecting system capabilities..."
TOTAL_RAM=$(free -m | awk 'NR==2{printf "%d", $2}')
CPU_CORES=$(nproc)
PI_MODEL_REV=$(cat /proc/cpuinfo | grep "Revision" | awk '{print $3}' | head -1)

echo "System specs: ${TOTAL_RAM}MB RAM, ${CPU_CORES} CPU cores, Pi model revision: ${PI_MODEL_REV}"

# Download models first (like transcribe worker does)
echo "Downloading Whisper models..."

# Always download tiny as fallback
./models/download-ggml-model.sh tiny.en

# Download appropriate models based on system capabilities
if [ "$TOTAL_RAM" -lt 2048 ]; then
    # Low memory systems (< 2GB) - tiny model only
    echo "Low memory system detected - using tiny model"
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-tiny.en.bin"
    THREAD_COUNT="2"
elif [ "$TOTAL_RAM" -lt 4096 ]; then
    # Medium memory systems (2-4GB) - base model
    echo "Medium memory system detected - downloading base model"
    ./models/download-ggml-model.sh base.en
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-base.en.bin"
    THREAD_COUNT="4"
else
    # High memory systems (4GB+) - small model (not medium like Docker to save space)
    echo "High memory system detected - downloading small model"
    ./models/download-ggml-model.sh small.en
    ./models/download-ggml-model.sh base.en   # backup
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-small.en.bin"
    THREAD_COUNT="6"
fi

# Build Whisper.cpp (matching transcribe worker build commands exactly)
echo "Building Whisper.cpp..."
cmake -B build
cmake --build build --config Release -j $(nproc)

# Verify the binary was built correctly
if [ ! -f "build/bin/main" ]; then
    echo "ERROR: whisper main binary not found after build!"
    exit 1
fi

echo "Build completed successfully. Binary location: $(pwd)/build/bin/main"

# Set appropriate permissions
chown -R root:root /opt/whisper.cpp
chmod +x /opt/whisper.cpp/build/bin/main

# Create environment configuration matching CUPCAKE settings.py format
echo "Creating Whisper.cpp environment configuration..."
mkdir -p /etc/environment.d
cat > /etc/environment.d/50-whisper.conf << \\EOF
# Whisper.cpp configuration for CUPCAKE (matches settings.py)
WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/main
WHISPERCPP_DEFAULT_MODEL=\${DEFAULT_MODEL}
WHISPERCPP_THREAD_COUNT=\${THREAD_COUNT}
EOF

# Create systemd environment file for services
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/whisper.conf << \\EOF
[Manager]
DefaultEnvironment=WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/main
DefaultEnvironment=WHISPERCPP_DEFAULT_MODEL=\${DEFAULT_MODEL}
DefaultEnvironment=WHISPERCPP_THREAD_COUNT=\${THREAD_COUNT}
EOF

# Test the installation
echo "Testing Whisper.cpp installation..."
if /opt/whisper.cpp/build/bin/main --help > /dev/null 2>&1; then
    echo "Whisper.cpp installation test passed"
else
    echo "WARNING: Whisper.cpp installation test failed"
fi

echo "=== Whisper.cpp setup completed ==="
echo "Binary path: /opt/whisper.cpp/build/bin/main"
echo "Default model: \${DEFAULT_MODEL}"
echo "Thread count: \${THREAD_COUNT}"
echo "Model files available:"
ls -la /opt/whisper.cpp/models/ | grep "\\.bin\$" || echo "No model files found"

# Configure PostgreSQL
systemctl enable postgresql
echo 'shared_buffers = 256MB' >> /etc/postgresql/14/main/postgresql.conf
echo 'work_mem = 8MB' >> /etc/postgresql/14/main/postgresql.conf
echo 'effective_cache_size = 1GB' >> /etc/postgresql/14/main/postgresql.conf
echo 'random_page_cost = 1.1' >> /etc/postgresql/14/main/postgresql.conf

# Start PostgreSQL to create database
service postgresql start
sudo -u postgres createuser cupcake
sudo -u postgres createdb cupcake_db -O cupcake
sudo -u postgres psql -c "ALTER USER cupcake WITH PASSWORD 'cupcake123';" || \\
    sudo -u postgres psql -c \\\$'ALTER USER cupcake WITH PASSWORD \\'cupcake123\\';'
service postgresql stop

# Configure Redis
systemctl enable redis-server
echo 'maxmemory 512mb' >> /etc/redis/redis.conf
echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf

# Configure Nginx
systemctl enable nginx
cat > /etc/nginx/sites-available/cupcake << \\EOF
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
EOF

ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Set ownership
chown -R cupcake:cupcake /opt/cupcake /var/log/cupcake /var/lib/cupcake

# Clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

CHROOT_EOF

# Create CUPCAKE systemd services
cat > "${ROOTFS_DIR}/etc/systemd/system/cupcake-web.service" << 'SERVICEEOF'
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
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-web

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Create CUPCAKE RQ worker services
for worker in transcribe export import maintenance ocr; do
    cat > "${ROOTFS_DIR}/etc/systemd/system/cupcake-${worker}.service" << SERVICEEOF
[Unit]
Description=CUPCAKE ${worker^} Worker
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
Environment=USE_OCR=True
ExecStart=/opt/cupcake/venv/bin/python manage.py rqworker ${worker}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cupcake-${worker}

[Install]
WantedBy=multi-user.target
SERVICEEOF
done

# Create first boot setup service
cat > "${ROOTFS_DIR}/etc/systemd/system/cupcake-setup.service" << 'SERVICEEOF'
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
SERVICEEOF

# Create first boot setup script
mkdir -p "${ROOTFS_DIR}/opt/cupcake/scripts"
cat > "${ROOTFS_DIR}/opt/cupcake/scripts/first-boot-setup.sh" << 'SETUPEOF'
#!/bin/bash
set -e

LOG_FILE="/var/log/cupcake/first-boot.log"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "$(date): Starting CUPCAKE first boot setup..."

cd /opt/cupcake/app

# Wait for services
while ! pg_isready -h localhost -p 5432 -U cupcake; do sleep 2; done
while ! redis-cli ping > /dev/null 2>&1; do sleep 2; done

# Activate virtual environment
source /opt/cupcake/venv/bin/activate

# Set environment variables
export DJANGO_SETTINGS_MODULE=cupcake.settings
export DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
export REDIS_URL=redis://localhost:6379/0

# Run Django setup
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

# Create admin user
python manage.py shell << PYEOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake.local', 'cupcake123')
    print('Admin user created: admin / cupcake123')
PYEOF

# Set permissions
chown -R cupcake:cupcake /opt/cupcake /var/log/cupcake /var/lib/cupcake

echo "$(date): CUPCAKE first boot setup completed successfully"
systemctl disable cupcake-setup.service
SETUPEOF

chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/first-boot-setup.sh"

# Create runtime directory config
echo 'd /var/run/cupcake 0755 cupcake cupcake -' > "${ROOTFS_DIR}/etc/tmpfiles.d/cupcake.conf"

# Create system capability detection script (from native version)
cat > "${ROOTFS_DIR}/usr/local/bin/cupcake-config" << 'CONFIGEOF'
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
        'medium': {'model': 'ggml-base.en', 'threads': 3},
        'high': {'model': 'ggml-base.en', 'threads': 4},
        'ultra': {'model': 'ggml-small.en', 'threads': 6}
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
CONFIGEOF

chmod +x "${ROOTFS_DIR}/usr/local/bin/cupcake-config"

# Enable all CUPCAKE services
on_chroot << 'ENABLEEOF'
systemctl enable cupcake-setup.service
systemctl enable cupcake-web.service
systemctl enable cupcake-transcribe.service
systemctl enable cupcake-export.service
systemctl enable cupcake-import.service
systemctl enable cupcake-maintenance.service
systemctl enable cupcake-ocr.service
ENABLEEOF

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
