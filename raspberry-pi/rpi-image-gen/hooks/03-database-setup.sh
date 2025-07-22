#!/bin/bash
# CUPCAKE Database Setup Hook
# Configures PostgreSQL and Redis for CUPCAKE

set -e

echo ">>> CUPCAKE: Setting up databases..."

# Configure PostgreSQL
echo ">>> CUPCAKE: Configuring PostgreSQL..."

# Stop PostgreSQL to configure it
systemctl stop postgresql

# Create PostgreSQL data directory
mkdir -p /var/lib/postgresql/14/main
chown -R postgres:postgres /var/lib/postgresql

# Initialize PostgreSQL cluster if needed
if [ ! -f /var/lib/postgresql/14/main/PG_VERSION ]; then
    sudo -u postgres /usr/lib/postgresql/14/bin/initdb \
        --pgdata=/var/lib/postgresql/14/main \
        --auth-local=peer \
        --auth-host=md5 \
        --encoding=UTF8 \
        --locale=en_US.UTF-8
fi

# Configure PostgreSQL for CUPCAKE performance
cat > /etc/postgresql/14/main/postgresql.conf << 'EOF'
# CUPCAKE PostgreSQL Configuration for Raspberry Pi 5

# Connection settings
listen_addresses = 'localhost'
port = 5432
max_connections = 50
unix_socket_directories = '/var/run/postgresql'

# Memory settings (optimized for Pi 5 8GB)
shared_buffers = 512MB
effective_cache_size = 2GB
maintenance_work_mem = 128MB
work_mem = 16MB
wal_buffers = 16MB

# Checkpoint settings
checkpoint_completion_target = 0.9
wal_level = replica
max_wal_size = 2GB
min_wal_size = 80MB

# Query planner
default_statistics_target = 100
random_page_cost = 1.1

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = '/var/log/postgresql'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_statement = 'none'
log_min_duration_statement = 1000
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '

# Performance monitoring
shared_preload_libraries = 'pg_stat_statements'
track_activity_query_size = 2048
pg_stat_statements.max = 10000
pg_stat_statements.track = all

# Vacuum and autovacuum
autovacuum = on
autovacuum_max_workers = 2
autovacuum_naptime = 30s
autovacuum_vacuum_threshold = 50
autovacuum_analyze_threshold = 50

# Locale
lc_messages = 'en_US.UTF-8'
lc_monetary = 'en_US.UTF-8'
lc_numeric = 'en_US.UTF-8'
lc_time = 'en_US.UTF-8'
default_text_search_config = 'pg_catalog.english'
timezone = 'UTC'
EOF

# Configure PostgreSQL authentication
cat > /etc/postgresql/14/main/pg_hba.conf << 'EOF'
# CUPCAKE PostgreSQL Authentication Configuration

# TYPE  DATABASE        USER            ADDRESS                 METHOD

# "local" is for Unix domain socket connections only
local   all             postgres                                peer
local   all             cupcake                                 md5
local   all             all                                     peer

# IPv4 local connections:
host    all             cupcake         127.0.0.1/32            md5
host    all             all             127.0.0.1/32            ident

# IPv6 local connections:
host    all             all             ::1/128                 ident
EOF

# Start PostgreSQL
systemctl start postgresql

# Create CUPCAKE database and user
sudo -u postgres createuser -P cupcake || echo "User cupcake already exists"
sudo -u postgres createdb -O cupcake cupcake_db || echo "Database cupcake_db already exists"

# Grant necessary permissions
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE cupcake_db TO cupcake;" || true
sudo -u postgres psql -d cupcake_db -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;" || true

# Configure Redis
echo ">>> CUPCAKE: Configuring Redis..."

# Backup original config
cp /etc/redis/redis.conf /etc/redis/redis.conf.bak

# Configure Redis for CUPCAKE
cat > /etc/redis/redis.conf << 'EOF'
# CUPCAKE Redis Configuration for Raspberry Pi 5

# Network
bind 127.0.0.1 ::1
port 6379
tcp-backlog 511
timeout 0
tcp-keepalive 300

# General
daemonize no
supervised systemd
pidfile /var/run/redis/redis-server.pid
loglevel notice
logfile /var/log/redis/redis-server.log
databases 16

# Memory management (optimized for Pi 5)
maxmemory 256mb
maxmemory-policy allkeys-lru
maxmemory-samples 5

# Persistence
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename cupcake.rdb
dir /var/lib/redis

# Security
requirepass redis_password_change_me
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command DEBUG ""
rename-command CONFIG "CONFIG_c0nf1g_r3n4m3d"

# Limits
maxclients 100

# Append only file
appendonly no
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
aof-load-truncated yes

# Slow log
slowlog-log-slower-than 10000
slowlog-max-len 128

# Event notification
notify-keyspace-events ""

# Advanced config
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
list-max-ziplist-size -2
list-compress-depth 0
set-max-intset-entries 512
zset-max-ziplist-entries 128
zset-max-ziplist-value 64
hll-sparse-max-bytes 3000
stream-node-max-bytes 4096
stream-node-max-entries 100
activerehashing yes
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit replica 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60
hz 10
dynamic-hz yes
aof-rewrite-incremental-fsync yes
rdb-save-incremental-fsync yes
EOF

# Set proper permissions
chown redis:redis /etc/redis/redis.conf
chmod 640 /etc/redis/redis.conf

# Create Redis log directory
mkdir -p /var/log/redis
chown redis:redis /var/log/redis

# Start Redis
systemctl start redis-server

# Create database initialization script
cat > /opt/cupcake/scripts/init-db.sh << 'EOF'
#!/bin/bash
# CUPCAKE Database Initialization Script

set -e

echo "Initializing CUPCAKE database..."

# Activate Python environment
source /opt/cupcake/venv/bin/activate

# Set environment variables
export DJANGO_SETTINGS_MODULE=cupcake.settings.production
export CUPCAKE_DB_HOST=localhost
export CUPCAKE_DB_PORT=5432
export CUPCAKE_DB_NAME=cupcake_db
export CUPCAKE_DB_USER=cupcake
export CUPCAKE_REDIS_HOST=localhost
export CUPCAKE_REDIS_PORT=6379

# Run Django migrations
cd /opt/cupcake/src
python manage.py makemigrations
python manage.py migrate

# Create superuser (interactive)
echo "Creating CUPCAKE superuser account..."
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput

echo "Database initialization completed successfully!"
EOF

chmod +x /opt/cupcake/scripts/init-db.sh
chown cupcake:cupcake /opt/cupcake/scripts/init-db.sh

echo ">>> CUPCAKE: Database setup completed successfully"
echo ">>> Run '/opt/cupcake/scripts/init-db.sh' after deploying CUPCAKE source code"