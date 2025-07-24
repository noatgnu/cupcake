#!/bin/bash

# CUPCAKE Raspberry Pi 5 Initial Setup Script
# This script configures the system after first boot

set -e

# Configuration
CUPCAKE_USER="cupcake"
CUPCAKE_DIR="/opt/cupcake"
LOG_DIR="/var/log/cupcake"
DATA_DIR="/var/lib/cupcake"
BACKUP_DIR="/opt/cupcake/backups"
VENV_DIR="/opt/cupcake/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_DIR/setup.log"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$LOG_DIR/setup.log"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOG_DIR/setup.log"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_DIR/setup.log"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
fi

# Create log file
mkdir -p "$LOG_DIR"
touch "$LOG_DIR/setup.log"
chown "$CUPCAKE_USER:$CUPCAKE_USER" "$LOG_DIR/setup.log"

log "Starting CUPCAKE Raspberry Pi 5 setup..."

# System optimization
optimize_system() {
    log "Optimizing system for low-power operation..."
    
    # Update GPU memory split
    if ! grep -q "gpu_mem=16" /boot/firmware/config.txt; then
        echo "gpu_mem=16" >> /boot/firmware/config.txt
        info "GPU memory reduced to 16MB"
    fi
    
    # Configure swap
    systemctl stop dphys-swapfile 2>/dev/null || true
    
    cat > /etc/dphys-swapfile << EOF
CONF_SWAPSIZE=1024
CONF_SWAPFILE=/var/swap
CONF_MAXSWAP=2048
EOF
    
    systemctl enable dphys-swapfile
    systemctl start dphys-swapfile
    
    # Set CPU governor
    echo 'GOVERNOR="ondemand"' > /etc/default/cpufrequtils
    
    # Configure log rotation
    cat > /etc/logrotate.d/cupcake << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 $CUPCAKE_USER $CUPCAKE_USER
}
EOF
    
    log "System optimization completed"
}

# Configure PostgreSQL
setup_postgresql() {
    log "Setting up PostgreSQL..."
    
    # Start PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database and user
    sudo -u postgres psql << EOF
CREATE USER cupcake WITH PASSWORD 'cupcake_db_password';
CREATE DATABASE cupcake OWNER cupcake;
GRANT ALL PRIVILEGES ON DATABASE cupcake TO cupcake;
ALTER USER cupcake CREATEDB;
\q
EOF
    
    # Configure PostgreSQL for low memory
    local pg_version=$(sudo -u postgres psql -t -c "SELECT version();" | grep -oP '\d+\.\d+' | head -1)
    local pg_config="/etc/postgresql/$pg_version/main/postgresql.conf"
    
    if [[ -f "$pg_config" ]]; then
        # Optimize for Raspberry Pi 5
        cat >> "$pg_config" << EOF

# CUPCAKE Raspberry Pi optimizations
shared_buffers = 128MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 4
work_mem = 4MB
max_connections = 50
EOF
        
        systemctl restart postgresql
        info "PostgreSQL optimized for Raspberry Pi"
    fi
    
    log "PostgreSQL setup completed"
}

# Configure Redis
setup_redis() {
    log "Setting up Redis..."
    
    # Configure Redis for low memory
    cat > /etc/redis/redis.conf << EOF
# CUPCAKE Redis Configuration
bind 127.0.0.1
port 6379
timeout 300
tcp-keepalive 60

# Memory optimization
maxmemory 256mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000

# Logging
loglevel notice
logfile /var/log/redis/redis-server.log

# Other settings
databases 16
dir /var/lib/redis
EOF
    
    systemctl restart redis-server
    systemctl enable redis-server
    
    log "Redis setup completed"
}

# Configure Nginx
setup_nginx() {
    log "Setting up Nginx..."
    
    # Create main nginx config
    cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name cupcake-pi.local cupcake-pi _;
    
    client_max_body_size 100M;
    
    # Static files
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
    
    # Main application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
    
    # WebSocket support
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    
    # Enable site
    ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Test configuration
    sudo nginx -t
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    
    log "Nginx setup completed"
}

# Setup Python environment
setup_python() {
    log "Setting up Python environment..."
    
    # Create virtual environment
    sudo -u "$CUPCAKE_USER" python3 -m venv "$VENV_DIR"
    
    # Upgrade pip
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
    
    # Install CUPCAKE requirements
    cd "$CUPCAKE_DIR/src"
    
    # Create optimized requirements for Pi
    cat > requirements-pi.txt << EOF
# Core Django
Django==4.2.16
djangorestframework==3.15.2
django-cors-headers==4.6.0
django-filter==24.3

# Database
psycopg2-binary==2.9.11

# Cache and sessions
redis==5.2.1
django-redis==5.4.0

# File handling
Pillow==11.1.0
python-docx==1.1.2
openpyxl==3.1.5

# Web server
gunicorn==23.0.0
whitenoise==6.9.0

# Background tasks (lightweight)
celery==5.4.0

# Essential scientific packages (lighter versions)
pandas==2.2.3
numpy==2.2.1

# System monitoring
psutil==6.2.0

# Other essentials
python-dateutil==2.9.0.post0
requests==2.32.3
python-dotenv==1.0.1
EOF
    
    # Install requirements
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install -r requirements-pi.txt
    
    log "Python environment setup completed"
}

# Configure CUPCAKE application
setup_cupcake() {
    log "Configuring CUPCAKE application..."
    
    cd "$CUPCAKE_DIR/src"
    
    # Create environment file
    cat > .env << EOF
# CUPCAKE Raspberry Pi Configuration
DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)

# Database
DATABASE_URL=postgresql://cupcake:cupcake_db_password@localhost:5432/cupcake

# Redis
REDIS_URL=redis://localhost:6379/0

# File storage
MEDIA_ROOT=/opt/cupcake/media
STATIC_ROOT=/opt/cupcake/staticfiles

# Email (configure as needed)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Security
ALLOWED_HOSTS=cupcake-pi.local,cupcake-pi,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://cupcake-pi.local,http://cupcake-pi

# Performance
WORKER_PROCESSES=2
WORKER_CONNECTIONS=1000
EOF
    
    chown "$CUPCAKE_USER:$CUPCAKE_USER" .env
    chmod 600 .env
    
    # Run Django setup
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py collectstatic --noinput
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py migrate
    
    # Create superuser
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py shell << EOF
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake-pi.local', 'cupcake_admin')
    print("Superuser 'admin' created")
else:
    print("Superuser already exists")
EOF
    
    log "CUPCAKE application configured"
}

# Setup systemd services
setup_services() {
    log "Setting up systemd services..."
    
    # CUPCAKE web service
    cat > /etc/systemd/system/cupcake-web.service << EOF
[Unit]
Description=CUPCAKE Web Application
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=forking
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$CUPCAKE_DIR/src
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/gunicorn cupcake.wsgi:application \\
    --bind 127.0.0.1:8000 \\
    --workers 2 \\
    --worker-class sync \\
    --worker-connections 1000 \\
    --max-requests 1000 \\
    --max-requests-jitter 100 \\
    --timeout 30 \\
    --keep-alive 2 \\
    --daemon \\
    --pid /var/run/cupcake-web.pid \\
    --user $CUPCAKE_USER \\
    --group $CUPCAKE_USER \\
    --log-level info \\
    --log-file $LOG_DIR/gunicorn.log \\
    --access-logfile $LOG_DIR/access.log
ExecReload=/bin/kill -s HUP \$MAINPID
ExecStop=/bin/kill -s TERM \$MAINPID
PIDFile=/var/run/cupcake-web.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # CUPCAKE worker service (for background tasks)
    cat > /etc/systemd/system/cupcake-worker.service << EOF
[Unit]
Description=CUPCAKE Background Worker
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$CUPCAKE_DIR/src
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/celery -A cupcake worker \\
    --loglevel=info \\
    --concurrency=1 \\
    --logfile=$LOG_DIR/celery.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # System monitoring service
    cat > /etc/systemd/system/cupcake-monitor.service << EOF
[Unit]
Description=CUPCAKE System Monitor
After=network.target

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
ExecStart=$CUPCAKE_DIR/scripts/monitoring.sh
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd and enable services
    systemctl daemon-reload
    systemctl enable cupcake-web.service
    systemctl enable cupcake-worker.service
    systemctl enable cupcake-monitor.service
    
    log "Systemd services configured"
}

# Configure networking
setup_networking() {
    log "Configuring networking..."
    
    # Set hostname
    echo "cupcake-pi" > /etc/hostname
    
    # Update hosts file
    cat > /etc/hosts << EOF
127.0.0.1       localhost
127.0.1.1       cupcake-pi cupcake-pi.local
::1             localhost ip6-localhost ip6-loopback
ff02::1         ip6-allnodes
ff02::2         ip6-allrouters
EOF
    
    # Configure static IP (optional)
    if [[ ! -f /etc/dhcpcd.conf.backup ]]; then
        cp /etc/dhcpcd.conf /etc/dhcpcd.conf.backup
    fi
    
    # Add static IP configuration (commented out by default)
    cat >> /etc/dhcpcd.conf << EOF

# CUPCAKE Static IP Configuration (uncomment to use)
# interface eth0
# static ip_address=192.168.1.100/24
# static routers=192.168.1.1
# static domain_name_servers=192.168.1.1 8.8.8.8
EOF
    
    log "Networking configured"
}

# Setup security
setup_security() {
    log "Configuring security..."
    
    # Configure SSH
    if [[ -f /etc/ssh/sshd_config ]]; then
        cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup
        
        # Secure SSH configuration
        cat >> /etc/ssh/sshd_config << EOF

# CUPCAKE Security Settings
PermitRootLogin no
PasswordAuthentication yes
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
        
        systemctl restart ssh
    fi
    
    # Configure firewall
    ufw --force enable
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow from 192.168.0.0/16 to any port 80
    ufw allow from 10.0.0.0/8 to any port 80
    
    # Set up fail2ban
    if command -v fail2ban-server &> /dev/null; then
        systemctl enable fail2ban
        systemctl start fail2ban
    fi
    
    log "Security configured"
}

# Setup backup system
setup_backup() {
    log "Setting up backup system..."
    
    # Create backup script
    cat > "$CUPCAKE_DIR/scripts/backup.sh" << 'EOF'
#!/bin/bash
# CUPCAKE Backup Script

BACKUP_DIR="/opt/cupcake/backups"
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/cupcake/backup.log"

# Database backup
sudo -u cupcake pg_dump cupcake | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Media files backup
tar -czf "$BACKUP_DIR/media_$DATE.tar.gz" -C /opt/cupcake media/

# Configuration backup
tar -czf "$BACKUP_DIR/config_$DATE.tar.gz" /opt/cupcake/src/.env /etc/nginx/sites-available/cupcake

# Cleanup old backups (keep 7 days)
find "$BACKUP_DIR" -name "*.gz" -mtime +7 -delete

echo "$(date): Backup completed" >> "$LOG_FILE"
EOF
    
    chmod +x "$CUPCAKE_DIR/scripts/backup.sh"
    
    # Setup cron job for daily backups
    cat > /tmp/cupcake-cron << EOF
# CUPCAKE Daily Backup at 2 AM
0 2 * * * /opt/cupcake/scripts/backup.sh
# CUPCAKE Log Cleanup at 3 AM
0 3 * * * find /var/log/cupcake -name "*.log" -mtime +7 -delete
EOF
    
    crontab -u "$CUPCAKE_USER" /tmp/cupcake-cron
    rm /tmp/cupcake-cron
    
    log "Backup system configured"
}

# Final setup
finalize_setup() {
    log "Finalizing setup..."
    
    # Set permissions
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR"
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$LOG_DIR"
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$DATA_DIR"
    
    # Create motd
    cat > /etc/motd << EOF

██████╗██╗   ██╗██████╗  ██████╗ █████╗ ██╗  ██╗███████╗
██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║ ██╔╝██╔════╝
██║     ██║   ██║██████╔╝██║     ███████║█████╔╝ █████╗  
██║     ██║   ██║██╔═══╝ ██║     ██╔══██║██╔═██╗ ██╔══╝  
╚██████╗╚██████╔╝██║     ╚██████╗██║  ██║██║  ██╗███████╗
 ╚═════╝ ╚═════╝ ╚═╝      ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝

Raspberry Pi 5 Edition - Low Power Laboratory Management

Web Interface: http://cupcake-pi.local
Admin Panel:   http://cupcake-pi.local/admin

Default credentials:
- SSH: cupcake / cupcake123 (CHANGE IMMEDIATELY)
- Web: admin / cupcake_admin (CHANGE IMMEDIATELY)

System Status: systemctl status cupcake-*
Logs:         tail -f /var/log/cupcake/*.log
Resources:    htop

EOF
    
    # Start services
    systemctl start cupcake-web
    systemctl start cupcake-worker
    systemctl start cupcake-monitor
    
    log "Setup finalization completed"
}

# Security reminder
security_reminder() {
    echo ""
    echo -e "${RED}IMPORTANT SECURITY NOTICE:${NC}"
    echo -e "${YELLOW}Please change the default passwords immediately:${NC}"
    echo "1. SSH password: passwd cupcake"
    echo "2. Web admin password: http://cupcake-pi.local/admin"
    echo "3. Database password: edit /opt/cupcake/src/.env"
    echo ""
    echo -e "${GREEN}CUPCAKE is now running at: http://cupcake-pi.local${NC}"
    echo ""
}

# Main execution
main() {
    log "Starting CUPCAKE setup on Raspberry Pi 5..."
    
    optimize_system
    setup_postgresql
    setup_redis
    setup_nginx
    setup_python
    setup_cupcake
    setup_services
    setup_networking
    setup_security
    setup_backup
    finalize_setup
    
    log "CUPCAKE setup completed successfully!"
    security_reminder
}

# Execute main function
main "$@"