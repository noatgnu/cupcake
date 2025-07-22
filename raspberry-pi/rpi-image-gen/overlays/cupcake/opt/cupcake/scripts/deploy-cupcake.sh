#!/bin/bash
# CUPCAKE Deployment Script for Raspberry Pi 5
# Deploys CUPCAKE source code and configures services

set -e

CUPCAKE_REPO="https://github.com/noatgnu/cupcake.git"
CUPCAKE_HOME="/opt/cupcake"
CUPCAKE_SRC="$CUPCAKE_HOME/src"
CUPCAKE_VENV="$CUPCAKE_HOME/venv"

echo "CUPCAKE Deployment Script"
echo "========================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root"
    exit 1
fi

# Create script directories if they don't exist
mkdir -p /opt/cupcake/scripts

# Function to print status
print_status() {
    echo ">>> $1"
}

print_status "Starting CUPCAKE deployment..."

# Stop any running services
systemctl stop cupcake || true
systemctl stop celery || true
systemctl stop nginx || true

# Clone or update CUPCAKE repository
if [ -d "$CUPCAKE_SRC" ]; then
    print_status "Updating CUPCAKE source code..."
    cd "$CUPCAKE_SRC"
    sudo -u cupcake git pull origin master
else
    print_status "Cloning CUPCAKE repository..."
    sudo -u cupcake git clone "$CUPCAKE_REPO" "$CUPCAKE_SRC"
    chown -R cupcake:cupcake "$CUPCAKE_SRC"
fi

cd "$CUPCAKE_SRC"

# Activate Python virtual environment
print_status "Activating Python environment..."
source "$CUPCAKE_VENV/bin/activate"

# Install/update Python dependencies
print_status "Installing Python dependencies..."
pip install -r requirements.txt

# Create production settings
print_status "Creating production settings..."
cat > "$CUPCAKE_SRC/cupcake/settings/production.py" << 'EOF'
# CUPCAKE Production Settings for Raspberry Pi 5

from .base import *
import os

# Production security settings
DEBUG = False
ALLOWED_HOSTS = ['*']  # Configure with actual domain names in production

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('CUPCAKE_DB_NAME', 'cupcake_db'),
        'USER': os.environ.get('CUPCAKE_DB_USER', 'cupcake'),
        'PASSWORD': os.environ.get('CUPCAKE_DB_PASSWORD', 'changeme'),
        'HOST': os.environ.get('CUPCAKE_DB_HOST', 'localhost'),
        'PORT': os.environ.get('CUPCAKE_DB_PORT', '5432'),
        'OPTIONS': {
            'sslmode': 'prefer',
        }
    }
}

# Redis configuration
REDIS_HOST = os.environ.get('CUPCAKE_REDIS_HOST', 'localhost')
REDIS_PORT = os.environ.get('CUPCAKE_REDIS_PORT', '6379')
REDIS_PASSWORD = os.environ.get('CUPCAKE_REDIS_PASSWORD', 'redis_password_change_me')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Celery configuration
CELERY_BROKER_URL = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
CELERY_RESULT_BACKEND = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'

# Static and media files
STATIC_ROOT = '/var/www/cupcake/static'
MEDIA_ROOT = '/var/www/cupcake/media'
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

# Security settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/cupcake/django.log',
            'maxBytes': 10*1024*1024,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'cupcake': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
EOF

chown cupcake:cupcake "$CUPCAKE_SRC/cupcake/settings/production.py"

# Create environment file
print_status "Creating environment configuration..."
cat > "$CUPCAKE_HOME/.env" << 'EOF'
# CUPCAKE Environment Configuration

# Django settings
DJANGO_SETTINGS_MODULE=cupcake.settings.production
SECRET_KEY=change-this-secret-key-in-production

# Database
CUPCAKE_DB_NAME=cupcake_db
CUPCAKE_DB_USER=cupcake
CUPCAKE_DB_PASSWORD=changeme
CUPCAKE_DB_HOST=localhost
CUPCAKE_DB_PORT=5432

# Redis
CUPCAKE_REDIS_HOST=localhost
CUPCAKE_REDIS_PORT=6379
CUPCAKE_REDIS_PASSWORD=redis_password_change_me

# External services (configure as needed)
PROTOCOLS_IO_ACCESS_TOKEN=
ANTHROPIC_API_KEY=
COTURN_SECRET=
COTURN_SERVER=
COTURN_PORT=3478

# Features
USE_LLM=false
USE_WHISPER=true
USE_WHISPER_CPP=true
USE_OCR=false
USE_COTURN=false

# Whisper.cpp configuration
WHISPER_MODEL_PATH=/opt/whisper/models
WHISPER_SERVICE_ENDPOINT=http://localhost:8002
EOF

chown cupcake:cupcake "$CUPCAKE_HOME/.env"
chmod 600 "$CUPCAKE_HOME/.env"

# Set environment variables for this session
export DJANGO_SETTINGS_MODULE=cupcake.settings.production
export $(grep -v '^#' "$CUPCAKE_HOME/.env" | xargs)

# Run Django management commands
print_status "Running Django migrations..."
python manage.py makemigrations
python manage.py migrate

print_status "Collecting static files..."
python manage.py collectstatic --noinput

# Create systemd service files
print_status "Creating systemd services..."

cat > /etc/systemd/system/cupcake.service << 'SERVICE_EOF'
[Unit]
Description=CUPCAKE Web Application
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=notify
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/src
EnvironmentFile=/opt/cupcake/.env
ExecStart=/opt/cupcake/venv/bin/gunicorn \
    --bind 127.0.0.1:8000 \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 300 \
    --keep-alive 2 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --preload \
    cupcake.asgi:application
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat > /etc/systemd/system/cupcake-websocket.service << 'SERVICE_EOF'
[Unit]
Description=CUPCAKE WebSocket Server
After=network.target postgresql.service redis.service cupcake.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/src
EnvironmentFile=/opt/cupcake/.env
ExecStart=/opt/cupcake/venv/bin/python manage.py runserver 127.0.0.1:8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat > /etc/systemd/system/cupcake-celery.service << 'SERVICE_EOF'
[Unit]
Description=CUPCAKE Celery Worker
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=cupcake
Group=cupcake
WorkingDirectory=/opt/cupcake/src
EnvironmentFile=/opt/cupcake/.env
ExecStart=/opt/cupcake/venv/bin/celery -A cupcake worker -l info --concurrency=2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# Reload systemd and enable services
systemctl daemon-reload
systemctl enable cupcake
systemctl enable cupcake-websocket
systemctl enable cupcake-celery

# Start services
print_status "Starting CUPCAKE services..."
systemctl start postgresql
systemctl start redis-server
systemctl start cupcake
systemctl start cupcake-websocket
systemctl start cupcake-celery
systemctl start nginx

# Check service status
print_status "Checking service status..."
systemctl is-active --quiet cupcake && echo "✓ CUPCAKE web service is running" || echo "✗ CUPCAKE web service failed to start"
systemctl is-active --quiet cupcake-websocket && echo "✓ CUPCAKE websocket service is running" || echo "✗ CUPCAKE websocket service failed to start"
systemctl is-active --quiet cupcake-celery && echo "✓ CUPCAKE celery worker is running" || echo "✗ CUPCAKE celery worker failed to start"
systemctl is-active --quiet nginx && echo "✓ Nginx is running" || echo "✗ Nginx failed to start"

print_status "Creating superuser account..."
echo "You can create a superuser account by running:"
echo "sudo -u cupcake /opt/cupcake/venv/bin/python /opt/cupcake/src/manage.py createsuperuser"

print_status "CUPCAKE deployment completed successfully!"
echo
echo "CUPCAKE is now running and accessible at:"
echo "  - HTTP:  http://$(hostname -I | awk '{print $1}')"
echo "  - HTTPS: https://$(hostname -I | awk '{print $1}') (self-signed certificate)"
echo
echo "Next steps:"
echo "1. Set up proper SSL certificates with Let's Encrypt"
echo "2. Configure domain name in production settings"
echo "3. Update passwords in /opt/cupcake/.env"
echo "4. Create superuser account"
echo "5. Configure external services (if needed)"
echo
echo "For SSL setup, run: /opt/cupcake/scripts/setup-ssl.sh your-domain.com"