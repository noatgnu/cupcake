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
    
    # WebSocket support for real-time features
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # WebSocket specific connection settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
        proxy_redirect off;

        # Minimal buffering for real-time connections
        proxy_buffering off;

        # Hide upstream headers
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;

        # Add custom headers
        proxy_set_header X-Forwarded-SSL $https;
        proxy_set_header X-Client-IP $remote_addr;
    }
    
    # Frontend (Angular) - serve from files
    location / {
        # Show maintenance page if CUPCAKE is not ready
        if (!-f /opt/cupcake/services-enabled) {
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
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CUPCAKE - Starting Up</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f8f9fa;
            color: #333;
            line-height: 1.6;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            max-width: 500px;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            text-align: center;
        }

        h1 {
            font-size: 24px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 20px;
        }

        .status {
            background-color: #e3f2fd;
            border: 1px solid #bbdefb;
            border-radius: 4px;
            padding: 20px;
            margin: 20px 0;
        }

        .status p {
            margin-bottom: 10px;
        }

        .info-section {
            background-color: #f5f5f5;
            border-radius: 4px;
            padding: 15px;
            margin: 15px 0;
            text-align: left;
        }

        .info-section h3 {
            font-size: 16px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 10px;
        }

        .info-section p {
            margin-bottom: 8px;
            font-size: 14px;
        }

        code {
            background-color: #2c3e50;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
            font-size: 13px;
        }

        .footer {
            margin-top: 30px;
            font-size: 12px;
            color: #666;
        }

        .footer p {
            margin-bottom: 5px;
        }

        .warning {
            color: #d32f2f;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>CUPCAKE is Starting Up</h1>

        <div class="status">
            <p><strong>Laboratory Management System</strong></p>
            <p>Services are initializing...</p>
            <p>This usually takes 1-2 minutes on first boot.</p>
            <p>Please refresh this page in a few moments.</p>
        </div>

        <div class="info-section">
            <h3>Access Information</h3>
            <p><strong>Web Interface:</strong> <code>http://cupcake-pi.local</code></p>
            <p><strong>SSH Access:</strong> <code>ssh cupcake@cupcake-pi.local</code></p>
        </div>

        <div class="info-section">
            <h3>What's Included</h3>
            <p>• Pre-loaded with 2M+ scientific ontology records</p>
            <p>• MONDO, NCBI, ChEBI, UniProt, PSI-MS databases</p>
            <p>• Local audio transcription with Whisper.cpp</p>
            <p>• Background workers for data processing</p>
        </div>

        <div class="footer">
            <p><strong>Troubleshooting:</strong> If this page persists for more than 5 minutes, check service status with <code>sudo systemctl status cupcake-*</code></p>
            <p class="warning"><strong>Security:</strong> Change default passwords before production use!</p>
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
