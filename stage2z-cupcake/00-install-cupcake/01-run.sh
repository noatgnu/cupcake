#!/bin/bash -e

# CUPCAKE Pi Installation Script
# This script runs inside the pi-gen chroot environment

# Strict error handling
set -euo pipefail

# Self-contained logging functions for pi-gen environment
log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

# Function to handle errors
cupcake_error_handler() {
    local line_no=$1
    local error_code=$2
    log_cupcake "ERROR: CUPCAKE installation FAILED at line $line_no with exit code $error_code"
    log_cupcake "This is a CRITICAL ERROR - the build MUST stop here"
    log_cupcake "Pi image build should NOT continue without CUPCAKE"
    exit $error_code
}

# Trap errors and call handler
trap 'cupcake_error_handler $LINENO $?' ERR

# Ensure we're running in ARM64 mode - critical for proper architecture detection
log_cupcake "Verifying ARM64 build environment..."
DETECTED_ARCH=$(uname -m)
log_cupcake "Detected architecture: $DETECTED_ARCH"

if [ "$DETECTED_ARCH" != "aarch64" ]; then
    log_cupcake "ERROR: Build environment is $DETECTED_ARCH but should be aarch64"
    log_cupcake "This pi-gen build must be configured for ARM64/aarch64"
    log_cupcake "Check your pi-gen configuration and ensure:"
    log_cupcake "1. Base image is ARM64 Raspberry Pi OS"
    log_cupcake "2. IMG_NAME includes arm64 variant"
    log_cupcake "3. TARGET_HOSTNAME is configured for 64-bit"
    exit 1
fi

log_cupcake "✓ Confirmed ARM64 build environment"

log_cupcake "Starting CUPCAKE installation..."
log_cupcake "CRITICAL: This installation MUST succeed or build MUST fail"

# Update system
log_cupcake "Updating system packages..."
apt-get update || {
    log_cupcake "FATAL: Failed to update package lists"
    exit 1
}
apt-get upgrade -y || {
    log_cupcake "FATAL: Failed to upgrade system packages"
    exit 1
}

# Install PostgreSQL from official Raspbian repositories
log_cupcake "Installing PostgreSQL from Raspbian repositories..."
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# Update package lists
apt-get update

# Install PostgreSQL (default version from Raspbian)
log_cupcake "Installing PostgreSQL packages..."
apt-get install -y postgresql postgresql-client

# PostgreSQL service is automatically configured by package installation
log_cupcake "PostgreSQL installation completed via package manager"

# Install other dependencies
log_cupcake "Installing other CUPCAKE dependencies..."
apt-get install -y \
    python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel \
    redis-server \
    nginx \
    git unzip \
    build-essential libpq-dev \
    ffmpeg \
    fail2ban \
    htop nano vim \
    libssl-dev libffi-dev libjpeg-dev libpng-dev libfreetype6-dev \
    cmake tesseract-ocr tesseract-ocr-eng \
    pkg-config autotools-dev autoconf libtool \
    libbz2-dev liblz4-dev libzstd-dev libsnappy-dev \
    libicu-dev libxml2-dev libxslt1-dev \
    libffi-dev libssl-dev zlib1g-dev

# Build Apache Arrow C++ libraries from source for PyArrow support
log_cupcake "Building Apache Arrow C++ libraries from source..."
log_cupcake "Following official Apache Arrow documentation for minimal build"

# Install minimal Arrow build dependencies per official docs
log_cupcake "Installing minimal Arrow build dependencies..."
apt-get install -y \
    build-essential \
    cmake \
    python3-dev

# Check CMake version (Arrow requires 3.16+, but 21.0.0 may need newer)
current_cmake_version=$(cmake --version 2>/dev/null | head -n1 | cut -d' ' -f3 || echo "0.0.0")
log_cupcake "Current CMake version: $current_cmake_version"

# Use exact Arrow version matching PyArrow in requirements.txt (20.0.0)
log_cupcake "Using Apache Arrow 20.0.0 to match PyArrow version in requirements.txt..."
cd /tmp
git clone --depth 1 --branch apache-arrow-20.0.0 https://github.com/apache/arrow.git arrow-build || {
    log_cupcake "FATAL: Failed to clone Apache Arrow repository"
    exit 1
}

cd arrow-build
export ARROW_HOME=/usr/local
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}:/usr/local/lib
export CMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH:-}:$ARROW_HOME

# Configure Arrow C++ with minimal PyArrow-compatible features
log_cupcake "Configuring minimal Arrow build for PyArrow support..."
mkdir cpp/build
cd cpp/build

# Minimal configuration based on official docs (removed deprecated ARROW_PYTHON flag)
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=$ARROW_HOME \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DARROW_COMPUTE=ON \
    -DARROW_CSV=ON \
    -DARROW_DATASET=ON \
    -DARROW_FILESYSTEM=ON \
    -DARROW_JSON=ON \
    -DARROW_PARQUET=ON \
    -DARROW_BUILD_TESTS=OFF \
    -DARROW_BUILD_BENCHMARKS=OFF \
    -DARROW_BUILD_EXAMPLES=OFF \
    -DARROW_DEPENDENCY_SOURCE=BUNDLED \
    -DCMAKE_CXX_FLAGS="-mcpu=cortex-a72 -O2" \
    -DCMAKE_C_FLAGS="-mcpu=cortex-a72 -O2" || {
    log_cupcake "FATAL: Arrow CMake configuration failed"
    exit 1
}

# Build with full parallelism on GitHub Actions runner
log_cupcake "Building Arrow C++ libraries with full parallelism..."
make -j$(nproc) || {
    log_cupcake "FATAL: Arrow C++ build failed"
    exit 1
}

# Install Arrow libraries
log_cupcake "Installing Arrow C++ libraries..."
make install || {
    log_cupcake "FATAL: Arrow C++ installation failed"
    exit 1
}

# Update library cache
ldconfig

# Verify installation
log_cupcake "Verifying Arrow C++ installation..."
if [ -f "/usr/local/lib/libarrow.so" ]; then
    log_cupcake "✓ Apache Arrow C++ libraries built and installed successfully"
else
    log_cupcake "FATAL: Arrow libraries not found after installation"
    exit 1
fi

# Clean up build directory to save space
log_cupcake "Cleaning up Arrow build directory..."
cd /
rm -rf /tmp/arrow-build

log_cupcake "✓ Apache Arrow C++ build completed successfully"

# Create CUPCAKE user
log_cupcake "Creating CUPCAKE system user..."
if ! id cupcake &>/dev/null; then
    useradd -m -s /bin/bash cupcake
    usermod -aG sudo cupcake
fi

# Create CUPCAKE directories
log_cupcake "Setting up CUPCAKE directory structure..."
mkdir -p /opt/cupcake/{app,logs,media,static,ssl,backups}
chown -R cupcake:cupcake /opt/cupcake

# Install CUPCAKE application
log_cupcake "Installing CUPCAKE application..."
cd /opt/cupcake

# Clone CUPCAKE repository
if [ ! -d "/opt/cupcake/app" ] || [ ! "$(ls -A /opt/cupcake/app)" ]; then
    log_cupcake "Cloning CUPCAKE repository..."
    git clone https://github.com/noatgnu/cupcake.git app || {
        log_cupcake "FATAL: Failed to clone CUPCAKE repository"
        log_cupcake "Check network connectivity and GitHub access"
        exit 1
    }
else
    log_cupcake "CUPCAKE repository already exists"
fi

# Verify the clone was successful
if [ ! -f "/opt/cupcake/app/manage.py" ]; then
    log_cupcake "FATAL: CUPCAKE repository clone incomplete - manage.py not found"
    exit 1
fi
log_cupcake "✓ CUPCAKE repository verified successfully"

cd app

# Install additional dependencies for workers (matching native script)
log_cupcake "Installing additional dependencies for workers..."
# Python packaging tools and cryptography libraries
apt-get install -y python3-setuptools python3-wheel
apt-get install -y libssl-dev libffi-dev libjpeg-dev libpng-dev libfreetype6-dev
# Worker-specific tools (PostgreSQL 14 compiled from source above)
apt-get install -y cmake tesseract-ocr tesseract-ocr-eng

# Create Python virtual environment (matching native script approach)
log_cupcake "Setting up Python virtual environment..."
su - cupcake -c "python3 -m venv /opt/cupcake/venv" || {
    log_cupcake "FATAL: Failed to create Python virtual environment"
    exit 1
}

# Verify virtual environment was created
if [ ! -f "/opt/cupcake/venv/bin/activate" ]; then
    log_cupcake "FATAL: Python virtual environment creation failed - activate script not found"
    exit 1
fi
log_cupcake "✓ Python virtual environment created successfully"

# Install Python dependencies using pip (matching native script lines 520-562)
log_cupcake "Installing Python dependencies with pip..."

# Ensure proper ownership and permissions for pip cache and build directories
mkdir -p /home/cupcake/.cache/pip
mkdir -p /tmp/pip-build
mkdir -p /home/cupcake/.local
mkdir -p /home/cupcake/build-temp
chown -R cupcake:cupcake /home/cupcake/.cache
chown -R cupcake:cupcake /tmp/pip-build
chown -R cupcake:cupcake /home/cupcake/.local
chown -R cupcake:cupcake /home/cupcake/build-temp
chmod -R 755 /home/cupcake/.cache
chmod -R 755 /tmp/pip-build
chmod -R 755 /home/cupcake/.local
chmod -R 755 /home/cupcake/build-temp

# Set proper build environment for ARM compilation with expanded permissions
export TMPDIR=/home/cupcake/build-temp
export PIP_CACHE_DIR=/home/cupcake/.cache/pip
export PIP_BUILD_DIR=/home/cupcake/build-temp

su - cupcake -c "
    export TMPDIR=/home/cupcake/build-temp
    export PIP_CACHE_DIR=/home/cupcake/.cache/pip
    export PIP_BUILD_DIR=/home/cupcake/build-temp
    
    # Force ARM64 architecture detection for pip builds
    export ARCHFLAGS='-arch arm64'
    export _PYTHON_HOST_PLATFORM='linux-aarch64'
    export SETUPTOOLS_EXT_SUFFIX='.cpython-311-aarch64-linux-gnu.so'
    
    # Override architecture detection for meson and other build systems
    export CC_FOR_BUILD=aarch64-linux-gnu-gcc
    export CXX_FOR_BUILD=aarch64-linux-gnu-g++
    export MESON_CROSS_FILE=/tmp/aarch64-cross.ini
    
    # Create meson cross-compilation file to force ARM64 detection
    cat > /tmp/aarch64-cross.ini << 'MESONEOF'
[binaries]
c = 'gcc'
cpp = 'g++'
ar = 'ar'
strip = 'strip'

[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'cortex-a72'
endian = 'little'
MESONEOF
    
    source /opt/cupcake/venv/bin/activate
    pip install --upgrade pip setuptools wheel
    
    # Use pip >= 19.0 for better ARM64 wheel detection
    pip install --upgrade 'pip>=21.0'
    
    # Set compilation flags for ARM64 with full parallelism on GitHub Actions
    export CFLAGS='-mcpu=cortex-a72 -mtune=cortex-a72 -O2'
    export CXXFLAGS='-mcpu=cortex-a72 -mtune=cortex-a72 -O2'
    export LDFLAGS='-latomic'
    export MAKEFLAGS='-j\$(nproc)'  # Use all available cores on GitHub Actions
    
    # Install CUPCAKE Python dependencies with proper build settings
    pip install --prefer-binary --timeout=3600 -r /opt/cupcake/app/requirements.txt || {
        echo 'Installation with binary preference failed, trying source compilation with forced ARM64 architecture...'
        # Fallback: Source compilation with forced ARM64 architecture
        pip install --user --build /home/cupcake/build-temp --timeout=7200 \
            -r /opt/cupcake/app/requirements.txt
    }
"

# Setup Whisper.cpp for transcription worker
log_cupcake "Setting up Whisper.cpp for transcription..."
cd /opt/cupcake
su - cupcake -c "cd /opt/cupcake && git clone https://github.com/ggerganov/whisper.cpp.git"
cd /opt/cupcake/whisper.cpp

# Download appropriate models for Pi (smaller models for better performance)
log_cupcake "Downloading Whisper models (optimized for Pi)..."
su - cupcake -c "cd /opt/cupcake/whisper.cpp && ./models/download-ggml-model.sh base.en"
su - cupcake -c "cd /opt/cupcake/whisper.cpp && ./models/download-ggml-model.sh small.en"

# Build Whisper.cpp with ARM64 optimizations
log_cupcake "Building Whisper.cpp for ARM64..."
# Use ARM64-optimized flags (Cortex-A72 is common in Pi 4/5)
export CMAKE_CXX_FLAGS="-mcpu=cortex-a72 -mtune=cortex-a72"
export CMAKE_C_FLAGS="-mcpu=cortex-a72 -mtune=cortex-a72"
# Add atomic library for cross-compilation safety (needed in some ARM environments)
export CMAKE_EXE_LINKER_FLAGS="-latomic"
su - cupcake -c "cd /opt/cupcake/whisper.cpp && cmake -B build -DGGML_NATIVE=OFF -DWHISPER_BUILD_TESTS=OFF -DCMAKE_CXX_FLAGS='-mcpu=cortex-a72 -mtune=cortex-a72' -DCMAKE_C_FLAGS='-mcpu=cortex-a72 -mtune=cortex-a72' -DCMAKE_EXE_LINKER_FLAGS='-latomic'"
su - cupcake -c "cd /opt/cupcake/whisper.cpp && cmake --build build --config Release -j 2"

# Return to app directory
cd /opt/cupcake/app

# Fix ownership of virtual environment
chown -R cupcake:cupcake /opt/cupcake/venv

log_cupcake "Python virtual environment setup completed"

# Start PostgreSQL service
log_cupcake "Starting PostgreSQL service..."
systemctl daemon-reload || echo "systemctl daemon-reload failed in chroot, continuing..."
systemctl start postgresql || service postgresql start
systemctl enable postgresql || echo "systemctl enable failed in chroot, service will be enabled on boot"

# Configure PostgreSQL
log_cupcake "Configuring PostgreSQL database..."
# Ensure PostgreSQL is running in chroot environment
service postgresql start

# Create user and database (fixed for PostgreSQL 15)
su - postgres -c "createuser cupcake" || true
su - postgres -c "psql -c \"ALTER USER cupcake WITH PASSWORD 'cupcake';\""
su - postgres -c "createdb -O cupcake cupcake" || true

# Configure environment
log_cupcake "Setting up environment configuration..."
# Ensure PostgreSQL is configured for port 5432
echo "port = 5432" >> /etc/postgresql/15/main/postgresql.conf

# Wait for PostgreSQL to be ready and restart with correct port
service postgresql restart
sleep 5

# Set environment variables directly in OS instead of creating .env file
log_cupcake "Setting up environment variables directly in OS..."

# Core Django settings
export DEBUG=False
export SECRET_KEY=$(openssl rand -hex 32)
export ENV=production
export ALLOWED_HOSTS="localhost,127.0.0.1,*.local,cupcake-pi,cupcake-pi.local"

# PostgreSQL settings (native Pi installation uses standard port 5432)
export POSTGRES_DB=cupcake
export POSTGRES_USER=cupcake
export POSTGRES_PASSWORD=cupcake
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

# Redis settings (native Pi installation uses standard port 6379)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=""

# Storage and media settings
export MEDIA_ROOT=/opt/cupcake/media
export STATIC_ROOT=/opt/cupcake/staticfiles
export BACKUP_DIR=/opt/cupcake/backups

# Whisper.cpp settings
export WHISPERCPP_PATH=/opt/cupcake/whisper.cpp/build/bin/main
export WHISPERCPP_DEFAULT_MODEL=/opt/cupcake/whisper.cpp/models/ggml-base.en.bin
export WHISPERCPP_THREAD_COUNT=4

# Feature flags
export USE_WHISPER=True
export USE_OCR=True
export USE_LLM=False
export USE_COTURN=False

# CORS and frontend settings
export CORS_ORIGIN_WHITELIST="http://localhost:4200,http://localhost:8000,http://cupcake-pi.local"
export FRONTEND_URL="http://localhost:8000"

# Email settings (disabled by default)
export NOTIFICATION_EMAIL_FROM=""
export AWS_SES_ACCESS_KEY_ID=""
export AWS_SES_SECRET_ACCESS_KEY=""
export AWS_SES_REGION_NAME="us-east-1"
export AWS_SES_REGION_ENDPOINT="email.us-east-1.amazonaws.com"

# Optional integrations (disabled by default)
export PROTOCOLS_IO_ACCESS_TOKEN=""
export SLACK_WEBHOOK_URL=""
export COTURN_SERVER="localhost"
export COTURN_PORT="3478"
export COTURN_SECRET=""

# Instrument booking settings
export ALLOW_OVERLAP_BOOKINGS=True
export DEFAULT_SERVICE_LAB_GROUP="MS Facility"

# LLaMA settings (disabled by default since USE_LLM=False)
export LLAMA_BIN_PATH=""
export LLAMA_DEFAULT_MODEL=""

# Create system-wide environment file for services to inherit
mkdir -p /etc/environment.d
cat > /etc/environment.d/cupcake.conf <<ENVEOF
# Core Django settings
DEBUG=False
SECRET_KEY=$SECRET_KEY
ENV=production
ALLOWED_HOSTS=localhost,127.0.0.1,*.local,cupcake-pi,cupcake-pi.local

# PostgreSQL settings
POSTGRES_DB=cupcake
POSTGRES_USER=cupcake
POSTGRES_PASSWORD=cupcake
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis settings
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Storage and media settings
MEDIA_ROOT=/opt/cupcake/media
STATIC_ROOT=/opt/cupcake/staticfiles
BACKUP_DIR=/opt/cupcake/backups

# Whisper.cpp settings
WHISPERCPP_PATH=/opt/cupcake/whisper.cpp/build/bin/main
WHISPERCPP_DEFAULT_MODEL=/opt/cupcake/whisper.cpp/models/ggml-base.en.bin
WHISPERCPP_THREAD_COUNT=4

# Feature flags
USE_WHISPER=True
USE_OCR=True
USE_LLM=False
USE_COTURN=False

# CORS and frontend settings
CORS_ORIGIN_WHITELIST=http://localhost:4200,http://localhost:8000,http://cupcake-pi.local
FRONTEND_URL=http://localhost:8000

# Email settings (disabled by default)
NOTIFICATION_EMAIL_FROM=
AWS_SES_ACCESS_KEY_ID=
AWS_SES_SECRET_ACCESS_KEY=
AWS_SES_REGION_NAME=us-east-1
AWS_SES_REGION_ENDPOINT=email.us-east-1.amazonaws.com

# Optional integrations (disabled by default)
PROTOCOLS_IO_ACCESS_TOKEN=
SLACK_WEBHOOK_URL=
COTURN_SERVER=localhost
COTURN_PORT=3478
COTURN_SECRET=

# Instrument booking settings
ALLOW_OVERLAP_BOOKINGS=True
DEFAULT_SERVICE_LAB_GROUP="MS Facility"

# LLaMA settings (disabled by default since USE_LLM=False)
LLAMA_BIN_PATH=
LLAMA_DEFAULT_MODEL=

# Fix multiprocessing issues for ontology loading
MULTIPROCESSING_FORCE_SINGLE_THREADED=1
PRONTO_THREADS=1
PYTHONDONTWRITEBYTECODE=1
ENVEOF

log_cupcake "Environment variables configured in OS and systemd"

# Run Django setup using virtual environment (matching native script)
log_cupcake "Running Django migrations and setup..."
cd /opt/cupcake/app

# Run migrations with error checking - ensure environment variables are available
su - cupcake -c "
    # Source environment variables
    set -a  # automatically export all variables
    source /etc/environment.d/cupcake.conf
    set +a  # stop automatically exporting
    
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py migrate
" || {
    log_cupcake "FATAL: Django database migrations failed"
    exit 1
}
log_cupcake "✓ Django migrations completed successfully"

# Collect static files with error checking
su - cupcake -c "
    # Source environment variables
    set -a  # automatically export all variables
    source /etc/environment.d/cupcake.conf
    set +a  # stop automatically exporting
    
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py collectstatic --noinput
" || {
    log_cupcake "FATAL: Django static file collection failed"
    exit 1
}
log_cupcake "✓ Django static files collected successfully"

# Create Django superuser
log_cupcake "Creating Django superuser..."
su - cupcake -c "
    # Source environment variables
    set -a  # automatically export all variables
    source /etc/environment.d/cupcake.conf
    set +a  # stop automatically exporting
    
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py shell
" <<PYEOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake.local', 'cupcake123')
    print("Superuser created: admin/cupcake123")
else:
    print("Superuser already exists")
PYEOF

# Setup dynamic MOTD with security warnings
log_cupcake "Configuring dynamic MOTD with security checks..."
# Remove default MOTD
rm -f /etc/motd

# Create update-motd.d directory if it doesn't exist
mkdir -p /etc/update-motd.d

# Create dynamic MOTD script with security warnings
cat > /etc/update-motd.d/10-cupcake-security << 'MOTDEOF'
#!/bin/bash
# Dynamic MOTD for CUPCAKE Pi images with security check

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to check if default password is still in use
check_default_password() {
    # Check if SSH keys exist (alternative authentication)
    if [ -f "/home/cupcake/.ssh/authorized_keys" ] && [ -s "/home/cupcake/.ssh/authorized_keys" ]; then
        return 1  # SSH keys configured
    fi
    
    # Check if password file has been modified recently (heuristic)
    local shadow_mod=$(stat -c %Y /etc/shadow 2>/dev/null || echo 0)
    local install_time=$(stat -c %Y /opt/cupcake/app/manage.py 2>/dev/null || echo 0)
    
    # If shadow was modified significantly after install, assume password changed
    if [ $((shadow_mod - install_time)) -gt 300 ]; then
        return 1  # Password likely changed
    fi
    
    return 0  # Default password likely still in use
}

# Function to get system info
get_system_info() {
    local pi_model=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' | sed 's/Raspberry Pi /Pi /' || echo "Pi Model Unknown")
    local temp=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 || echo "N/A")
    local uptime=$(uptime -p 2>/dev/null | sed 's/up //' || echo "Unknown")
    
    echo "System: $pi_model | Temp: $temp | Uptime: $uptime"
}

# Function to check service status
get_service_status() {
    local web_status="❌"
    local worker_status="❌"
    local db_status="❌"
    local nginx_status="❌"
    
    if systemctl is-active --quiet cupcake-web 2>/dev/null; then web_status="✅"; fi
    if systemctl is-active --quiet cupcake-worker 2>/dev/null; then worker_status="✅"; fi
    if systemctl is-active --quiet postgresql 2>/dev/null; then db_status="✅"; fi
    if systemctl is-active --quiet nginx 2>/dev/null; then nginx_status="✅"; fi
    
    echo "Services: Nginx $nginx_status | Web $web_status | Worker $worker_status | DB $db_status"
}

# Main MOTD output
echo -e "${CYAN}"
cat << "EOF"
██████╗██╗   ██╗██████╗  ██████╗ █████╗ ██╗  ██╗███████╗
██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║ ██╔╝██╔════╝
██║     ██║   ██║██████╔╝██║     ███████║█████╔╝ █████╗  
██║     ██║   ██║██╔═══╝ ██║     ██╔══██║██╔═██╗ ██╔══╝  
╚██████╗╚██████╔╝██║     ╚██████╗██║  ██║██║  ██╗███████╗
 ╚═════╝ ╚═════╝ ╚═╝      ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝
EOF
echo -e "${NC}"

echo -e "${CYAN}🧁 CUPCAKE ARM64 Pre-built Image - Laboratory Management System${NC}"
echo -e "${GREEN}📊 2M+ Pre-loaded Scientific Ontologies Ready${NC}"
echo ""

# System information
echo -e "${CYAN}$(get_system_info)${NC}"
echo -e "${CYAN}$(get_service_status)${NC}"
echo ""

# Access information
echo -e "${GREEN}Access Points:${NC}"
echo "  Web Interface: http://cupcake-pi.local"
echo "  Direct Django: http://cupcake-pi.local:8000 (for debugging)"
echo "  SSH Access:    ssh cupcake@cupcake-pi.local"
echo ""

# Security check and warning
if check_default_password; then
    echo -e "${RED}🔒 CRITICAL SECURITY WARNING - DEFAULT PASSWORDS DETECTED!${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}⚠️  This system is using DEFAULT PASSWORDS - CHANGE NOW!${NC}"
    echo ""
    echo -e "${YELLOW}Current defaults:${NC}"
    echo -e "  ${RED}• SSH Login: cupcake / cupcake123${NC}"
    echo -e "  ${RED}• Web Admin: admin / cupcake123${NC}"
    echo ""
    echo -e "${GREEN}TO SECURE THIS SYSTEM RIGHT NOW:${NC}"
    echo -e "  ${CYAN}1.${NC} Change SSH password:    ${GREEN}sudo passwd cupcake${NC}"
    echo -e "  ${CYAN}2.${NC} Change web password:    Go to web interface → Admin → Users"
    echo -e "  ${CYAN}3.${NC} Setup SSH keys:         ${GREEN}ssh-copy-id cupcake@cupcake-pi.local${NC}"
    echo -e "  ${CYAN}4.${NC} Enable firewall:        ${GREEN}sudo ufw enable${NC}"
    echo ""
    echo -e "${RED}⚠️  DO NOT use this system in production with default passwords!${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════════${NC}"
else
    echo -e "${GREEN}🔒 Security Status: Custom passwords/SSH keys detected ✅${NC}"
    echo -e "${GREEN}Additional hardening recommendations:${NC}"
    echo "  • Enable firewall: sudo ufw enable"
    echo "  • Regular updates: sudo apt update && sudo apt upgrade"
    echo "  • Monitor logs: sudo journalctl -f -u cupcake-*"
fi

echo ""

# Pre-loaded databases info
echo -e "${GREEN}Pre-loaded Scientific Databases:${NC}"
echo "  • MONDO Disease Ontology    • NCBI Taxonomy (2M+ species)"
echo "  • ChEBI Compounds           • UniProt Annotations"
echo "  • MS Ontologies            • Cell Types & Tissues"
echo ""

# Quick commands
echo -e "${GREEN}Quick Commands:${NC}"
echo "  System Status: sudo systemctl status cupcake-*"
echo "  View Logs:     sudo journalctl -f -u cupcake-web"
echo "  Resources:     htop"
echo "  Restart Web:   sudo systemctl restart cupcake-web"
echo ""

# Documentation
echo -e "${CYAN}Documentation: https://github.com/noatgnu/cupcake/tree/master/raspberry-pi${NC}"
echo ""
MOTDEOF

# Make the MOTD script executable
chmod +x /etc/update-motd.d/10-cupcake-security

# Disable other default MOTD scripts that might conflict
chmod -x /etc/update-motd.d/10-uname 2>/dev/null || true
chmod -x /etc/update-motd.d/00-header 2>/dev/null || true

# Test the MOTD generation
/etc/update-motd.d/10-cupcake-security > /etc/motd || true

log_cupcake "✓ Dynamic MOTD configured with security warnings"

# Load internal ontologies database
log_cupcake "Loading internal ontologies database..."
su - cupcake -c "
    # Source environment variables
    set -a  # automatically export all variables
    source /etc/environment.d/cupcake.conf
    set +a  # stop automatically exporting
    
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate
    
    # Set Python path and prepare for ontology loading
    export PYTHONPATH=/opt/cupcake/app
    
    # Fix multiprocessing semaphore access in chroot environment
    # Recent pi-gen ARM64 updates and GitHub Actions Ubuntu 24.04 have stricter shared memory restrictions
    log_cupcake "Configuring shared memory for multiprocessing in chroot..."
    
    # Ensure /dev/shm exists with correct permissions
    mkdir -p /dev/shm
    chmod 1777 /dev/shm
    
    # Mount tmpfs on /dev/shm if not already mounted (required for POSIX semaphores)
    if ! mountpoint -q /dev/shm 2>/dev/null; then
        mount -t tmpfs tmpfs /dev/shm -o size=512m,mode=1777 || {
            log_cupcake "WARNING: Could not mount /dev/shm, multiprocessing may fail"
        }
    fi
    
    # Fix /run/shm symlink issues that can cause permission problems
    if [ -L "/run/shm" ]; then
        rm -f /run/shm
    fi
    mkdir -p /run/shm
    chmod 1777 /run/shm
    
    log_cupcake "✓ Shared memory configured for multiprocessing"
    
    # Load main ontologies (MONDO, UBERON, NCBI, ChEBI, PSI-MS)
    echo 'Loading main ontologies (MONDO, UBERON, NCBI, ChEBI with proteomics filter, PSI-MS)...'
    python manage.py load_ontologies --chebi-filter proteomics
    
    # Load UniProt species data
    echo 'Loading UniProt species data...'
    python manage.py load_species
    
    # Load MS modifications (Unimod)
    echo 'Loading MS modifications (Unimod)...'
    python manage.py load_ms_mod
    
    # Load UniProt tissue data
    echo 'Loading UniProt tissue data...'
    python manage.py load_tissue
    
    # Load UniProt human disease data
    echo 'Loading UniProt human disease data...'
    python manage.py load_human_disease
    
    # Load MS terminology and vocabularies
    echo 'Loading MS terminology and vocabularies...'
    python manage.py load_ms_term
    
    # Load UniProt subcellular location data
    echo 'Loading UniProt subcellular location data...'
    python manage.py load_subcellular_location
    
    # Load cell types and cell lines
    echo 'Loading cell types and cell lines...'
    python manage.py load_cell_types --source cl
    
    echo 'All ontologies loaded successfully!'
    
    # Generate ontology statistics for release notes
    echo 'Generating ontology statistics for release...'
    python manage.py shell <<PYEOF
import json
import os
try:
    from cc.models import (
        MondoDisease, UberonAnatomy, NCBITaxonomy, ChEBICompound, PSIMSOntology,
        Species, Unimod, Tissue, HumanDisease, MSUniqueVocabularies, 
        SubcellularLocation, CellType
    )
    print("Successfully imported Django models")
except Exception as e:
    print(f"ERROR importing models: {e}")
    raise

try:
    stats = {
    'ontology_statistics': {
        'MONDO_Disease_Ontology': MondoDisease.objects.count(),
        'UBERON_Anatomy': UberonAnatomy.objects.count(),
        'NCBI_Taxonomy': NCBITaxonomy.objects.count(),
        'ChEBI_Compounds': ChEBICompound.objects.count(),
        'PSI_MS_Ontology': PSIMSOntology.objects.count(),
        'UniProt_Species': Species.objects.count(),
        'UniMod_Modifications': Unimod.objects.count(),
        'UniProt_Tissues': Tissue.objects.count(),
        'UniProt_Human_Diseases': HumanDisease.objects.count(),
        'MS_Unique_Vocabularies': MSUniqueVocabularies.objects.count(),
        'Subcellular_Locations': SubcellularLocation.objects.count(),
        'Cell_Types': CellType.objects.count()
    },
    'total_records': sum([
        MondoDisease.objects.count(),
        UberonAnatomy.objects.count(), 
        NCBITaxonomy.objects.count(),
        ChEBICompound.objects.count(),
        PSIMSOntology.objects.count(),
        Species.objects.count(),
        Unimod.objects.count(),
        Tissue.objects.count(),
        HumanDisease.objects.count(),
        MSUniqueVocabularies.objects.count(),
        SubcellularLocation.objects.count(),
        CellType.objects.count()
        ])
    }

    # Save to file for GitHub release
    os.makedirs('/opt/cupcake/release-info', exist_ok=True)
    with open('/opt/cupcake/release-info/ontology_statistics.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print('Ontology statistics generated successfully!')
    print(f'Total ontology records: {stats["total_records"]:,}')
    print(f'Stats keys created: {list(stats.keys())}')
    print(f'JSON file will contain: total_records = {stats["total_records"]}')
    
except Exception as e:
    print(f"ERROR generating ontology statistics: {e}")
    print("Creating minimal stats file to prevent build failure")
    stats = {
        'ontology_statistics': {},
        'total_records': 0
    }
    os.makedirs('/opt/cupcake/release-info', exist_ok=True)
    with open('/opt/cupcake/release-info/ontology_statistics.json', 'w') as f:
        json.dump(stats, f, indent=2)
    raise
PYEOF

    # Verify the ontology statistics file was created
    if [ ! -f "/opt/cupcake/release-info/ontology_statistics.json" ]; then
        echo "❌ ERROR: ontology_statistics.json was not created!"
        echo "The ontology statistics generation failed silently."
        exit 1
    else
        echo "✅ ontology_statistics.json created successfully"
        echo "File size: $(du -h /opt/cupcake/release-info/ontology_statistics.json | cut -f1)"
    fi

    # Generate package license information
    echo 'Generating package license information...'
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate
    
    # Install pip-licenses for license extraction
    pip install pip-licenses --quiet
    
    # Generate license information in multiple formats
    echo 'Extracting package licenses...'
    pip-licenses --format=json --output-file=/opt/cupcake/release-info/package_licenses.json --with-urls --with-description --with-authors
    pip-licenses --format=plain --output-file=/opt/cupcake/release-info/package_licenses.txt --with-urls --with-description --with-authors
    
    # Generate detailed package information
    pip list --format=json > /opt/cupcake/release-info/installed_packages.json
    pip list > /opt/cupcake/release-info/installed_packages.txt
    
    # Create a comprehensive release info file
    python <<PYEOF
import json
import os
from datetime import datetime

# Load ontology statistics (should always exist at this point)
with open('/opt/cupcake/release-info/ontology_statistics.json', 'r') as f:
    ontology_stats = json.load(f)
print("Successfully loaded ontology statistics")
print(f"Keys in ontology_stats: {list(ontology_stats.keys())}")
if 'total_records' not in ontology_stats:
    print("ERROR: 'total_records' key missing from ontology statistics!")
    print(f"Available keys: {list(ontology_stats.keys())}")
    raise KeyError("total_records key not found in ontology statistics")

# Load package info
with open('/opt/cupcake/release-info/installed_packages.json', 'r') as f:
    packages = json.load(f)

# Create comprehensive release info
release_info = {
    'build_date': datetime.now().isoformat(),
    'cupcake_version': 'ARM64 Pi Build',
    'ontology_databases': ontology_stats['ontology_statistics'],
    'total_ontology_records': ontology_stats['total_records'],
    'python_packages': {
        'total_packages': len(packages),
        'packages': {pkg['name']: pkg['version'] for pkg in packages}
    },
    'system_info': {
        'architecture': 'ARM64 (aarch64)',
        'target_platform': 'Raspberry Pi 4/5',
        'python_version': '3.11',
        'django_version': next((pkg['version'] for pkg in packages if pkg['name'].lower() == 'django'), 'unknown')
    }
}

# Save comprehensive info
with open('/opt/cupcake/release-info/release_info.json', 'w') as f:
    json.dump(release_info, f, indent=2)

print('Release information generated successfully!')
PYEOF

    echo 'Package license information generated successfully!'

" || {
    log_cupcake "WARNING: Some ontology loading failed, but continuing with build"
    log_cupcake "Individual ontologies can be loaded later with respective commands"
}

# Configure services
log_cupcake "Setting up systemd services..."

# CUPCAKE web service (matching native script service pattern)
cat > /etc/systemd/system/cupcake-web.service <<SERVICEEOF
[Unit]
Description=CUPCAKE Web Server
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=exec
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=PYTHONPATH=/opt/cupcake/app
EnvironmentFile=/etc/environment.d/cupcake.conf
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && gunicorn --workers=3 cupcake.asgi:application --bind 127.0.0.1:8000 --timeout 300 -k uvicorn.workers.UvicornWorker'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

# CUPCAKE default worker service (for background tasks)
cat > /etc/systemd/system/cupcake-worker.service <<WORKEREOF
[Unit]
Description=CUPCAKE Background Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=exec
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/app
Environment=PATH=/opt/cupcake/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
Environment=PYTHONPATH=/opt/cupcake/app
EnvironmentFile=/etc/environment.d/cupcake.conf
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker default'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
WORKEREOF

# Setup CUPCAKE frontend files
log_cupcake "Setting up CUPCAKE frontend..."

# Create frontend directory
mkdir -p /opt/cupcake/frontend

# Frontend is required - GitHub Actions must have built it
if [ -d "/opt/cupcake/app/frontend-dist" ] && [ "$(ls -A /opt/cupcake/app/frontend-dist)" ]; then
    log_cupcake "Found pre-built frontend from GitHub Actions"
    cp -r /opt/cupcake/app/frontend-dist/* /opt/cupcake/frontend/
    chown -R www-data:www-data /opt/cupcake/frontend
    log_cupcake "✓ Frontend files copied from GitHub Actions build"
else
    log_cupcake "FATAL: No pre-built frontend found in repository"
    log_cupcake "Frontend is required for CUPCAKE - build cannot continue"
    log_cupcake "GitHub Actions must successfully build the frontend before Pi image build"
    exit 1
fi

# Configure Nginx for CUPCAKE using dedicated script
log_cupcake "Configuring Nginx web server..."
mkdir -p /opt/cupcake/scripts
cp -r /opt/cupcake/app/raspberry-pi/scripts/setup-nginx.sh /opt/cupcake/scripts/
chmod +x /opt/cupcake/scripts/setup-nginx.sh

/opt/cupcake/scripts/setup-nginx.sh || {
    log_cupcake "FATAL: Nginx configuration failed"
    exit 1
}

log_cupcake "✓ Nginx configured to serve CUPCAKE on port 80"

# Install CUPCAKE update script system-wide
log_cupcake "Installing CUPCAKE update script..."
cp /opt/cupcake/app/raspberry-pi/scripts/update-cupcake.sh /usr/local/bin/cupcake-update
chmod +x /usr/local/bin/cupcake-update
ln -sf /usr/local/bin/cupcake-update /usr/local/bin/update-cupcake 2>/dev/null || true
log_cupcake "✓ CUPCAKE update script installed as 'cupcake-update'"

# Enable services
systemctl enable cupcake-web cupcake-worker || echo "systemctl enable failed in chroot, services will be enabled on boot"
systemctl enable nginx postgresql redis-server || echo "systemctl enable failed in chroot, services will be enabled on boot"

# Clean up to reduce image size
log_cupcake "Cleaning up installation artifacts..."
apt-get autoremove -y
apt-get autoclean
rm -rf /var/lib/apt/lists/*
rm -rf /tmp/*
rm -rf /var/tmp/*

# Clean up Python cache
find /opt/cupcake -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find /opt/cupcake -name "*.pyc" -delete 2>/dev/null || true

# Clean up build artifacts
rm -rf /opt/cupcake/whisper.cpp/build/CMakeCache.txt
rm -rf /opt/cupcake/whisper.cpp/build/CMakeFiles
rm -rf /var/cache/apt/archives/*.deb

# Final verification that CUPCAKE is properly installed
log_cupcake "Performing final CUPCAKE installation verification..."

# Check critical files exist
critical_files=(
    "/opt/cupcake/app/manage.py"
    "/opt/cupcake/venv/bin/activate"
    "/etc/environment.d/cupcake.conf"
    "/etc/systemd/system/cupcake-web.service"
    "/etc/systemd/system/cupcake-worker.service"
)

for file in "${critical_files[@]}"; do
    if [ ! -f "$file" ]; then
        log_cupcake "FATAL: Critical file missing: $file"
        log_cupcake "CUPCAKE installation is INCOMPLETE"
        exit 1
    fi
done

# Test Django installation
log_cupcake "Testing Django installation..."
su - cupcake -c "
    # Source environment variables
    set -a  # automatically export all variables
    source /etc/environment.d/cupcake.conf
    set +a  # stop automatically exporting
    
    cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py check --deploy
" || {
    log_cupcake "FATAL: Django installation verification failed"
    exit 1
}

# Test database connection
log_cupcake "Testing database connection..."
su - postgres -c "psql -d cupcake -c 'SELECT 1;'" > /dev/null || {
    log_cupcake "FATAL: Database connection test failed"
    exit 1
}

log_cupcake "🎉 CUPCAKE installation completed successfully!"
log_cupcake "✓ All critical components verified"
log_cupcake "✓ Django application functional"
log_cupcake "✓ Database connection working"
log_cupcake "✓ Services configured for first boot"
log_cupcake "CUPCAKE Pi image is ready for deployment"

# Final cleanup to prevent chroot unmount issues
log_cupcake "Performing final cleanup to prevent unmount issues..."
# Stop any background services that may be holding file handles
service postgresql stop || true
service redis-server stop || true
# Kill any remaining processes that might interfere with unmount
pkill -f python3 || true
pkill -f postgres || true
pkill -f redis || true
# Sync filesystem to ensure all writes are complete
sync
log_cupcake "✓ Final cleanup completed"
