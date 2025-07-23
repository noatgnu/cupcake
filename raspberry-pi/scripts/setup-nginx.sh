#!/bin/bash
set -e

echo "=== Configuring Nginx ==="

# Configure Nginx
systemctl enable nginx

# Create CUPCAKE nginx configuration
cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    location /static/ {
        alias /opt/cupcake/staticfiles/;
        expires 30d;
    }

    location /media/ {
        alias /opt/cupcake/media/;
        expires 7d;
    }
}
EOF

ln -sf /etc/nginx/sites-available/cupcake /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

echo "=== Nginx configuration completed ==="
