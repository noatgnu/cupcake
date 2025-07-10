#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/cupcake_deployment"

echo "=== CUPCAKE Installation Script ==="
echo "This script will set up a new CUPCAKE deployment with custom configuration."
echo

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

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    if ! command -v openssl &> /dev/null; then
        log_warning "OpenSSL not found. Random string generation may not work."
    fi
    
    log_success "Prerequisites check completed."
}

# Collect user configuration
collect_configuration() {
    log_info "Collecting deployment configuration..."
    
    # Hostname configuration
    while true; do
        read -p "Enter the hostname for your CUPCAKE deployment (e.g., cupcake.yourlab.com): " HOSTNAME
        if validate_hostname "$HOSTNAME"; then
            break
        else
            log_error "Invalid hostname format. Please enter a valid hostname."
        fi
    done
    
    # Frontend port
    read -p "Enter the frontend port [default: 80]: " FRONTEND_PORT
    FRONTEND_PORT=${FRONTEND_PORT:-80}
    
    # Backend port  
    read -p "Enter the backend port [default: 8000]: " BACKEND_PORT
    BACKEND_PORT=${BACKEND_PORT:-8000}
    
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
    
    read -p "Enable COTURN (WebRTC TURN/STUN server)? [y/N]: " ENABLE_COTURN
    ENABLE_COTURN=${ENABLE_COTURN,,}
    
    read -p "Enable Whisper (Audio transcription worker)? [y/N]: " ENABLE_WHISPER
    ENABLE_WHISPER=${ENABLE_WHISPER,,}
    
    read -p "Enable OCR (Optical Character Recognition worker)? [y/N]: " ENABLE_OCR
    ENABLE_OCR=${ENABLE_OCR,,}
    
    read -p "Enable LLaMA (AI Protocol Summarization worker)? [y/N]: " ENABLE_LLAMA
    ENABLE_LLAMA=${ENABLE_LLAMA,,}
    
    read -p "Enable document export worker? [Y/n]: " ENABLE_DOCX
    ENABLE_DOCX=${ENABLE_DOCX,,}
    ENABLE_DOCX=${ENABLE_DOCX:-y}
    
    read -p "Enable data import worker? [Y/n]: " ENABLE_IMPORT
    ENABLE_IMPORT=${ENABLE_IMPORT,,}
    ENABLE_IMPORT=${ENABLE_IMPORT:-y}
    
    # Storage configuration
    echo
    log_info "Storage Configuration:"
    echo "Choose storage type for media and static files:"
    echo "1) Local storage (default, bind mounts)"
    echo "2) NFS network storage"
    echo "3) CIFS/SMB network storage"
    echo "4) S3-compatible object storage (with s3fs)"
    read -p "Choose storage type [1]: " STORAGE_TYPE
    STORAGE_TYPE=${STORAGE_TYPE:-1}
    
    case $STORAGE_TYPE in
        2)
            log_info "NFS Configuration:"
            read -p "NFS server address (e.g., 192.168.1.100): " NFS_SERVER
            read -p "NFS export path for media (e.g., /exports/cupcake/media): " NFS_MEDIA_PATH
            read -p "NFS export path for static (e.g., /exports/cupcake/static): " NFS_STATIC_PATH
            read -p "NFS mount options [default: nfsvers=4,rsize=1048576,wsize=1048576,hard,intr]: " NFS_OPTIONS
            NFS_OPTIONS=${NFS_OPTIONS:-"nfsvers=4,rsize=1048576,wsize=1048576,hard,intr"}
            ;;
        3)
            log_info "CIFS/SMB Configuration:"
            read -p "SMB server address (e.g., //192.168.1.100/cupcake): " SMB_SERVER
            read -p "SMB username: " SMB_USERNAME
            read -s -p "SMB password: " SMB_PASSWORD
            echo
            read -p "SMB domain [optional]: " SMB_DOMAIN
            read -p "CIFS mount options [default: uid=33,gid=33,iocharset=utf8]: " CIFS_OPTIONS
            CIFS_OPTIONS=${CIFS_OPTIONS:-"uid=33,gid=33,iocharset=utf8"}
            ;;
        4)
            log_info "S3 Object Storage Configuration:"
            read -p "S3 endpoint URL (e.g., https://s3.amazonaws.com): " S3_ENDPOINT
            read -p "S3 bucket name: " S3_BUCKET
            read -p "S3 access key: " S3_ACCESS_KEY
            read -s -p "S3 secret key: " S3_SECRET_KEY
            echo
            read -p "S3 region [default: us-east-1]: " S3_REGION
            S3_REGION=${S3_REGION:-"us-east-1"}
            ;;
    esac

    # Admin user configuration
    echo
    log_info "Initial Admin User Configuration:"
    read -p "Admin username: " ADMIN_USERNAME
    read -p "Admin email: " ADMIN_EMAIL
    read -s -p "Admin password: " ADMIN_PASSWORD
    echo
    
    log_success "Configuration collected successfully."
}

# Create deployment directory
create_deployment_directory() {
    log_info "Creating deployment directory..."
    
    if [[ -d "$INSTALL_DIR" ]]; then
        read -p "Deployment directory already exists. Remove it? [y/N]: " REMOVE_DIR
        if [[ "$REMOVE_DIR" == "y" || "$REMOVE_DIR" == "Y" ]]; then
            rm -rf "$INSTALL_DIR"
        else
            log_error "Cannot proceed with existing directory. Exiting."
            exit 1
        fi
    fi
    
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR/dockerfiles"
    mkdir -p "$INSTALL_DIR/nginx-conf"
    mkdir -p "$INSTALL_DIR/scripts"
    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/media"
    mkdir -p "$INSTALL_DIR/staticfiles"
    
    # Set proper permissions for media and static directories
    chmod 755 "$INSTALL_DIR/media"
    chmod 755 "$INSTALL_DIR/staticfiles"
    
    log_success "Deployment directory created at $INSTALL_DIR"
}

# Generate frontend Dockerfile with hostname replacement
generate_frontend_dockerfile() {
    log_info "Generating frontend Dockerfile with hostname replacement..."
    
    cat > "$INSTALL_DIR/dockerfiles/Dockerfile-frontend-custom" << EOF
FROM node:20-bookworm-slim

WORKDIR /app
RUN apt update
RUN apt -y upgrade
RUN apt install -y git
RUN git clone https://github.com/noatgnu/cupcake-ng.git
WORKDIR /app/cupcake-ng

# Replace hostname in environment configuration
RUN sed -i 's;https://cupcake.proteo.info;http://${HOSTNAME}:${FRONTEND_PORT};g' src/environments/environment.ts
RUN sed -i 's;http://localhost;http://${HOSTNAME}:${FRONTEND_PORT};g' src/environments/environment.ts

# Install dependencies and build
RUN npm install
RUN npm run build

FROM nginx:latest

# Copy built application
COPY --from=0 /app/cupcake-ng/dist/browser /usr/share/nginx/html

EXPOSE 80
EOF
    
    log_success "Frontend Dockerfile generated with hostname: $HOSTNAME"
}

# Generate nginx configuration
generate_nginx_config() {
    log_info "Generating nginx configuration..."
    
    cat > "$INSTALL_DIR/nginx-conf/cc-custom.conf" << EOF
# Nginx configuration for CUPCAKE deployment

# Define the upstream server (Django backend)
upstream django {
    server cc:${BACKEND_PORT};
}

# Configuration for the server
server {
    listen 80;
    server_name ${HOSTNAME};
    client_max_body_size 100M;
    charset utf-8;

    # Frontend serving
    location / {
        proxy_pass http://ccfrontend:80;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Static files
    location /static/ {
        alias /static/;
        expires 1y;
        add_header Cache-Control "public";
    }

    # Media files
    location /media/ {
        internal;
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
        alias /media/;
    }

    # API endpoints
    location /api {
        proxy_pass http://django/api;
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
        proxy_pass http://django/admin;
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
        proxy_pass http://django/ws;
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
    
    # Generate custom nginx Dockerfile
    cat > "$INSTALL_DIR/dockerfiles/Dockerfile-nginx-custom" << EOF
FROM nginx:1.21.3

RUN rm -rf /etc/nginx/user.conf.d/*
COPY ./nginx-conf/cc-custom.conf /etc/nginx/conf.d/cc.conf
EOF
    
    log_success "Nginx configuration generated for hostname: $HOSTNAME"
}

# Generate volume configuration based on storage type
generate_volume_config() {
    case $STORAGE_TYPE in
        1)
            # Local storage
            NGINX_VOLUMES="      - ./media:/media/:rw
      - ./staticfiles:/static/:ro"
            DJANGO_VOLUMES="      - ./media:/app/media/:rw
      - ./staticfiles:/app/staticfiles/:rw"
            WORKER_VOLUMES="      - ./media:/app/media/:rw"
            DOCKER_VOLUMES=""
            ;;
        2)
            # NFS storage
            NGINX_VOLUMES="      - media_nfs:/media/:rw
      - static_nfs:/static/:ro"
            DJANGO_VOLUMES="      - media_nfs:/app/media/:rw
      - static_nfs:/app/staticfiles/:rw"
            WORKER_VOLUMES="      - media_nfs:/app/media/:rw"
            DOCKER_VOLUMES="
volumes:
  media_nfs:
    driver: local
    driver_opts:
      type: nfs
      o: addr=${NFS_SERVER},${NFS_OPTIONS}
      device: \"${NFS_MEDIA_PATH}\"
  static_nfs:
    driver: local
    driver_opts:
      type: nfs
      o: addr=${NFS_SERVER},${NFS_OPTIONS}
      device: \"${NFS_STATIC_PATH}\""
            ;;
        3)
            # CIFS/SMB storage
            NGINX_VOLUMES="      - media_cifs:/media/:rw
      - static_cifs:/static/:ro"
            DJANGO_VOLUMES="      - media_cifs:/app/media/:rw
      - static_cifs:/app/staticfiles/:rw"
            WORKER_VOLUMES="      - media_cifs:/app/media/:rw"
            SMB_CREDENTIALS="username=${SMB_USERNAME},password=${SMB_PASSWORD}"
            if [[ -n "$SMB_DOMAIN" ]]; then
                SMB_CREDENTIALS="${SMB_CREDENTIALS},domain=${SMB_DOMAIN}"
            fi
            DOCKER_VOLUMES="
volumes:
  media_cifs:
    driver: local
    driver_opts:
      type: cifs
      o: \"${SMB_CREDENTIALS},${CIFS_OPTIONS}\"
      device: \"${SMB_SERVER}/media\"
  static_cifs:
    driver: local
    driver_opts:
      type: cifs
      o: \"${SMB_CREDENTIALS},${CIFS_OPTIONS}\"
      device: \"${SMB_SERVER}/static\""
            ;;
        4)
            # S3 storage (requires s3fs container)
            NGINX_VOLUMES="      - media_s3:/media/:rw
      - static_s3:/static/:ro"
            DJANGO_VOLUMES="      - media_s3:/app/media/:rw
      - static_s3:/app/staticfiles/:rw"
            WORKER_VOLUMES="      - media_s3:/app/media/:rw"
            DOCKER_VOLUMES="
volumes:
  media_s3:
  static_s3:"
            ;;
    esac
}

# Generate docker-compose.yml
generate_docker_compose() {
    log_info "Generating docker-compose.yml..."
    
    # Generate volume configuration
    generate_volume_config
    
    cat > "$INSTALL_DIR/docker-compose.yml" << EOF
services:
  ccnginx:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-nginx-custom
    container_name: ccnginx
    restart: always
    ports:
      - "${FRONTEND_PORT}:80"
    volumes:
${NGINX_VOLUMES}
    depends_on:
      - cc
      - ccfrontend
    networks:
      - cc-net

  ccfrontend:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-frontend-custom
    container_name: ccfrontend
    restart: always
    networks:
      - cc-net

  cc:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile
      network: host
    ports:
      - "${BACKEND_PORT}:8000"
    container_name: cc
    volumes:
${DJANGO_VOLUMES}
    env_file:
      - .env
    depends_on:
      ccdb:
        condition: service_healthy
      ccredis:
        condition: service_started
    networks:
      - cc-net
    restart: always

EOF

    # Add optional workers
    if [[ "$ENABLE_DOCX" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccdocx:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-export-worker
      network: host
    container_name: ccdocx
    volumes:
${WORKER_VOLUMES}
    env_file:
      - .env
    networks:
      - cc-net
    restart: always

EOF
    fi

    if [[ "$ENABLE_IMPORT" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccimport:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-import-data-worker
      network: host
    container_name: ccimport
    volumes:
${WORKER_VOLUMES}
    env_file:
      - .env
    networks:
      - cc-net
    restart: always

EOF
    fi

    if [[ "$ENABLE_WHISPER" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccworker:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-transcribe-worker
      network: host
    container_name: ccworker
    volumes:
${WORKER_VOLUMES}
    env_file:
      - .env
    networks:
      - cc-net
    restart: always

EOF
    fi

    if [[ "$ENABLE_OCR" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccocr:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-ocr
      network: host
    container_name: ccocr
    volumes:
${WORKER_VOLUMES}
    env_file:
      - .env
    networks:
      - cc-net
    restart: always

EOF
    fi

    if [[ "$ENABLE_LLAMA" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccllama:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-llama-worker
      network: host
    container_name: ccllama
    env_file:
      - .env
    networks:
      - cc-net
    restart: always

EOF
    fi

    if [[ "$ENABLE_COTURN" == "y" ]]; then
        cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  coturn:
    build:
      context: .
      dockerfile: dockerfiles/Dockerfile-turn-stun
      network: host
    container_name: coturn
    ports:
      - "3478:3478/udp"
      - "3478:3478/tcp"
      - "49152-65535:49152-65535/udp"
    networks:
      - cc-net
    restart: always

EOF
    fi

    # Add database and redis
    cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  ccdb:
    container_name: ccdb
    image: postgres:14
    restart: always
    shm_size: '2gb'
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_HOST_AUTH_METHOD: trust
    ports:
      - "5433:5432"
    volumes:
      - ./data:/var/lib/postgresql/data
    networks:
      - cc-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 30s
      timeout: 10s
      retries: 5

  ccredis:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-redis
      network: host
    container_name: ccredis
    restart: always
    env_file:
      - .env
    ports:
      - "6380:6379"
    networks:
      - cc-net

EOF

# Add S3 service if S3 storage is selected
if [[ "$STORAGE_TYPE" == "4" ]]; then
    cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
  s3fs:
    image: efrecon/s3fs
    privileged: true
    environment:
      - AWS_S3_ACCESS_KEY_ID=${S3_ACCESS_KEY}
      - AWS_S3_SECRET_ACCESS_KEY=${S3_SECRET_KEY}
      - AWS_S3_BUCKET=${S3_BUCKET}
      - AWS_S3_URL=${S3_ENDPOINT}
      - AWS_S3_REGION=${S3_REGION}
    volumes:
      - media_s3:/mnt/s3:rshared
    networks:
      - cc-net
    restart: always

EOF
fi

# Add the volumes and networks section
cat >> "$INSTALL_DIR/docker-compose.yml" << EOF
${DOCKER_VOLUMES}

networks:
  cc-net:
EOF
    
    log_success "Docker Compose configuration generated."
}

# Generate .env file
generate_env_file() {
    log_info "Generating .env file..."
    
    cat > "$INSTALL_DIR/.env" << EOF
# CUPCAKE Deployment Configuration
# Generated on $(date)

# Django Configuration
SECRET_KEY=${DJANGO_SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${HOSTNAME},localhost,127.0.0.1
CORS_ORIGIN_WHITELIST=http://${HOSTNAME}:${FRONTEND_PORT}

# Database Configuration
POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASSWORD}

# Feature Flags
USE_COTURN=$([ "$ENABLE_COTURN" == "y" ] && echo "True" || echo "False")
USE_WHISPER=$([ "$ENABLE_WHISPER" == "y" ] && echo "True" || echo "False")
USE_OCR=$([ "$ENABLE_OCR" == "y" ] && echo "True" || echo "False")
USE_LLM=$([ "$ENABLE_LLAMA" == "y" ] && echo "True" || echo "False")

# Redis Configuration
REDIS_HOST=ccredis
REDIS_PORT=6379

# Storage Configuration
STORAGE_TYPE=${STORAGE_TYPE}
$([ "$STORAGE_TYPE" == "2" ] && echo "NFS_SERVER=${NFS_SERVER}")
$([ "$STORAGE_TYPE" == "3" ] && echo "SMB_SERVER=${SMB_SERVER}")
$([ "$STORAGE_TYPE" == "4" ] && echo "S3_BUCKET=${S3_BUCKET}")

# Admin Configuration (for initialization)
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
EOF
    
    log_success ".env file generated."
}

# Generate setup scripts
generate_setup_scripts() {
    log_info "Generating setup scripts..."
    
    # Database initialization script
    cat > "$INSTALL_DIR/scripts/init_database.py" << 'EOF'
#!/usr/bin/env python3
import os
import sys
import django
from django.conf import settings

# Add the project directory to Python path
sys.path.insert(0, '/app')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
django.setup()

from django.contrib.auth.models import User
from cc.models import LabGroup, StorageObject

def create_admin_user():
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@localhost')
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
    
    if not User.objects.filter(username=admin_username).exists():
        User.objects.create_superuser(
            username=admin_username,
            email=admin_email,
            password=admin_password
        )
        print(f"Created admin user: {admin_username}")
    else:
        print(f"Admin user {admin_username} already exists")

def create_ms_facility():
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
    else:
        print("MS Facility lab group already exists")
    
    # Get or create admin user for storage ownership
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        print("No admin user found for storage object creation")
        return
    
    # Create storage object for MS Facility
    storage_obj, created = StorageObject.objects.get_or_create(
        name="MS Facility Storage",
        defaults={
            'object_type': 'room',
            'description': 'Main storage for MS Facility',
            'user': admin_user
        }
    )
    
    if created:
        # Add access to MS Facility group
        storage_obj.access_lab_groups.add(ms_facility)
        storage_obj.save()
        print("Created MS Facility storage object")
    else:
        print("MS Facility storage object already exists")
    
    # Set as service storage for MS Facility
    if not ms_facility.service_storage:
        ms_facility.service_storage = storage_obj
        ms_facility.save()
        print("Assigned service storage to MS Facility")

if __name__ == '__main__':
    try:
        create_admin_user()
        create_ms_facility()
        print("Database initialization completed successfully")
    except Exception as e:
        print(f"Error during database initialization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
EOF
    
    # Main deployment script
    cat > "$INSTALL_DIR/deploy.sh" << 'EOF'
#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Load environment variables
if [[ -f .env ]]; then
    source .env
fi

log_info "Starting CUPCAKE deployment..."

# Build and start services
log_info "Building and starting Docker services..."
docker-compose up -d --build

# Wait for database to be ready
log_info "Waiting for database to be ready..."
timeout=120
while ! docker-compose exec -T ccdb pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} > /dev/null 2>&1; do
    echo -n "."
    sleep 2
    timeout=$((timeout - 2))
    if [[ $timeout -le 0 ]]; then
        log_error "Database failed to start within 2 minutes"
        docker-compose logs ccdb
        exit 1
    fi
done
echo
log_success "Database is ready"

# Wait a bit more for Django to be ready
log_info "Waiting for Django service to be ready..."
sleep 15

# Run migrations
log_info "Running database migrations..."
if docker-compose exec -T cc python manage.py migrate; then
    log_success "Migrations completed"
else
    log_error "Migration failed"
    docker-compose logs cc
    exit 1
fi

# Collect static files
log_info "Collecting static files..."
if docker-compose exec -T cc python manage.py collectstatic --noinput; then
    log_success "Static files collected"
else
    log_warning "Static files collection failed (continuing anyway)"
fi

# Ensure media directory has proper permissions
log_info "Setting up media directory permissions..."
if docker-compose exec -T cc chown -R www-data:www-data /app/media/; then
    log_success "Media directory permissions set"
else
    log_warning "Could not set media directory permissions (continuing anyway)"
fi

# Copy initialization script and run it
log_info "Copying and running database initialization..."
docker cp scripts/init_database.py cc:/tmp/init_database.py
if docker-compose exec -T cc python /tmp/init_database.py; then
    log_success "Database initialization completed"
else
    log_error "Database initialization failed"
    exit 1
fi

# Wait for all services to be ready
log_info "Waiting for all services to stabilize..."
sleep 10

# Test connectivity
log_info "Testing connectivity..."
FRONTEND_URL="http://localhost:${FRONTEND_PORT:-80}"
if curl -f "$FRONTEND_URL" > /dev/null 2>&1; then
    log_success "Frontend is accessible at $FRONTEND_URL"
else
    log_warning "Frontend may not be fully ready yet"
fi

# Test backend health
if docker-compose exec -T cc python -c "import requests; requests.get('http://localhost:8000/admin/', timeout=5)" 2>/dev/null; then
    log_success "Backend is responding"
else
    log_warning "Backend may not be fully ready yet"
fi

log_success "CUPCAKE deployment completed!"
echo
echo "=================================="
echo "CUPCAKE Deployment Summary"
echo "=================================="
echo "Frontend URL: http://${HOSTNAME}:${FRONTEND_PORT:-80}"
echo "Backend URL: http://${HOSTNAME}:${BACKEND_PORT:-8000}"
echo "Admin Interface: http://${HOSTNAME}:${FRONTEND_PORT:-80}/admin"
echo
echo "Admin Credentials:"
echo "  Username: ${ADMIN_USERNAME}"
echo "  Email: ${ADMIN_EMAIL}"
echo
echo "Services Status:"
docker-compose ps
echo
echo "Management Commands:"
echo "  Stop services: docker-compose down"
echo "  View logs: docker-compose logs -f [service_name]"
echo "  Restart services: docker-compose restart"
echo "  Update services: docker-compose up -d --build"
echo
echo "MS Facility has been configured with default storage."
echo "=================================="
EOF
    
    chmod +x "$INSTALL_DIR/scripts/init_database.py"
    chmod +x "$INSTALL_DIR/deploy.sh"
    
    log_success "Setup scripts generated."
}

# Copy source files
copy_source_files() {
    log_info "Copying source files to deployment directory..."
    
    # Copy core application files
    cp -r "$SCRIPT_DIR/cc" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/cupcake" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/manage.py" "$INSTALL_DIR/"
    
    # Copy requirements if exists
    if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    else
        log_warning "requirements.txt not found, you may need to add it manually"
    fi
    
    # Copy existing dockerfiles (excluding the ones we'll generate)
    for dockerfile in "$SCRIPT_DIR/dockerfiles"/*; do
        filename=$(basename "$dockerfile")
        if [[ "$filename" != "Dockerfile-frontend-custom" && "$filename" != "Dockerfile-nginx-custom" ]]; then
            cp "$dockerfile" "$INSTALL_DIR/dockerfiles/"
        fi
    done
    
    log_success "Source files copied to deployment directory."
}

# Main installation function
main() {
    echo "Starting CUPCAKE installation process..."
    echo "This will create a new deployment with customized configuration."
    echo
    
    check_prerequisites
    collect_configuration
    create_deployment_directory
    generate_frontend_dockerfile
    generate_nginx_config  
    generate_docker_compose
    generate_env_file
    generate_setup_scripts
    copy_source_files
    
    echo
    log_success "CUPCAKE installation files generated successfully!"
    echo
    echo "Generated deployment at: $INSTALL_DIR"
    echo
    echo "Files created:"
    echo "  ├── docker-compose.yml (customized for your configuration)"
    echo "  ├── .env (environment variables)"
    echo "  ├── dockerfiles/"
    echo "  │   ├── Dockerfile-frontend-custom (with hostname: $HOSTNAME)"
    echo "  │   └── Dockerfile-nginx-custom (custom nginx config)"
    echo "  ├── nginx-conf/"
    echo "  │   └── cc-custom.conf (nginx configuration)"
    echo "  ├── scripts/"
    echo "  │   └── init_database.py (database initialization)"
    echo "  └── deploy.sh (deployment script)"
    echo
    
    read -p "Would you like to start the deployment now? [y/N]: " START_DEPLOY
    if [[ "$START_DEPLOY" == "y" || "$START_DEPLOY" == "Y" ]]; then
        log_info "Starting deployment..."
        cd "$INSTALL_DIR"
        ./deploy.sh
    else
        echo
        log_info "To deploy later, run:"
        echo "  cd $INSTALL_DIR"
        echo "  ./deploy.sh"
        echo
        log_info "To customize further, edit the files in $INSTALL_DIR before deploying"
    fi
}

# Run main function
main "$@"