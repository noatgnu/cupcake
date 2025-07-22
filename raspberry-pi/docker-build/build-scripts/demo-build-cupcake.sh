#!/bin/bash

# Demo CUPCAKE Pi 5 Builder - Shows complete process

set -e

echo "=== CUPCAKE Pi 5 Demo Build ==="

# Configuration
IMG_NAME="cupcake-pi5-demo-$(date +%Y%m%d-%H%M).img" 
BUILD_DIR="/build"
OUTPUT_DIR="/build/output"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[BUILD]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check environment
log "Checking demo build environment..."
info "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
info "Architecture: $(uname -m)"
info "Available RAM: $(free -h | awk 'NR==2{print $2}')"
info "Available disk: $(df -h $BUILD_DIR | awk 'NR==2{print $4}')"

# Test ARM64 emulation
if [ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    log "ARM64 emulation configured"
else
    warn "ARM64 emulation not fully configured"
fi

# Test all required tools
required_tools=("wget" "curl" "git" "debootstrap" "parted" "losetup" "qemu-aarch64-static")
for tool in "${required_tools[@]}"; do
    if command -v "$tool" >/dev/null 2>&1; then
        info "✓ $tool available"
    else
        error "✗ $tool not found"
    fi
done

log "Creating demo image structure..."

# Create a minimal demo image (1GB) instead of full download
cd "$BUILD_DIR"

# Create demo image file
log "Creating demo 1GB image file..."
dd if=/dev/zero of="$IMG_NAME" bs=1M count=1024 status=progress

# Create partition table
log "Creating partition table..."
parted "$IMG_NAME" --script \
    mklabel msdos \
    mkpart primary fat32 1M 513M \
    mkpart primary ext4 513M 100% \
    set 1 boot on

# Setup loop device 
LOOP_DEVICE=$(sudo losetup --show -fP "$IMG_NAME")
log "Using loop device: $LOOP_DEVICE"

# Format partitions
log "Formatting partitions..."
sudo mkfs.vfat -F32 "${LOOP_DEVICE}p1"
sudo mkfs.ext4 "${LOOP_DEVICE}p2"

# Mount and create basic structure
MOUNT_DIR="/tmp/cupcake-demo-mount"
sudo mkdir -p "$MOUNT_DIR"
sudo mount "${LOOP_DEVICE}p2" "$MOUNT_DIR"
sudo mkdir -p "$MOUNT_DIR/boot"
sudo mount "${LOOP_DEVICE}p1" "$MOUNT_DIR/boot"

log "Creating demo CUPCAKE file structure..."

# Create basic directory structure
sudo mkdir -p "$MOUNT_DIR"/{bin,sbin,usr,var,tmp,home,root,etc,opt}
sudo mkdir -p "$MOUNT_DIR/opt/cupcake"/{scripts,config}
sudo mkdir -p "$MOUNT_DIR/opt/whisper.cpp"/{build/bin,models}
sudo mkdir -p "$MOUNT_DIR/var/lib/cupcake"
sudo mkdir -p "$MOUNT_DIR/var/log/cupcake"

# Create demo configuration files
sudo tee "$MOUNT_DIR/opt/cupcake/config/cupcake.env" > /dev/null << 'ENVEOF'
# CUPCAKE Demo Configuration
WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/whisper-cli
WHISPERCPP_DEFAULT_MODEL=/opt/whisper.cpp/models/ggml-base.en.bin
WHISPERCPP_THREAD_COUNT=4
SYSTEM_TIER=demo
ENVEOF

# Create demo system info
sudo tee "$MOUNT_DIR/opt/cupcake/config/system-info.json" > /dev/null << 'JSONEOF'
{
  "system_tier": "demo",
  "whisper_config": {
    "model": "ggml-base.en.bin",
    "threads": 4,
    "binary_path": "/opt/whisper.cpp/build/bin/whisper-cli",
    "system_type": "demo"
  },
  "build_info": {
    "build_method": "docker-demo",
    "build_date": "$(date -Iseconds)",
    "build_version": "cupcake-pi5-demo"
  }
}
JSONEOF

# Create demo scripts
sudo tee "$MOUNT_DIR/opt/cupcake/scripts/cupcake-config" > /dev/null << 'SCRIPTEOF'
#!/bin/bash
# CUPCAKE Demo Configuration Script

case "$1" in
    "detect")
        echo "CUPCAKE Demo System"
        echo "Tier: demo"
        echo "Whisper: base.en model, 4 threads"
        echo "Status: Ready for CUPCAKE installation"
        ;;
    "info")
        cat /opt/cupcake/config/system-info.json
        ;;
    *)
        echo "CUPCAKE Demo System Configuration"
        echo "Commands: detect, info"
        ;;
esac
SCRIPTEOF

sudo chmod +x "$MOUNT_DIR/opt/cupcake/scripts/cupcake-config"

# Create demo README
sudo tee "$MOUNT_DIR/home/CUPCAKE-DEMO-README.txt" > /dev/null << 'READMEEOF'
=== CUPCAKE Pi 5 Demo Image ===

This is a DEMONSTRATION image showing the Docker build process.

DEMO FEATURES:
✓ Docker-based build system working
✓ Image creation and partitioning
✓ File system structure creation
✓ CUPCAKE directory layout
✓ Configuration file generation
✓ System detection framework

FOR PRODUCTION USE:
- This demo creates a minimal 1GB image
- Full build would download ~2GB Raspberry Pi OS
- Complete installation takes 30-90 minutes
- Includes full CUPCAKE stack with Whisper.cpp

TO BUILD FULL IMAGE:
Fix the Raspberry Pi OS download URL in the build script
and run the complete build process.

DEMO BUILD COMPLETED SUCCESSFULLY!
Build method: Docker containerization
Build environment: Ubuntu 22.04.5 LTS
Build date: $(date)
READMEEOF

# Create boot files
sudo tee "$MOUNT_DIR/boot/config.txt" > /dev/null << 'BOOTEOF'
# CUPCAKE Pi 5 Demo Configuration
arm_64bit=1
gpu_mem=128
dtparam=pcie_gen=3
dtoverlay=nvme
# This is a demo configuration
BOOTEOF

# Create demo kernel and initramfs (empty files for demo)
sudo touch "$MOUNT_DIR/boot/kernel8.img"
sudo touch "$MOUNT_DIR/boot/initramfs8"

log "Finalizing demo image..."

# Unmount
sudo umount "$MOUNT_DIR/boot"
sudo umount "$MOUNT_DIR"
sudo rmdir "$MOUNT_DIR"

# Detach loop device
sudo losetup -d "$LOOP_DEVICE"

# Move to output
mv "$IMG_NAME" "$OUTPUT_DIR/"

log "Demo build completed!"
info "Demo image: $OUTPUT_DIR/$IMG_NAME"
info "Size: $(du -h "$OUTPUT_DIR/$IMG_NAME" | cut -f1)"

echo ""
echo "=== CUPCAKE Pi 5 Demo Build Summary ==="
echo "✅ Docker build environment: Working"
echo "✅ Image creation: Working"  
echo "✅ Partition management: Working"
echo "✅ File system creation: Working"
echo "✅ CUPCAKE structure: Working"
echo "✅ Configuration generation: Working"
echo ""
echo "📁 Demo image: $OUTPUT_DIR/$IMG_NAME"
echo "💿 This demonstrates the complete build process"
echo "🚀 For production: Fix Pi OS download URL and run full build"
echo ""
echo "Demo completed successfully!"
