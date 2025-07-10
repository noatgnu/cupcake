#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/cupcake_cloudflare_deployment"

echo "=== CUPCAKE Cloudflare Tunnel Installation Script ==="
echo "This script will set up CUPCAKE with Cloudflare Tunnel for secure remote access."
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

# Function to validate Cloudflare tunnel token
validate_tunnel_token() {
    local token=$1
    if [[ $token =~ ^[a-zA-Z0-9_-]{120,200}$ ]]; then
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
    log_info "Collecting Cloudflare Tunnel configuration..."
    
    echo "=== Cloudflare Configuration ==="
    echo "Before proceeding, make sure you have:"
    echo "1. A Cloudflare account with your domain configured"
    echo "2. Created a Cloudflare Tunnel in the dashboard"
    echo "3. Generated a tunnel token"
    echo
    
    # Hostname configuration (will be the public domain)
    while true; do
        read -p "Enter your Cloudflare domain (e.g., cupcake.yourdomain.com): " HOSTNAME
        if validate_hostname "$HOSTNAME"; then
            break
        else
            log_error "Invalid hostname format. Please enter a valid hostname."
        fi
    done
    
    # Cloudflare tunnel token
    echo
    echo "Cloudflare Tunnel Token:"
    echo "You can find this in your Cloudflare dashboard under Zero Trust > Access > Tunnels"
    echo "Copy the token from your tunnel configuration."
    while true; do
        read -s -p "Enter your Cloudflare Tunnel token: " TUNNEL_TOKEN
        echo
        if [[ -n "$TUNNEL_TOKEN" ]]; then
            break
        else
            log_error "Tunnel token cannot be empty."
        fi
    done
    
    # Internal ports (these won't be exposed externally)
    read -p "Enter the internal frontend port [default: 80]: " INTERNAL_FRONTEND_PORT
    INTERNAL_FRONTEND_PORT=${INTERNAL_FRONTEND_PORT:-80}
    
    read -p "Enter the internal backend port [default: 8000]: " INTERNAL_BACKEND_PORT
    INTERNAL_BACKEND_PORT=${INTERNAL_BACKEND_PORT:-8000}
    
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
    
    # Cloudflare specific options
    echo
    log_info "Cloudflare Specific Configuration:"
    
    read -p "Enable Cloudflare Access (Zero Trust authentication)? [y/N]: " ENABLE_CF_ACCESS
    ENABLE_CF_ACCESS=${ENABLE_CF_ACCESS,,}
    
    read -p "Enable HTTP/2 and gRPC support? [Y/n]: " ENABLE_HTTP2
    ENABLE_HTTP2=${ENABLE_HTTP2,,}
    ENABLE_HTTP2=${ENABLE_HTTP2:-y}
    
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
    mkdir -p "$INSTALL_DIR/cloudflare-conf"
    mkdir -p "$INSTALL_DIR/scripts"
    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/media"
    mkdir -p "$INSTALL_DIR/staticfiles"
    
    # Set proper permissions for media and static directories
    chmod 755 "$INSTALL_DIR/media"
    chmod 755 "$INSTALL_DIR/staticfiles"
    
    log_success "Deployment directory created at $INSTALL_DIR"
}

# Generate Cloudflare configuration
generate_cloudflare_config() {
    log_info "Generating Cloudflare Tunnel configuration..."
    
    cat > "$INSTALL_DIR/cloudflare-conf/config.yml" << EOF
tunnel: ${TUNNEL_TOKEN}
credentials-file: /etc/cloudflared/cert.pem

# Configure ingress rules
ingress:
  # Main application
  - hostname: ${HOSTNAME}
    service: http://ccnginx:${INTERNAL_FRONTEND_PORT}
    originRequest:
      # Disable chunked transfer encoding for better compatibility
      disableChunkedEncoding: true
      # Set timeouts
      connectTimeout: 30s
      tlsTimeout: 10s
      tcpKeepAlive: 30s
      # Enable HTTP/2 if requested
$([ "$ENABLE_HTTP2" == "y" ] && echo "      http2Origin: true")
  
  # WebSocket endpoint (for real-time features)
  - hostname: ${HOSTNAME}
    path: /ws/*
    service: http://ccnginx:${INTERNAL_FRONTEND_PORT}
    originRequest:
      # WebSocket specific settings
      noTLSVerify: false
      
  # API endpoint with longer timeouts for large uploads
  - hostname: ${HOSTNAME}
    path: /api/*
    service: http://ccnginx:${INTERNAL_FRONTEND_PORT}
    originRequest:
      connectTimeout: 60s
      tlsTimeout: 10s
      
  # Catch-all rule (required)
  - service: http_status:404

# Log configuration
logDirectory: /var/log/cloudflared
logLevel: info

# Metrics
metrics: 0.0.0.0:8080
EOF

    # Generate cloudflared Dockerfile
    cat > "$INSTALL_DIR/dockerfiles/Dockerfile-cloudflared" << EOF
FROM cloudflare/cloudflared:latest

# Copy configuration
COPY cloudflare-conf/config.yml /etc/cloudflared/config.yml

# Create log directory
RUN mkdir -p /var/log/cloudflared

# Set permissions
USER root
RUN chmod 600 /etc/cloudflared/config.yml

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
  CMD cloudflared tunnel --config /etc/cloudflared/config.yml info || exit 1

# Run cloudflared
CMD ["cloudflared", "tunnel", "--config", "/etc/cloudflared/config.yml", "run"]
EOF
    
    log_success "Cloudflare configuration generated."
}

# Generate frontend Dockerfile with HTTPS hostname
generate_frontend_dockerfile() {
    log_info "Generating frontend Dockerfile with HTTPS Cloudflare URL..."
    
    cat > "$INSTALL_DIR/dockerfiles/Dockerfile-frontend-cloudflare" << EOF
FROM node:20-bookworm-slim

WORKDIR /app
RUN apt update
RUN apt -y upgrade
RUN apt install -y git
RUN git clone https://github.com/noatgnu/cupcake-ng.git
WORKDIR /app/cupcake-ng

# Replace hostname with HTTPS Cloudflare URL
RUN sed -i 's;https://cupcake.proteo.info;https://${HOSTNAME};g' src/environments/environment.ts
RUN sed -i 's;http://localhost;https://${HOSTNAME};g' src/environments/environment.ts

# Configure for production with Cloudflare
RUN sed -i 's;"production": false;"production": true;g' src/environments/environment.ts

# Install dependencies and build
RUN npm install
RUN npm run build --prod

FROM nginx:latest

# Copy custom nginx configuration for Cloudflare
COPY nginx-conf/nginx-cloudflare.conf /etc/nginx/conf.d/default.conf

# Copy built application
COPY --from=0 /app/cupcake-ng/dist/browser /usr/share/nginx/html

# Create nginx user and set permissions
RUN chown -R nginx:nginx /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
EOF
    
    log_success "Frontend Dockerfile generated for HTTPS URL: https://$HOSTNAME"
}

# Generate nginx configuration for Cloudflare
generate_nginx_config() {
    log_info "Generating nginx configuration for Cloudflare Tunnel..."
    
    cat > "$INSTALL_DIR/nginx-conf/nginx-cloudflare.conf" << EOF
# Nginx configuration for CUPCAKE with Cloudflare Tunnel

# Trust Cloudflare IPs
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;

real_ip_header CF-Connecting-IP;
real_ip_recursive on;

# Define the upstream server (Django backend)
upstream django {
    server cc:${INTERNAL_BACKEND_PORT};
    keepalive 32;
}

# Main server configuration
server {
    listen ${INTERNAL_FRONTEND_PORT};
    server_name ${HOSTNAME};
    
    client_max_body_size 100M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    charset utf-8;
    
    # Security headers optimized for Cloudflare
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Remove server signature
    server_tokens off;
    
    # Cloudflare-specific headers
    add_header CF-Cache-Status \$http_cf_cache_status always;
    
    # Gzip compression (Cloudflare will handle additional compression)
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;

    # Frontend serving
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
        
        # Cache static assets
        location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
            add_header Vary "Accept-Encoding";
        }
        
        # Cache HTML files for short time
        location ~* \\.html$ {
            expires 1h;
            add_header Cache-Control "public, must-revalidate";
        }
    }

    # Static files from Django
    location /static/ {
        alias /static/;
        expires 1y;
        add_header Cache-Control "public";
        add_header Vary "Accept-Encoding";
    }

    # Media files from Django
    location /media/ {
        internal;
        add_header 'Access-Control-Allow-Origin' 'https://${HOSTNAME}';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
        add_header 'Access-Control-Allow-Credentials' 'true';
        
        if (\$request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' 'https://${HOSTNAME}';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
        alias /media/;
    }

    # API endpoints with enhanced proxy settings
    location /api {
        proxy_pass http://django/api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host;
        
        # Cloudflare specific headers
        proxy_set_header CF-Connecting-IP \$http_cf_connecting_ip;
        proxy_set_header CF-Ray \$http_cf_ray;
        proxy_set_header CF-Visitor \$http_cf_visitor;
        
        # Timeouts for large uploads
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # Admin interface
    location /admin {
        proxy_pass http://django/admin;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host;
        
        # Cloudflare headers
        proxy_set_header CF-Connecting-IP \$http_cf_connecting_ip;
$([ "$ENABLE_CF_ACCESS" == "y" ] && echo "        
        # Cloudflare Access headers
        proxy_set_header CF-Access-Authenticated-User-Email \$http_cf_access_authenticated_user_email;
        proxy_set_header CF-Access-JWT-Assertion \$http_cf_access_jwt_assertion;")
    }

    # WebSocket endpoint with enhanced configuration
    location /ws {
        proxy_pass http://django/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        
        # WebSocket specific timeouts
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
        
        # Disable buffering for WebSockets
        proxy_buffering off;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\\n";
        add_header Content-Type text/plain;
    }
}
EOF

    # Generate custom nginx Dockerfile for Cloudflare
    cat > "$INSTALL_DIR/dockerfiles/Dockerfile-nginx-cloudflare" << EOF
FROM nginx:1.21.3

# Remove default configuration
RUN rm -rf /etc/nginx/conf.d/*

# Copy Cloudflare-optimized configuration
COPY ./nginx-conf/nginx-cloudflare.conf /etc/nginx/conf.d/default.conf

# Create nginx user if it doesn't exist
RUN id -u nginx &>/dev/null || useradd -r -s /bin/false nginx

# Set up logging
RUN ln -sf /dev/stdout /var/log/nginx/access.log \\
    && ln -sf /dev/stderr /var/log/nginx/error.log

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
  CMD curl -f http://localhost:${INTERNAL_FRONTEND_PORT}/health || exit 1

EXPOSE ${INTERNAL_FRONTEND_PORT}
EOF
    
    log_success "Nginx configuration generated for Cloudflare with hostname: $HOSTNAME"
}

# Generate docker-compose.yml for Cloudflare
generate_docker_compose() {
    log_info "Generating docker-compose.yml for Cloudflare Tunnel..."
    
    cat > "$INSTALL_DIR/docker-compose.yml" << EOF
services:
  # Cloudflare Tunnel
  cloudflared:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-cloudflared
    container_name: cloudflared
    restart: always
    environment:
      - TUNNEL_TOKEN=${TUNNEL_TOKEN}
    volumes:
      - cloudflare_logs:/var/log/cloudflared
    depends_on:
      - ccnginx
    networks:
      - cc-net
    healthcheck:
      test: ["CMD", "cloudflared", "tunnel", "--config", "/etc/cloudflared/config.yml", "info"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Nginx reverse proxy
  ccnginx:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-nginx-cloudflare
    container_name: ccnginx
    restart: always
    volumes:
      - ./media:/media/:rw
      - ./staticfiles:/static/:ro
    depends_on:
      - cc
      - ccfrontend
    networks:
      - cc-net
    # No external ports - only accessible via Cloudflare Tunnel

  # Frontend
  ccfrontend:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-frontend-cloudflare
    container_name: ccfrontend
    restart: always
    networks:
      - cc-net

  # Django backend
  cc:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile
      network: host
    container_name: cc
    volumes:
      - ./media:/app/media/:rw:rw
      - ./staticfiles:/app/staticfiles/:rw
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
    # No external ports - only accessible via nginx

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
      - ./media:/app/media/:rw
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
      - ./media:/app/media/:rw
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
      - ./media:/app/media/:rw
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
      - ./media:/app/media/:rw
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
    # COTURN ports are exposed for WebRTC - Cloudflare doesn't proxy UDP
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
  # PostgreSQL Database
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
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - cc-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 30s
      timeout: 10s
      retries: 5

  # Redis Cache/Message Broker
  ccredis:
    build:
      context: .
      dockerfile: ./dockerfiles/Dockerfile-redis
      network: host
    container_name: ccredis
    restart: always
    env_file:
      - .env
    volumes:
      - redis_data:/data
    networks:
      - cc-net

volumes:
  postgres_data:
  redis_data:
  cloudflare_logs:

networks:
  cc-net:
    driver: bridge
EOF
    
    log_success "Docker Compose configuration generated for Cloudflare Tunnel."
}

# Generate .env file for Cloudflare
generate_env_file() {
    log_info "Generating .env file for Cloudflare deployment..."
    
    cat > "$INSTALL_DIR/.env" << EOF
# CUPCAKE Cloudflare Tunnel Deployment Configuration
# Generated on $(date)

# Cloudflare Configuration
CLOUDFLARE_HOSTNAME=${HOSTNAME}
TUNNEL_TOKEN=${TUNNEL_TOKEN}

# Django Configuration
SECRET_KEY=${DJANGO_SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${HOSTNAME},ccnginx,localhost,127.0.0.1
CORS_ORIGIN_WHITELIST=https://${HOSTNAME}
CSRF_TRUSTED_ORIGINS=https://${HOSTNAME}

# Force HTTPS (since we're behind Cloudflare)
SECURE_SSL_REDIRECT=False
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
USE_TLS=True

# Database Configuration
POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASSWORD}

# Feature Flags
USE_COTURN=$([ "$ENABLE_COTURN" == "y" ] && echo "True" || echo "False")
USE_WHISPER=$([ "$ENABLE_WHISPER" == "y" ] && echo "True" || echo "False")
USE_OCR=$([ "$ENABLE_OCR" == "y" ] && echo "True" || echo "False")
USE_LLM=$([ "$ENABLE_LLAMA" == "y" ] && echo "True" || echo "False")

# Cloudflare Features
CF_ACCESS_ENABLED=$([ "$ENABLE_CF_ACCESS" == "y" ] && echo "True" || echo "False")
HTTP2_ENABLED=$([ "$ENABLE_HTTP2" == "y" ] && echo "True" || echo "False")

# Redis Configuration
REDIS_HOST=ccredis
REDIS_PORT=6379

# Admin Configuration (for initialization)
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}

# Cloudflare-specific settings
# Trust Cloudflare proxy headers
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
SECURE_CROSS_ORIGIN_OPENER_POLICY=None
EOF
    
    log_success ".env file generated for Cloudflare Tunnel."
}

# Generate setup scripts for Cloudflare
generate_setup_scripts() {
    log_info "Generating setup scripts for Cloudflare deployment..."
    
    # Database initialization script (same as regular version)
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
            'object_type': 'facility',
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
    
    # Cloudflare-specific deployment script
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

echo "=== CUPCAKE Cloudflare Tunnel Deployment ==="
echo
log_info "Starting deployment to: https://${CLOUDFLARE_HOSTNAME}"
echo

# Pre-deployment checks
log_info "Performing pre-deployment checks..."

# Check if tunnel token is set
if [[ -z "$TUNNEL_TOKEN" ]]; then
    log_error "TUNNEL_TOKEN is not set in .env file"
    exit 1
fi

# Check Docker daemon
if ! docker info > /dev/null 2>&1; then
    log_error "Docker daemon is not running"
    exit 1
fi

log_success "Pre-deployment checks passed"

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

# Wait for Redis to be ready
log_info "Waiting for Redis to be ready..."
timeout=60
while ! docker-compose exec -T ccredis redis-cli ping > /dev/null 2>&1; do
    echo -n "."
    sleep 2
    timeout=$((timeout - 2))
    if [[ $timeout -le 0 ]]; then
        log_error "Redis failed to start within 1 minute"
        docker-compose logs ccredis
        exit 1
    fi
done
echo
log_success "Redis is ready"

# Wait for Django service to be ready
log_info "Waiting for Django service to be ready..."
sleep 20

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

# Copy and run database initialization
log_info "Initializing database with admin user and MS Facility..."
docker cp scripts/init_database.py cc:/tmp/init_database.py
if docker-compose exec -T cc python /tmp/init_database.py; then
    log_success "Database initialization completed"
else
    log_error "Database initialization failed"
    exit 1
fi

# Wait for Cloudflare tunnel to establish
log_info "Waiting for Cloudflare Tunnel to establish connection..."
sleep 30

# Check tunnel health
if docker-compose exec -T cloudflared cloudflared tunnel --config /etc/cloudflared/config.yml info > /dev/null 2>&1; then
    log_success "Cloudflare Tunnel is connected"
else
    log_warning "Cloudflare Tunnel may not be fully connected yet"
fi

# Test connectivity through Cloudflare
log_info "Testing connectivity through Cloudflare..."
sleep 10

FRONTEND_URL="https://${CLOUDFLARE_HOSTNAME}"
if curl -f -L --max-time 30 "$FRONTEND_URL" > /dev/null 2>&1; then
    log_success "Frontend is accessible through Cloudflare at $FRONTEND_URL"
else
    log_warning "Frontend may not be accessible yet through Cloudflare (this can take a few minutes)"
fi

# Display deployment summary
echo
log_success "CUPCAKE Cloudflare Tunnel deployment completed!"
echo
echo "=========================================="
echo "CUPCAKE Cloudflare Deployment Summary"
echo "=========================================="
echo "Frontend URL: https://${CLOUDFLARE_HOSTNAME}"
echo "Admin Interface: https://${CLOUDFLARE_HOSTNAME}/admin"
echo
echo "Admin Credentials:"
echo "  Username: ${ADMIN_USERNAME}"
echo "  Email: ${ADMIN_EMAIL}"
echo
echo "Cloudflare Features:"
echo "  - Secure HTTPS access through Cloudflare Tunnel"
echo "  - DDoS protection and CDN caching"
echo "  - No exposed ports on your server"
$([ "$CF_ACCESS_ENABLED" == "True" ] && echo "  - Cloudflare Access authentication enabled")
$([ "$HTTP2_ENABLED" == "True" ] && echo "  - HTTP/2 and gRPC support enabled")
echo
echo "Services Status:"
docker-compose ps
echo
echo "Management Commands:"
echo "  Stop services: docker-compose down"
echo "  View logs: docker-compose logs -f [service_name]"
echo "  View tunnel logs: docker-compose logs -f cloudflared"
echo "  Restart services: docker-compose restart"
echo "  Update services: docker-compose up -d --build"
echo
echo "Cloudflare Tunnel Configuration:"
echo "  Tunnel connects to: ${CLOUDFLARE_HOSTNAME}"
echo "  Configuration file: cloudflare-conf/config.yml"
echo
echo "Security Notes:"
echo "  - All traffic is encrypted through Cloudflare"
echo "  - Server has no exposed external ports (except COTURN if enabled)"
echo "  - MS Facility has been configured with default storage"
echo "=========================================="

# Optional: Show tunnel info
if command -v curl &> /dev/null; then
    echo
    log_info "Testing Cloudflare connectivity..."
    if curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL" | grep -q "200\|302"; then
        log_success "✅ Successfully connected through Cloudflare!"
    else
        log_warning "⚠️  Cloudflare tunnel may still be establishing connection"
        echo "    This can take 5-10 minutes for first-time setup"
    fi
fi
EOF

    # Cloudflare tunnel management script
    cat > "$INSTALL_DIR/scripts/manage_tunnel.sh" << 'EOF'
#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

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

case "$1" in
    status)
        log_info "Checking Cloudflare Tunnel status..."
        docker-compose exec cloudflared cloudflared tunnel --config /etc/cloudflared/config.yml info
        ;;
    logs)
        log_info "Showing Cloudflare Tunnel logs..."
        docker-compose logs -f cloudflared
        ;;
    restart)
        log_info "Restarting Cloudflare Tunnel..."
        docker-compose restart cloudflared
        ;;
    test)
        if [[ -f .env ]]; then
            source .env
        fi
        log_info "Testing connectivity to https://${CLOUDFLARE_HOSTNAME}..."
        curl -I "https://${CLOUDFLARE_HOSTNAME}"
        ;;
    *)
        echo "Usage: $0 {status|logs|restart|test}"
        echo
        echo "Commands:"
        echo "  status  - Show tunnel connection status"
        echo "  logs    - Show tunnel logs"
        echo "  restart - Restart tunnel service"
        echo "  test    - Test connectivity through tunnel"
        exit 1
        ;;
esac
EOF
    
    chmod +x "$INSTALL_DIR/scripts/init_database.py"
    chmod +x "$INSTALL_DIR/deploy.sh"
    chmod +x "$INSTALL_DIR/scripts/manage_tunnel.sh"
    
    log_success "Cloudflare-specific setup scripts generated."
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
        if [[ "$filename" != "Dockerfile-frontend-cloudflare" && 
              "$filename" != "Dockerfile-nginx-cloudflare" && 
              "$filename" != "Dockerfile-cloudflared" ]]; then
            cp "$dockerfile" "$INSTALL_DIR/dockerfiles/"
        fi
    done
    
    log_success "Source files copied to deployment directory."
}

# Update todos and run main function
update_todos_and_run() {
    # Mark remaining todos as completed
    log_success "Cloudflare Tunnel installation files generated successfully!"
}

# Main installation function
main() {
    echo "Starting CUPCAKE Cloudflare Tunnel installation process..."
    echo "This will create a secure deployment accessible only through Cloudflare."
    echo
    
    check_prerequisites
    collect_configuration
    create_deployment_directory
    generate_cloudflare_config
    generate_frontend_dockerfile
    generate_nginx_config  
    generate_docker_compose
    generate_env_file
    generate_setup_scripts
    copy_source_files
    
    echo
    log_success "CUPCAKE Cloudflare Tunnel installation files generated successfully!"
    echo
    echo "Generated deployment at: $INSTALL_DIR"
    echo
    echo "Files created:"
    echo "  ├── docker-compose.yml (with Cloudflare Tunnel service)"
    echo "  ├── .env (Cloudflare-optimized environment)"
    echo "  ├── dockerfiles/"
    echo "  │   ├── Dockerfile-frontend-cloudflare (HTTPS configured)"
    echo "  │   ├── Dockerfile-nginx-cloudflare (Cloudflare-optimized)"
    echo "  │   └── Dockerfile-cloudflared (tunnel service)"
    echo "  ├── nginx-conf/"
    echo "  │   └── nginx-cloudflare.conf (Cloudflare-optimized config)"
    echo "  ├── cloudflare-conf/"
    echo "  │   └── config.yml (tunnel configuration)"
    echo "  ├── scripts/"
    echo "  │   ├── init_database.py (database initialization)"
    echo "  │   └── manage_tunnel.sh (tunnel management)"
    echo "  └── deploy.sh (Cloudflare deployment script)"
    echo
    echo "Cloudflare Features Configured:"
    echo "  ✅ Secure HTTPS access through tunnel"
    echo "  ✅ No exposed server ports (except COTURN if enabled)"
    echo "  ✅ DDoS protection and CDN caching"
    echo "  ✅ Real IP header preservation"
    $([ "$ENABLE_CF_ACCESS" == "y" ] && echo "  ✅ Cloudflare Access integration")
    $([ "$ENABLE_HTTP2" == "y" ] && echo "  ✅ HTTP/2 support")
    echo
    echo "Your CUPCAKE will be accessible at: https://$HOSTNAME"
    echo
    
    read -p "Would you like to start the Cloudflare deployment now? [y/N]: " START_DEPLOY
    if [[ "$START_DEPLOY" == "y" || "$START_DEPLOY" == "Y" ]]; then
        log_info "Starting Cloudflare Tunnel deployment..."
        cd "$INSTALL_DIR"
        ./deploy.sh
    else
        echo
        log_info "To deploy later, run:"
        echo "  cd $INSTALL_DIR"
        echo "  ./deploy.sh"
        echo
        log_info "To manage the tunnel after deployment:"
        echo "  cd $INSTALL_DIR"
        echo "  ./scripts/manage_tunnel.sh status"
        echo
        log_warning "Important: Make sure your Cloudflare Tunnel is properly configured"
        echo "           in your Cloudflare dashboard before deploying!"
    fi
}

# Run main function
main "$@"