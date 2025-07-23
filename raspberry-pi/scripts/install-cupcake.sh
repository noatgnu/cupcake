#!/bin/bash
set -e

# Main CUPCAKE installation script for pi-gen
echo "=== Starting CUPCAKE installation ==="

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Update package list and install base packages
export DEBIAN_FRONTEND=noninteractive
apt-get update

# Add PostgreSQL official APT repository
curl https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/apt.postgresql.org.gpg > /dev/null
echo 'deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list
apt-get update

# Install all required packages
apt-get install -y postgresql-14 postgresql-client-14 postgresql-contrib-14
apt-get install -y redis-server redis-tools
apt-get install -y nginx
apt-get install -y python3 python3-pip python3-venv python3-dev
apt-get install -y build-essential libpq-dev libffi-dev libssl-dev
apt-get install -y libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
apt-get install -y git curl wget unzip htop nvme-cli cmake pkg-config
apt-get install -y ffmpeg libavcodec-extra fail2ban ufw libopenblas-dev

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs npm

# Create cupcake user and directories
useradd -m -s /bin/bash cupcake
usermod -aG sudo cupcake
echo 'cupcake ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/cupcake

# Create CUPCAKE directories
mkdir -p /opt/cupcake/{scripts,config,logs,app,venv,data,backup,assets}
mkdir -p /var/lib/cupcake
mkdir -p /var/log/cupcake
mkdir -p /opt/whisper.cpp

# Run component setup scripts
echo "Running component setup scripts..."
bash "$SCRIPT_DIR/setup-whisper.sh"
bash "$SCRIPT_DIR/setup-postgresql.sh"
bash "$SCRIPT_DIR/setup-redis.sh"
bash "$SCRIPT_DIR/setup-nginx.sh"

# Install systemd services
bash "$SCRIPT_DIR/install-systemd-services.sh"

# Install cupcake-config utility
cp "$SCRIPT_DIR/cupcake-config" /usr/local/bin/
chmod +x /usr/local/bin/cupcake-config

# Create runtime directory config
echo 'd /var/run/cupcake 0755 cupcake cupcake -' > /etc/tmpfiles.d/cupcake.conf

# Set ownership
chown -R cupcake:cupcake /opt/cupcake /var/log/cupcake /var/lib/cupcake

# Clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "=== CUPCAKE installation completed successfully ==="
