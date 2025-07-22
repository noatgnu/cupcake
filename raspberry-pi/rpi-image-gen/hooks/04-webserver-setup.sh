#!/bin/bash
# CUPCAKE Web Server Setup Hook
# Configures Nginx as reverse proxy for CUPCAKE

set -e

echo ">>> CUPCAKE: Setting up web server..."

# Remove default Nginx configuration
rm -f /etc/nginx/sites-enabled/default

# Create CUPCAKE Nginx configuration
cat > /etc/nginx/sites-available/cupcake << 'EOF'
# CUPCAKE Nginx Configuration
# Optimized for Raspberry Pi 5 deployment

# Rate limiting
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=general:10m rate=20r/s;

# Upstream backend servers
upstream cupcake_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

upstream cupcake_websocket {
    server 127.0.0.1:8001;
}

# HTTP to HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name _;
    
    # Let's Encrypt challenge location
    location /.well-known/acme-challenge/ {
        root /var/www/html;
        try_files $uri =404;
    }
    
    # Redirect all other traffic to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# Main HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name _;
    
    # SSL Configuration (will be populated by certbot)
    ssl_certificate /etc/ssl/cupcake/cert.pem;
    ssl_certificate_key /etc/ssl/cupcake/key.pem;
    
    # SSL security settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Client settings
    client_max_body_size 100M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    
    # Compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;
    
    # Static files
    location /static/ {
        alias /var/www/cupcake/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        
        location ~* \.(js|css)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
        
        location ~* \.(jpg|jpeg|png|gif|ico|svg)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
    
    # Media files
    location /media/ {
        alias /var/www/cupcake/media/;
        expires 30d;
        add_header Cache-Control "public";
    }
    
    # API endpoints with rate limiting
    location /api/auth/ {
        limit_req zone=login burst=10 nodelay;
        proxy_pass http://cupcake_backend;
        include /etc/nginx/proxy_params;
    }
    
    location /api/ {
        limit_req zone=api burst=30 nodelay;
        proxy_pass http://cupcake_backend;
        include /etc/nginx/proxy_params;
    }
    
    # WebSocket connections
    location /ws/ {
        proxy_pass http://cupcake_websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
    
    # Admin interface
    location /admin/ {
        limit_req zone=general burst=10 nodelay;
        proxy_pass http://cupcake_backend;
        include /etc/nginx/proxy_params;
    }
    
    # Main application
    location / {
        limit_req zone=general burst=50 nodelay;
        proxy_pass http://cupcake_backend;
        include /etc/nginx/proxy_params;
    }
    
    # Health check endpoint
    location /health/ {
        access_log off;
        proxy_pass http://cupcake_backend;
        include /etc/nginx/proxy_params;
    }
}
EOF

# Create proxy parameters file
cat > /etc/nginx/proxy_params << 'EOF'
# CUPCAKE Nginx Proxy Parameters

proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Port $server_port;

proxy_connect_timeout 30s;
proxy_send_timeout 120s;
proxy_read_timeout 120s;

proxy_buffering on;
proxy_buffer_size 128k;
proxy_buffers 4 256k;
proxy_busy_buffers_size 256k;

proxy_http_version 1.1;
proxy_set_header Connection "";
EOF

# Enable CUPCAKE site
ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/

# Create web directories
mkdir -p /var/www/cupcake/static
mkdir -p /var/www/cupcake/media
mkdir -p /var/www/html

# Set proper ownership and permissions
chown -R www-data:www-data /var/www/cupcake
chown -R www-data:www-data /var/www/html
chmod -R 755 /var/www/cupcake
chmod -R 755 /var/www/html

# Configure Nginx main settings for Pi 5
cat > /etc/nginx/nginx.conf << 'EOF'
# CUPCAKE Nginx Configuration for Raspberry Pi 5

user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 100;
    types_hash_max_size 2048;
    server_tokens off;
    
    # Server names
    server_names_hash_bucket_size 64;
    
    # MIME types
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # SSL Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    
    # Logging Settings
    log_format cupcake '$remote_addr - $remote_user [$time_local] '
                      '"$request" $status $body_bytes_sent '
                      '"$http_referer" "$http_user_agent" '
                      '$request_time $upstream_response_time';
    
    access_log /var/log/nginx/access.log cupcake;
    error_log /var/log/nginx/error.log warn;
    
    # Gzip Settings
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;
    
    # Virtual Host Configs
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF

# Create self-signed SSL certificate for initial setup
mkdir -p /etc/ssl/cupcake
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/cupcake/key.pem \
    -out /etc/ssl/cupcake/cert.pem \
    -subj "/C=US/ST=Lab/L=Lab/O=CUPCAKE/OU=Lab/CN=cupcake-pi"

chmod 600 /etc/ssl/cupcake/key.pem
chmod 644 /etc/ssl/cupcake/cert.pem
chown root:cupcake /etc/ssl/cupcake/*

# Test Nginx configuration
nginx -t

# Create SSL certificate renewal script
cat > /opt/cupcake/scripts/renew-ssl.sh << 'EOF'
#!/bin/bash
# CUPCAKE SSL Certificate Renewal Script

set -e

echo "Renewing CUPCAKE SSL certificates..."

# Stop nginx temporarily
systemctl stop nginx

# Renew certificates with certbot
certbot renew --standalone --quiet

# Update certificate paths in nginx config if needed
if [ -f /etc/letsencrypt/live/*/fullchain.pem ]; then
    CERT_DIR=$(ls -1d /etc/letsencrypt/live/*/ | head -1)
    sed -i "s|ssl_certificate .*|ssl_certificate ${CERT_DIR}fullchain.pem;|" /etc/nginx/sites-available/cupcake
    sed -i "s|ssl_certificate_key .*|ssl_certificate_key ${CERT_DIR}privkey.pem;|" /etc/nginx/sites-available/cupcake
fi

# Restart nginx
systemctl start nginx

echo "SSL certificates renewed successfully"
EOF

chmod +x /opt/cupcake/scripts/renew-ssl.sh
chown cupcake:cupcake /opt/cupcake/scripts/renew-ssl.sh

# Create cron job for SSL renewal
cat > /etc/cron.d/cupcake-ssl << 'EOF'
# CUPCAKE SSL Certificate Renewal
# Runs monthly at 3:30 AM
30 3 1 * * root /opt/cupcake/scripts/renew-ssl.sh >> /var/log/cupcake/ssl-renewal.log 2>&1
EOF

echo ">>> CUPCAKE: Web server setup completed successfully"
echo ">>> Use '/opt/cupcake/scripts/renew-ssl.sh' to set up Let's Encrypt certificates"