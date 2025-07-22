#!/bin/bash

# CUPCAKE Raspberry Pi 5 Deployment Script
# Deploys CUPCAKE stack natively on Raspberry Pi without Docker

set -e

# Configuration
CUPCAKE_USER="cupcake"
CUPCAKE_DIR="/opt/cupcake"
VENV_DIR="/opt/cupcake/venv"
LOG_DIR="/var/log/cupcake"
DATA_DIR="/var/lib/cupcake"
BACKUP_DIR="/opt/cupcake/backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_DIR/deploy.log"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$LOG_DIR/deploy.log"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOG_DIR/deploy.log"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_DIR/deploy.log"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
fi

# Create log directory
mkdir -p "$LOG_DIR"
touch "$LOG_DIR/deploy.log"

log "Starting CUPCAKE deployment on Raspberry Pi 5..."

# Pre-deployment checks
pre_deployment_checks() {
    log "Running pre-deployment checks..."
    
    # Check Pi model
    if ! grep -q "Raspberry Pi 5" /proc/cpuinfo; then
        warn "This script is optimized for Raspberry Pi 5. Other models may work but performance may vary."
    fi
    
    # Check available memory
    local total_memory=$(free -m | awk '/^Mem:/{print $2}')
    if [[ $total_memory -lt 2048 ]]; then
        warn "Less than 2GB RAM detected. Consider using a Pi with more memory for better performance."
    fi
    
    # Check available disk space
    local available_space=$(df / | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 4194304 ]]; then # 4GB in KB
        error "Need at least 4GB free disk space for CUPCAKE deployment"
    fi
    
    # Check network connectivity
    if ! ping -c 1 google.com &> /dev/null; then
        warn "No internet connectivity detected. Some packages may fail to install."
    fi
    
    log "Pre-deployment checks completed"
}

# Install system dependencies
install_dependencies() {
    log "Installing system dependencies..."
    
    # Update package lists
    apt-get update
    
    # Install essential packages
    local packages=(
        "python3" "python3-pip" "python3-venv" "python3-dev"
        "postgresql" "postgresql-contrib" "postgresql-client"
        "redis-server"
        "nginx"
        "git" "curl" "wget" "unzip" "htop"
        "build-essential" "libpq-dev" "libffi-dev" "libssl-dev"
        "libxml2-dev" "libxslt1-dev" "libjpeg-dev" "zlib1g-dev"
        "supervisor" "logrotate" "fail2ban"
        "ufw" "rsync" "cron"
    )
    
    for package in "${packages[@]}"; do
        info "Installing $package..."
        apt-get install -y "$package" || warn "Failed to install $package"
    done
    
    # Install Node.js for frontend builds (optional)
    if ! command -v node &> /dev/null; then
        info "Installing Node.js..."
        curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
        apt-get install -y nodejs
    fi
    
    # Clean up
    apt-get autoremove -y
    apt-get clean
    
    log "System dependencies installed"
}

# Create user and directories
setup_user_directories() {
    log "Setting up user and directories..."
    
    # Create cupcake user if it doesn't exist
    if ! id "$CUPCAKE_USER" &>/dev/null; then
        useradd -m -s /bin/bash "$CUPCAKE_USER"
        echo "$CUPCAKE_USER:cupcake123" | chpasswd
        usermod -aG sudo "$CUPCAKE_USER"
        info "Created user: $CUPCAKE_USER"
    fi
    
    # Create necessary directories
    local directories=(
        "$CUPCAKE_DIR"
        "$CUPCAKE_DIR/src"
        "$CUPCAKE_DIR/scripts"
        "$CUPCAKE_DIR/config"
        "$CUPCAKE_DIR/staticfiles"
        "$CUPCAKE_DIR/media"
        "$LOG_DIR"
        "$DATA_DIR"
        "$BACKUP_DIR"
    )
    
    for dir in "${directories[@]}"; do
        mkdir -p "$dir"
        chown "$CUPCAKE_USER:$CUPCAKE_USER" "$dir"
    done
    
    log "User and directories setup completed"
}

# Setup Python environment
setup_python_environment() {
    log "Setting up Python environment..."
    
    # Create virtual environment
    sudo -u "$CUPCAKE_USER" python3 -m venv "$VENV_DIR"
    
    # Upgrade pip
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
    
    # Create optimized requirements for Raspberry Pi
    cat > "$CUPCAKE_DIR/requirements-pi.txt" << EOF
# Core Django framework
Django==4.2.16
djangorestframework==3.15.2

# Database
psycopg2-binary==2.9.11

# Cache and sessions
redis==5.2.1
django-redis==5.4.0

# CORS and security
django-cors-headers==4.6.0
django-filter==24.3

# File handling and images
Pillow==11.1.0
python-docx==1.1.2
openpyxl==3.1.5

# Web server
gunicorn==23.0.0
whitenoise==6.9.0

# Background tasks
celery==5.4.0

# Scientific computing (lightweight versions)
pandas==2.2.3
numpy==2.2.1

# System monitoring
psutil==6.2.0

# Utilities
python-dateutil==2.9.0.post0
requests==2.32.3
python-dotenv==1.0.1
Markdown==3.7

# Development and testing (optional)
# pytest==8.3.4
# pytest-django==4.9.0

# Additional CUPCAKE-specific packages
beautifulsoup4==4.13.4
lxml==5.3.0
matplotlib==3.9.3
seaborn==0.13.2
scipy==1.14.1

# File format support
xlsxwriter==3.2.0
python-magic==0.4.27

# Authentication and security
cryptography==45.1.0
bcrypt==4.2.1

# API and serialization
jsonschema==4.23.0
PyYAML==6.0.2

# Time and timezone handling
pytz==2025.2
EOF
    
    # Install requirements
    info "Installing Python packages (this may take 10-15 minutes)..."
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install -r "$CUPCAKE_DIR/requirements-pi.txt"
    
    chown "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/requirements-pi.txt"
    
    log "Python environment setup completed"
}

# Deploy CUPCAKE source code
deploy_source_code() {
    log "Deploying CUPCAKE source code..."
    
    # Check if source code exists in the expected location
    if [[ -d "$CUPCAKE_DIR/src" && -f "$CUPCAKE_DIR/src/manage.py" ]]; then
        info "CUPCAKE source code already exists"
    else
        error "CUPCAKE source code not found. This script should be run from the pi-gen built image."
    fi
    
    # Set proper ownership
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/src"
    
    # Make manage.py executable
    chmod +x "$CUPCAKE_DIR/src/manage.py"
    
    log "Source code deployment completed"
}

# Configure CUPCAKE application
configure_application() {
    log "Configuring CUPCAKE application..."
    
    cd "$CUPCAKE_DIR/src"
    
    # Generate secret key
    local secret_key=$(openssl rand -hex 32)
    
    # Create environment configuration
    cat > .env << EOF
# CUPCAKE Raspberry Pi Configuration
DEBUG=False
SECRET_KEY=$secret_key

# Database configuration
DATABASE_URL=postgresql://cupcake:cupcake_db_password@localhost:5432/cupcake

# Redis configuration
REDIS_URL=redis://localhost:6379/0

# File storage
MEDIA_ROOT=$CUPCAKE_DIR/media
STATIC_ROOT=$CUPCAKE_DIR/staticfiles

# Email configuration (configure as needed)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Security settings
ALLOWED_HOSTS=cupcake-pi.local,cupcake-pi,localhost,127.0.0.1,$(hostname -I | awk '{print $1}')
CSRF_TRUSTED_ORIGINS=http://cupcake-pi.local,http://cupcake-pi,http://localhost

# Performance settings
WORKER_PROCESSES=2
WORKER_CONNECTIONS=1000

# Pi-specific settings
PI_OPTIMIZED=True
LOW_MEMORY_MODE=True
DISABLE_DEBUG_TOOLBAR=True

# Logging
LOG_LEVEL=INFO
LOG_DIR=$LOG_DIR

# Backup settings
BACKUP_DIR=$BACKUP_DIR
AUTO_BACKUP=True
EOF
    
    # Set permissions
    chown "$CUPCAKE_USER:$CUPCAKE_USER" .env
    chmod 600 .env
    
    # Run Django setup commands
    info "Running Django migrations..."
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py collectstatic --noinput
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py migrate
    
    # Create superuser
    info "Creating superuser account..."
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py shell << EOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake-pi.local', 'cupcake_admin_$(openssl rand -hex 8)')
    print("Superuser 'admin' created with secure password")
else:
    print("Superuser already exists")
EOF
    
    log "Application configuration completed"
}

# Configure databases
configure_databases() {
    log "Configuring databases..."
    
    # Start and enable PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database and user
    info "Setting up PostgreSQL database..."
    sudo -u postgres psql << EOF
-- Create user and database
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'cupcake') THEN
        CREATE USER cupcake WITH PASSWORD 'cupcake_db_password';
    END IF;
END
\$\$;

-- Create database if it doesn't exist
SELECT 'CREATE DATABASE cupcake OWNER cupcake'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cupcake')\gexec

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE cupcake TO cupcake;
ALTER USER cupcake CREATEDB;
EOF
    
    # Configure Redis
    info "Configuring Redis..."
    systemctl start redis-server
    systemctl enable redis-server
    
    # Apply optimized PostgreSQL configuration
    local pg_version=$(sudo -u postgres psql -t -c "SELECT version();" | grep -oP '\d+\.\d+' | head -1)
    local pg_config="/etc/postgresql/$pg_version/main/postgresql.conf"
    
    if [[ -f "$pg_config" ]]; then
        cp "$pg_config" "$pg_config.backup"
        
        # Apply our optimized configuration
        if [[ -f "$CUPCAKE_DIR/../config/postgresql/postgresql-pi.conf" ]]; then
            cp "$CUPCAKE_DIR/../config/postgresql/postgresql-pi.conf" "$pg_config"
            systemctl restart postgresql
            info "Applied PostgreSQL optimization for Raspberry Pi"
        fi
    fi
    
    log "Database configuration completed"
}

# Setup system services
setup_services() {
    log "Setting up system services..."
    
    # Create systemd service for CUPCAKE web application
    cat > /etc/systemd/system/cupcake-web.service << EOF
[Unit]
Description=CUPCAKE Web Application
Documentation=https://github.com/noatgnu/cupcake
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=notify
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$CUPCAKE_DIR/src
Environment=PATH=$VENV_DIR/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
ExecStart=$VENV_DIR/bin/gunicorn cupcake.wsgi:application \\
    --bind 127.0.0.1:8000 \\
    --workers 2 \\
    --worker-class sync \\
    --worker-connections 1000 \\
    --max-requests 1000 \\
    --max-requests-jitter 100 \\
    --timeout 30 \\
    --keep-alive 2 \\
    --user $CUPCAKE_USER \\
    --group $CUPCAKE_USER \\
    --log-level info \\
    --log-file $LOG_DIR/gunicorn.log \\
    --access-logfile $LOG_DIR/access.log \\
    --error-logfile $LOG_DIR/error.log \\
    --pid /var/run/cupcake-web.pid \\
    --preload
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # Create systemd service for CUPCAKE worker
    cat > /etc/systemd/system/cupcake-worker.service << EOF
[Unit]
Description=CUPCAKE Background Worker
Documentation=https://github.com/noatgnu/cupcake
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$CUPCAKE_DIR/src
Environment=PATH=$VENV_DIR/bin
Environment=DJANGO_SETTINGS_MODULE=cupcake.settings
ExecStart=$VENV_DIR/bin/celery -A cupcake worker \\
    --loglevel=info \\
    --concurrency=1 \\
    --logfile=$LOG_DIR/celery.log \\
    --pidfile=/var/run/cupcake-worker.pid
Restart=always
RestartSec=10
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
    
    # Create systemd service for monitoring
    cat > /etc/systemd/system/cupcake-monitor.service << EOF
[Unit]
Description=CUPCAKE System Monitor
Documentation=https://github.com/noatgnu/cupcake
After=network.target

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
ExecStart=$CUPCAKE_DIR/scripts/monitoring.sh
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Enable and start services
    systemctl daemon-reload
    systemctl enable cupcake-web.service
    systemctl enable cupcake-worker.service
    systemctl enable cupcake-monitor.service
    
    log "System services configured"
}

# Configure web server
configure_web_server() {
    log "Configuring web server..."
    
    # Configure Nginx
    if [[ -f "$CUPCAKE_DIR/../config/nginx/cupcake.conf" ]]; then
        cp "$CUPCAKE_DIR/../config/nginx/cupcake.conf" /etc/nginx/sites-available/cupcake
        cp "$CUPCAKE_DIR/../config/nginx/proxy_params.conf" /etc/nginx/conf.d/proxy_params.conf
    else
        # Fallback configuration
        cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name cupcake-pi.local cupcake-pi _;
    
    client_max_body_size 100M;
    
    location /static/ {
        alias /opt/cupcake/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    location /media/ {
        alias /opt/cupcake/media/;
        expires 1y;
        add_header Cache-Control "public";
    }
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    fi
    
    # Enable site
    ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Test and restart Nginx
    nginx -t
    systemctl restart nginx
    systemctl enable nginx
    
    log "Web server configuration completed"
}

# Setup monitoring and maintenance
setup_monitoring() {
    log "Setting up monitoring and maintenance..."
    
    # Copy monitoring scripts if they exist
    if [[ -f "$CUPCAKE_DIR/../scripts/monitoring.sh" ]]; then
        cp "$CUPCAKE_DIR/../scripts/monitoring.sh" "$CUPCAKE_DIR/scripts/"
        chmod +x "$CUPCAKE_DIR/scripts/monitoring.sh"
    fi
    
    # Create backup script
    cat > "$CUPCAKE_DIR/scripts/backup.sh" << 'EOF'
#!/bin/bash
# CUPCAKE Backup Script

BACKUP_DIR="/opt/cupcake/backups"
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/cupcake/backup.log"

mkdir -p "$BACKUP_DIR"

# Database backup
echo "$(date): Starting database backup" >> "$LOG_FILE"
sudo -u cupcake pg_dump cupcake | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Media files backup
echo "$(date): Starting media backup" >> "$LOG_FILE"
tar -czf "$BACKUP_DIR/media_$DATE.tar.gz" -C /opt/cupcake media/

# Configuration backup
echo "$(date): Starting configuration backup" >> "$LOG_FILE"
tar -czf "$BACKUP_DIR/config_$DATE.tar.gz" /opt/cupcake/src/.env /etc/nginx/sites-available/cupcake

# Cleanup old backups (keep 7 days)
find "$BACKUP_DIR" -name "*.gz" -mtime +7 -delete

echo "$(date): Backup completed" >> "$LOG_FILE"
EOF
    
    chmod +x "$CUPCAKE_DIR/scripts/backup.sh"
    
    # Setup cron jobs
    cat > /tmp/cupcake-cron << EOF
# CUPCAKE Daily Backup at 2 AM
0 2 * * * /opt/cupcake/scripts/backup.sh

# CUPCAKE Log Cleanup at 3 AM
0 3 * * * find /var/log/cupcake -name "*.log" -mtime +7 -delete

# CUPCAKE System Check every 6 hours
0 */6 * * * /opt/cupcake/scripts/monitoring.sh --check

# CUPCAKE Database Maintenance weekly
0 1 * * 0 sudo -u cupcake psql -d cupcake -c "VACUUM ANALYZE;"
EOF
    
    crontab -u "$CUPCAKE_USER" /tmp/cupcake-cron
    rm /tmp/cupcake-cron
    
    log "Monitoring and maintenance setup completed"
}

# Configure security
configure_security() {
    log "Configuring security..."
    
    # Configure firewall
    ufw --force enable
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    
    # Allow local network access
    ufw allow from 192.168.0.0/16 to any port 80
    ufw allow from 10.0.0.0/8 to any port 80
    
    # Configure fail2ban
    if command -v fail2ban-server &> /dev/null; then
        systemctl enable fail2ban
        systemctl start fail2ban
    fi
    
    # Set file permissions
    chmod 600 "$CUPCAKE_DIR/src/.env"
    chown "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/src/.env"
    
    log "Security configuration completed"
}

# Start services
start_services() {
    log "Starting CUPCAKE services..."
    
    # Start database services
    systemctl start postgresql
    systemctl start redis-server
    
    # Start web server
    systemctl start nginx
    
    # Start CUPCAKE services
    systemctl start cupcake-web
    systemctl start cupcake-worker
    systemctl start cupcake-monitor
    
    # Check service status
    local services=("cupcake-web" "cupcake-worker" "cupcake-monitor" "nginx" "postgresql" "redis-server")
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "$service"; then
            info "✓ $service is running"
        else
            warn "✗ $service is not running"
        fi
    done
    
    log "Services startup completed"
}

# Post-deployment tasks
post_deployment() {
    log "Running post-deployment tasks..."
    
    # Create completion marker
    touch "$DATA_DIR/deployment-complete"
    echo "$(date)" > "$DATA_DIR/deployment-complete"
    
    # Set final permissions
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR"
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$LOG_DIR"
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$DATA_DIR"
    
    # Create MOTD
    if [[ -f "$CUPCAKE_DIR/../config/system/etc/motd" ]]; then
        cp "$CUPCAKE_DIR/../config/system/etc/motd" /etc/motd
    fi
    
    # Get system information for summary
    local ip_address=$(hostname -I | awk '{print $1}')
    local total_memory=$(free -h | awk '/^Mem:/{print $2}')
    local disk_usage=$(df -h / | awk 'NR==2{print $3"/"$2" ("$5")"}')
    
    log "Post-deployment tasks completed"
    
    # Display deployment summary
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}🎉 CUPCAKE Deployment Completed Successfully! 🎉${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}System Information:${NC}"
    echo "  • Hostname: $(hostname)"
    echo "  • IP Address: $ip_address"
    echo "  • Memory: $total_memory"
    echo "  • Disk Usage: $disk_usage"
    echo "  • Python Version: $(python3 --version)"
    echo ""
    echo -e "${BLUE}Access Information:${NC}"
    echo "  • Web Interface: http://cupcake-pi.local or http://$ip_address"
    echo "  • Admin Panel: http://cupcake-pi.local/admin"
    echo "  • System Dashboard: http://cupcake-pi.local/dashboard"
    echo ""
    echo -e "${BLUE}Default Credentials:${NC}"
    echo "  • SSH: $CUPCAKE_USER / cupcake123"
    echo "  • Web Admin: admin / [check deployment log for password]"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo "  • Service Status: sudo systemctl status cupcake-*"
    echo "  • View Logs: sudo journalctl -f -u cupcake-web"
    echo "  • System Resources: htop"
    echo "  • Run Backup: $CUPCAKE_DIR/scripts/backup.sh"
    echo ""
    echo -e "${RED}⚠️  SECURITY REMINDER:${NC}"
    echo -e "${YELLOW}Change default passwords immediately!${NC}"
    echo "  1. SSH password: passwd $CUPCAKE_USER"
    echo "  2. Web admin password: http://cupcake-pi.local/admin"
    echo ""
    echo -e "${GREEN}Deployment log: $LOG_DIR/deploy.log${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Main execution
main() {
    log "Starting CUPCAKE deployment on Raspberry Pi 5..."
    
    pre_deployment_checks
    install_dependencies
    setup_user_directories
    setup_python_environment
    deploy_source_code
    configure_application
    configure_databases
    setup_services
    configure_web_server
    setup_monitoring
    configure_security
    start_services
    post_deployment
    
    log "CUPCAKE deployment completed successfully!"
}

# Handle script interruption
cleanup() {
    warn "Deployment interrupted. Check logs and run again if needed."
    exit 1
}

trap cleanup SIGTERM SIGINT

# Execute main function
main "$@"