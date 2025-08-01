#!/bin/bash
set -e

# CUPCAKE Nginx Configuration Script for Raspberry Pi
# This script configures nginx to serve CUPCAKE on port 80 with Django backend on 8000

echo "=== Configuring Nginx for CUPCAKE ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

# Install nginx if not already installed
if ! command -v nginx &> /dev/null; then
    echo "Installing nginx..."
    apt-get update
    apt-get install -y nginx
fi

# Enable nginx service
systemctl enable nginx

# Create nginx configuration directories
mkdir -p /etc/nginx/sites-available
mkdir -p /etc/nginx/sites-enabled
mkdir -p /etc/nginx/conf.d

echo "Creating proxy parameters configuration..."

# Create proxy parameters file
cat > /etc/nginx/conf.d/proxy_params.conf << 'PROXYEOF'
# CUPCAKE Nginx Proxy Parameters
# Optimized for Raspberry Pi performance

proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Port $server_port;

# Connection settings optimized for Pi
proxy_connect_timeout 60s;
proxy_send_timeout 60s;
proxy_read_timeout 60s;
proxy_redirect off;

# Buffering settings for low memory
proxy_buffering on;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
proxy_busy_buffers_size 8k;
proxy_max_temp_file_size 1024m;
proxy_temp_file_write_size 8k;

# Hide upstream headers
proxy_hide_header X-Powered-By;
proxy_hide_header Server;

# Add custom headers
proxy_set_header X-Forwarded-SSL $https;
proxy_set_header X-Client-IP $remote_addr;
PROXYEOF

echo "Creating CUPCAKE site configuration..."

# Create comprehensive CUPCAKE nginx site configuration
cat > /etc/nginx/sites-available/cupcake << 'NGINXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name cupcake-pi.local cupcake-pi _;
    
    # Security headers
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Client settings
    client_max_body_size 100M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    
    # Static files served directly by nginx
    location /static/ {
        alias /opt/cupcake/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        add_header Vary "Accept-Encoding";
        
        # Handle missing static files gracefully
        try_files $uri $uri/ =404;
        
        # Compression for CSS/JS
        location ~* \.(css|js|json)$ {
            gzip_static on;
            expires 1y;
        }
        
        # Images
        location ~* \.(jpg|jpeg|png|gif|ico|svg|webp)$ {
            expires 30d;
            add_header Cache-Control "public";
        }
        
        # Fonts
        location ~* \.(woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public";
            add_header Access-Control-Allow-Origin "*";
        }
    }
    
    # Media files with security restrictions
    location /media/ {
        alias /opt/cupcake/media/;
        expires 7d;
        add_header Cache-Control "public";
        
        # Security: prevent execution of scripts in media directory
        location ~* \.(php|py|pl|sh|cgi|exe|bat)$ {
            deny all;
            return 403;
        }
    }
    
    # Health check endpoint (no logging)
    location /health {
        access_log off;
        add_header Content-Type text/plain;
        return 200 "healthy\n";
    }
    
    # Favicon
    location = /favicon.ico {
        alias /opt/cupcake/staticfiles/favicon.ico;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
        
        # Fallback if favicon doesn't exist
        try_files $uri =204;
    }
    
    # Robots.txt
    location = /robots.txt {
        add_header Content-Type text/plain;
        return 200 "User-agent: *\nDisallow: /admin/\n";
        access_log off;
    }
    
    # API endpoints with CORS headers
    location /api/ {
        # CORS headers for API
        add_header Access-Control-Allow-Origin "$http_origin" always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization" always;
        add_header Access-Control-Expose-Headers "Content-Length,Content-Range" always;
        add_header Access-Control-Allow-Credentials "true" always;
        
        # Handle preflight requests
        if ($request_method = 'OPTIONS') {
            add_header Access-Control-Max-Age 86400;
            add_header Content-Type 'text/plain; charset=utf-8';
            add_header Content-Length 0;
            return 204;
        }
        
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # WebSocket support for real-time features
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        include /etc/nginx/conf.d/proxy_params.conf;
        
        # WebSocket specific timeouts (override proxy_params.conf)
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
    
    # Frontend (Angular) - serve from files
    location / {
        # Show maintenance page if CUPCAKE is not ready
        if (!-f /tmp/cupcake-ready) {
            return 503;
        }
        
        root /opt/cupcake/frontend;
        try_files $uri $uri/ /index.html;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
    
    # Admin interface - proxy to Django
    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
        
        # Additional security for admin
        add_header X-Frame-Options DENY always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';" always;
    }
    
    # API endpoints - proxy to Django
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
        
        # CORS headers for API
        add_header 'Access-Control-Allow-Origin' '$http_origin' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
        
        # Handle preflight requests
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '$http_origin';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 86400;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
    }
    
    # WebSocket support - proxy to Django
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        include /etc/nginx/conf.d/proxy_params.conf;
        
        # WebSocket specific timeouts (override proxy_params.conf)
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
    
    # Auth endpoints - proxy to Django
    location /auth/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # DRF (Django REST Framework) endpoints - proxy to Django
    location /drf/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # OAuth endpoints - proxy to Django
    location /o/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # Social auth endpoints - proxy to Django
    location /social/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # MCP (Model Context Protocol) endpoints - proxy to Django
    location /mcp/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/conf.d/proxy_params.conf;
    }
    
    # Security: Block access to sensitive files
    location ~* \.(env|log|ini|conf|bak|backup|old|tmp|temp)$ {
        deny all;
        return 404;
    }
    
    # Security: Block access to hidden files
    location ~ /\. {
        deny all;
        return 404;
    }
    
    # Security: Block access to version control
    location ~ /\.(git|svn|hg) {
        deny all;
        return 404;
    }
    
    # Custom error pages
    error_page 502 503 504 /maintenance.html;
    
    location = /maintenance.html {
        root /var/www/html;
        internal;
    }
}
NGINXEOF

echo "Creating maintenance page..."

# Create maintenance page directory and file
mkdir -p /var/www/html
cat > /var/www/html/maintenance.html << 'MAINTEOF'
<!DOCTYPE html>
<html>
<head>
    <title>CUPCAKE Starting Up</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; margin: 0; padding: 50px 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; min-height: 100vh; box-sizing: border-box; }
        .container { max-width: 600px; margin: 0 auto; background: rgba(255,255,255,0.95); padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); color: #333; }
        .logo { font-size: 64px; margin-bottom: 20px; animation: bounce 2s infinite; }
        @keyframes bounce { 0%, 20%, 50%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-10px); } 60% { transform: translateY(-5px); } }
        h1 { color: #333; margin-bottom: 20px; font-size: 28px; font-weight: 600; }
        p { color: #666; line-height: 1.8; margin-bottom: 20px; font-size: 16px; }
        .status { background: linear-gradient(135deg, #e3f2fd, #f3e5f5); padding: 20px; border-radius: 10px; margin: 25px 0; border-left: 4px solid #2196F3; }
        .spinner { border: 3px solid #f3f3f3; border-top: 3px solid #2196F3; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .access-info { background: #f8f9fa; padding: 20px; border-radius: 10px; margin: 20px 0; border: 2px solid #e9ecef; }
        .access-info h3 { margin-top: 0; color: #495057; font-size: 18px; }
        code { background: #007bff; color: white; padding: 4px 8px; border-radius: 4px; font-family: 'Monaco', 'Menlo', monospace; font-size: 14px; }
        .footer { margin-top: 30px; font-size: 14px; color: #999; }
        .progress { background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 20px 0; }
        .progress-bar { background: linear-gradient(90deg, #007bff, #0056b3); height: 6px; border-radius: 10px; animation: progress 3s ease-in-out infinite; }
        @keyframes progress { 0% { width: 10%; } 50% { width: 80%; } 100% { width: 10%; } }
    </style>
    <script>
        let dots = 0;
        setInterval(function() {
            dots = (dots + 1) % 4;
            const loading = document.getElementById('loading-text');
            if (loading) {
                loading.textContent = 'Services are initializing' + '.'.repeat(dots);
            }
        }, 500);
        
        setTimeout(function() { 
            location.reload(); 
        }, 15000);
    </script>
</head>
<body>
    <div class="container">
        <div class="logo">🧁</div>
        <h1>CUPCAKE is Starting Up</h1>
        <div class="spinner"></div>
        <div class="progress">
            <div class="progress-bar"></div>
        </div>
        <div class="status">
            <p><strong>Laboratory Management System</strong></p>
            <p id="loading-text">Services are initializing...</p>
            <p>This usually takes 1-2 minutes on first boot.</p>
            <p>The page will refresh automatically every 15 seconds.</p>
        </div>
        <div class="access-info">
            <h3>🌐 Default Access Information</h3>
            <p><strong>Web Interface:</strong> <code>http://cupcake-pi.local</code></p>
            <p><strong>Username:</strong> <code>admin</code> | <strong>Password:</strong> <code>cupcake123</code></p>
            <p><strong>SSH Access:</strong> <code>ssh cupcake@cupcake-pi.local</code></p>
        </div>
        <div class="access-info">
            <h3>📊 What's Included</h3>
            <p>✅ Pre-loaded with <strong>2M+ scientific ontology records</strong></p>
            <p>✅ MONDO, NCBI, ChEBI, UniProt, PSI-MS databases</p>
            <p>✅ Local audio transcription with Whisper.cpp</p>
            <p>✅ Background workers for data processing</p>
        </div>
        <div class="footer">
            <p><strong>Troubleshooting:</strong> If this page persists for more than 5 minutes, check service status with <code>sudo systemctl status cupcake-*</code></p>
            <p><strong>Security:</strong> ⚠️ Change default passwords before production use!</p>
        </div>
    </div>
</body>
</html>
MAINTEOF

echo "Configuring nginx sites..."

# Remove default nginx site and enable CUPCAKE site
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
rm -f /var/www/html/index.nginx-debian.html

echo "Testing nginx configuration..."

# Test nginx configuration
if nginx -t; then
    echo "✅ Nginx configuration test passed"
else
    echo "❌ Nginx configuration test failed"
    exit 1
fi

echo "Configuring nginx service..."

# Restart and enable nginx
systemctl restart nginx || {
    echo "❌ Failed to restart nginx"
    systemctl status nginx
    exit 1
}

systemctl enable nginx

echo "Checking nginx status..."

# Check if nginx is running
if systemctl is-active --quiet nginx; then
    echo "✅ Nginx is running successfully"
    echo "🌐 CUPCAKE will be available at: http://cupcake-pi.local"
    echo "🔧 Direct Django access: http://cupcake-pi.local:8000"
else
    echo "❌ Nginx failed to start"
    systemctl status nginx
    exit 1
fi

echo ""
echo "=== Nginx Configuration Summary ==="
echo "✅ Nginx configured to serve CUPCAKE on port 80"
echo "✅ Django backend proxied from port 8000"
echo "✅ Static files served directly by nginx"
echo "✅ Maintenance page configured for startup"
echo "✅ Security headers and file restrictions enabled"
echo "✅ WebSocket support configured"
echo "✅ CORS headers configured for API"
echo ""
echo "Access CUPCAKE at: http://cupcake-pi.local"
echo "Default login: admin / cupcake123"
echo ""
echo "=== Nginx configuration completed successfully ==="
