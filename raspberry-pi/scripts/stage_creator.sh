#!/bin/bash

# CUPCAKE Pi Build - Stage Creator
# Creates the custom CUPCAKE stage for pi-gen

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

create_custom_stage() {
    log "Creating custom CUPCAKE stage..."
    
    # Use stage name that comes after stage2 (lite) alphabetically  
    local stage_dir="$PI_GEN_DIR/stage2z-cupcake"
    
    # Create clean stage directory
    rm -rf "$stage_dir"
    mkdir -p "$stage_dir/00-install-cupcake"
    local files_dir="$stage_dir/00-install-cupcake/files"
    mkdir -p "$files_dir"
    
    # Copy stage configuration if it exists
    if [ -d "$CONFIG_DIR/pi-gen-config/stage-cupcake" ]; then
        cp "$CONFIG_DIR/pi-gen-config/stage-cupcake/"* "$stage_dir/" 2>/dev/null || true
    fi
    
    # Ensure stage control files exist
    touch "$stage_dir/EXPORT_IMAGE"
    
    # Create stage info file
    create_stage_info "$stage_dir"
    
    # Create prerun script
    create_prerun_script "$stage_dir"
    
    # Create main installation script
    create_install_script "$stage_dir" "$files_dir"
    
    # Create boot configuration scripts
    create_boot_config "$stage_dir"
    
    log "Custom CUPCAKE stage created with $PI_MODEL optimizations"
}

create_stage_info() {
    local stage_dir="$1"
    
    cat > "$stage_dir/EXPORT_NOOBS" <<EOF
CUPCAKE-${PI_MODEL^}-${IMAGE_VERSION}
EOF

    cat > "$stage_dir/EXPORT_IMAGE" <<EOF
IMG_SUFFIX=-${PI_MODEL}
EOF
}

create_prerun_script() {
    local stage_dir="$1"
    
    cat > "$stage_dir/prerun.sh" <<'EOF'
#!/bin/bash -e

# Pi-gen prerun script for CUPCAKE stage
# This script runs before the stage execution

# Use copy_previous instead of validating ROOTFS_DIR
copy_previous

log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

log_cupcake "CUPCAKE stage prerun completed"
EOF
    
    chmod +x "$stage_dir/prerun.sh"
}

create_install_script() {
    local stage_dir="$1"
    local files_dir="$2"
    
    log "Creating CUPCAKE installation script..."
    
    # Source other setup scripts to get their functions
    source "$(dirname "${BASH_SOURCE[0]}")/frontend_setup.sh"
    source "$(dirname "${BASH_SOURCE[0]}")/ssl_setup.sh"
    
    # Setup frontend
    setup_frontend "$files_dir"
    
    # Create the main installation script
    cat > "$stage_dir/00-install-cupcake/01-run.sh" <<'EOF'
#!/bin/bash -e

# CUPCAKE Pi Installation Script
# This script runs inside the pi-gen chroot environment

# Self-contained logging functions for pi-gen environment
log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CUPCAKE] $1"
}

log_config() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CONFIG] $1"
}

log_ssl() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [SSL] $1"
}

log_cupcake "Starting CUPCAKE installation..."

# Update system
log_cupcake "Updating system packages..."
apt-get update
apt-get upgrade -y

# Add PostgreSQL official repository FIRST (matching native script lines 354-360)
log_cupcake "Adding PostgreSQL official repository..."
curl https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/apt.postgresql.org.gpg > /dev/null
echo 'deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list
apt-get update

# Install required packages (matching native script pattern)
log_cupcake "Installing CUPCAKE dependencies..."
apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    postgresql-14 postgresql-client-14 postgresql-contrib-14 \
    redis-server \
    nginx \
    git curl wget unzip \
    build-essential libpq-dev \
    ffmpeg \
    fail2ban \
    htop nano vim \
    certbot python3-certbot-nginx

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
    git clone https://github.com/noatgnu/cupcake.git app
fi

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
su - cupcake -c "python3 -m venv /opt/cupcake/venv"

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
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py migrate"
su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py collectstatic --noinput"

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

# CUPCAKE export worker service
cat > /etc/systemd/system/cupcake-worker-export.service <<EXPORTEOF
[Unit]
Description=CUPCAKE Export Worker
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
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker export'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EXPORTEOF

# CUPCAKE import worker service
cat > /etc/systemd/system/cupcake-worker-import.service <<IMPORTEOF
[Unit]
Description=CUPCAKE Import Worker
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
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker import-data'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
IMPORTEOF

# CUPCAKE maintenance worker service
cat > /etc/systemd/system/cupcake-worker-maintenance.service <<MAINTENANCEEOF
[Unit]
Description=CUPCAKE Maintenance Worker
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
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker maintenance'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
MAINTENANCEEOF

# CUPCAKE transcribe worker service (for audio/speech processing)
cat > /etc/systemd/system/cupcake-worker-transcribe.service <<TRANSCRIBEEOF
[Unit]
Description=CUPCAKE Transcribe Worker
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
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker transcribe'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
TRANSCRIBEEOF

# CUPCAKE OCR worker service (for document processing)
cat > /etc/systemd/system/cupcake-worker-ocr.service <<OCREOF
[Unit]
Description=CUPCAKE OCR Worker
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
ExecStart=/bin/bash -c 'cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py rqworker ocr'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
OCREOF

# Enable services
systemctl enable cupcake-web cupcake-worker cupcake-worker-export cupcake-worker-import cupcake-worker-maintenance cupcake-worker-transcribe cupcake-worker-ocr
systemctl enable nginx postgresql redis-server

# Configure nginx
log_cupcake "Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default

# Configure fail2ban
log_cupcake "Configuring fail2ban..."
systemctl enable fail2ban

# Set up log rotation
log_cupcake "Setting up log rotation..."
cat > /etc/logrotate.d/cupcake <<LOGEOF
/opt/cupcake/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    notifempty
    create 644 cupcake cupcake
    postrotate
        systemctl reload cupcake-web
    endscript
}
LOGEOF

# Create startup script for first boot configuration
log_cupcake "Creating first boot configuration script..."
cat > /opt/cupcake/first-boot-setup.sh <<BOOTEOF
#!/bin/bash

# CUPCAKE First Boot Setup Script
# Handles configuration that requires the system to be fully booted

SETUP_COMPLETE_FILE="/opt/cupcake/.first-boot-complete"

if [ -f "\$SETUP_COMPLETE_FILE" ]; then
    echo "First boot setup already completed"
    exit 0
fi

echo "Running CUPCAKE first boot setup..."

# Process any configuration files from boot partition
if [ -f "/boot/cupcake-config.txt" ]; then
    echo "Processing CUPCAKE configuration..."
    source /boot/cupcake-config.txt
    
    # Configure hostname if specified
    if [ -n "\$CUPCAKE_HOSTNAME" ]; then
        echo "Setting hostname to: \$CUPCAKE_HOSTNAME"
        echo "\$CUPCAKE_HOSTNAME" > /etc/hostname
        sed -i "s/127.0.1.1.*/127.0.1.1 \$CUPCAKE_HOSTNAME/" /etc/hosts
    fi
    
    # Configure admin user if specified
    if [ -n "\$CUPCAKE_ADMIN_USER" ] && [ -n "\$CUPCAKE_ADMIN_PASSWORD" ]; then
        echo "Creating CUPCAKE admin user: \$CUPCAKE_ADMIN_USER"
        cd /opt/cupcake/app
        su - cupcake -c "cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate && python manage.py shell" <<PYEOF
from django.contrib.auth.models import User
try:
    user = User.objects.get(username='\$CUPCAKE_ADMIN_USER')
    user.set_password('\$CUPCAKE_ADMIN_PASSWORD')
    user.save()
    print("Updated existing user: \$CUPCAKE_ADMIN_USER")
except User.DoesNotExist:
    User.objects.create_superuser('\$CUPCAKE_ADMIN_USER', '\${CUPCAKE_ADMIN_EMAIL:-admin@cupcake.local}', '\$CUPCAKE_ADMIN_PASSWORD')
    print("Created new superuser: \$CUPCAKE_ADMIN_USER")
PYEOF
    fi
    
    # Remove config file for security
    rm -f /boot/cupcake-config.txt
fi

# Start services
echo "Starting CUPCAKE services..."
systemctl start postgresql redis-server
systemctl start cupcake-web cupcake-worker cupcake-worker-export cupcake-worker-import cupcake-worker-maintenance cupcake-worker-transcribe cupcake-worker-ocr
systemctl start nginx

# Mark setup as complete
touch "\$SETUP_COMPLETE_FILE"

echo "CUPCAKE first boot setup completed!"
echo "CUPCAKE is now accessible at: http://\$(hostname).local"
echo "Default login: admin / cupcake123 (change immediately!)"
BOOTEOF

chmod +x /opt/cupcake/first-boot-setup.sh

# Create systemd service for first boot setup
cat > /etc/systemd/system/cupcake-first-boot.service <<FIRSTBOOTEOF
[Unit]
Description=CUPCAKE First Boot Setup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/first-boot-setup.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
FIRSTBOOTEOF

systemctl enable cupcake-first-boot

log_cupcake "CUPCAKE installation completed successfully!"
log_cupcake "Services will start automatically on first boot"
EOF
    
    chmod +x "$stage_dir/00-install-cupcake/01-run.sh"
}

create_boot_config() {
    local stage_dir="$1"
    
    log "Creating Pi-specific boot configuration..."
    
    mkdir -p "$stage_dir/02-boot-config"
    
    # Create Pi-specific boot configuration
    if [ "$PI_MODEL" = "pi4" ]; then
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
#!/bin/bash -e

log_config() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CONFIG] $1"
}

log_config "Applying Pi 4 specific configuration..."

cat >> "${BOOT_CONFIG}" << 'BOOTEOF'

# CUPCAKE Pi 4 Optimizations
arm_64bit=1
dtparam=arm_freq=2000
dtparam=over_voltage=1
gpu_mem=64

# Enable NVMe support
dtparam=pcie_gen=2
dtoverlay=pcie-32bit-dma

# Disable unused interfaces for performance
dtparam=i2c_arm=off
dtparam=spi=off
dtparam=audio=off

# Camera and display
camera_auto_detect=0
display_auto_detect=0

# Memory and performance optimizations
disable_splash=1
boot_delay=0
arm_boost=1
BOOTEOF

log_config "Pi 4 configuration applied"
EOF
    else
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
#!/bin/bash -e

log_config() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [CONFIG] $1"
}

log_config "Applying Pi 5 specific configuration..."

cat >> "${BOOT_CONFIG}" << 'BOOTEOF'

# CUPCAKE Pi 5 Optimizations
arm_64bit=1
dtparam=arm_freq=2400
dtparam=over_voltage=2
gpu_mem=128

# Enable PCIe Gen 3 for NVMe
dtparam=pciex1_gen=3
dtoverlay=pcie-32bit-dma

# Pi 5 specific optimizations
dtparam=i2c_arm=off
dtparam=spi=off

# Disable unused interfaces
dtparam=audio=off
camera_auto_detect=0
display_auto_detect=0

# Memory and performance optimizations
disable_splash=1
boot_delay=0
arm_boost=1
BOOTEOF

log_config "Pi 5 configuration applied"
EOF
    fi
    
    chmod +x "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh"
}