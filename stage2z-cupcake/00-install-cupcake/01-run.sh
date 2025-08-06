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

# Update system and install essential dependencies first
log_cupcake "Updating system packages..."
apt-get update || {
    log_cupcake "FATAL: Failed to update package lists"
    exit 1
}
apt-get upgrade -y || {
    log_cupcake "FATAL: Failed to upgrade system packages"
    exit 1
}

# Install essential tools needed for frontend build and general installation
log_cupcake "Installing essential tools for installation..."
apt-get install -y git curl build-essential

# Install GitHub CLI inside chroot for artifact downloading
log_cupcake "Installing GitHub CLI for artifact downloading..."
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt-get update
apt-get install -y gh

# Verify GitHub CLI installation
if command -v gh >/dev/null 2>&1; then
    log_cupcake "✓ GitHub CLI installed successfully: $(gh --version | head -1)"
else
    log_cupcake "❌ GitHub CLI installation failed"
fi

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

# NOW DO FRONTEND CHECK AND BUILD - After all dependencies are installed
log_cupcake "=== FRONTEND VALIDATION AND BUILD ==="
log_cupcake "Checking if frontend files are available, building if necessary..."

# Check for GitHub Actions pre-built frontend in the exact location it should be
SCRIPT_DIR="$(dirname "$0")"
GITHUB_ACTIONS_FRONTEND="$SCRIPT_DIR/frontend-dist"

log_cupcake "Checking for GitHub Actions pre-built frontend at: $GITHUB_ACTIONS_FRONTEND"
log_cupcake "Script directory: $SCRIPT_DIR"
log_cupcake "Current working directory: $(pwd)"

# List contents of script directory for debugging
log_cupcake "Contents of script directory:"
ls -la "$SCRIPT_DIR" | while read line; do log_cupcake "  $line"; done

FRONTEND_EXISTS=false
if [ -d "$GITHUB_ACTIONS_FRONTEND" ] && [ -n "$(ls -A "$GITHUB_ACTIONS_FRONTEND" 2>/dev/null)" ]; then
    log_cupcake "✓ Found GitHub Actions pre-built frontend with $(ls "$GITHUB_ACTIONS_FRONTEND" | wc -l) files"
    FRONTEND_EXISTS=true
else
    log_cupcake "❌ GitHub Actions pre-built frontend not found or empty"
    log_cupcake "Directory exists: $([ -d "$GITHUB_ACTIONS_FRONTEND" ] && echo "YES" || echo "NO")"
    if [ -d "$GITHUB_ACTIONS_FRONTEND" ]; then
        log_cupcake "Directory is empty: $([ -z "$(ls -A "$GITHUB_ACTIONS_FRONTEND" 2>/dev/null)" ] && echo "YES" || echo "NO")"
    fi
fi

# If no frontend found, try to download it from GitHub Actions
if [ "$FRONTEND_EXISTS" = false ]; then
    log_cupcake "No pre-built frontend found - attempting to download from GitHub releases"

    # First try to download from GitHub releases (more reliable in chroot)
    if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
        log_cupcake "Attempting to download frontend from GitHub releases..."

        # Create temporary directory for download
        TEMP_DOWNLOAD_DIR=$(mktemp -d)
        cd "$TEMP_DOWNLOAD_DIR"

        # Try to get the specific release version or use a specific tag
        REPO_OWNER="noatgnu"
        REPO_NAME="cupcake"
        DOWNLOAD_URL=""

        # Determine the version to use for frontend download
        FRONTEND_VERSION=""

        # Priority 1: Use explicitly set CUPCAKE_VERSION environment variable
        if [ -n "${CUPCAKE_VERSION:-}" ]; then
            FRONTEND_VERSION="$CUPCAKE_VERSION"
            log_cupcake "Using explicit CUPCAKE_VERSION: $FRONTEND_VERSION"
        # Priority 2: Use GitHub ref if we're in GitHub Actions
        elif [ -n "${GITHUB_REF:-}" ]; then
            # Extract version from GitHub ref (e.g., refs/tags/v1.2.3 -> v1.2.3)
            if [[ "$GITHUB_REF" =~ refs/tags/(.*) ]]; then
                FRONTEND_VERSION="${BASH_REMATCH[1]}"
                log_cupcake "Using GitHub tag from GITHUB_REF: $FRONTEND_VERSION"
            elif [[ "$GITHUB_REF" =~ refs/heads/(.*) ]]; then
                # For branch builds, try to get the latest tag
                BRANCH_NAME="${BASH_REMATCH[1]}"
                log_cupcake "Building from branch '$BRANCH_NAME', attempting to get latest tag..."
                # Try to get the latest tag from the current repository
                if command -v git >/dev/null 2>&1 && [ -d "/opt/cupcake/app/.git" ]; then
                    cd /opt/cupcake/app
                    FRONTEND_VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
                    if [ -n "$FRONTEND_VERSION" ]; then
                        log_cupcake "Found latest git tag: $FRONTEND_VERSION"
                    else
                        log_cupcake "No git tags found, will use latest release"
                    fi
                fi
            fi
        # Priority 3: Try to get version from the cloned repository
        elif command -v git >/dev/null 2>&1 && [ -d "/opt/cupcake/app/.git" ]; then
            cd /opt/cupcake/app
            FRONTEND_VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
            if [ -n "$FRONTEND_VERSION" ]; then
                log_cupcake "Using latest git tag from repository: $FRONTEND_VERSION"
            else
                log_cupcake "No git tags found in repository"
            fi
        fi

        # Build download URL
        if [ -n "$FRONTEND_VERSION" ]; then
            DOWNLOAD_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download/${FRONTEND_VERSION}/cupcake-frontend-pi.tar.gz"
            log_cupcake "Trying version-specific download: ${FRONTEND_VERSION}"
            log_cupcake "Download URL: $DOWNLOAD_URL"
        else
            # Only fall back to latest if no version could be determined
            DOWNLOAD_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download/cupcake-frontend-pi.tar.gz"
            log_cupcake "WARNING: Could not determine version, falling back to latest release"
            log_cupcake "This should not happen in GitHub Actions builds"
        fi

        # Download using curl or wget
        DOWNLOAD_SUCCESS=false
        if command -v curl >/dev/null 2>&1; then
            log_cupcake "Attempting download with curl: $DOWNLOAD_URL"
            if curl -L -f -o cupcake-frontend-pi.tar.gz "$DOWNLOAD_URL"; then
                DOWNLOAD_SUCCESS=true
                log_cupcake "✅ Successfully downloaded frontend using curl"
            else
                log_cupcake "❌ Failed to download frontend using curl (exit code: $?)"
            fi
        elif command -v wget >/dev/null 2>&1; then
            log_cupcake "Attempting download with wget: $DOWNLOAD_URL"
            if wget -O cupcake-frontend-pi.tar.gz "$DOWNLOAD_URL"; then
                DOWNLOAD_SUCCESS=true
                log_cupcake "✅ Successfully downloaded frontend using wget"
            else
                log_cupcake "❌ Failed to download frontend using wget (exit code: $?)"
            fi
        fi

        # If download succeeded, extract the frontend
        if [ "$DOWNLOAD_SUCCESS" = true ] && [ -f "cupcake-frontend-pi.tar.gz" ]; then
            # Verify the downloaded file is not empty or an error page
            if [ -s "cupcake-frontend-pi.tar.gz" ]; then
                mkdir -p "$SCRIPT_DIR/frontend-dist"
                if tar -xzf cupcake-frontend-pi.tar.gz -C "$SCRIPT_DIR/frontend-dist/" 2>/dev/null; then
                    # Verify extraction was successful
                    if [ -d "$SCRIPT_DIR/frontend-dist" ] && [ -n "$(ls -A "$SCRIPT_DIR/frontend-dist" 2>/dev/null)" ]; then
                        log_cupcake "✅ Frontend files extracted successfully from GitHub releases"
                        FRONTEND_EXISTS=true
                    else
                        log_cupcake "❌ Failed to extract frontend files from download"
                    fi
                else
                    log_cupcake "❌ Failed to extract downloaded frontend archive"
                fi
            else
                log_cupcake "❌ Downloaded file is empty or invalid"
            fi
        fi

        # Cleanup temporary directory
        cd /
        rm -rf "$TEMP_DOWNLOAD_DIR"
    fi

    # Fallback: Try GitHub Actions artifact download if release download failed
    if [ "$FRONTEND_EXISTS" = false ]; then
        log_cupcake "GitHub releases download failed - trying GitHub Actions fallback..."

        # Check if we have GitHub CLI available and necessary environment variables
        if command -v gh >/dev/null 2>&1 && [ -n "${GITHUB_RUN_ID:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
            log_cupcake "Attempting to download frontend artifact from current GitHub Actions run..."

            # Create temporary directory for download
            TEMP_DOWNLOAD_DIR=$(mktemp -d)
            cd "$TEMP_DOWNLOAD_DIR"

            # Download the frontend artifact from the current GitHub Actions run
            if gh run download "$GITHUB_RUN_ID" --name cupcake-frontend-shared 2>/dev/null; then
                log_cupcake "✅ Successfully downloaded frontend artifact from GitHub Actions"

                # Extract the frontend files to the script directory
                if [ -f "cupcake-frontend-pi.tar.gz" ]; then
                    mkdir -p "$SCRIPT_DIR/frontend-dist"
                    tar -xzf cupcake-frontend-pi.tar.gz -C "$SCRIPT_DIR/frontend-dist/"

                    # Verify extraction was successful
                    if [ -d "$SCRIPT_DIR/frontend-dist" ] && [ -n "$(ls -A "$SCRIPT_DIR/frontend-dist" 2>/dev/null)" ]; then
                        log_cupcake "✅ Frontend files extracted successfully from GitHub Actions"
                        FRONTEND_EXISTS=true
                    else
                        log_cupcake "❌ Failed to extract frontend files"
                    fi
                else
                    log_cupcake "❌ Downloaded artifact does not contain cupcake-frontend-pi.tar.gz"
                fi
            else
                log_cupcake "❌ Failed to download frontend artifact from GitHub Actions"
            fi

            # Cleanup temporary directory
            cd /
            rm -rf "$TEMP_DOWNLOAD_DIR"
        else
            log_cupcake "GitHub CLI not available or missing environment variables for artifact download"
            log_cupcake "GITHUB_RUN_ID: ${GITHUB_RUN_ID:-not_set}"
            log_cupcake "GITHUB_TOKEN: ${GITHUB_TOKEN:+set}"
            log_cupcake "gh command available: $(command -v gh >/dev/null 2>&1 && echo "yes" || echo "no")"
        fi
    fi
fi

# If still no frontend found after download attempt, FAIL THE BUILD
if [ "$FRONTEND_EXISTS" = false ]; then
    log_cupcake "FATAL: No frontend found and unable to download from GitHub Actions"
    log_cupcake "This could be due to:"
    log_cupcake "1. Frontend artifact not created by GitHub Actions build-frontend job"
    log_cupcake "2. GitHub CLI not available inside chroot environment"
    log_cupcake "3. Missing GitHub authentication token"
    log_cupcake "4. Network connectivity issues inside chroot"
    log_cupcake ""
    log_cupcake "Please ensure:"
    log_cupcake "- The build-frontend job completes successfully"
    log_cupcake "- GitHub CLI is installed in the pi-gen environment"
    log_cupcake "- GITHUB_TOKEN is passed to the chroot environment"
    exit 1
else
    log_cupcake "✅ Pre-built frontend available - proceeding with installation"
fi


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

# FRONTEND VALIDATION - Now that repository is cloned
log_cupcake "=== FRONTEND VALIDATION ==="
log_cupcake "Looking for frontend files in repository..."

# First, do a comprehensive search for any frontend-dist directories
log_cupcake "Searching for all frontend-dist directories in the system..."
FOUND_FRONTEND_DIRS=$(find / -name "frontend-dist" -type d 2>/dev/null | head -20)
if [ -n "$FOUND_FRONTEND_DIRS" ]; then
    log_cupcake "Found frontend-dist directories:"
    echo "$FOUND_FRONTEND_DIRS" | while read -r dir; do
        if [ -d "$dir" ]; then
            file_count=$(ls -A "$dir" 2>/dev/null | wc -l)
            log_cupcake "  - $dir (files: $file_count)"
        fi
    done
else
    log_cupcake "No frontend-dist directories found anywhere in the system"
fi

# Also search for other common frontend build directories
log_cupcake "Searching for other common frontend directories..."
OTHER_FRONTEND_DIRS=$(find /opt/cupcake/app -name "dist" -o -name "build" -o -name "frontend" 2>/dev/null | head -10)
if [ -n "$OTHER_FRONTEND_DIRS" ]; then
    log_cupcake "Found other potential frontend directories:"
    echo "$OTHER_FRONTEND_DIRS" | while read -r dir; do
        if [ -d "$dir" ]; then
            file_count=$(ls -A "$dir" 2>/dev/null | wc -l)
            log_cupcake "  - $dir (files: $file_count)"
        fi
    done
else
    log_cupcake "No other frontend directories found in /opt/cupcake/app"
fi

# Try multiple possible locations for frontend files
FRONTEND_PATHS=(
    "/opt/cupcake/frontend-built"  # Early emergency build location
    "/opt/cupcake/app/frontend-dist"
    "/opt/cupcake/app/dist"
    "/opt/cupcake/app/build"
    "/opt/cupcake/app/stage2z-cupcake/00-install-cupcake/frontend-dist"
    "$(dirname "$0")/frontend-dist"  # Look relative to script location (GitHub Actions copies here)
    "/tmp/stage2a/00-install-cupcake/frontend-dist"  # GitHub Actions stage2a location
    "./frontend-dist"  # Relative path in case script is run from within the stage directory
    "../frontend-dist"  # One level up from script directory
)

VALID_FRONTEND=""
for FRONTEND_PATH in "${FRONTEND_PATHS[@]}"; do
    log_cupcake "Checking: $FRONTEND_PATH"
    if [ -d "$FRONTEND_PATH" ] && [ -n "$(ls -A $FRONTEND_PATH 2>/dev/null)" ]; then
        log_cupcake "  ✓ Found frontend with $(ls $FRONTEND_PATH | wc -l) files"
        VALID_FRONTEND="$FRONTEND_PATH"
        break
    else
        log_cupcake "  ❌ Not found or empty"
    fi
done

if [ -z "$VALID_FRONTEND" ]; then
    log_cupcake "FATAL: No frontend found in any expected location"
    log_cupcake "This should not happen since we build frontend at the start if needed"
    log_cupcake "Searched locations:"
    for path in "${FRONTEND_PATHS[@]}"; do
        log_cupcake "  - $path (exists: $([ -d "$path" ] && echo "YES" || echo "NO"))"
    done

    # Show the complete directory structure of the repository for debugging
    log_cupcake "Complete directory structure of /opt/cupcake/app:"
    find /opt/cupcake/app -type d | head -50 | while read -r dir; do
        log_cupcake "  DIR: $dir"
    done

    log_cupcake "Files in repository root:"
    ls -la /opt/cupcake/app/ | while read -r line; do
        log_cupcake "  $line"
    done

    log_cupcake "This is unexpected - frontend should have been built during early setup"
    exit 1
fi
export CUPCAKE_FRONTEND_PATH="$VALID_FRONTEND"

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

# CUPCAKE boot service (runs enable-cupcake-services.sh on every boot)
cat > /etc/systemd/system/cupcake-boot.service <<BOOTEOF
[Unit]
Description=CUPCAKE Service Starter
After=network.target postgresql.service redis-server.service
Before=nginx.service cupcake-web.service cupcake-worker.service
DefaultDependencies=false

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/enable-cupcake-services.sh
RemainAfterExit=true
TimeoutSec=300
User=root
StandardOutput=journal
StandardError=journal
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
BOOTEOF

# Enable the boot service
systemctl enable cupcake-boot || echo "systemctl enable failed in chroot, service will be enabled on boot"

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

# Run the enable-cupcake-services script to create the ready flag
log_cupcake "Running enable-cupcake-services to create ready flag..."
cp -r /opt/cupcake/app/raspberry-pi/scripts/enable-cupcake-services.sh /opt/cupcake/scripts/
chmod +x /opt/cupcake/scripts/enable-cupcake-services.sh
/opt/cupcake/scripts/enable-cupcake-services.sh || {
    log_cupcake "FATAL: Enable cupcake services failed"
    exit 1
}
log_cupcake "✓ CUPCAKE services enabled and ready flag created"

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
