#!/bin/bash
set -e

# CUPCAKE PostgreSQL Setup Script for Raspberry Pi
# This script configures PostgreSQL for optimal performance on Pi hardware

echo "=== Configuring PostgreSQL for CUPCAKE ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

# Install PostgreSQL if not already installed
if ! command -v psql &> /dev/null; then
    echo "Installing PostgreSQL..."
    apt-get update
    apt-get install -y postgresql postgresql-client
fi

# Enable PostgreSQL service (handle chroot environment)
# Detect chroot: if /proc/1/root doesn't point to real root, we're in chroot
if [ "$(stat -c %d:%i /)" != "$(stat -c %d:%i /proc/1/root/. 2>/dev/null)" ] 2>/dev/null; then
    # We're in chroot, skip systemctl enable but still configure
    echo "Detected chroot environment, will manually start PostgreSQL"
    CHROOT_MODE=true
else
    systemctl enable postgresql
    CHROOT_MODE=false
fi

echo "Configuring PostgreSQL for Raspberry Pi performance..."

# Configure PostgreSQL for Raspberry Pi (optimized for 4-8GB RAM)
cat >> /etc/postgresql/15/main/postgresql.conf << 'PGCONF'

# CUPCAKE Raspberry Pi Optimized Settings
# Optimized for 4-8GB Pi with moderate concurrent usage

# Memory settings (conservative for Pi)
shared_buffers = 256MB                    # 25% of RAM for 1GB, adjust for your Pi
work_mem = 8MB                           # Per-operation memory
maintenance_work_mem = 64MB              # Maintenance operations
effective_cache_size = 1GB               # Available memory for caching

# Connection settings
max_connections = 50                     # Reduced for Pi resource limits

# Write-ahead logging (performance vs reliability balance)
wal_buffers = 16MB
checkpoint_completion_target = 0.9
checkpoint_timeout = 15min

# Query planner settings (optimized for SSD/fast storage)
random_page_cost = 1.1                  # Assumes SSD storage (Pi with NVMe)
effective_io_concurrency = 200          # For SSD storage

# Logging (reduced for Pi storage)
log_destination = 'stderr'
logging_collector = on
log_directory = '/var/log/postgresql'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_min_duration_statement = 1000ms     # Log slow queries (1 second)

# Auto vacuum settings (important for CUPCAKE data)
autovacuum = on
autovacuum_max_workers = 2               # Reduced for Pi
autovacuum_naptime = 1min               # More frequent cleanup

# Ensure correct port configuration
port = 5432
PGCONF

if [ "$CHROOT_MODE" = "false" ]; then
    echo "Starting PostgreSQL service..."
    
    # Start PostgreSQL service
    systemctl daemon-reload
    systemctl start postgresql
    
    # Wait for PostgreSQL to be ready
    sleep 3
else
    echo "Starting PostgreSQL manually in chroot environment..."
    
    # Initialize database if needed
    if [ ! -d "/var/lib/postgresql/15/main" ]; then
        echo "Initializing PostgreSQL database cluster..."
        su - postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/15/main"
    fi
    
    # Start PostgreSQL manually
    echo "Starting PostgreSQL server..."
    su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/15/main -l /var/log/postgresql/postgresql-15-main.log start" || {
        echo "Manual PostgreSQL start failed"
        exit 1
    }
    sleep 3
fi

echo "Creating CUPCAKE database and user..."

# Create user and database (with error handling for existing resources)
su - postgres -c "createuser cupcake" 2>/dev/null || echo "User 'cupcake' already exists"
su - postgres -c "psql -c \"ALTER USER cupcake WITH PASSWORD 'cupcake';\"" || {
    echo "Error setting password for cupcake user"
    exit 1
}
su - postgres -c "createdb -O cupcake cupcake" 2>/dev/null || echo "Database 'cupcake' already exists"

echo "Testing database connection..."

# Test database connection
if su - postgres -c "psql -d cupcake -c 'SELECT 1;'" > /dev/null 2>&1; then
    echo "✅ Database connection test successful"
else
    echo "❌ Database connection test failed"
    exit 1
fi

echo "Configuring PostgreSQL service..."

if [ "$CHROOT_MODE" = "false" ]; then
    # Restart PostgreSQL to apply configuration changes
    systemctl restart postgresql
    
    # Verify PostgreSQL is running and configured correctly
    if systemctl is-active --quiet postgresql; then
        echo "✅ PostgreSQL is running successfully"
        echo "📊 Database: cupcake"
        echo "👤 User: cupcake"
        echo "🔌 Port: 5432"
        echo "🗂️  Config: /etc/postgresql/15/main/postgresql.conf"
    else
        echo "❌ PostgreSQL failed to start"
        systemctl status postgresql
        exit 1
    fi
else
    echo "✅ PostgreSQL configured successfully (chroot mode)"
    echo "📊 Database: cupcake"
    echo "👤 User: cupcake"
    echo "🔌 Port: 5432"
    echo "🗂️  Config: /etc/postgresql/15/main/postgresql.conf"
    echo "ℹ️  Services will be started on first boot"
    
    # Stop the manually started PostgreSQL
    su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/15/main stop" 2>/dev/null || true
fi

echo ""
echo "=== PostgreSQL Configuration Summary ==="
echo "✅ PostgreSQL 15 installed and configured"
echo "✅ Optimized for Raspberry Pi hardware"
echo "✅ CUPCAKE database and user created"
echo "✅ Performance tuning applied"
echo "✅ Logging configured for monitoring"
echo ""
echo "Database: cupcake"
echo "User: cupcake / cupcake"
echo "Port: 5432 (local only)"
echo ""
echo "=== PostgreSQL configuration completed successfully ==="
