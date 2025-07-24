#!/bin/bash

# CUPCAKE Raspberry Pi 5 Performance Optimization Script
# Optimizes the system for better performance and reduced power consumption

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
fi

log "Starting Raspberry Pi 5 optimization for CUPCAKE..."

# System optimization
optimize_system() {
    log "Optimizing system configuration..."
    
    # Disable unnecessary services
    local services_to_disable=(
        "bluetooth"
        "hciuart"
        "triggerhappy"
        "avahi-daemon"
        "ModemManager"
    )
    
    for service in "${services_to_disable[@]}"; do
        if systemctl is-enabled --quiet "$service" 2>/dev/null; then
            systemctl disable "$service"
            systemctl stop "$service" 2>/dev/null || true
            info "Disabled service: $service"
        fi
    done
    
    # Configure kernel parameters
    cat >> /etc/sysctl.conf << EOF

# CUPCAKE Performance Optimizations
vm.swappiness=10
vm.dirty_ratio=15
vm.dirty_background_ratio=5
vm.vfs_cache_pressure=50

# Network optimizations
net.core.rmem_max=134217728
net.core.wmem_max=134217728
net.ipv4.tcp_rmem=4096 65536 134217728
net.ipv4.tcp_wmem=4096 65536 134217728

# File system optimizations
fs.file-max=100000
EOF
    
    # Apply immediately
    sysctl -p
    
    log "System optimization completed"
}

# CPU optimization
optimize_cpu() {
    log "Optimizing CPU configuration..."
    
    # Set CPU governor
    echo 'GOVERNOR="ondemand"' > /etc/default/cpufrequtils
    
    # Configure CPU frequency scaling
    cat > /etc/udev/rules.d/50-cpu-scaling.rules << EOF
# CPU frequency scaling optimization
ACTION=="add", SUBSYSTEM=="cpu", KERNEL=="cpu[0-9]*", RUN+="/bin/sh -c 'echo ondemand > /sys/devices/system/cpu/%k/cpufreq/scaling_governor'"
ACTION=="add", SUBSYSTEM=="cpu", KERNEL=="cpu[0-9]*", RUN+="/bin/sh -c 'echo 50 > /sys/devices/system/cpu/%k/cpufreq/ondemand/up_threshold'"
ACTION=="add", SUBSYSTEM=="cpu", KERNEL=="cpu[0-9]*", RUN+="/bin/sh -c 'echo 10 > /sys/devices/system/cpu/%k/cpufreq/ondemand/sampling_down_factor'"
EOF
    
    # Configure thermal management
    cat >> /boot/firmware/config.txt << EOF

# CPU thermal and performance settings
temp_limit=75
initial_turbo=30
arm_freq=2400
gpu_freq=750
over_voltage=2
EOF
    
    log "CPU optimization completed"
}

# Memory optimization
optimize_memory() {
    log "Optimizing memory configuration..."
    
    # Configure GPU memory split
    if ! grep -q "gpu_mem=16" /boot/firmware/config.txt; then
        echo "gpu_mem=16" >> /boot/firmware/config.txt
    fi
    
    # Configure swap
    local swap_size=1024
    local total_memory=$(free -m | awk '/^Mem:/{print $2}')
    
    if [[ $total_memory -gt 4096 ]]; then
        swap_size=2048
    fi
    
    # Configure swap file
    cat > /etc/dphys-swapfile << EOF
CONF_SWAPSIZE=$swap_size
CONF_SWAPFILE=/var/swap
CONF_MAXSWAP=4096
CONF_SWAPFACTOR=2
EOF
    
    # Restart swap service
    systemctl restart dphys-swapfile
    
    # Configure ZRAM for better memory efficiency
    if ! dpkg -l | grep -q "zram-tools"; then
        apt-get update
        apt-get install -y zram-tools
    fi
    
    cat > /etc/default/zramswap << EOF
# ZRAM configuration for CUPCAKE
ENABLED=true
SIZE=512
PRIORITY=100
EOF
    
    systemctl enable zramswap
    systemctl start zramswap
    
    log "Memory optimization completed"
}

# Storage optimization
optimize_storage() {
    log "Optimizing storage configuration..."
    
    # Detect storage type (NVMe vs SD card)
    local root_device=$(findmnt -n -o SOURCE /)
    local is_nvme=false
    
    if [[ "$root_device" =~ nvme ]]; then
        is_nvme=true
        info "NVMe SSD detected - applying NVMe optimizations"
    else
        info "SD card detected - applying SD card optimizations"
    fi
    
    # Configure tmpfs for temporary files
    if [[ "$is_nvme" == "true" ]]; then
        # NVMe optimizations - less aggressive tmpfs
        cat >> /etc/fstab << EOF

# CUPCAKE NVMe optimizations
tmpfs /tmp tmpfs defaults,noatime,nosuid,size=200m 0 0
tmpfs /var/tmp tmpfs defaults,noatime,nosuid,size=100m 0 0
EOF
        
        # Enable TRIM for NVMe
        systemctl enable fstrim.timer
        
        # NVMe-specific mount options
        sed -i 's/defaults,noatime/defaults,noatime,discard/' /etc/fstab
        
    else
        # SD card optimizations - more aggressive tmpfs
        cat >> /etc/fstab << EOF

# CUPCAKE SD card optimizations
tmpfs /tmp tmpfs defaults,noatime,nosuid,size=100m 0 0
tmpfs /var/tmp tmpfs defaults,noatime,nosuid,size=50m 0 0
tmpfs /var/log tmpfs defaults,noatime,nosuid,size=50m 0 0
tmpfs /run tmpfs defaults,noatime,nosuid,size=50m 0 0
EOF
    fi
    
    # Configure log rotation
    cat > /etc/logrotate.d/cupcake-system << EOF
/var/log/cupcake/*.log {
    daily
    missingok
    rotate 3
    compress
    delaycompress
    notifempty
    create 0644 cupcake cupcake
    postrotate
        systemctl reload cupcake-web || true
    endscript
}

/var/log/syslog
/var/log/auth.log
/var/log/kern.log
/var/log/daemon.log {
    daily
    missingok
    rotate 3
    compress
    delaycompress
    notifempty
}
EOF
    
    # Set mount options for better performance
    if ! grep -q "noatime" /etc/fstab; then
        sed -i 's/defaults/defaults,noatime/' /etc/fstab
    fi
    
    log "Storage optimization completed"
}

# Network optimization
optimize_network() {
    log "Optimizing network configuration..."
    
    # Configure network buffers
    cat > /etc/sysctl.d/60-cupcake-network.conf << EOF
# CUPCAKE Network Optimizations
net.core.netdev_max_backlog=5000
net.core.netdev_budget=600
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_window_scaling=1
net.ipv4.tcp_timestamps=1
net.ipv4.tcp_sack=1
net.ipv4.tcp_low_latency=1
net.ipv4.tcp_fastopen=3
EOF
    
    # Apply network settings
    sysctl -p /etc/sysctl.d/60-cupcake-network.conf
    
    log "Network optimization completed"
}

# PostgreSQL optimization
optimize_postgresql() {
    log "Optimizing PostgreSQL configuration..."
    
    local pg_version=$(sudo -u postgres psql -t -c "SELECT version();" | grep -oP '\d+\.\d+' | head -1)
    local pg_config="/etc/postgresql/$pg_version/main/postgresql.conf"
    local total_memory=$(free -m | awk '/^Mem:/{print $2}')
    
    # Detect storage type
    local root_device=$(findmnt -n -o SOURCE /)
    local is_nvme=false
    
    if [[ "$root_device" =~ nvme ]]; then
        is_nvme=true
        info "Optimizing PostgreSQL for NVMe SSD"
    else
        info "Optimizing PostgreSQL for SD card"
    fi
    
    if [[ -f "$pg_config" ]]; then
        # Backup original config
        cp "$pg_config" "$pg_config.backup"
        
        # Calculate memory settings based on available RAM
        local shared_buffers=$((total_memory / 4))
        local effective_cache_size=$((total_memory * 3 / 4))
        local work_mem=$((total_memory / 50))
        local maintenance_work_mem=$((total_memory / 8))
        
        # Add optimizations
        if [[ "$is_nvme" == "true" ]]; then
            # NVMe SSD optimizations
            cat >> "$pg_config" << EOF

# CUPCAKE Raspberry Pi PostgreSQL Optimizations (NVMe SSD)
shared_buffers = ${shared_buffers}MB
effective_cache_size = ${effective_cache_size}MB
work_mem = ${work_mem}MB
maintenance_work_mem = ${maintenance_work_mem}MB

# Connection settings
max_connections = 50
superuser_reserved_connections = 3

# WAL settings (NVMe optimized)
wal_buffers = 16MB
checkpoint_completion_target = 0.9
checkpoint_timeout = 10min
max_wal_size = 1GB
min_wal_size = 256MB
wal_compression = on
full_page_writes = off

# Query optimization (NVMe)
random_page_cost = 1.1
seq_page_cost = 1.0
effective_io_concurrency = 200
maintenance_io_concurrency = 10
default_statistics_target = 100

# Background writer (NVMe)
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0
bgwriter_flush_after = 0

# Autovacuum (more aggressive for NVMe)
autovacuum = on
autovacuum_max_workers = 3
autovacuum_naptime = 30s
autovacuum_vacuum_threshold = 50
autovacuum_analyze_threshold = 50
EOF
        else
            # SD card optimizations
            cat >> "$pg_config" << EOF

# CUPCAKE Raspberry Pi PostgreSQL Optimizations (SD Card)
shared_buffers = ${shared_buffers}MB
effective_cache_size = ${effective_cache_size}MB
work_mem = ${work_mem}MB
maintenance_work_mem = ${maintenance_work_mem}MB

# Connection settings
max_connections = 50
superuser_reserved_connections = 3

# WAL settings (SD card optimized)
wal_buffers = 16MB
checkpoint_completion_target = 0.9
checkpoint_timeout = 15min
max_wal_size = 512MB
min_wal_size = 128MB
wal_compression = on

# Query optimization (SD card)
random_page_cost = 4.0
seq_page_cost = 1.0
effective_io_concurrency = 1
maintenance_io_concurrency = 1
default_statistics_target = 100

# Background writer (SD card conservative)
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0

# Autovacuum (conservative for SD card)
autovacuum = on
autovacuum_max_workers = 2
autovacuum_naptime = 1min
autovacuum_vacuum_threshold = 50
autovacuum_analyze_threshold = 50
EOF
        fi
        
        # Common logging settings
        cat >> "$pg_config" << EOF

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = '/var/log/postgresql'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 10MB
log_min_duration_statement = 1000
log_line_prefix = '%t [%p-%l] %q%u@%d '
EOF
        
        systemctl restart postgresql
        info "PostgreSQL optimized for ${total_memory}MB RAM"
    fi
    
    log "PostgreSQL optimization completed"
}

# Redis optimization
optimize_redis() {
    log "Optimizing Redis configuration..."
    
    local total_memory=$(free -m | awk '/^Mem:/{print $2}')
    local redis_memory=$((total_memory / 8))
    
    # Backup original config
    cp /etc/redis/redis.conf /etc/redis/redis.conf.backup
    
    cat > /etc/redis/redis.conf << EOF
# CUPCAKE Redis Configuration for Raspberry Pi
bind 127.0.0.1
port 6379
timeout 300
tcp-keepalive 60

# Memory optimization
maxmemory ${redis_memory}mb
maxmemory-policy allkeys-lru
maxmemory-samples 5

# Persistence
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb

# Logging
loglevel notice
logfile /var/log/redis/redis-server.log
syslog-enabled yes
syslog-ident redis

# Slow log
slowlog-log-slower-than 10000
slowlog-max-len 128

# Advanced config
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
list-max-ziplist-size -2
list-compress-depth 0
set-max-intset-entries 512
zset-max-ziplist-entries 128
zset-max-ziplist-value 64
hll-sparse-max-bytes 3000

# Security
protected-mode yes
requirepass cupcake_redis_password

# Other settings
databases 16
dir /var/lib/redis
supervised systemd
EOF
    
    systemctl restart redis-server
    info "Redis optimized with ${redis_memory}MB memory limit"
    
    log "Redis optimization completed"
}

# Nginx optimization
optimize_nginx() {
    log "Optimizing Nginx configuration..."
    
    # Backup original config
    cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
    
    cat > /etc/nginx/nginx.conf << EOF
user www-data;
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;
    
    # Buffer sizes
    client_body_buffer_size 128k;
    client_header_buffer_size 1k;
    client_max_body_size 100m;
    large_client_header_buffers 4 4k;
    
    # Timeouts
    client_body_timeout 12;
    client_header_timeout 12;
    send_timeout 10;
    
    # MIME
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;
    
    # Logging
    log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                    '\$status \$body_bytes_sent "\$http_referer" '
                    '"\$http_user_agent" "\$http_x_forwarded_for"';
    
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log;
    
    # Rate limiting
    limit_req_zone \$binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone \$binary_remote_addr zone=login:10m rate=1r/s;
    
    # Include sites
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF
    
    # Update site configuration
    cat > /etc/nginx/sites-available/cupcake << 'EOF'
server {
    listen 80;
    server_name cupcake-pi.local cupcake-pi _;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
    
    # Rate limiting
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
    }
    
    location /admin/login/ {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
    }
    
    # Static files with caching
    location /static/ {
        alias /opt/cupcake/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        add_header Vary Accept-Encoding;
        
        # Compression for static files
        location ~* \.(css|js)$ {
            gzip_static on;
        }
    }
    
    location /media/ {
        alias /opt/cupcake/media/;
        expires 30d;
        add_header Cache-Control "public";
        
        # Security for uploaded files
        location ~* \.(php|py|pl|sh|cgi)$ {
            deny all;
        }
    }
    
    # Main application
    location / {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
        
        # Caching for some responses
        location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
            expires 1y;
            add_header Cache-Control "public";
        }
    }
    
    # WebSocket support
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        include /etc/nginx/proxy_params;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF
    
    # Create proxy params
    cat > /etc/nginx/proxy_params << EOF
proxy_set_header Host \$http_host;
proxy_set_header X-Real-IP \$remote_addr;
proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto \$scheme;
proxy_connect_timeout 30s;
proxy_send_timeout 30s;
proxy_read_timeout 30s;
proxy_buffering on;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
EOF
    
    # Test configuration
    nginx -t
    systemctl restart nginx
    
    log "Nginx optimization completed"
}

# Create system monitoring dashboard
create_dashboard() {
    log "Creating system monitoring dashboard..."
    
    cat > /opt/cupcake/scripts/dashboard.py << 'EOF'
#!/usr/bin/env python3
"""
CUPCAKE System Dashboard
Simple web-based system monitoring for Raspberry Pi
"""

import json
import time
import psutil
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import subprocess

class SystemDashboard:
    def __init__(self):
        self.status_file = "/var/lib/cupcake/system_status.json"
    
    def get_system_info(self):
        """Get current system information"""
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory': psutil.virtual_memory()._asdict(),
            'disk': psutil.disk_usage('/')._asdict(),
            'temperature': self.get_temperature(),
            'load_avg': psutil.getloadavg(),
            'uptime': time.time() - psutil.boot_time(),
            'processes': len(psutil.pids()),
            'network': psutil.net_io_counters()._asdict()
        }
    
    def get_temperature(self):
        """Get CPU temperature"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = int(f.read().strip()) / 1000
                return round(temp, 1)
        except:
            return 0
    
    def get_services_status(self):
        """Get CUPCAKE services status"""
        services = ['cupcake-web', 'cupcake-worker', 'postgresql', 'redis-server', 'nginx']
        status = {}
        
        for service in services:
            try:
                result = subprocess.run(['systemctl', 'is-active', service], 
                                      capture_output=True, text=True)
                status[service] = result.stdout.strip()
            except:
                status[service] = 'unknown'
        
        return status

class DashboardHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, dashboard=None, **kwargs):
        self.dashboard = dashboard
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_dashboard_html().encode())
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            data = {
                'system': self.dashboard.get_system_info(),
                'services': self.dashboard.get_services_status(),
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def get_dashboard_html(self):
        return '''
<!DOCTYPE html>
<html>
<head>
    <title>CUPCAKE System Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; color: #333; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metric { margin: 10px 0; }
        .metric-label { font-weight: bold; color: #555; }
        .metric-value { font-size: 18px; color: #333; }
        .status-ok { color: #4CAF50; }
        .status-error { color: #f44336; }
        .progress { width: 100%; height: 20px; background: #eee; border-radius: 10px; overflow: hidden; }
        .progress-bar { height: 100%; transition: width 0.3s; }
        .progress-low { background: #4CAF50; }
        .progress-medium { background: #FF9800; }
        .progress-high { background: #f44336; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧁 CUPCAKE System Dashboard</h1>
            <p>Raspberry Pi 5 - Real-time System Monitoring</p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>System Resources</h3>
                <div class="metric">
                    <div class="metric-label">CPU Usage</div>
                    <div class="progress">
                        <div id="cpu-bar" class="progress-bar progress-low"></div>
                    </div>
                    <div id="cpu-value" class="metric-value">0%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Memory Usage</div>
                    <div class="progress">
                        <div id="memory-bar" class="progress-bar progress-low"></div>
                    </div>
                    <div id="memory-value" class="metric-value">0%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">CPU Temperature</div>
                    <div id="temperature" class="metric-value">0°C</div>
                </div>
            </div>
            
            <div class="card">
                <h3>Services Status</h3>
                <div id="services"></div>
            </div>
            
            <div class="card">
                <h3>System Information</h3>
                <div class="metric">
                    <div class="metric-label">Load Average</div>
                    <div id="load-avg" class="metric-value">0.00</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Uptime</div>
                    <div id="uptime" class="metric-value">0 days</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Processes</div>
                    <div id="processes" class="metric-value">0</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function updateDashboard() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    // Update CPU
                    const cpu = data.system.cpu_percent;
                    document.getElementById('cpu-value').textContent = cpu.toFixed(1) + '%';
                    const cpuBar = document.getElementById('cpu-bar');
                    cpuBar.style.width = cpu + '%';
                    cpuBar.className = 'progress-bar ' + getProgressClass(cpu);
                    
                    // Update Memory
                    const memPercent = (data.system.memory.used / data.system.memory.total) * 100;
                    document.getElementById('memory-value').textContent = memPercent.toFixed(1) + '%';
                    const memBar = document.getElementById('memory-bar');
                    memBar.style.width = memPercent + '%';
                    memBar.className = 'progress-bar ' + getProgressClass(memPercent);
                    
                    // Update Temperature
                    document.getElementById('temperature').textContent = data.system.temperature + '°C';
                    
                    // Update Services
                    const servicesDiv = document.getElementById('services');
                    servicesDiv.innerHTML = '';
                    for (const [service, status] of Object.entries(data.services)) {
                        const div = document.createElement('div');
                        div.className = 'metric';
                        div.innerHTML = `
                            <span class="metric-label">${service}:</span>
                            <span class="${status === 'active' ? 'status-ok' : 'status-error'}">${status}</span>
                        `;
                        servicesDiv.appendChild(div);
                    }
                    
                    // Update System Info
                    document.getElementById('load-avg').textContent = data.system.load_avg[0].toFixed(2);
                    document.getElementById('uptime').textContent = formatUptime(data.system.uptime);
                    document.getElementById('processes').textContent = data.system.processes;
                })
                .catch(error => console.error('Error updating dashboard:', error));
        }
        
        function getProgressClass(value) {
            if (value < 50) return 'progress-low';
            if (value < 80) return 'progress-medium';
            return 'progress-high';
        }
        
        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${days}d ${hours}h ${minutes}m`;
        }
        
        // Update every 5 seconds
        updateDashboard();
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
        '''

def main():
    dashboard = SystemDashboard()
    
    def handler(*args, **kwargs):
        DashboardHandler(*args, dashboard=dashboard, **kwargs)
    
    server = HTTPServer(('127.0.0.1', 9000), handler)
    print("Dashboard available at http://localhost:9000")
    server.serve_forever()

if __name__ == '__main__':
    main()
EOF
    
    chmod +x /opt/cupcake/scripts/dashboard.py
    
    # Create systemd service for dashboard
    cat > /etc/systemd/system/cupcake-dashboard.service << EOF
[Unit]
Description=CUPCAKE System Dashboard
After=network.target

[Service]
Type=simple
User=cupcake
Group=cupcake
ExecStart=/usr/bin/python3 /opt/cupcake/scripts/dashboard.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable cupcake-dashboard.service
    systemctl start cupcake-dashboard.service
    
    log "System monitoring dashboard created at http://localhost:9000"
}

# Performance testing
run_performance_test() {
    log "Running performance tests..."
    
    # Create performance test script
    cat > /opt/cupcake/scripts/perf-test.sh << 'EOF'
#!/bin/bash
# CUPCAKE Performance Test Script

echo "=== CUPCAKE Performance Test ==="
echo "Date: $(date)"
echo "System: $(uname -a)"
echo ""

# CPU test
echo "CPU Performance:"
time python3 -c "
import time
start = time.time()
for i in range(1000000):
    x = i ** 2
print(f'CPU test completed in {time.time() - start:.2f} seconds')
"

# Memory test
echo -e "\nMemory Performance:"
python3 -c "
import time
import sys
start = time.time()
data = [i for i in range(1000000)]
print(f'Memory allocation test: {time.time() - start:.2f} seconds')
print(f'Memory usage: {sys.getsizeof(data) / 1024 / 1024:.2f} MB')
"

# Disk I/O test
echo -e "\nDisk I/O Performance:"
time dd if=/dev/zero of=/tmp/testfile bs=1M count=100 2>&1 | grep -v records
rm -f /tmp/testfile

# Database test
echo -e "\nDatabase Performance:"
time sudo -u cupcake psql -d cupcake -c "
CREATE TEMP TABLE test_perf AS SELECT generate_series(1,10000) as id, random() as value;
SELECT COUNT(*) FROM test_perf WHERE value > 0.5;
" 2>/dev/null | grep -E "COUNT|Time"

# Web server test
echo -e "\nWeb Server Performance:"
curl -o /dev/null -s -w "Connect: %{time_connect}s, TTFB: %{time_starttransfer}s, Total: %{time_total}s\n" http://localhost:8000/

echo -e "\n=== Performance Test Completed ==="
EOF
    
    chmod +x /opt/cupcake/scripts/perf-test.sh
    sudo -u cupcake /opt/cupcake/scripts/perf-test.sh
    
    log "Performance test completed"
}

# Main execution
main() {
    log "Starting comprehensive Raspberry Pi 5 optimization..."
    
    optimize_system
    optimize_cpu
    optimize_memory
    optimize_storage
    optimize_network
    optimize_postgresql
    optimize_redis
    optimize_nginx
    create_dashboard
    run_performance_test
    
    log "Raspberry Pi 5 optimization completed successfully!"
    
    echo ""
    echo -e "${GREEN}Optimization Summary:${NC}"
    echo "✓ System services optimized"
    echo "✓ CPU frequency scaling configured"
    echo "✓ Memory and swap optimized"
    echo "✓ Storage and filesystem tuned"
    echo "✓ Network performance improved"
    echo "✓ PostgreSQL optimized for Pi hardware"
    echo "✓ Redis configured for low memory usage"
    echo "✓ Nginx optimized for performance"
    echo "✓ System monitoring dashboard created"
    echo ""
    echo -e "${YELLOW}Recommended next steps:${NC}"
    echo "1. Reboot the system to apply all changes"
    echo "2. Check system dashboard at http://localhost:9000"
    echo "3. Monitor system performance over time"
    echo "4. Adjust settings based on your specific workload"
    echo ""
    echo -e "${BLUE}Note: Some optimizations require a reboot to take full effect${NC}"
}

# Execute main function
main "$@"