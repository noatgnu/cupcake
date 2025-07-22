#!/bin/bash
# CUPCAKE System Setup Hook for rpi-image-gen
# Configures basic system settings for CUPCAKE deployment

set -e

echo ">>> CUPCAKE: Setting up system configuration..."

# Create cupcake user and group
if ! getent group cupcake > /dev/null 2>&1; then
    groupadd --system cupcake
    echo "Created cupcake group"
fi

if ! getent passwd cupcake > /dev/null 2>&1; then
    useradd --system --gid cupcake --home-dir /opt/cupcake \
            --shell /bin/bash --comment "CUPCAKE Service User" cupcake
    echo "Created cupcake user"
fi

# Create required directories
mkdir -p /opt/cupcake
mkdir -p /var/lib/cupcake
mkdir -p /var/log/cupcake
mkdir -p /etc/ssl/cupcake

# Set proper ownership
chown -R cupcake:cupcake /opt/cupcake
chown -R cupcake:cupcake /var/lib/cupcake
chown -R cupcake:cupcake /var/log/cupcake
chown -R root:cupcake /etc/ssl/cupcake
chmod 750 /etc/ssl/cupcake

# Configure PostgreSQL
echo ">>> CUPCAKE: Configuring PostgreSQL..."
systemctl enable postgresql

# Configure Redis
echo ">>> CUPCAKE: Configuring Redis..."
systemctl enable redis-server

# Configure Nginx
echo ">>> CUPCAKE: Configuring Nginx..."
systemctl enable nginx

# Configure SSH
echo ">>> CUPCAKE: Configuring SSH..."
systemctl enable ssh

# Configure UFW firewall
echo ">>> CUPCAKE: Configuring firewall..."
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
systemctl enable ufw

# Configure fail2ban
echo ">>> CUPCAKE: Configuring fail2ban..."
systemctl enable fail2ban

# Configure system limits for database performance
cat >> /etc/security/limits.conf << 'EOF'

# CUPCAKE database optimization
postgres soft nofile 65536
postgres hard nofile 65536
cupcake soft nofile 65536
cupcake hard nofile 65536
EOF

# Configure sysctl for network and database performance
cat >> /etc/sysctl.d/99-cupcake.conf << 'EOF'
# CUPCAKE system optimization
vm.swappiness=1
vm.dirty_background_ratio=5
vm.dirty_ratio=10
net.core.somaxconn=1024
net.core.netdev_max_backlog=5000
net.ipv4.tcp_max_syn_backlog=1024
fs.file-max=2097152
EOF

# Enable I2C and SPI for potential lab hardware
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

# Configure GPU memory split for headless operation
echo "gpu_mem=64" >> /boot/config.txt

# Set up log rotation for CUPCAKE
cat > /etc/logrotate.d/cupcake << 'EOF'
/var/log/cupcake/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    sharedscripts
    postrotate
        systemctl reload cupcake || true
    endscript
    su cupcake cupcake
}
EOF

echo ">>> CUPCAKE: System setup completed successfully"