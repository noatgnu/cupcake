#!/bin/bash
# CUPCAKE NVMe Storage Optimization Hook
# Optimizes Pi 5 for NVMe SSD performance

set -e

echo ">>> CUPCAKE: Setting up NVMe optimization..."

# Configure boot options for NVMe
cat >> /boot/config.txt << 'EOF'

# CUPCAKE NVMe and Storage Optimization
# Enable PCIe Gen 3 for better NVMe performance
dtparam=pcie_gen=3

# NVMe overlay
dtoverlay=nvme

# Disable unused interfaces to save power and improve performance
dtparam=audio=off
dtparam=bluetooth=off
dtparam=wifi=off

# GPU memory allocation (minimal for headless)
gpu_mem=64

# Overclock settings for better performance (conservative)
arm_freq=2400
gpu_freq=750
over_voltage=6

# USB power management
dtparam=usb_max_current_enable=1
EOF

# Configure NVMe kernel parameters
cat >> /boot/cmdline.txt << ' EOF'
 nvme_core.default_ps_max_latency_us=0 pcie_aspm=off
EOF

# Create NVMe optimization script
cat > /opt/cupcake/scripts/optimize-nvme.sh << 'EOF'
#!/bin/bash
# CUPCAKE NVMe Performance Optimization

set -e

echo "Optimizing NVMe storage performance..."

# Find NVMe devices
NVME_DEVICES=$(ls /dev/nvme*n1 2>/dev/null || true)

if [ -z "$NVME_DEVICES" ]; then
    echo "No NVMe devices found. Skipping NVMe optimization."
    exit 0
fi

for device in $NVME_DEVICES; do
    echo "Optimizing NVMe device: $device"
    
    # Set scheduler to none for NVMe (best for SSD)
    echo none > /sys/block/$(basename $device)/queue/scheduler
    
    # Optimize queue depth
    echo 32 > /sys/block/$(basename $device)/queue/nr_requests
    
    # Disable NCQ if needed (some SSDs perform better without it)
    echo 1 > /sys/block/$(basename $device)/queue/nomerges
    
    # Set read-ahead to 256KB
    blockdev --setra 512 $device
    
    # Enable TRIM support
    fstrim -v /
done

# Configure I/O scheduler in kernel parameters
if ! grep -q "elevator=" /boot/cmdline.txt; then
    sed -i 's/$/ elevator=none/' /boot/cmdline.txt
fi

# Create systemd service to apply optimizations on boot
cat > /etc/systemd/system/cupcake-nvme-optimize.service << 'SERVICE_EOF'
[Unit]
Description=CUPCAKE NVMe Storage Optimization
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/opt/cupcake/scripts/optimize-nvme.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl enable cupcake-nvme-optimize.service

echo "NVMe optimization completed successfully"
EOF

chmod +x /opt/cupcake/scripts/optimize-nvme.sh
chown cupcake:cupcake /opt/cupcake/scripts/optimize-nvme.sh

# Configure filesystem optimization for NVMe
cat > /opt/cupcake/scripts/setup-nvme-filesystem.sh << 'EOF'
#!/bin/bash
# CUPCAKE NVMe Filesystem Setup and Optimization

set -e

echo "Setting up NVMe filesystem optimization..."

# Create optimized fstab entries for NVMe
# This assumes the user will move root to NVMe
cat >> /etc/fstab << 'FSTAB_EOF'

# CUPCAKE NVMe optimization entries (uncomment after moving to NVMe)
# /dev/nvme0n1p2 / ext4 defaults,noatime,nodiratime,commit=60 0 1
# /dev/nvme0n1p1 /boot vfat defaults,noatime 0 2

# Temporary filesystem for better performance
tmpfs /tmp tmpfs defaults,noatime,mode=1777,size=512M 0 0
tmpfs /var/tmp tmpfs defaults,noatime,mode=1777,size=256M 0 0
FSTAB_EOF

# Create NVMe migration script
cat > /opt/cupcake/scripts/migrate-to-nvme.sh << 'MIGRATE_EOF'
#!/bin/bash
# CUPCAKE NVMe Migration Script
# Helps migrate from SD card to NVMe SSD

set -e

echo "CUPCAKE NVMe Migration Assistant"
echo "================================"

# Check if NVMe is available
if [ ! -e /dev/nvme0n1 ]; then
    echo "ERROR: No NVMe device found at /dev/nvme0n1"
    echo "Please ensure NVMe SSD is properly connected via M.2 HAT"
    exit 1
fi

# Warning message
echo "WARNING: This will erase all data on the NVMe SSD!"
echo "Make sure you have backed up any important data."
echo
read -p "Do you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Migration cancelled."
    exit 0
fi

# Partition the NVMe drive
echo "Partitioning NVMe drive..."
parted /dev/nvme0n1 --script mklabel gpt
parted /dev/nvme0n1 --script mkpart primary fat32 0% 512MB
parted /dev/nvme0n1 --script mkpart primary ext4 512MB 100%
parted /dev/nvme0n1 --script set 1 boot on

# Format partitions
echo "Formatting partitions..."
mkfs.vfat -F 32 /dev/nvme0n1p1
mkfs.ext4 -F /dev/nvme0n1p2

# Create mount points
mkdir -p /mnt/nvme-boot
mkdir -p /mnt/nvme-root

# Mount partitions
mount /dev/nvme0n1p1 /mnt/nvme-boot
mount /dev/nvme0n1p2 /mnt/nvme-root

# Copy boot partition
echo "Copying boot partition..."
rsync -axHAWX --numeric-ids /boot/ /mnt/nvme-boot/

# Copy root partition (excluding /boot)
echo "Copying root partition (this may take a while)..."
rsync -axHAWX --numeric-ids --exclude=/boot / /mnt/nvme-root/

# Update fstab on NVMe
echo "Updating fstab..."
sed -i 's|^PARTUUID=.*-01|/dev/nvme0n1p1|' /mnt/nvme-root/etc/fstab
sed -i 's|^PARTUUID=.*-02|/dev/nvme0n1p2|' /mnt/nvme-root/etc/fstab

# Update boot command line
echo "Updating boot configuration..."
PARTUUID=$(blkid /dev/nvme0n1p2 | grep -o 'PARTUUID="[^"]*"' | cut -d'"' -f2)
sed -i "s|root=PARTUUID=[^ ]*|root=PARTUUID=$PARTUUID|" /mnt/nvme-boot/cmdline.txt

# Unmount
umount /mnt/nvme-boot
umount /mnt/nvme-root
rmdir /mnt/nvme-boot /mnt/nvme-root

echo
echo "Migration completed successfully!"
echo "Please reboot and remove the SD card to boot from NVMe."
echo "After successful boot, run 'raspi-config' and expand filesystem."
MIGRATE_EOF

chmod +x /opt/cupcake/scripts/migrate-to-nvme.sh
chown cupcake:cupcake /opt/cupcake/scripts/migrate-to-nvme.sh

echo "NVMe filesystem setup completed successfully"
EOF

chmod +x /opt/cupcake/scripts/setup-nvme-filesystem.sh
chown cupcake:cupcake /opt/cupcake/scripts/setup-nvme-filesystem.sh

# Create NVMe monitoring script
cat > /opt/cupcake/scripts/monitor-nvme.sh << 'EOF'
#!/bin/bash
# CUPCAKE NVMe Health Monitoring Script

set -e

echo "CUPCAKE NVMe Health Monitor"
echo "=========================="

# Check if nvme-cli is available
if ! command -v nvme &> /dev/null; then
    echo "nvme-cli not installed. Installing..."
    apt-get update
    apt-get install -y nvme-cli
fi

# Find NVMe devices
NVME_DEVICES=$(ls /dev/nvme*n1 2>/dev/null || true)

if [ -z "$NVME_DEVICES" ]; then
    echo "No NVMe devices found."
    exit 0
fi

for device in $NVME_DEVICES; do
    echo
    echo "NVMe Device: $device"
    echo "==================="
    
    # Basic device info
    nvme id-ctrl $device | grep -E "(mn|sn|fr|tnvmcap)" || true
    
    # SMART health info
    echo
    echo "Health Information:"
    nvme smart-log $device | grep -E "(temperature|available_spare|percentage_used|data_units|host_reads|host_writes)" || true
    
    # Check for any critical warnings
    echo
    echo "Critical Warnings:"
    nvme smart-log $device | grep -E "critical_warning" || true
    
done

echo
echo "NVMe monitoring completed."
EOF

chmod +x /opt/cupcake/scripts/monitor-nvme.sh
chown cupcake:cupcake /opt/cupcake/scripts/monitor-nvme.sh

# Create cron job for NVMe health monitoring
cat > /etc/cron.d/cupcake-nvme-health << 'EOF'
# CUPCAKE NVMe Health Monitoring
# Runs daily at 2:00 AM
0 2 * * * root /opt/cupcake/scripts/monitor-nvme.sh >> /var/log/cupcake/nvme-health.log 2>&1
EOF

# Run initial optimization
/opt/cupcake/scripts/optimize-nvme.sh || echo "Initial NVMe optimization failed (device may not be present yet)"

echo ">>> CUPCAKE: NVMe optimization setup completed successfully"
echo ">>> Use '/opt/cupcake/scripts/migrate-to-nvme.sh' to migrate from SD card to NVMe"
echo ">>> Use '/opt/cupcake/scripts/monitor-nvme.sh' to check NVMe health"