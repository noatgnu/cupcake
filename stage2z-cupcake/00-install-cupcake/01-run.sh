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

# Add PostgreSQL 14 repository (required for correct version)
log_cupcake "Adding PostgreSQL 14 repository..."
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# Install prerequisites first
apt-get install -y ca-certificates gnupg curl wget

# Add PostgreSQL signing key and repository
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg

# Add repository for Bookworm
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list

# Update package lists
apt-get update

# Install PostgreSQL 14 and other dependencies
log_cupcake "Installing CUPCAKE dependencies with PostgreSQL 14..."
apt-get install -y \
    python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel \
    postgresql-14 postgresql-client-14 postgresql-contrib-14 \
    redis-server \
    nginx \
    git unzip \
    build-essential libpq-dev \
    ffmpeg \
    fail2ban \
    htop nano vim \
    libssl-dev libffi-dev libjpeg-dev libpng-dev libfreetype6-dev \
    cmake tesseract-ocr tesseract-ocr-eng

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
# Worker-specific tools (postgresql-client-14 already installed above)
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
su - cupcake -c "
    source /opt/cupcake/venv/bin/activate
    pip install --upgrade pip setuptools wheel
    
    # Install CUPCAKE Python dependencies (matching native script exact packages)
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

# Build Whisper.cpp
log_cupcake "Building Whisper.cpp..."
su - cupcake -c "cd /opt/cupcake/whisper.cpp && cmake -B build"
su - cupcake -c "cd /opt/cupcake/whisper.cpp && cmake --build build --config Release -j 2"

# Return to app directory
cd /opt/cupcake/app

# Fix ownership of virtual environment
chown -R cupcake:cupcake /opt/cupcake/venv

log_cupcake "Python virtual environment setup completed"

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
systemctl enable nginx postgresql-14 redis-server

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