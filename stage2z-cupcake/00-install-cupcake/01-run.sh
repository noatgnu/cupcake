#!/bin/bash -e

# CUPCAKE Pi Installation Script
# This script runs inside the pi-gen chroot environment

# Strict error handling
set -euo pipefail

# Self-contained logging functions for pi-gen environment
log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

# IMMEDIATE FRONTEND VALIDATION - Fail fast if frontend is missing
log_cupcake "=== FRONTEND VALIDATION ==="
log_cupcake "Current working directory: $(pwd)"
log_cupcake "Script location: $0"

# Search for frontend-dist directory anywhere in /tmp
FRONTEND_SEARCH_RESULTS=$(find /tmp -name "frontend-dist" -type d 2>/dev/null || true)

if [ -z "$FRONTEND_SEARCH_RESULTS" ]; then
    log_cupcake "FATAL: No frontend-dist directory found anywhere in /tmp"
    log_cupcake "GitHub Actions must build the frontend before pi-gen starts"
    exit 1
fi

# Check each found frontend-dist directory
VALID_FRONTEND=""
for frontend_dir in $FRONTEND_SEARCH_RESULTS; do
    log_cupcake "Found frontend-dist at: $frontend_dir"
    if [ -n "$(ls -A $frontend_dir 2>/dev/null)" ]; then
        log_cupcake "  ✓ Contains $(ls $frontend_dir | wc -l) files"
        VALID_FRONTEND="$frontend_dir"
        break
    else
        log_cupcake "  ✗ Directory is empty"
    fi
done

if [ -z "$VALID_FRONTEND" ]; then
    log_cupcake "FATAL: Found frontend-dist directories but all are empty"
    log_cupcake "GitHub Actions frontend build failed or was not copied properly"
    exit 1
fi

log_cupcake "✓ Frontend validation passed: $VALID_FRONTEND"
export CUPCAKE_FRONTEND_PATH="$VALID_FRONTEND"

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

# Build with full parallelism on GitHub Actions runner - with retry for network issues
log_cupcake "Building Arrow C++ libraries with full parallelism..."

# Retry logic for network-dependent Arrow build
for attempt in 1 2 3; do
    log_cupcake "Arrow build attempt $attempt/3..."
    
    if make -j$(nproc); then
        log_cupcake "✓ Arrow build succeeded on attempt $attempt"
        break
    else
        if [ $attempt -eq 3 ]; then
            log_cupcake "FATAL: Arrow C++ build failed after 3 attempts"
            log_cupcake "This is likely due to network issues downloading dependencies (utf8proc, re2, etc.)"
            exit 1
        else
            log_cupcake "Arrow build attempt $attempt failed, retrying in 30 seconds..."
            sleep 30
            # Clean up partial downloads that might be corrupted
            find . -name "*-download" -type f -delete 2>/dev/null || true
        fi
    fi
done

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

# Create scripts directory and copy scripts
mkdir -p /opt/cupcake/scripts
cp /opt/cupcake/app/stage2z-cupcake/00-install-cupcake/scripts/*.sh /opt/cupcake/scripts/
chmod +x /opt/cupcake/scripts/*.sh
chown cupcake:cupcake /opt/cupcake/scripts/*.sh

# Setup shared memory for multiprocessing
log_cupcake "Setting up shared memory for multiprocessing..."
su - cupcake -c "/opt/cupcake/scripts/setup-shared-memory.sh" || {
    log_cupcake "FATAL: Shared memory setup failed"
    exit 1
}

# Load ontologies
log_cupcake "Loading ontologies and databases..."
su - cupcake -c "/opt/cupcake/scripts/load-ontologies.sh" || {
    log_cupcake "FATAL: Ontology loading failed"
    exit 1
}

# Generate ontology statistics
log_cupcake "Generating ontology statistics..."
su - cupcake -c "/opt/cupcake/scripts/generate-stats.sh" || {
    log_cupcake "FATAL: Statistics generation failed"
    exit 1
}

# Generate package license information
log_cupcake "Generating package license information..."
su - cupcake -c "/opt/cupcake/scripts/generate-licenses.sh" || {
    log_cupcake "FATAL: License generation failed"
    exit 1
}

# Create comprehensive release info
log_cupcake "Creating comprehensive release info..."
su - cupcake -c "/opt/cupcake/scripts/generate-release-info.sh" || {
    log_cupcake "FATAL: Release info generation failed"
    exit 1
}

log_cupcake "✓ All ontologies and release information generated successfully"

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

# Frontend setup using validated path from beginning of script
log_cupcake "Setting up frontend from validated location: $CUPCAKE_FRONTEND_PATH"
cp -r $CUPCAKE_FRONTEND_PATH/* /opt/cupcake/frontend/
chown -R www-data:www-data /opt/cupcake/frontend
log_cupcake "✓ Frontend files copied successfully"

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
