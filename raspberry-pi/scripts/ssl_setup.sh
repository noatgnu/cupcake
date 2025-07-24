#!/bin/bash

# CUPCAKE Pi Build - SSL Configuration
# Handles SSL certificate generation and configuration

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

# SSL configuration variables
SSL_DIR="/opt/cupcake/ssl"
NGINX_SSL_DIR="/etc/nginx/ssl"

generate_self_signed() {
    log_ssl "Generating self-signed certificate for $HOSTNAME.local"
    
    # Create SSL directories
    mkdir -p "$SSL_DIR" "$NGINX_SSL_DIR"
    
    # Generate private key
    openssl genrsa -out "$SSL_DIR/cupcake.key" 2048
    
    # Generate certificate signing request
    openssl req -new -key "$SSL_DIR/cupcake.key" -out "$SSL_DIR/cupcake.csr" \
        -subj "/C=${CUPCAKE_SSL_COUNTRY:-US}/ST=${CUPCAKE_SSL_STATE:-California}/L=${CUPCAKE_SSL_CITY:-Berkeley}/O=${CUPCAKE_SSL_ORG:-CUPCAKE Lab}/CN=$HOSTNAME.local"
    
    # Create temporary config file for certificate extensions
    cat > "$SSL_DIR/cert_extensions.conf" <<EOF
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $HOSTNAME.local
DNS.2 = $HOSTNAME
DNS.3 = localhost
IP.1 = 127.0.0.1
EOF
    
    # Generate self-signed certificate
    openssl x509 -req -days 365 -in "$SSL_DIR/cupcake.csr" -signkey "$SSL_DIR/cupcake.key" \
        -out "$SSL_DIR/cupcake.crt" -extensions v3_req -extfile "$SSL_DIR/cert_extensions.conf"
    
    # Clean up temporary config file
    rm -f "$SSL_DIR/cert_extensions.conf"
    
    # Copy to nginx directory
    cp "$SSL_DIR/cupcake.crt" "$NGINX_SSL_DIR/"
    cp "$SSL_DIR/cupcake.key" "$NGINX_SSL_DIR/"
    
    # Set permissions
    chown -R root:root "$SSL_DIR" "$NGINX_SSL_DIR"
    chmod 600 "$SSL_DIR/cupcake.key" "$NGINX_SSL_DIR/cupcake.key"
    chmod 644 "$SSL_DIR/cupcake.crt" "$NGINX_SSL_DIR/cupcake.crt"
    
    log_ssl "Self-signed certificate generated successfully"
}

setup_letsencrypt() {
    log_ssl "Setting up Let's Encrypt for domain: $CUPCAKE_DOMAIN"
    
    # Install certbot
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
    
    # Generate certificate (will need manual DNS validation or HTTP challenge)
    log_ssl "Note: Let's Encrypt setup requires manual domain validation"
    log_ssl "Run: certbot --nginx -d $CUPCAKE_DOMAIN after first boot"
}

setup_cloudflare_tunnel() {
    log_ssl "Setting up Cloudflare tunnel for domain: $CUPCAKE_TUNNEL_DOMAIN"
    
    # Install cloudflared
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cloudflared.deb
    dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
    
    # Create tunnel config
    mkdir -p /opt/cupcake/tunnel
    cat > /opt/cupcake/tunnel/config.yml <<EOF
tunnel: $CUPCAKE_TUNNEL_TOKEN
credentials-file: /opt/cupcake/tunnel/cert.pem

ingress:
  - hostname: $CUPCAKE_TUNNEL_DOMAIN
    service: http://localhost:80
  - service: http_status:404
EOF
    
    # Create systemd service
    cat > /etc/systemd/system/cloudflared.service <<EOF
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=cupcake
ExecStart=/usr/local/bin/cloudflared tunnel --config /opt/cupcake/tunnel/config.yml run
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl enable cloudflared
    log_ssl "Cloudflare tunnel configured - requires manual token setup"
}

configure_ssl() {
    log_ssl "Configuring SSL based on environment variables..."
    
    if [ "$CUPCAKE_ENABLE_SSL" = "true" ]; then
        generate_self_signed
    elif [ -n "$CUPCAKE_DOMAIN" ] && [ "$CUPCAKE_ENABLE_LETSENCRYPT" = "true" ]; then
        setup_letsencrypt
    elif [ "$CUPCAKE_CLOUDFLARE_TUNNEL" = "true" ] && [ -n "$CUPCAKE_TUNNEL_TOKEN" ]; then
        setup_cloudflare_tunnel
    else
        log_ssl "No SSL configuration specified - HTTP only"
    fi
}