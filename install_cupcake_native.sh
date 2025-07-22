#!/bin/bash

set -e

# CUPCAKE Native Installation Script
# This script installs CUPCAKE without Docker for lower power systems
# Supports Ubuntu 20.04+ and Debian 11+

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/cupcake_native_install"
CUPCAKE_USER="cupcake"
VENV_DIR="/opt/cupcake/venv"
APP_DIR="/opt/cupcake/app"
MEDIA_DIR="/opt/cupcake/media"
STATIC_DIR="/opt/cupcake/static"
LOG_DIR="/var/log/cupcake"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to generate random string
generate_random_string() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# Function to validate hostname
validate_hostname() {
    local hostname=$1
    if [[ $hostname =~ ^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$ ]]; then
        return 0
    else
        return 1
    fi
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "This script should not be run as root for security reasons."
        log_info "Please run as a regular user with sudo privileges."
        exit 1
    fi
    
    if ! sudo -n true 2>/dev/null; then
        log_error "This script requires sudo privileges. Please ensure you can run sudo commands."
        exit 1
    fi
}

# Detect OS and version
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$NAME
        VERSION=$VERSION_ID
    else
        log_error "Cannot detect operating system"
        exit 1
    fi
    
    log_info "Detected OS: $OS $VERSION"
    
    case $OS in
        "Ubuntu")
            if [[ $(echo "$VERSION >= 20.04" | bc -l) -eq 0 ]]; then
                log_error "Ubuntu 20.04 or newer is required"
                exit 1
            fi
            PACKAGE_MANAGER="apt"
            ;;
        "Debian GNU/Linux")
            if [[ $(echo "$VERSION >= 11" | bc -l) -eq 0 ]]; then
                log_error "Debian 11 or newer is required"
                exit 1
            fi
            PACKAGE_MANAGER="apt"
            ;;
        *)
            log_error "Unsupported operating system: $OS"
            log_info "This script supports Ubuntu 20.04+ and Debian 11+"
            exit 1
            ;;
    esac
}

# Check system requirements
check_system_requirements() {
    log_info "Checking system requirements..."
    
    # Check available memory (minimum 2GB recommended)
    MEMORY_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    MEMORY_GB=$((MEMORY_KB / 1024 / 1024))
    
    if [[ $MEMORY_GB -lt 2 ]]; then
        log_warning "System has only ${MEMORY_GB}GB RAM. Minimum 2GB recommended."
        read -p "Continue anyway? [y/N]: " CONTINUE_LOW_MEMORY
        if [[ "$CONTINUE_LOW_MEMORY" != "y" && "$CONTINUE_LOW_MEMORY" != "Y" ]]; then
            exit 1
        fi
    else
        log_success "Memory check passed: ${MEMORY_GB}GB RAM available"
    fi
    
    # Check available disk space (minimum 5GB recommended)
    AVAILABLE_SPACE=$(df / | awk 'NR==2 {print $4}')
    AVAILABLE_GB=$((AVAILABLE_SPACE / 1024 / 1024))
    
    if [[ $AVAILABLE_GB -lt 5 ]]; then
        log_warning "Only ${AVAILABLE_GB}GB disk space available. Minimum 5GB recommended."
        read -p "Continue anyway? [y/N]: " CONTINUE_LOW_SPACE
        if [[ "$CONTINUE_LOW_SPACE" != "y" && "$CONTINUE_LOW_SPACE" != "Y" ]]; then
            exit 1
        fi
    else
        log_success "Disk space check passed: ${AVAILABLE_GB}GB available"
    fi
    
    # Check CPU cores
    CPU_CORES=$(nproc)
    if [[ $CPU_CORES -lt 2 ]]; then
        log_warning "System has only $CPU_CORES CPU core. 2+ cores recommended for better performance."
    else
        log_success "CPU check passed: $CPU_CORES cores available"
    fi
}

# Collect user configuration
collect_configuration() {
    log_info "Collecting installation configuration..."
    
    # Hostname configuration
    while true; do
        read -p "Enter the hostname for your CUPCAKE installation (e.g., cupcake.yourlab.com or localhost): " HOSTNAME
        if validate_hostname "$HOSTNAME" || [[ "$HOSTNAME" == "localhost" ]]; then
            break
        else
            log_error "Invalid hostname format. Please enter a valid hostname or 'localhost'."
        fi
    done
    
    # Port configuration
    read -p "Enter the web server port [default: 8080]: " WEB_PORT
    WEB_PORT=${WEB_PORT:-8080}
    
    # Django secret key
    echo
    echo "Django Secret Key Configuration:"
    echo "1) Generate automatically (recommended)"
    echo "2) Provide your own"
    read -p "Choose option [1]: " SECRET_OPTION
    SECRET_OPTION=${SECRET_OPTION:-1}
    
    if [[ "$SECRET_OPTION" == "2" ]]; then
        read -s -p "Enter your Django secret key: " DJANGO_SECRET_KEY
        echo
    else
        DJANGO_SECRET_KEY=$(generate_random_string)
        log_info "Generated Django secret key automatically."
    fi
    
    # Database configuration
    echo
    log_info "Database Configuration:"
    echo "CUPCAKE requires PostgreSQL. This script will install and configure it locally."
    read -p "Enter PostgreSQL database name [default: cupcake_db]: " DB_NAME
    DB_NAME=${DB_NAME:-cupcake_db}
    
    read -p "Enter PostgreSQL username [default: cupcake_user]: " DB_USER
    DB_USER=${DB_USER:-cupcake_user}
    
    read -s -p "Enter PostgreSQL password [will generate if empty]: " DB_PASSWORD
    echo
    if [[ -z "$DB_PASSWORD" ]]; then
        DB_PASSWORD=$(generate_random_string)
        log_info "Generated database password automatically."
    fi
    
    # Optional services
    echo
    log_info "Optional Services Configuration:"
    
    read -p "Enable Whisper (Audio transcription)? [y/N]: " ENABLE_WHISPER
    ENABLE_WHISPER=${ENABLE_WHISPER,,}
    
    read -p "Enable OCR (Optical Character Recognition)? [y/N]: " ENABLE_OCR
    ENABLE_OCR=${ENABLE_OCR,,}
    
    read -p "Enable background task workers? [Y/n]: " ENABLE_WORKERS
    ENABLE_WORKERS=${ENABLE_WORKERS,,}
    ENABLE_WORKERS=${ENABLE_WORKERS:-y}
    
    # Admin user configuration
    echo
    log_info "Initial Admin User Configuration:"
    read -p "Admin username: " ADMIN_USERNAME
    read -p "Admin email: " ADMIN_EMAIL
    read -s -p "Admin password: " ADMIN_PASSWORD
    echo
    
    log_success "Configuration collected successfully."
}

# Install system packages
install_system_packages() {
    log_info "Installing system packages..."
    
    # Update package lists
    sudo apt update
    
    # Install core packages
    log_info "Installing core system packages..."
    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        postgresql \
        postgresql-contrib \
        postgresql-client \
        redis-server \
        nginx \
        git \
        curl \
        wget \
        build-essential \
        pkg-config \
        libpq-dev \
        libssl-dev \
        libffi-dev \
        libjpeg-dev \
        libpng-dev \
        ffmpeg \
        supervisor \
        openssl \
        bc
    
    # Install Node.js for frontend building
    log_info "Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt install -y nodejs
    
    # Install optional packages
    if [[ "$ENABLE_OCR" == "y" ]]; then
        log_info "Installing OCR packages..."
        sudo apt install -y tesseract-ocr tesseract-ocr-eng
    fi
    
    log_success "System packages installed."
}

# Create system user
create_system_user() {
    log_info "Creating system user '$CUPCAKE_USER'..."
    
    if ! id "$CUPCAKE_USER" &>/dev/null; then
        sudo useradd --system --shell /bin/bash --home-dir /opt/cupcake --create-home "$CUPCAKE_USER"
        sudo usermod -a -G www-data "$CUPCAKE_USER"
        log_success "User '$CUPCAKE_USER' created."
    else
        log_info "User '$CUPCAKE_USER' already exists."
    fi
}

# Setup directories
setup_directories() {
    log_info "Setting up directories..."
    
    sudo mkdir -p "$VENV_DIR" "$APP_DIR" "$MEDIA_DIR" "$STATIC_DIR" "$LOG_DIR"
    sudo chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "/opt/cupcake"
    sudo chown -R "$CUPCAKE_USER:www-data" "$LOG_DIR"
    sudo chmod -R 755 "$MEDIA_DIR" "$STATIC_DIR"
    sudo chmod -R 750 "$LOG_DIR"
    
    log_success "Directories created and configured."
}

# Setup PostgreSQL
setup_postgresql() {
    log_info "Setting up PostgreSQL..."
    
    # Start and enable PostgreSQL
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    
    # Create database and user
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" || true
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" || true
    sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;" || true
    
    # Configure PostgreSQL for local connections
    PG_VERSION=$(sudo -u postgres psql -t -c "SELECT version();" | grep -oP '\d+\.\d+' | head -1)
    PG_CONFIG_DIR="/etc/postgresql/$PG_VERSION/main"
    
    if [[ -f "$PG_CONFIG_DIR/pg_hba.conf" ]]; then
        sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = 'localhost'/" "$PG_CONFIG_DIR/postgresql.conf"
        
        # Ensure local connections are allowed
        if ! sudo grep -q "local.*$DB_NAME.*$DB_USER.*md5" "$PG_CONFIG_DIR/pg_hba.conf"; then
            echo "local   $DB_NAME   $DB_USER   md5" | sudo tee -a "$PG_CONFIG_DIR/pg_hba.conf"
        fi
        
        sudo systemctl restart postgresql
    fi
    
    log_success "PostgreSQL configured."
}

# Setup Redis
setup_redis() {
    log_info "Setting up Redis..."
    
    # Configure Redis
    sudo sed -i 's/^# requirepass foobared/requirepass redis/' /etc/redis/redis.conf
    sudo sed -i 's/^bind 127.0.0.1 ::1/bind 127.0.0.1/' /etc/redis/redis.conf
    
    sudo systemctl start redis-server
    sudo systemctl enable redis-server
    
    log_success "Redis configured."
}

# Install Python application
install_python_app() {
    log_info "Installing Python application..."
    
    # Create virtual environment
    sudo -u "$CUPCAKE_USER" python3 -m venv "$VENV_DIR"
    
    # Copy application files
    sudo cp -r "$SCRIPT_DIR"/* "$APP_DIR/"
    sudo chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$APP_DIR"
    
    # Install Python requirements
    log_info "Installing Python packages..."
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
    
    # Additional packages for native installation
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install gunicorn
    
    log_success "Python application installed."
}

# Build frontend
build_frontend() {
    log_info "Building frontend application..."
    
    # Clone and build frontend
    FRONTEND_BUILD_DIR="/tmp/cupcake-ng-build"
    if [[ -d "$FRONTEND_BUILD_DIR" ]]; then
        rm -rf "$FRONTEND_BUILD_DIR"
    fi
    
    git clone https://github.com/noatgnu/cupcake-ng.git "$FRONTEND_BUILD_DIR"
    cd "$FRONTEND_BUILD_DIR"
    
    # Update environment configuration
    sed -i "s;https://cupcake.proteo.info;http://$HOSTNAME:$WEB_PORT;g" src/environments/environment.ts
    sed -i "s;http://localhost;http://$HOSTNAME:$WEB_PORT;g" src/environments/environment.ts
    
    # Install dependencies and build
    npm install
    npm run build
    
    # Copy built files to static directory
    sudo cp -r dist/browser/* "$STATIC_DIR/"
    sudo chown -R "$CUPCAKE_USER:www-data" "$STATIC_DIR"
    
    # Cleanup
    cd "$SCRIPT_DIR"
    rm -rf "$FRONTEND_BUILD_DIR"
    
    log_success "Frontend built and installed."
}

# Generate configuration files
generate_config_files() {
    log_info "Generating configuration files..."
    
    # Create Django settings override
    cat > "$APP_DIR/local_settings.py" << EOF
# Local settings for native installation
import os

DEBUG = False
ALLOWED_HOSTS = ['$HOSTNAME', 'localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': '$DB_NAME',
        'USER': '$DB_USER',
        'PASSWORD': '$DB_PASSWORD',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {'password': 'redis'}
        }
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],
            'channel_capacity': {
                'http.request': 200,
                'http.response!*': 10,
            },
        },
    },
}

RQ_QUEUES = {
    'default': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
        'PASSWORD': 'redis',
    },
    'docx': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
        'PASSWORD': 'redis',
    },
    'import': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
        'PASSWORD': 'redis',
    },
    'ocr': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
        'PASSWORD': 'redis',
    },
    'transcribe': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
        'PASSWORD': 'redis',
    },
}

SECRET_KEY = '$DJANGO_SECRET_KEY'

STATIC_URL = '/static/'
STATIC_ROOT = '$STATIC_DIR'

MEDIA_URL = '/media/'
MEDIA_ROOT = '$MEDIA_DIR'

CORS_ORIGIN_WHITELIST = [
    'http://$HOSTNAME:$WEB_PORT',
    'http://localhost:$WEB_PORT',
    'http://127.0.0.1:$WEB_PORT',
]

# Feature flags
USE_COTURN = False
USE_WHISPER = $([ "$ENABLE_WHISPER" == "y" ] && echo "True" || echo "False")
USE_OCR = $([ "$ENABLE_OCR" == "y" ] && echo "True" || echo "False")
USE_LLM = False

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '$LOG_DIR/django.log',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
EOF

    # Update main settings to import local settings
    if ! grep -q "from .local_settings import" "$APP_DIR/cupcake/settings.py"; then
        echo "# Import local settings" >> "$APP_DIR/cupcake/settings.py"
        echo "try:" >> "$APP_DIR/cupcake/settings.py"
        echo "    from .local_settings import *" >> "$APP_DIR/cupcake/settings.py"
        echo "except ImportError:" >> "$APP_DIR/cupcake/settings.py"
        echo "    pass" >> "$APP_DIR/cupcake/settings.py"
    fi
    
    sudo chown "$CUPCAKE_USER:$CUPCAKE_USER" "$APP_DIR/local_settings.py"
    
    log_success "Configuration files generated."
}

# Setup Nginx
setup_nginx() {
    log_info "Setting up Nginx..."
    
    # Create Nginx configuration
    sudo tee /etc/nginx/sites-available/cupcake << EOF
server {
    listen $WEB_PORT;
    server_name $HOSTNAME;
    client_max_body_size 100M;
    charset utf-8;

    # Frontend files
    location / {
        root $STATIC_DIR;
        try_files \$uri \$uri/ /index.html;
    }

    # Static files
    location /static/ {
        alias $STATIC_DIR/;
        expires 1y;
        add_header Cache-Control "public";
    }

    # Media files
    location /media/ {
        internal;
        alias $MEDIA_DIR/;
        add_header 'Access-Control-Allow-Origin' '*';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
        
        if (\$request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
    }

    # API endpoints
    location /api {
        proxy_pass http://127.0.0.1:8000/api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Admin interface
    location /admin {
        proxy_pass http://127.0.0.1:8000/admin;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # WebSocket endpoint
    location /ws {
        proxy_pass http://127.0.0.1:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    # Enable the site
    sudo ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
    
    # Remove default site if it exists
    sudo rm -f /etc/nginx/sites-enabled/default
    
    # Test and reload Nginx
    sudo nginx -t
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    
    log_success "Nginx configured."
}

# Setup systemd services
setup_services() {
    log_info "Setting up systemd services..."
    
    # Django/Gunicorn service
    sudo tee /etc/systemd/system/cupcake-web.service << EOF
[Unit]
Description=CUPCAKE Django Web Application
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=notify
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/gunicorn --workers 4 --bind 127.0.0.1:8000 --timeout 300 --access-logfile $LOG_DIR/access.log --error-logfile $LOG_DIR/error.log cupcake.asgi:application -k uvicorn.workers.UvicornWorker
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Worker services (if enabled)
    if [[ "$ENABLE_WORKERS" == "y" ]]; then
        # Main worker service
        sudo tee /etc/systemd/system/cupcake-worker.service << EOF
[Unit]
Description=CUPCAKE Background Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python manage.py rqworker default
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

        # Document export worker
        sudo tee /etc/systemd/system/cupcake-docx-worker.service << EOF
[Unit]
Description=CUPCAKE Document Export Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python manage.py rqworker docx
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

        # Data import worker
        sudo tee /etc/systemd/system/cupcake-import-worker.service << EOF
[Unit]
Description=CUPCAKE Data Import Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python manage.py rqworker import
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

        # OCR worker (if enabled)
        if [[ "$ENABLE_OCR" == "y" ]]; then
            sudo tee /etc/systemd/system/cupcake-ocr-worker.service << EOF
[Unit]
Description=CUPCAKE OCR Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python manage.py rqworker ocr
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        fi

        # Transcription worker (if enabled)
        if [[ "$ENABLE_WHISPER" == "y" ]]; then
            sudo tee /etc/systemd/system/cupcake-transcribe-worker.service << EOF
[Unit]
Description=CUPCAKE Transcription Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=$CUPCAKE_USER
Group=$CUPCAKE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python manage.py rqworker transcribe
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        fi
    fi
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    log_success "Systemd services configured."
}

# Initialize database
initialize_database() {
    log_info "Initializing database..."
    
    cd "$APP_DIR"
    
    # Run migrations
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py migrate
    
    # Collect static files
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py collectstatic --noinput
    
    # Create admin user
    sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py shell << EOF
from django.contrib.auth.models import User
from cc.models import LabGroup, StorageObject

# Create admin user
if not User.objects.filter(username='$ADMIN_USERNAME').exists():
    User.objects.create_superuser('$ADMIN_USERNAME', '$ADMIN_EMAIL', '$ADMIN_PASSWORD')
    print("Created admin user: $ADMIN_USERNAME")

# Create MS Facility lab group
ms_facility, created = LabGroup.objects.get_or_create(
    name="MS Facility",
    defaults={
        'description': 'Mass Spectrometry Facility',
        'is_professional': True
    }
)

if created:
    print("Created MS Facility lab group")

# Create storage object
admin_user = User.objects.filter(is_superuser=True).first()
if admin_user:
    storage_obj, created = StorageObject.objects.get_or_create(
        name="MS Facility Storage",
        defaults={
            'object_type': 'room',
            'description': 'Main storage for MS Facility',
            'user': admin_user
        }
    )
    
    if created:
        storage_obj.access_lab_groups.add(ms_facility)
        storage_obj.save()
        print("Created MS Facility storage object")
    
    if not ms_facility.service_storage:
        ms_facility.service_storage = storage_obj
        ms_facility.save()
        print("Assigned service storage to MS Facility")
EOF
    
    log_success "Database initialized."
}

# Start services
start_services() {
    log_info "Starting services..."
    
    # Start main web service
    sudo systemctl enable cupcake-web.service
    sudo systemctl start cupcake-web.service
    
    # Start worker services (if enabled)
    if [[ "$ENABLE_WORKERS" == "y" ]]; then
        sudo systemctl enable cupcake-worker.service
        sudo systemctl start cupcake-worker.service
        
        sudo systemctl enable cupcake-docx-worker.service
        sudo systemctl start cupcake-docx-worker.service
        
        sudo systemctl enable cupcake-import-worker.service
        sudo systemctl start cupcake-import-worker.service
        
        if [[ "$ENABLE_OCR" == "y" ]]; then
            sudo systemctl enable cupcake-ocr-worker.service
            sudo systemctl start cupcake-ocr-worker.service
        fi
        
        if [[ "$ENABLE_WHISPER" == "y" ]]; then
            sudo systemctl enable cupcake-transcribe-worker.service
            sudo systemctl start cupcake-transcribe-worker.service
        fi
    fi
    
    # Wait for services to start
    sleep 10
    
    log_success "Services started."
}

# Test installation
test_installation() {
    log_info "Testing installation..."
    
    # Test web service
    if systemctl is-active --quiet cupcake-web.service; then
        log_success "Web service is running"
    else
        log_error "Web service is not running"
        sudo systemctl status cupcake-web.service
        return 1
    fi
    
    # Test web accessibility
    if curl -f "http://localhost:$WEB_PORT" > /dev/null 2>&1; then
        log_success "Web interface is accessible"
    else
        log_warning "Web interface may not be fully ready yet"
    fi
    
    # Test database connection
    cd "$APP_DIR"
    if sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py dbshell -c "\q" 2>/dev/null; then
        log_success "Database connection is working"
    else
        log_error "Database connection failed"
        return 1
    fi
    
    log_success "Installation test completed."
}

# Generate management scripts
generate_management_scripts() {
    log_info "Generating management scripts..."
    
    mkdir -p "$INSTALL_DIR"
    
    # Main management script
    cat > "$INSTALL_DIR/manage_cupcake.sh" << 'EOF'
#!/bin/bash

# CUPCAKE Native Installation Management Script

CUPCAKE_USER="cupcake"
VENV_DIR="/opt/cupcake/venv"
APP_DIR="/opt/cupcake/app"

case "$1" in
    start)
        echo "Starting CUPCAKE services..."
        sudo systemctl start cupcake-web.service
        sudo systemctl start cupcake-worker.service 2>/dev/null || true
        sudo systemctl start cupcake-docx-worker.service 2>/dev/null || true
        sudo systemctl start cupcake-import-worker.service 2>/dev/null || true
        sudo systemctl start cupcake-ocr-worker.service 2>/dev/null || true
        sudo systemctl start cupcake-transcribe-worker.service 2>/dev/null || true
        echo "Services started."
        ;;
    stop)
        echo "Stopping CUPCAKE services..."
        sudo systemctl stop cupcake-web.service
        sudo systemctl stop cupcake-worker.service 2>/dev/null || true
        sudo systemctl stop cupcake-docx-worker.service 2>/dev/null || true
        sudo systemctl stop cupcake-import-worker.service 2>/dev/null || true
        sudo systemctl stop cupcake-ocr-worker.service 2>/dev/null || true
        sudo systemctl stop cupcake-transcribe-worker.service 2>/dev/null || true
        echo "Services stopped."
        ;;
    restart)
        $0 stop
        sleep 5
        $0 start
        ;;
    status)
        echo "CUPCAKE Services Status:"
        sudo systemctl status cupcake-web.service --no-pager
        sudo systemctl status cupcake-worker.service --no-pager 2>/dev/null || true
        sudo systemctl status cupcake-docx-worker.service --no-pager 2>/dev/null || true
        sudo systemctl status cupcake-import-worker.service --no-pager 2>/dev/null || true
        sudo systemctl status cupcake-ocr-worker.service --no-pager 2>/dev/null || true
        sudo systemctl status cupcake-transcribe-worker.service --no-pager 2>/dev/null || true
        ;;
    logs)
        echo "CUPCAKE Service Logs:"
        sudo journalctl -u cupcake-web.service -f
        ;;
    django)
        echo "Running Django management command: ${@:2}"
        cd "$APP_DIR"
        sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py "${@:2}"
        ;;
    backup)
        echo "Creating database backup..."
        BACKUP_FILE="/opt/cupcake/backup_$(date +%Y%m%d_%H%M%S).sql"
        sudo -u postgres pg_dump cupcake_db > "$BACKUP_FILE"
        echo "Backup created: $BACKUP_FILE"
        ;;
    update)
        echo "Updating CUPCAKE..."
        cd "$APP_DIR"
        git pull
        sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/pip" install -r requirements.txt
        sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py migrate
        sudo -u "$CUPCAKE_USER" "$VENV_DIR/bin/python" manage.py collectstatic --noinput
        $0 restart
        echo "Update completed."
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|django|backup|update}"
        echo ""
        echo "Commands:"
        echo "  start    - Start all CUPCAKE services"
        echo "  stop     - Stop all CUPCAKE services"
        echo "  restart  - Restart all CUPCAKE services"
        echo "  status   - Show status of all services"
        echo "  logs     - Show live logs from web service"
        echo "  django   - Run Django management commands"
        echo "  backup   - Create database backup"
        echo "  update   - Update CUPCAKE from git repository"
        echo ""
        echo "Examples:"
        echo "  $0 django createsuperuser"
        echo "  $0 django shell"
        echo "  $0 django dbshell"
        exit 1
        ;;
esac
EOF

    chmod +x "$INSTALL_DIR/manage_cupcake.sh"
    
    # Create convenience symlink
    sudo ln -sf "$INSTALL_DIR/manage_cupcake.sh" /usr/local/bin/cupcake
    
    log_success "Management scripts created."
}

# Main installation function
main() {
    echo "========================================"
    echo "CUPCAKE Native Installation Script"
    echo "========================================"
    echo "This script will install CUPCAKE without Docker for lower power systems."
    echo "Supports Ubuntu 20.04+ and Debian 11+"
    echo

    check_root
    detect_os
    check_system_requirements
    collect_configuration
    
    echo
    log_info "Starting installation with the following configuration:"
    echo "  Hostname: $HOSTNAME"
    echo "  Web Port: $WEB_PORT"
    echo "  Database: $DB_NAME (user: $DB_USER)"
    echo "  Features: OCR=$ENABLE_OCR, Whisper=$ENABLE_WHISPER, Workers=$ENABLE_WORKERS"
    echo
    
    read -p "Continue with installation? [y/N]: " CONFIRM_INSTALL
    if [[ "$CONFIRM_INSTALL" != "y" && "$CONFIRM_INSTALL" != "Y" ]]; then
        log_info "Installation cancelled."
        exit 0
    fi
    
    install_system_packages
    create_system_user
    setup_directories
    setup_postgresql
    setup_redis
    install_python_app
    build_frontend
    generate_config_files
    setup_nginx
    setup_services
    initialize_database
    start_services
    test_installation
    generate_management_scripts
    
    echo
    log_success "CUPCAKE installation completed successfully!"
    echo
    echo "========================================"
    echo "Installation Summary"
    echo "========================================"
    echo "Web Interface: http://$HOSTNAME:$WEB_PORT"
    echo "Admin Interface: http://$HOSTNAME:$WEB_PORT/admin"
    echo ""
    echo "Admin Credentials:"
    echo "  Username: $ADMIN_USERNAME"
    echo "  Email: $ADMIN_EMAIL"
    echo ""
    echo "File Locations:"
    echo "  Application: $APP_DIR"
    echo "  Media files: $MEDIA_DIR"
    echo "  Static files: $STATIC_DIR"
    echo "  Logs: $LOG_DIR"
    echo ""
    echo "Management Commands:"
    echo "  cupcake start       - Start services"
    echo "  cupcake stop        - Stop services"
    echo "  cupcake restart     - Restart services"
    echo "  cupcake status      - Check service status"
    echo "  cupcake logs        - View live logs"
    echo "  cupcake backup      - Create database backup"
    echo "  cupcake update      - Update from git repository"
    echo ""
    echo "Django Commands:"
    echo "  cupcake django createsuperuser"
    echo "  cupcake django shell"
    echo "  cupcake django migrate"
    echo ""
    echo "Service Management:"
    echo "  sudo systemctl status cupcake-web.service"
    echo "  sudo systemctl restart cupcake-web.service"
    echo "  sudo journalctl -u cupcake-web.service -f"
    echo ""
    echo "MS Facility has been configured with default storage."
    echo "========================================"
    
    if ! curl -f "http://localhost:$WEB_PORT" > /dev/null 2>&1; then
        echo
        log_warning "The web interface may need a few more minutes to fully start."
        log_info "You can check the status with: cupcake status"
        log_info "Or view logs with: cupcake logs"
    fi
}

# Run main function
main "$@"