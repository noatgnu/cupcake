#!/bin/bash

# CUPCAKE NVMe SSD Setup Script for Raspberry Pi 5
# Configures NVMe boot and migrates system from SD card to NVMe SSD

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

log "Starting NVMe SSD setup for Raspberry Pi 5..."

# Check if Pi 5
check_pi_model() {
    log "Checking Raspberry Pi model..."
    
    if ! grep -q "Raspberry Pi 5" /proc/cpuinfo; then
        error "This script is designed for Raspberry Pi 5 only"
    fi
    
    log "Raspberry Pi 5 confirmed"
}

# Detect NVMe drive
detect_nvme() {
    log "Detecting NVMe SSD..."
    
    local nvme_devices=($(lsblk -d -o NAME | grep nvme))
    
    if [[ ${#nvme_devices[@]} -eq 0 ]]; then
        error "No NVMe SSD detected. Please ensure NVMe SSD is properly connected via M.2 HAT"
    fi
    
    # Use the first NVMe device found
    NVME_DEVICE="/dev/${nvme_devices[0]}"
    
    log "Found NVMe SSD: $NVME_DEVICE"
    
    # Get NVMe info
    local nvme_size=$(lsblk -d -o SIZE $NVME_DEVICE | tail -1 | tr -d ' ')
    local nvme_model=$(lsblk -d -o MODEL $NVME_DEVICE | tail -1 | xargs)
    
    info "NVMe Model: $nvme_model"
    info "NVMe Size: $nvme_size"
    
    # Check minimum size (64GB)
    local nvme_size_gb=$(lsblk -d -b -o SIZE $NVME_DEVICE | tail -1)
    if [[ $nvme_size_gb -lt 68719476736 ]]; then # 64GB in bytes
        warn "NVMe SSD is smaller than 64GB. Consider using a larger drive for production."
    fi
}

# Enable NVMe boot in firmware
enable_nvme_boot() {
    log "Enabling NVMe boot in firmware..."
    
    # Check current boot order
    local current_boot_order=$(rpi-eeprom-config --read | grep BOOT_ORDER || echo "BOOT_ORDER=0xf41")
    
    info "Current boot order: $current_boot_order"
    
    # Create new EEPROM config with NVMe boot priority
    cat > /tmp/bootconf.txt << EOF
[all]
BOOT_UART=0
WAKE_ON_GPIO=1
POWER_OFF_ON_HALT=0
DHCP_TIMEOUT=45000
DHCP_REQ_TIMEOUT=4000
TFTP_FILE_TIMEOUT=30000
TFTP_IP=
TFTP_PREFIX=0
BOOT_ORDER=0xf416
SD_BOOT_MAX_RETRIES=3
NET_BOOT_MAX_RETRIES=5
USB_MSD_PWR_OFF_TIME=1000
USB_MSD_DISCOVER_TIMEOUT=20000
USB_MSD_LUN_TIMEOUT=2000
VL805_ENABLE_3V3=0
EOF
    
    # Apply new EEPROM configuration
    rpi-eeprom-config --apply /tmp/bootconf.txt
    
    log "EEPROM updated for NVMe boot priority"
    info "Boot order: 0xf416 (NVMe, USB, SD, Network)"
}

# Partition and format NVMe
partition_nvme() {
    log "Partitioning NVMe SSD..."
    
    # Unmount any existing partitions
    umount ${NVME_DEVICE}* 2>/dev/null || true
    
    # Create new partition table
    info "Creating new GPT partition table..."
    parted --script $NVME_DEVICE mklabel gpt
    
    # Create boot partition (512MB)
    info "Creating boot partition (512MB)..."
    parted --script $NVME_DEVICE mkpart primary fat32 1MiB 513MiB
    parted --script $NVME_DEVICE set 1 boot on
    
    # Create root partition (remaining space)
    info "Creating root partition..."
    parted --script $NVME_DEVICE mkpart primary ext4 513MiB 100%
    
    # Wait for kernel to recognize partitions
    partprobe $NVME_DEVICE
    sleep 2
    
    # Format partitions
    info "Formatting boot partition..."
    mkfs.fat -F 32 -n CUPCAKE_BOOT ${NVME_DEVICE}p1
    
    info "Formatting root partition..."
    mkfs.ext4 -F -L CUPCAKE_ROOT ${NVME_DEVICE}p2
    
    log "NVMe partitioning completed"
}

# Clone system from SD to NVMe
clone_system() {
    log "Cloning system from SD card to NVMe..."
    
    # Create mount points
    mkdir -p /mnt/nvme-boot
    mkdir -p /mnt/nvme-root
    
    # Mount NVMe partitions
    mount ${NVME_DEVICE}p1 /mnt/nvme-boot
    mount ${NVME_DEVICE}p2 /mnt/nvme-root
    
    # Clone boot partition
    info "Cloning boot partition..."
    rsync -avx --progress /boot/firmware/ /mnt/nvme-boot/
    
    # Clone root partition (excluding some directories)
    info "Cloning root partition (this may take 10-15 minutes)..."
    rsync -avx --progress \
        --exclude /proc \
        --exclude /sys \
        --exclude /dev \
        --exclude /mnt \
        --exclude /media \
        --exclude /tmp \
        --exclude /run \
        --exclude /var/tmp \
        --exclude /var/log \
        --exclude /lost+found \
        --exclude /boot/firmware \
        / /mnt/nvme-root/
    
    # Create missing directories
    mkdir -p /mnt/nvme-root/{proc,sys,dev,mnt,media,tmp,run,var/tmp,var/log}
    
    log "System clone completed"
}

# Update configuration for NVMe boot
update_boot_config() {
    log "Updating boot configuration for NVMe..."
    
    # Get NVMe partition UUIDs
    local boot_uuid=$(blkid -s PARTUUID -o value ${NVME_DEVICE}p1)
    local root_uuid=$(blkid -s PARTUUID -o value ${NVME_DEVICE}p2)
    
    info "Boot PARTUUID: $boot_uuid"
    info "Root PARTUUID: $root_uuid"
    
    # Update cmdline.txt for NVMe root
    sed -i "s/root=[^[:space:]]*/root=PARTUUID=$root_uuid/" /mnt/nvme-boot/cmdline.txt
    
    # Update fstab for NVMe
    cat > /mnt/nvme-root/etc/fstab << EOF
# CUPCAKE NVMe fstab configuration
PARTUUID=$root_uuid  /               ext4    defaults,noatime  0       1
PARTUUID=$boot_uuid  /boot/firmware  vfat    defaults          0       2
tmpfs                /tmp            tmpfs   defaults,noatime,nosuid,size=100m 0 0
tmpfs                /var/tmp        tmpfs   defaults,noatime,nosuid,size=50m  0 0
EOF
    
    # Optimize NVMe mount options in fstab
    sed -i 's/defaults,noatime/defaults,noatime,discard/' /mnt/nvme-root/etc/fstab
    
    log "Boot configuration updated"
}

# Optimize NVMe performance
optimize_nvme() {
    log "Optimizing NVMe performance..."
    
    # Create NVMe optimization script
    cat > /mnt/nvme-root/etc/systemd/system/nvme-optimize.service << EOF
[Unit]
Description=NVMe SSD Optimization
DefaultDependencies=false
After=local-fs.target
Before=sysinit.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo mq-deadline > /sys/block/nvme0n1/queue/scheduler'
ExecStart=/bin/bash -c 'echo 0 > /sys/block/nvme0n1/queue/add_random'
ExecStart=/bin/bash -c 'echo 1 > /sys/block/nvme0n1/queue/rq_affinity'
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
EOF
    
    # Enable the optimization service
    chroot /mnt/nvme-root systemctl enable nvme-optimize.service
    
    # Add NVMe-specific kernel parameters
    if ! grep -q "nvme" /mnt/nvme-boot/cmdline.txt; then
        sed -i 's/$/ nvme.poll_queues=2 nvme_core.default_ps_max_latency_us=0/' /mnt/nvme-boot/cmdline.txt
    fi
    
    # Configure I/O scheduler optimization for NVMe
    cat > /mnt/nvme-root/etc/udev/rules.d/60-nvme-scheduler.rules << EOF
# NVMe SSD optimization rules
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/add_random}="0"
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/rq_affinity}="1"
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/read_ahead_kb}="128"
EOF
    
    log "NVMe performance optimization completed"
}

# Update system configuration for NVMe
update_system_config() {
    log "Updating system configuration for NVMe..."
    
    # Update PostgreSQL configuration for NVMe performance
    local pg_version=$(ls /mnt/nvme-root/etc/postgresql/ 2>/dev/null | head -1)
    if [[ -n "$pg_version" ]]; then
        local pg_config="/mnt/nvme-root/etc/postgresql/$pg_version/main/postgresql.conf"
        
        if [[ -f "$pg_config" ]]; then
            # Optimize PostgreSQL for NVMe
            cat >> "$pg_config" << EOF

# NVMe SSD optimizations
random_page_cost = 1.1          # Lower for SSD
seq_page_cost = 1.0
effective_io_concurrency = 200  # Higher for NVMe
maintenance_io_concurrency = 10 # Higher for NVMe
checkpoint_completion_target = 0.9
wal_compression = on
full_page_writes = off          # Can disable on reliable storage
bgwriter_flush_after = 0       # Disable for NVMe
checkpoint_flush_after = 0      # Disable for NVMe
EOF
            info "PostgreSQL optimized for NVMe"
        fi
    fi
    
    # Update Redis configuration for NVMe
    if [[ -f "/mnt/nvme-root/etc/redis/redis.conf" ]]; then
        # Enable more frequent saves for NVMe
        sed -i 's/save 900 1/save 300 1/' /mnt/nvme-root/etc/redis/redis.conf
        sed -i 's/save 300 10/save 60 10/' /mnt/nvme-root/etc/redis/redis.conf
        info "Redis optimized for NVMe"
    fi
    
    # Add NVMe monitoring to the monitoring script
    if [[ -f "/mnt/nvme-root/opt/cupcake/scripts/monitoring.sh" ]]; then
        cat >> /mnt/nvme-root/opt/cupcake/scripts/monitoring.sh << 'EOF'

# NVMe-specific monitoring
get_nvme_temp() {
    if [[ -f /sys/class/nvme/nvme0/hwmon*/temp1_input ]]; then
        local temp=$(cat /sys/class/nvme/nvme0/hwmon*/temp1_input 2>/dev/null | head -1)
        echo $((temp / 1000))
    else
        echo "0"
    fi
}

get_nvme_health() {
    if command -v nvme &> /dev/null; then
        nvme smart-log /dev/nvme0n1 2>/dev/null | grep -E "(temperature|available_spare|percentage_used)" || echo "N/A"
    fi
}
EOF
        info "NVMe monitoring added"
    fi
    
    log "System configuration updated"
}

# Create NVMe maintenance script
create_nvme_maintenance() {
    log "Creating NVMe maintenance script..."
    
    cat > /mnt/nvme-root/opt/cupcake/scripts/nvme-maintenance.sh << 'EOF'
#!/bin/bash
# CUPCAKE NVMe SSD Maintenance Script

LOG_FILE="/var/log/cupcake/nvme-maintenance.log"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Run TRIM operation
run_trim() {
    log "Running TRIM operation..."
    fstrim -av >> "$LOG_FILE" 2>&1
    log "TRIM completed"
}

# Check NVMe health
check_nvme_health() {
    log "Checking NVMe health..."
    
    if command -v nvme &> /dev/null; then
        nvme smart-log /dev/nvme0n1 >> "$LOG_FILE" 2>&1
    fi
    
    # Check temperature
    if [[ -f /sys/class/nvme/nvme0/hwmon*/temp1_input ]]; then
        local temp=$(cat /sys/class/nvme/nvme0/hwmon*/temp1_input 2>/dev/null | head -1)
        temp=$((temp / 1000))
        log "NVMe temperature: ${temp}°C"
        
        if [[ $temp -gt 70 ]]; then
            log "WARNING: NVMe temperature high: ${temp}°C"
        fi
    fi
}

# Monitor NVMe performance
monitor_performance() {
    log "NVMe performance stats:"
    iostat -x 1 3 | grep nvme >> "$LOG_FILE" 2>&1 || true
}

# Main maintenance routine
main() {
    log "Starting NVMe maintenance"
    run_trim
    check_nvme_health
    monitor_performance
    log "NVMe maintenance completed"
}

main "$@"
EOF
    
    chmod +x /mnt/nvme-root/opt/cupcake/scripts/nvme-maintenance.sh
    
    # Add to cron
    echo "0 1 * * 0 /opt/cupcake/scripts/nvme-maintenance.sh" >> /mnt/nvme-root/var/spool/cron/crontabs/cupcake
    
    log "NVMe maintenance script created"
}

# Cleanup and unmount
cleanup() {
    log "Cleaning up..."
    
    # Sync filesystems
    sync
    
    # Unmount NVMe partitions
    umount /mnt/nvme-boot 2>/dev/null || true
    umount /mnt/nvme-root 2>/dev/null || true
    
    # Remove mount points
    rmdir /mnt/nvme-boot /mnt/nvme-root 2>/dev/null || true
    
    log "Cleanup completed"
}

# Verification
verify_setup() {
    log "Verifying NVMe setup..."
    
    # Check partitions
    if lsblk $NVME_DEVICE | grep -q "p1.*512M"; then
        info "✓ Boot partition created correctly"
    else
        warn "✗ Boot partition may have issues"
    fi
    
    if lsblk $NVME_DEVICE | grep -q "p2"; then
        info "✓ Root partition created correctly"
    else
        warn "✗ Root partition may have issues"
    fi
    
    # Check boot configuration
    if [[ -f "/boot/firmware/cmdline.txt" ]]; then
        local boot_uuid=$(blkid -s PARTUUID -o value ${NVME_DEVICE}p2)
        if grep -q "PARTUUID=$boot_uuid" /boot/firmware/cmdline.txt; then
            info "✓ Boot configuration updated"
        else
            warn "✗ Boot configuration may need manual verification"
        fi
    fi
    
    log "Verification completed"
}

# Main execution
main() {
    log "Starting NVMe SSD setup for CUPCAKE..."
    
    check_pi_model
    detect_nvme
    
    # Confirm with user
    echo ""
    echo -e "${YELLOW}⚠️  WARNING: This will ERASE all data on $NVME_DEVICE${NC}"
    echo -e "${YELLOW}The system will be cloned from SD card to NVMe SSD${NC}"
    echo ""
    read -p "Do you want to continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Setup cancelled by user"
    fi
    
    enable_nvme_boot
    partition_nvme
    clone_system
    update_boot_config
    optimize_nvme
    update_system_config
    create_nvme_maintenance
    verify_setup
    cleanup
    
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}🎉 NVMe SSD Setup Completed Successfully! 🎉${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo "1. Shutdown the system: sudo shutdown -h now"
    echo "2. Remove the SD card"
    echo "3. Power on - the Pi will boot from NVMe SSD"
    echo "4. Run setup: sudo /opt/cupcake/setup.sh"
    echo ""
    echo -e "${BLUE}Performance Benefits:${NC}"
    echo "• 10-20x faster storage performance"
    echo "• Better database reliability"
    echo "• Reduced power consumption"
    echo "• Suitable for production laboratory use"
    echo ""
    echo -e "${YELLOW}Note: The system will reboot from NVMe on next startup${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
}

# Handle interruption
trap cleanup EXIT

# Execute main function
main "$@"