#!/bin/bash
# CUPCAKE SSL Certificate Setup Script
# Sets up Let's Encrypt SSL certificates for production use

set -e

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: $0 <domain-name>"
    echo "Example: $0 cupcake.lab.university.edu"
    exit 1
fi

DOMAIN=$1
EMAIL="admin@$DOMAIN"

echo "CUPCAKE SSL Certificate Setup"
echo "============================"
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"

# Check if domain resolves to this server
echo "Checking domain resolution..."
DOMAIN_IP=$(dig +short $DOMAIN | tail -n1)
SERVER_IP=$(curl -s http://checkip.amazonaws.com/)

if [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
    echo "WARNING: Domain $DOMAIN does not resolve to this server ($SERVER_IP)"
    echo "Current resolution: $DOMAIN_IP"
    echo "Please ensure DNS is properly configured before continuing."
    read -p "Continue anyway? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        exit 1
    fi
fi

# Stop nginx temporarily
systemctl stop nginx

# Install certbot if not already installed
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
fi

# Obtain SSL certificate
echo "Obtaining SSL certificate for $DOMAIN..."
certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN"

# Update nginx configuration with real certificate
echo "Updating nginx configuration..."
sed -i "s|ssl_certificate /etc/ssl/cupcake/cert.pem;|ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;|" /etc/nginx/sites-available/cupcake
sed -i "s|ssl_certificate_key /etc/ssl/cupcake/key.pem;|ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;|" /etc/nginx/sites-available/cupcake

# Update server_name in nginx config
sed -i "s|server_name _;|server_name $DOMAIN;|g" /etc/nginx/sites-available/cupcake

# Test nginx configuration
nginx -t

# Start nginx
systemctl start nginx

# Update CUPCAKE settings
echo "Updating CUPCAKE settings..."
SETTINGS_FILE="/opt/cupcake/src/cupcake/settings/production.py"

# Update ALLOWED_HOSTS
sudo -u cupcake sed -i "s|ALLOWED_HOSTS = \['\\*'\]|ALLOWED_HOSTS = ['$DOMAIN', 'localhost', '127.0.0.1']|" "$SETTINGS_FILE"

# Restart CUPCAKE services
echo "Restarting CUPCAKE services..."
systemctl restart cupcake
systemctl restart cupcake-websocket
systemctl restart nginx

# Test SSL certificate
echo "Testing SSL certificate..."
if curl -s "https://$DOMAIN" > /dev/null; then
    echo "✓ SSL certificate is working correctly"
else
    echo "✗ SSL certificate test failed"
fi

# Set up automatic renewal
echo "Setting up automatic certificate renewal..."
cat > /etc/cron.d/cupcake-ssl << EOF
# CUPCAKE SSL Certificate Renewal
# Runs twice daily
0 2,14 * * * root certbot renew --quiet --post-hook "systemctl reload nginx"
EOF

echo
echo "SSL setup completed successfully!"
echo "CUPCAKE is now accessible at: https://$DOMAIN"
echo
echo "Important notes:"
echo "- SSL certificates will auto-renew every 60 days"
echo "- Update your DNS to point $DOMAIN to this server's IP: $SERVER_IP"
echo "- Consider setting up a firewall to restrict access"
echo
echo "Next steps:"
echo "1. Test CUPCAKE functionality at https://$DOMAIN"
echo "2. Create superuser account: sudo -u cupcake /opt/cupcake/venv/bin/python /opt/cupcake/src/manage.py createsuperuser"
echo "3. Configure laboratory-specific settings in the admin panel"