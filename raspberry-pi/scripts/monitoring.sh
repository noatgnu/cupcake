#!/bin/bash

# CUPCAKE Raspberry Pi System Monitoring Script
# Monitors system resources and service health

set -e

# Configuration
LOG_FILE="/var/log/cupcake/monitoring.log"
STATUS_FILE="/var/lib/cupcake/system_status.json"
ALERT_THRESHOLD_CPU=80
ALERT_THRESHOLD_MEMORY=85
ALERT_THRESHOLD_DISK=90
ALERT_THRESHOLD_TEMP=70
CHECK_INTERVAL=60

# Services to monitor
SERVICES=("cupcake-web" "cupcake-worker" "postgresql" "redis-server" "nginx")

# Create directories if they don't exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$STATUS_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Get CPU temperature
get_cpu_temp() {
    if [[ -f /sys/class/thermal/thermal_zone0/temp ]]; then
        local temp=$(cat /sys/class/thermal/thermal_zone0/temp)
        echo $((temp / 1000))
    else
        echo "0"
    fi
}

# Get CPU usage
get_cpu_usage() {
    grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print int(usage)}'
}

# Get memory usage
get_memory_usage() {
    free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}'
}

# Get disk usage
get_disk_usage() {
    df / | tail -1 | awk '{print $5}' | sed 's/%//'
}

# Get load average
get_load_average() {
    cat /proc/loadavg | awk '{print $1}'
}

# Check service status
check_service() {
    local service=$1
    if systemctl is-active --quiet "$service"; then
        echo "running"
    else
        echo "failed"
    fi
}

# Get service uptime
get_service_uptime() {
    local service=$1
    systemctl show "$service" --property=ActiveEnterTimestamp | cut -d= -f2
}

# Check database connectivity
check_database() {
    if sudo -u cupcake psql -d cupcake -c "SELECT 1;" > /dev/null 2>&1; then
        echo "connected"
    else
        echo "disconnected"
    fi
}

# Check Redis connectivity
check_redis() {
    if redis-cli ping > /dev/null 2>&1; then
        echo "connected"
    else
        echo "disconnected"
    fi
}

# Check web application
check_web_app() {
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q "200\|302"; then
        echo "responding"
    else
        echo "not_responding"
    fi
}

# Get network statistics
get_network_stats() {
    local interface="eth0"
    if [[ -d "/sys/class/net/$interface" ]]; then
        local rx_bytes=$(cat "/sys/class/net/$interface/statistics/rx_bytes")
        local tx_bytes=$(cat "/sys/class/net/$interface/statistics/tx_bytes")
        echo "{\"rx_bytes\": $rx_bytes, \"tx_bytes\": $tx_bytes}"
    else
        echo "{\"rx_bytes\": 0, \"tx_bytes\": 0}"
    fi
}

# Send alert (placeholder - can be extended for email/webhook notifications)
send_alert() {
    local message=$1
    local level=$2
    
    log "ALERT [$level]: $message"
    
    # Write to system log
    logger -t cupcake-monitor "[$level] $message"
    
    # Could add email/webhook notifications here
    # Example: curl -X POST webhook_url -d "$message"
}

# Generate system status report
generate_status() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local cpu_temp=$(get_cpu_temp)
    local cpu_usage=$(get_cpu_usage)
    local memory_usage=$(get_memory_usage)
    local disk_usage=$(get_disk_usage)
    local load_avg=$(get_load_average)
    local network_stats=$(get_network_stats)
    
    # Check for alerts
    local alerts=()
    
    if [[ $cpu_usage -gt $ALERT_THRESHOLD_CPU ]]; then
        alerts+=("High CPU usage: ${cpu_usage}%")
    fi
    
    if [[ $memory_usage -gt $ALERT_THRESHOLD_MEMORY ]]; then
        alerts+=("High memory usage: ${memory_usage}%")
    fi
    
    if [[ $disk_usage -gt $ALERT_THRESHOLD_DISK ]]; then
        alerts+=("High disk usage: ${disk_usage}%")
    fi
    
    if [[ $cpu_temp -gt $ALERT_THRESHOLD_TEMP ]]; then
        alerts+=("High CPU temperature: ${cpu_temp}°C")
    fi
    
    # Check services
    local service_status=()
    for service in "${SERVICES[@]}"; do
        local status=$(check_service "$service")
        service_status+=("\"$service\": \"$status\"")
        
        if [[ "$status" != "running" ]]; then
            alerts+=("Service $service is $status")
        fi
    done
    
    # Check database and Redis
    local db_status=$(check_database)
    local redis_status=$(check_redis)
    local web_status=$(check_web_app)
    
    if [[ "$db_status" != "connected" ]]; then
        alerts+=("Database connection failed")
    fi
    
    if [[ "$redis_status" != "connected" ]]; then
        alerts+=("Redis connection failed")
    fi
    
    if [[ "$web_status" != "responding" ]]; then
        alerts+=("Web application not responding")
    fi
    
    # Generate JSON status
    cat > "$STATUS_FILE" << EOF
{
    "timestamp": "$timestamp",
    "system": {
        "cpu_usage": $cpu_usage,
        "cpu_temperature": $cpu_temp,
        "memory_usage": $memory_usage,
        "disk_usage": $disk_usage,
        "load_average": "$load_avg"
    },
    "services": {
        $(IFS=,; echo "${service_status[*]}")
    },
    "connectivity": {
        "database": "$db_status",
        "redis": "$redis_status",
        "web_app": "$web_status"
    },
    "network": $network_stats,
    "alerts": [
        $(printf '"%s",' "${alerts[@]}" | sed 's/,$//')
    ]
}
EOF
    
    # Send alerts if any
    for alert in "${alerts[@]}"; do
        send_alert "$alert" "WARNING"
    done
    
    # Log status
    log "Status: CPU:${cpu_usage}% MEM:${memory_usage}% DISK:${disk_usage}% TEMP:${cpu_temp}°C"
}

# Health check function
health_check() {
    local issues=0
    
    # Check critical services
    for service in "${SERVICES[@]}"; do
        if ! systemctl is-active --quiet "$service"; then
            log "ERROR: Service $service is not running"
            ((issues++))
            
            # Try to restart the service
            log "Attempting to restart $service"
            if systemctl restart "$service"; then
                log "Successfully restarted $service"
            else
                log "Failed to restart $service"
                send_alert "Failed to restart service: $service" "CRITICAL"
            fi
        fi
    done
    
    # Check database connectivity
    if [[ $(check_database) != "connected" ]]; then
        log "ERROR: Database connectivity check failed"
        ((issues++))
    fi
    
    # Check Redis connectivity
    if [[ $(check_redis) != "connected" ]]; then
        log "ERROR: Redis connectivity check failed"
        ((issues++))
    fi
    
    # Check disk space
    local disk_usage=$(get_disk_usage)
    if [[ $disk_usage -gt 95 ]]; then
        log "CRITICAL: Disk usage is at ${disk_usage}%"
        send_alert "Critical disk usage: ${disk_usage}%" "CRITICAL"
        
        # Clean up logs if disk is full
        find /var/log/cupcake -name "*.log" -mtime +3 -delete
        find /opt/cupcake/backups -name "*.gz" -mtime +3 -delete
    fi
    
    return $issues
}

# Performance optimization
optimize_performance() {
    local memory_usage=$(get_memory_usage)
    
    # If memory usage is high, clear caches
    if [[ $memory_usage -gt 90 ]]; then
        log "High memory usage detected, clearing caches"
        sync
        echo 1 > /proc/sys/vm/drop_caches
        
        # Restart Redis to clear memory
        systemctl restart redis-server
    fi
    
    # Check for zombie processes
    local zombies=$(ps aux | awk '$8 ~ /^Z/ { print $2 }' | wc -l)
    if [[ $zombies -gt 0 ]]; then
        log "Found $zombies zombie processes"
    fi
}

# Maintenance tasks
maintenance() {
    local hour=$(date +%H)
    
    # Run daily maintenance at 3 AM
    if [[ $hour -eq 3 ]]; then
        log "Running daily maintenance tasks"
        
        # Clean temporary files
        find /tmp -type f -mtime +1 -delete 2>/dev/null || true
        find /var/tmp -type f -mtime +1 -delete 2>/dev/null || true
        
        # Clean old logs
        find /var/log/cupcake -name "*.log" -mtime +7 -delete
        
        # Vacuum database
        sudo -u cupcake psql -d cupcake -c "VACUUM ANALYZE;" || true
        
        # Clean Redis
        redis-cli FLUSHDB || true
        
        log "Daily maintenance completed"
    fi
}

# Main monitoring loop
main() {
    log "CUPCAKE monitoring started (PID: $$)"
    
    while true; do
        # Generate status report
        generate_status
        
        # Perform health checks
        if ! health_check; then
            log "Health check completed with issues"
        fi
        
        # Performance optimization
        optimize_performance
        
        # Maintenance tasks
        maintenance
        
        # Wait for next check
        sleep $CHECK_INTERVAL
    done
}

# Signal handlers
cleanup() {
    log "CUPCAKE monitoring stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Start monitoring if run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi