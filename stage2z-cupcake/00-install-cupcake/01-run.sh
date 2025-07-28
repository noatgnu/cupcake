#!/bin/bash -e

# CUPCAKE Pi Installation Script
# This script runs inside the pi-gen chroot environment

# Strict error handling
set -euo pipefail

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

# Self-contained logging functions for pi-gen environment
log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

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

# Build with single thread to avoid memory issues using make instead of ninja
log_cupcake "Building Arrow C++ libraries (this may take 30-60 minutes)..."
make -j1 || {
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
chown -R cupcake:cupcake /home/cupcake/.cache
chown -R cupcake:cupcake /tmp/pip-build
chmod -R 755 /home/cupcake/.cache
chmod -R 755 /tmp/pip-build

# Set proper build environment for ARM compilation
export TMPDIR=/tmp/pip-build
export PIP_CACHE_DIR=/home/cupcake/.cache/pip
export PIP_BUILD_DIR=/tmp/pip-build

su - cupcake -c "
    export TMPDIR=/tmp/pip-build
    export PIP_CACHE_DIR=/home/cupcake/.cache/pip
    export PIP_BUILD_DIR=/tmp/pip-build
    
    source /opt/cupcake/venv/bin/activate
    pip install --upgrade pip setuptools wheel
    
    # Use pip >= 19.0 for better ARM64 wheel detection
    pip install --upgrade 'pip>=21.0'
    
    # Set memory-efficient compilation flags for ARM64 
    export CFLAGS='-mcpu=cortex-a72 -mtune=cortex-a72 -O1'
    export CXXFLAGS='-mcpu=cortex-a72 -mtune=cortex-a72 -O1'
    export LDFLAGS='-latomic'
    export MAKEFLAGS='-j1'  # Single-threaded compilation to avoid memory issues
    
    # Install CUPCAKE Python dependencies with optimized settings for ARM64
    # Use --prefer-binary to prioritize pre-built wheels for duckdb and pyarrow
    pip install --prefer-binary --only-binary=:all: --timeout=3600 \
        -r /opt/cupcake/app/requirements.txt || {
        log_cupcake 'Binary wheel installation failed, falling back to source compilation...'
        # Fallback: Allow source compilation with extended timeout
        pip install --timeout=7200 -r /opt/cupcake/app/requirements.txt
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
systemctl daemon-reload
systemctl start postgresql
systemctl enable postgresql

# Configure PostgreSQL
log_cupcake "Configuring PostgreSQL database..."
su - postgres -c "createuser -D -A -P cupcake" || true
su - postgres -c "createdb -O cupcake cupcake" || true

# Configure environment
log_cupcake "Setting up environment configuration..."
cat > /opt/cupcake/app/.env <<ENVEOF
DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql://cupcake:cupcake@localhost:5432/cupcake
REDIS_URL=redis://localhost:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1,*.local
MEDIA_ROOT=/opt/cupcake/media
STATIC_ROOT=/opt/cupcake/static
LOG_LEVEL=INFO
ENVEOF

chown cupcake:cupcake /opt/cupcake/app/.env

# Run Django setup using virtual environment (matching native script)
log_cupcake "Running Django migrations and setup..."
cd /opt/cupcake/app

# Run migrations with error checking
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py migrate" || {
    log_cupcake "FATAL: Django database migrations failed"
    exit 1
}
log_cupcake "✓ Django migrations completed successfully"

# Collect static files with error checking
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py collectstatic --noinput" || {
    log_cupcake "FATAL: Django static file collection failed"
    exit 1
}
log_cupcake "✓ Django static files collected successfully"

# Create Django superuser
log_cupcake "Creating Django superuser..."
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py shell" <<PYEOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake.local', 'cupcake123')
    print("Superuser created: admin/cupcake123")
else:
    print("Superuser already exists")
PYEOF

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
Environment=DATABASE_URL=postgresql://cupcake:cupcake@localhost:5432/cupcake
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
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
Environment=DATABASE_URL=postgresql://cupcake:cupcake@localhost:5432/cupcake
Environment=REDIS_URL=redis://localhost:6379/0
Environment=PYTHONPATH=/opt/cupcake/app
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker default'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
WORKEREOF

# Enable services
systemctl enable cupcake-web cupcake-worker
systemctl enable nginx postgresql redis-server

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
    "/opt/cupcake/app/.env"
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
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py check --deploy" || {
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
