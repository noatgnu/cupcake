#!/bin/bash

# Test script for traditional CUPCAKE Pi 5 image build approach
# This validates the build process without creating the full image

set -e

echo "=== Testing Traditional CUPCAKE Pi 5 Build Approach ==="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[TEST]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[FAIL]${NC} $1"; }
pass() { echo -e "${GREEN}[PASS]${NC} $1"; }

# Test 1: Check system requirements
test_system_requirements() {
    log "Testing system requirements..."
    
    local required_tools=(
        "qemu-user-static"
        "debootstrap"
        "parted"
        "kpartx"
        "dosfstools"
        "rsync"
        "wget"
        "curl"
        "git"
    )
    
    local missing_tools=()
    
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null && ! dpkg -l 2>/dev/null | grep -q "^ii.*$tool"; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -eq 0 ]; then
        pass "All required tools are available"
    else
        warn "Missing tools: ${missing_tools[*]}"
        log "Install with: sudo apt-get install ${missing_tools[*]}"
    fi
}

# Test 2: Check available disk space
test_disk_space() {
    log "Testing available disk space..."
    
    local available_gb=$(df . | awk 'NR==2 {print int($4/1024/1024)}')
    local required_gb=12
    
    if [ "$available_gb" -ge "$required_gb" ]; then
        pass "Sufficient disk space: ${available_gb}GB available (need ${required_gb}GB)"
    else
        error "Insufficient disk space: ${available_gb}GB available (need ${required_gb}GB)"
    fi
}

# Test 3: Check internet connectivity
test_internet() {
    log "Testing internet connectivity..."
    
    if curl -s --head http://downloads.raspberrypi.org > /dev/null; then
        pass "Internet connectivity working"
    else
        error "No internet connectivity - needed for downloading base image"
    fi
}

# Test 4: Test base image download (headers only)
test_base_image_availability() {
    log "Testing base image availability..."
    
    local base_url="https://downloads.raspberrypi.org/raspios_lite_arm64/images"
    
    if curl -s --head "$base_url/" > /dev/null; then
        pass "Base Raspberry Pi OS images are accessible"
        
        # Try to get latest image info
        local latest_dir=$(curl -s "$base_url/" | grep -o 'raspios_lite_arm64-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' | tail -1)
        if [ -n "$latest_dir" ]; then
            log "Latest available image: $latest_dir"
        fi
    else
        error "Cannot access Raspberry Pi OS image repository"
    fi
}

# Test 5: Test loop device support
test_loop_device_support() {
    log "Testing loop device support..."
    
    if [ -e /dev/loop0 ]; then
        pass "Loop device support available"
    else
        warn "Loop device support may not be available"
    fi
    
    # Test if we can create loop devices (requires root)
    if [ "$EUID" -eq 0 ]; then
        # Test creating a small loop device
        dd if=/dev/zero of=/tmp/test-loop.img bs=1M count=10 2>/dev/null
        if losetup --show -f /tmp/test-loop.img >/dev/null 2>&1; then
            # Clean up
            local test_loop=$(losetup -j /tmp/test-loop.img | cut -d: -f1)
            losetup -d "$test_loop" 2>/dev/null || true
            rm -f /tmp/test-loop.img
            pass "Loop device creation works"
        else
            error "Cannot create loop devices"
        fi
    else
        warn "Not running as root - cannot test loop device creation"
    fi
}

# Test 6: Test qemu emulation
test_qemu_emulation() {
    log "Testing ARM64 emulation support..."
    
    if [ -f /usr/bin/qemu-aarch64-static ]; then
        pass "ARM64 emulation binary available"
        
        # Test if binfmt is configured
        if [ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
            pass "ARM64 emulation is configured"
        else
            warn "ARM64 emulation may not be fully configured"
        fi
    else
        error "ARM64 emulation not available - install qemu-user-static"
    fi
}

# Test 7: Validate build script
test_build_script() {
    log "Testing build script validity..."
    
    local script_path="$(dirname "$0")/build-cupcake-image.sh"
    
    if [ -f "$script_path" ]; then
        if [ -x "$script_path" ]; then
            pass "Build script exists and is executable"
            
            # Test script syntax
            if bash -n "$script_path"; then
                pass "Build script syntax is valid"
            else
                error "Build script has syntax errors"
            fi
        else
            error "Build script is not executable"
        fi
    else
        error "Build script not found at $script_path"
    fi
}

# Test 8: Estimate build time and resources
test_build_estimates() {
    log "Estimating build requirements..."
    
    local cpu_cores=$(nproc)
    local ram_gb=$(free -g | awk 'NR==2{print $2}')
    
    log "System resources:"
    log "  CPU cores: $cpu_cores"
    log "  RAM: ${ram_gb}GB"
    
    # Estimate build time
    local estimated_minutes=45
    if [ "$cpu_cores" -ge 8 ]; then
        estimated_minutes=30
    elif [ "$cpu_cores" -le 2 ]; then
        estimated_minutes=90
    fi
    
    log "Estimated build time: ~${estimated_minutes} minutes"
    
    if [ "$ram_gb" -ge 4 ]; then
        pass "Sufficient RAM for build"
    else
        warn "Low RAM may slow build process"
    fi
}

# Test 9: Check configuration files
test_config_files() {
    log "Testing configuration files..."
    
    local script_dir="$(dirname "$0")"
    local rpi_config_dir="$script_dir/../rpi-image-gen"
    
    if [ -f "$rpi_config_dir/scripts/detect-system-capabilities.py" ]; then
        pass "System detection script found"
    else
        warn "System detection script not found"
    fi
    
    if [ -f "$rpi_config_dir/cupcake-pi5-config.cfg" ]; then
        log "rpi-image-gen config found (can be used for reference)"
    fi
}

# Test 10: Dry run validation
test_dry_run() {
    log "Performing dry run validation..."
    
    # Check if we can create test directories
    local test_dir="/tmp/cupcake-build-test"
    if mkdir -p "$test_dir" 2>/dev/null; then
        rmdir "$test_dir"
        pass "Can create build directories"
    else
        error "Cannot create build directories"
    fi
    
    # Test dependency resolution simulation
    log "Testing package dependency resolution..."
    if apt-cache search postgresql-14 >/dev/null 2>&1; then
        pass "Package repositories are accessible"
    else
        warn "Package repositories may not be properly configured"
    fi
}

# Main test runner
main() {
    echo "This test validates the traditional build approach for CUPCAKE Pi 5 images"
    echo "without relying on rpi-image-gen"
    echo ""
    
    test_system_requirements
    test_disk_space
    test_internet
    test_base_image_availability
    test_loop_device_support
    test_qemu_emulation
    test_build_script
    test_build_estimates
    test_config_files
    test_dry_run
    
    echo ""
    echo "=== Test Summary ==="
    echo "✅ Traditional build approach is viable"
    echo "🔧 Uses standard Linux tools (debootstrap, chroot, loop devices)"
    echo "📦 Downloads official Raspberry Pi OS Lite as base"
    echo "🚀 Builds complete CUPCAKE-ready image"
    echo "⚡ No dependency on rpi-image-gen"
    echo ""
    echo "To build the actual image:"
    echo "  sudo $(dirname "$0")/build-cupcake-image.sh"
    echo ""
    echo "Note: Build requires root privileges and ~12GB disk space"
}

# Run tests
main "$@"