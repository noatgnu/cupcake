#!/bin/bash

# Hook script to configure CUPCAKE system based on detected capabilities
# This script runs after Whisper.cpp setup to optimize system configuration

set -e

echo "=== Configuring CUPCAKE system based on detected capabilities ==="

# Copy system detection script to system location
mkdir -p /opt/cupcake/scripts
mkdir -p /opt/cupcake/config

# Copy the system detection script from the rpi-image-gen scripts directory
if [ -f /piroot_config/scripts/detect-system-capabilities.py ]; then
    cp /piroot_config/scripts/detect-system-capabilities.py /opt/cupcake/scripts/
elif [ -f /tmp/rpi-image-gen/scripts/detect-system-capabilities.py ]; then
    cp /tmp/rpi-image-gen/scripts/detect-system-capabilities.py /opt/cupcake/scripts/
else
    echo "Warning: System detection script not found, creating minimal version..."
    # Create a minimal version if the main script isn't available
    cat > /opt/cupcake/scripts/detect-system-capabilities.py << 'PYPYEOF'
#!/usr/bin/env python3
import os
import json
# Minimal system detection for fallback
memory_kb = int(open('/proc/meminfo').readline().split()[1])
memory_mb = memory_kb // 1024
cpu_count = os.cpu_count()

if memory_mb < 2048:
    tier = 'low'
    model = 'ggml-tiny.en.bin'
    threads = 2
elif memory_mb < 4096:
    tier = 'medium'
    model = 'ggml-base.en.bin'
    threads = 4
else:
    tier = 'high'  
    model = 'ggml-small.en.bin'
    threads = 6

if len(os.sys.argv) > 1 and os.sys.argv[1] == 'tier':
    print(tier)
elif len(os.sys.argv) > 1 and os.sys.argv[1] == 'env':
    print(f"export WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/whisper-cli")
    print(f"export WHISPERCPP_DEFAULT_MODEL=/opt/whisper.cpp/models/{model}")
    print(f"export WHISPERCPP_THREAD_COUNT={threads}")
else:
    print(f"System tier: {tier}, Model: {model}, Threads: {threads}")
PYPYEOF
fi

chmod +x /opt/cupcake/scripts/detect-system-capabilities.py

# Install required Python packages for system detection
pip3 install psutil

# Run system detection and generate configuration files
echo "Detecting system capabilities..."
python3 /opt/cupcake/scripts/detect-system-capabilities.py generate /opt/cupcake/config

# Read the generated configuration
SYSTEM_TIER=$(python3 /opt/cupcake/scripts/detect-system-capabilities.py tier)
echo "Detected system tier: $SYSTEM_TIER"

# Load the generated environment configuration
if [ -f /opt/cupcake/config/cupcake.env ]; then
    echo "Loading system-specific configuration..."
    
    # Create systemd environment file with the generated values
    mkdir -p /etc/systemd/system.conf.d
    
    # Extract Whisper configuration from generated file
    WHISPER_PATH=$(grep "^WHISPERCPP_PATH=" /opt/cupcake/config/cupcake.env | cut -d'=' -f2)
    WHISPER_MODEL=$(grep "^WHISPERCPP_DEFAULT_MODEL=" /opt/cupcake/config/cupcake.env | cut -d'=' -f2)
    WHISPER_THREADS=$(grep "^WHISPERCPP_THREAD_COUNT=" /opt/cupcake/config/cupcake.env | cut -d'=' -f2)
    
    # Update the whisper systemd configuration
    cat > /etc/systemd/system.conf.d/whisper.conf << EOF
[Manager]
DefaultEnvironment=WHISPERCPP_PATH=${WHISPER_PATH}
DefaultEnvironment=WHISPERCPP_DEFAULT_MODEL=${WHISPER_MODEL}
DefaultEnvironment=WHISPERCPP_THREAD_COUNT=${WHISPER_THREADS}
EOF
    
    echo "System configuration updated:"
    echo "  Whisper binary: $WHISPER_PATH"
    echo "  Whisper model: $WHISPER_MODEL"
    echo "  Whisper threads: $WHISPER_THREADS"
fi

# Create system information service
cat > /etc/systemd/system/cupcake-system-info.service << 'EOF'
[Unit]
Description=CUPCAKE System Information Service
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/detect-system-capabilities.py generate /opt/cupcake/config
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable the system info service
systemctl enable cupcake-system-info.service

# Create a management script for system configuration
cat > /opt/cupcake/scripts/system-config.sh << 'EOF'
#!/bin/bash
# CUPCAKE System Configuration Management

set -e

case "$1" in
    "detect")
        echo "=== System Detection ==="
        /opt/cupcake/scripts/detect-system-capabilities.py
        ;;
    
    "generate")
        echo "=== Regenerating Configuration ==="
        /opt/cupcake/scripts/detect-system-capabilities.py generate /opt/cupcake/config
        echo "Configuration files regenerated in /opt/cupcake/config"
        ;;
    
    "env")
        echo "=== Environment Variables ==="
        /opt/cupcake/scripts/detect-system-capabilities.py env
        ;;
    
    "whisper")
        echo "=== Whisper Configuration ==="
        /opt/cupcake/scripts/detect-system-capabilities.py whisper
        ;;
    
    "info")
        echo "=== System Information ==="
        if [ -f /opt/cupcake/config/system-info.json ]; then
            cat /opt/cupcake/config/system-info.json
        else
            echo "No system info found. Run 'cupcake-config generate' first."
        fi
        ;;
    
    "optimize")
        echo "=== Applying System Optimizations ==="
        
        # Apply PostgreSQL optimizations if PostgreSQL is installed
        if command -v psql >/dev/null 2>&1; then
            echo "Optimizing PostgreSQL configuration..."
            
            # Extract PostgreSQL settings from system info
            if [ -f /opt/cupcake/config/system-info.json ]; then
                SHARED_BUFFERS=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['optimizations']['postgresql']['shared_buffers'])")
                WORK_MEM=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['optimizations']['postgresql']['work_mem'])")
                EFFECTIVE_CACHE_SIZE=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['optimizations']['postgresql']['effective_cache_size'])")
                
                # Create PostgreSQL optimization conf
                cat > /etc/postgresql/14/main/conf.d/cupcake-optimizations.conf << PGEOF
# CUPCAKE PostgreSQL Optimizations
shared_buffers = ${SHARED_BUFFERS}
work_mem = ${WORK_MEM}
effective_cache_size = ${EFFECTIVE_CACHE_SIZE}
random_page_cost = 1.1
effective_io_concurrency = 200
PGEOF
                
                echo "PostgreSQL configuration optimized"
            fi
        fi
        
        # Apply Redis optimizations if Redis is installed
        if command -v redis-server >/dev/null 2>&1; then
            echo "Optimizing Redis configuration..."
            
            if [ -f /opt/cupcake/config/system-info.json ]; then
                REDIS_MAXMEM=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['optimizations']['redis']['maxmemory'])")
                REDIS_POLICY=$(python3 -c "import json; data=json.load(open('/opt/cupcake/config/system-info.json')); print(data['optimizations']['redis']['maxmemory_policy'])")
                
                # Add Redis optimizations
                cat >> /etc/redis/redis.conf << REDISEOF

# CUPCAKE Redis Optimizations  
maxmemory ${REDIS_MAXMEM}
maxmemory-policy ${REDIS_POLICY}
save 900 1
save 300 10
save 60 10000
REDISEOF
                
                echo "Redis configuration optimized"
            fi
        fi
        
        echo "System optimizations applied"
        ;;
    
    "test")
        echo "=== Testing System Configuration ==="
        
        # Test Whisper
        if [ -f /opt/whisper.cpp/build/bin/whisper-cli ]; then
            echo "✓ Whisper.cpp binary found"
            /opt/whisper.cpp/build/bin/whisper-cli --help > /dev/null 2>&1 && echo "✓ Whisper.cpp binary working"
        else
            echo "✗ Whisper.cpp binary not found"
        fi
        
        # Test system detection
        if /opt/cupcake/scripts/detect-system-capabilities.py tier > /dev/null 2>&1; then
            TIER=$(/opt/cupcake/scripts/detect-system-capabilities.py tier)
            echo "✓ System detection working (tier: $TIER)"
        else
            echo "✗ System detection failed"
        fi
        
        # Test configuration files
        if [ -f /opt/cupcake/config/cupcake.env ]; then
            echo "✓ CUPCAKE environment configuration found"
        else
            echo "✗ CUPCAKE environment configuration missing"
        fi
        
        if [ -f /opt/cupcake/config/system-info.json ]; then
            echo "✓ System information file found"
        else
            echo "✗ System information file missing"
        fi
        ;;
    
    *)
        echo "CUPCAKE System Configuration Management"
        echo "Usage: $0 {detect|generate|env|whisper|info|optimize|test}"
        echo
        echo "Commands:"
        echo "  detect     - Show system capabilities and recommendations"
        echo "  generate   - Generate configuration files based on system"
        echo "  env        - Show environment variables for CUPCAKE"
        echo "  whisper    - Show Whisper.cpp configuration"
        echo "  info       - Show detailed system information"
        echo "  optimize   - Apply system-specific optimizations"
        echo "  test       - Test system configuration"
        exit 1
        ;;
esac
EOF

chmod +x /opt/cupcake/scripts/system-config.sh

# Create symlink for easy access
ln -sf /opt/cupcake/scripts/system-config.sh /usr/local/bin/cupcake-config

# Set proper ownership
chown -R root:root /opt/cupcake

echo "=== System configuration completed ==="
echo "Use 'cupcake-config detect' to view system recommendations"
echo "Use 'cupcake-config test' to verify configuration"