#!/bin/bash
set -e

echo "=== Configuring PostgreSQL ==="

# Configure PostgreSQL
systemctl enable postgresql
echo 'shared_buffers = 256MB' >> /etc/postgresql/14/main/postgresql.conf
echo 'work_mem = 8MB' >> /etc/postgresql/14/main/postgresql.conf
echo 'effective_cache_size = 1GB' >> /etc/postgresql/14/main/postgresql.conf
echo 'random_page_cost = 1.1' >> /etc/postgresql/14/main/postgresql.conf

# Start PostgreSQL to create database
service postgresql start
sudo -u postgres createuser cupcake
sudo -u postgres createdb cupcake_db -O cupcake
sudo -u postgres psql -c "ALTER USER cupcake WITH PASSWORD 'cupcake123';" || \
    sudo -u postgres psql -c $'ALTER USER cupcake WITH PASSWORD \'cupcake123\';'
service postgresql stop

echo "=== PostgreSQL configuration completed ==="
