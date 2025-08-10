#!/bin/bash




set -e


PI_MODEL="${1:-pi5}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUPCAKE_ROOT="$(dirname "$SCRIPT_DIR")"


DOCKER_IMAGE_NAME="cupcake-pi-builder"
DOCKER_TAG="latest"
CONTAINER_NAME="cupcake-pi-build-$(date +%s)"


RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' 

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


validate_inputs() {
    if [[ "$PI_MODEL" != "pi4" && "$PI_MODEL" != "pi5" ]]; then
        error "PI_MODEL must be 'pi4' or 'pi5'"
    fi
    
    if [[ "$ENABLE_SSH" != "0" && "$ENABLE_SSH" != "1" ]]; then
        error "ENABLE_SSH must be '0' or '1'"
    fi
}


check_prerequisites() {
    log "Checking prerequisites..."
    
    
    if ! command -v docker &> /dev/null; then
        error "Docker is required but not installed. Please install Docker first."
    fi
    
    if ! docker info &> /dev/null; then
        error "Docker daemon is not running. Please start Docker first."
    fi
    
    
    if command -v apt-get &> /dev/null; then
        if ! dpkg -l | grep -q "^ii  binfmt-support "; then
            log "Installing binfmt-support package on host..."
            sudo apt-get update
            sudo apt-get install -y binfmt-support
        fi
        
        
        if systemctl list-unit-files | grep -q "binfmt-support.service"; then
            sudo systemctl restart binfmt-support || warn "Could not restart binfmt-support service"
        else
            warn "binfmt-support service not available, binfmt should work via kernel module"
        fi
    fi
    
    
    local available_space=$(df "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 10485760 ]]; then 
        error "Need at least 10GB free disk space for Docker image building"
    fi
    
    log "Prerequisites check completed"
}


build_docker_image() {
    log "Building Docker image for pi-gen..."
    
    
    if docker images | grep -q "$DOCKER_IMAGE_NAME.*$DOCKER_TAG"; then
        info "Docker image $DOCKER_IMAGE_NAME:$DOCKER_TAG already exists"
        read -p "Rebuild the Docker image? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Using existing Docker image"
            return 0
        fi
    fi
    
    
    info "Building Docker image (this may take 10-15 minutes)..."
    cd "$SCRIPT_DIR"
    
    docker build \
        -f Dockerfile.pi-builder \
        -t "$DOCKER_IMAGE_NAME:$DOCKER_TAG" \
        . || error "Failed to build Docker image"
    
    log "Docker image built successfully"
}


create_container_build_script() {
    log "Creating container build script..."
    
    cat > "$SCRIPT_DIR/container-build.sh" << 'EOF'
#!/bin/bash
set -e


PI_MODEL="$1"
IMAGE_VERSION="$2"
ENABLE_SSH="$3"

echo "Starting CUPCAKE Pi $PI_MODEL image build in container..."
echo "Image Version: $IMAGE_VERSION"
echo "SSH Enabled: $ENABLE_SSH"


echo "Setting up binfmt_misc in container..."


modprobe binfmt_misc 2>/dev/null || echo "binfmt_misc module already loaded"


if [[ ! -d "/proc/sys/fs/binfmt_misc" ]]; then
    echo "Mounting binfmt_misc in container..."
    mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || {
        echo "ERROR: Failed to mount binfmt_misc in container"
        exit 1
    }
fi


echo "Registering ARM interpreters in container..."
if [[ -f "/usr/bin/qemu-aarch64-static" ]]; then
    
    if [[ ! -f "/proc/sys/fs/binfmt_misc/qemu-aarch64" ]]; then
        echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:CF' > /proc/sys/fs/binfmt_misc/register 2>/dev/null || echo "Could not register qemu-aarch64"
    fi
fi

if [[ -f "/usr/bin/qemu-arm-static" ]]; then
    
    if [[ ! -f "/proc/sys/fs/binfmt_misc/qemu-arm" ]]; then
        echo ':qemu-arm:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-arm-static:CF' > /proc/sys/fs/binfmt_misc/register 2>/dev/null || echo "Could not register qemu-arm"
    fi
fi


echo "Container binfmt_misc status:"
cat /proc/sys/fs/binfmt_misc/status 2>/dev/null || echo "status file not readable"
echo "Registered interpreters:"
ls -la /proc/sys/fs/binfmt_misc/ | grep -E "(qemu|arm|aarch64)" || echo "No ARM interpreters found"


cd /build/pi-gen


if [[ -d "work" ]]; then
    echo "Cleaning previous build..."
    sudo rm -rf work deploy || true
fi


echo "Configuring pi-gen for $PI_MODEL..."


if [[ "$PI_MODEL" == "pi4" ]]; then
    PI_MODEL_NUM="4"
    GPU_MEM="64"
    HOSTNAME="cupcake-pi4"
else
    PI_MODEL_NUM="5"
    GPU_MEM="128"
    HOSTNAME="cupcake-pi5"
fi

cat > config << EOC

IMG_NAME="cupcake-$PI_MODEL-$IMAGE_VERSION"
IMG_DATE="$(date +%Y-%m-%d)"
RELEASE="bookworm"
DEPLOY_COMPRESSION="none"


PI_MODEL="$PI_MODEL_NUM"
ARCH="arm64"


ENABLE_SSH=$ENABLE_SSH
DISABLE_SPLASH=1
DISABLE_FIRST_BOOT_USER_RENAME=1


STAGE_LIST="stage0 stage1 stage2 stage-cupcake"


TIMEZONE_DEFAULT="UTC"
KEYBOARD_KEYMAP="us"
KEYBOARD_LAYOUT="English (US)"


FIRST_USER_NAME="cupcake"
FIRST_USER_PASS="cupcake123"
HOSTNAME="$HOSTNAME"


GPU_MEM=$GPU_MEM
EOC


echo "Creating custom CUPCAKE stage..."
STAGE_DIR="stage-cupcake"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"


cat > "$STAGE_DIR/prerun.sh" << 'PRERUN_EOF'
#!/bin/bash -e


if [ -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf" ]; then
    rm -f "${ROOTFS_DIR}/etc/systemd/system/dhcpcd.service.d/wait.conf"
fi
PRERUN_EOF
chmod +x "$STAGE_DIR/prerun.sh"


mkdir -p "$STAGE_DIR/01-cupcake/files"


mkdir -p "$STAGE_DIR/01-cupcake/files/opt/cupcake"/{scripts,src,data,logs,backup,media,config,assets,frontend}
mkdir -p "$STAGE_DIR/01-cupcake/files/var/log/cupcake"
mkdir -p "$STAGE_DIR/01-cupcake/files/var/lib/cupcake"


echo "Copying CUPCAKE source code..."
if [[ -d "/build/cupcake-src" ]]; then
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='.git' \
              --exclude='.github' \
              --exclude='.idea' \
              --exclude='.claude' \
              --exclude='node_modules' \
              --exclude='venv' \
              --exclude='env' \
              --exclude='.env' \
              --exclude='build' \
              --exclude='dist' \
              --exclude='raspberry-pi' \
              --exclude='pi-deployment' \
              --exclude='tests' \
              --exclude='test_*' \
              --exclude='*_test.py' \
              --exclude='*.md' \
              --exclude='*.MD' \
              --exclude='README*' \
              --exclude='*.adoc' \
              --exclude='*.svg' \
              --exclude='docker-compose*.yml' \
              --exclude='captain-definition*' \
              --exclude='Dockerfile*' \
              --exclude='dockerfiles' \
              --exclude='ansible-playbooks' \
              --exclude='*.zip' \
              --exclude='*.tar.gz' \
              --exclude='*.tar' \
              --exclude='*.rar' \
              --exclude='*.7z' \
              --exclude='backups' \
              --exclude='temp_extract' \
              --exclude='data2' \
              --exclude='test_*' \
              --exclude='*test*' \
              --exclude='staticfiles' \
              --exclude='media' \
              --exclude='*.lock' \
              --exclude='.dockerignore' \
              --exclude='.gitignore' \
              --exclude='install_cupcake*.sh' \
              --exclude='build-multiarch.sh' \
              --exclude='turnserver*' \
              --exclude='cron' \
              --exclude='models' \
              /build/cupcake-src/ "$STAGE_DIR/01-cupcake/files/opt/cupcake/src/"
else
    echo "Warning: No CUPCAKE source found at /build/cupcake-src"
fi


cat > "$STAGE_DIR/01-cupcake/01-run.sh" << 'SETUP_EOF'
#!/bin/bash -e


if [ -d "files" ]; then
    cp -r files/* "${ROOTFS_DIR}/"
fi


on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive


apt-get update


apt-get install -y postgresql postgresql-contrib postgresql-client


apt-get install -y redis-server


apt-get install -y nginx


apt-get install -y python3 python3-pip python3-venv python3-dev


apt-get install -y build-essential libpq-dev libffi-dev libssl-dev
apt-get install -y libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
apt-get install -y git curl wget unzip htop nvme-cli


curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs


echo "Building CUPCAKE Angular frontend..."
cd /tmp
git clone https://github.com/noatgnu/cupcake-ng.git
cd cupcake-ng


HOSTNAME_VAR=""
if [[ "$PI_MODEL" == "pi4" ]]; then
    HOSTNAME_VAR="cupcake-pi4.local"
else
    HOSTNAME_VAR="cupcake-pi5.local"
fi

sed -i "s;https://cupcake.proteo.info;http://$HOSTNAME_VAR;g" src/environments/environment.ts
sed -i "s;http://localhost;http://$HOSTNAME_VAR;g" src/environments/environment.ts


npm install
npm run build


mkdir -p /opt/cupcake/frontend
cp -r dist/browser/* /opt/cupcake/frontend/


cd /
rm -rf /tmp/cupcake-ng


apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

CHROOT_EOF


if [ -d "${ROOTFS_DIR}/opt/cupcake/scripts" ]; then
    chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"*
fi


on_chroot << 'USER_EOF'

if ! id "cupcake" &>/dev/null; then
    useradd -m -s /bin/bash cupcake
    echo "cupcake:cupcake123" | chpasswd
    usermod -aG sudo cupcake
fi


mkdir -p /var/log/cupcake
mkdir -p /var/lib/cupcake
mkdir -p /opt/cupcake/{data,logs,backup,media}


chown -R cupcake:cupcake /opt/cupcake
chown -R cupcake:cupcake /var/log/cupcake
chown -R cupcake:cupcake /var/lib/cupcake


systemctl enable ssh
systemctl enable postgresql
systemctl enable redis-server
systemctl enable nginx


if [ -f "/etc/systemd/system/cupcake-setup.service" ]; then
    systemctl enable cupcake-setup.service
fi

USER_EOF

echo "CUPCAKE stage completed successfully"
SETUP_EOF
chmod +x "$STAGE_DIR/01-cupcake/01-run.sh"


mkdir -p "$STAGE_DIR/02-boot-config"

cat > "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'BOOT_EOF'
#!/bin/bash -e


if [ -f "${ROOTFS_DIR}/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
elif [ -f "${ROOTFS_DIR}/boot/config.txt" ]; then
    BOOT_CONFIG="${ROOTFS_DIR}/boot/config.txt"
else
    echo "Creating boot config file..."
    mkdir -p "${ROOTFS_DIR}/boot/firmware"
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
fi

BOOT_EOF


if [[ "$PI_MODEL" == "pi4" ]]; then
    cat >> "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'PI4_BOOT_EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTCONFIG_EOF'


arm_64bit=1
dtparam=arm_freq=2000
dtparam=over_voltage=2
gpu_mem=64


dtparam=pciex1
dtoverlay=pcie-32bit-dma


dtparam=audio=off
camera_auto_detect=0
display_auto_detect=0


disable_splash=1
boot_delay=0
BOOTCONFIG_EOF
PI4_BOOT_EOF
else
    cat >> "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh" << 'PI5_BOOT_EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTCONFIG_EOF'


arm_64bit=1
dtparam=arm_freq=2400
dtparam=over_voltage=2
gpu_mem=128


dtparam=pciex1_gen=3
dtoverlay=pcie-32bit-dma


dtparam=i2c_arm=off
dtparam=spi=off


dtparam=audio=off
camera_auto_detect=0
display_auto_detect=0


disable_splash=1
boot_delay=0
arm_boost=1
BOOTCONFIG_EOF
PI5_BOOT_EOF
fi

chmod +x "$STAGE_DIR/02-boot-config/01-${PI_MODEL}-config.sh"


echo "Starting pi-gen build process..."
echo "This will take 1-3 hours depending on your system..."

sudo ./build.sh


if [[ -f "deploy/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img" ]]; then
    echo "Build completed successfully!"
    cp deploy/cupcake-${PI_MODEL}-*.img /build/output/
    echo "Image copied to output directory"
    ls -la /build/output/
else
    echo "Build failed! Checking deploy directory..."
    ls -la deploy/ || echo "Deploy directory not found"
    exit 1
fi
EOF

    chmod +x "$SCRIPT_DIR/container-build.sh"
    log "Container build script created"
}


run_docker_build() {
    log "Starting Docker-based Pi image build..."
    
    
    mkdir -p "$SCRIPT_DIR/output"
    
    info "Running build container (this will take 1-3 hours)..."
    
    
    
    docker run \
        --rm \
        --privileged \
        --name "$CONTAINER_NAME" \
        -v "$CUPCAKE_ROOT:/build/cupcake-src:ro" \
        -v "$SCRIPT_DIR/container-build.sh:/build/container-build.sh:ro" \
        -v "$SCRIPT_DIR/output:/build/output:rw" \
        "$DOCKER_IMAGE_NAME:$DOCKER_TAG" \
        /build/container-build.sh "$PI_MODEL" "$IMAGE_VERSION" "$ENABLE_SSH"
    
    log "Docker build completed"
}


finalize_image() {
    log "Finalizing image..."
    
    local image_file="$SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
    
    if [[ -f "$image_file" ]]; then
        info "Compressing image..."
        cd "$SCRIPT_DIR/output"
        
        
        xz -9 -T 0 "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img"
        
        
        sha256sum "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz" > "cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
        
        log "Image finalized:"
        log "  Image: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz"
        log "  Checksum: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
    else
        error "Image file not found: $image_file"
    fi
}


cleanup() {
    log "Cleaning up temporary files..."
    
    
    rm -f "$SCRIPT_DIR/container-build.sh"
    
    
    if docker ps -a | grep -q "$CONTAINER_NAME"; then
        docker rm -f "$CONTAINER_NAME" &>/dev/null || true
    fi
}


show_usage() {
    echo "Usage: $0 [pi4|pi5] [version] [enable_ssh]"
    echo ""
    echo "Arguments:"
    echo "  pi_model     - Raspberry Pi model: 'pi4' or 'pi5' (default: pi5)"
    echo "  version      - Image version tag (default: current date)"
    echo "  enable_ssh   - Enable SSH: '1' or '0' (default: 1)"
    echo ""
    echo "Examples:"
    echo "  $0                          
    echo "  $0 pi4                      
    echo "  $0 pi5 v1.0.0               
    echo "  $0 pi4 v1.0.0 0             
    echo ""
    echo "Requirements:"
    echo "  - Docker installed and running"
    echo "  - At least 10GB free disk space"
    echo "  - Privileged Docker access (for pi-gen)"
}


main() {
    log "Starting CUPCAKE Raspberry Pi $PI_MODEL Docker image build..."
    info "Pi Model: $PI_MODEL"
    info "Image Version: $IMAGE_VERSION"
    info "SSH Enabled: $ENABLE_SSH"
    info "Build Directory: $SCRIPT_DIR"
    
    
    log "Loading binfmt_misc kernel module on host (required for pi-gen)..."
    sudo modprobe binfmt_misc || warn "Could not load binfmt_misc module"
    
    
    if [[ ! -d "/proc/sys/fs/binfmt_misc" ]] || ! mount | grep -q binfmt_misc; then
        log "Mounting binfmt_misc filesystem on host..."
        sudo mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || error "CRITICAL: Failed to mount binfmt_misc on host"
    fi
    
    
    if [[ ! -f "/proc/sys/fs/binfmt_misc/status" ]]; then
        error "CRITICAL: binfmt_misc not properly mounted on host - Docker pi-gen will fail"
    fi
    
    info "Host binfmt_misc status: $(cat /proc/sys/fs/binfmt_misc/status 2>/dev/null || echo 'unknown')"
    
    
    trap cleanup EXIT
    
    validate_inputs
    check_prerequisites
    build_docker_image
    create_container_build_script
    run_docker_build
    finalize_image
    
    log "CUPCAKE Raspberry Pi $PI_MODEL Docker image build completed successfully!"
    
    echo ""
    echo -e "${GREEN}Build Results:${NC}"
    echo "📦 Image: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz"
    echo "🔐 Checksum: $SCRIPT_DIR/output/cupcake-${PI_MODEL}-${IMAGE_VERSION}.img.xz.sha256"
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo "1. Flash the image to an SD card (64GB+ recommended)"
    echo "2. Boot the Raspberry Pi ${PI_MODEL^^}"
    echo "3. SSH to cupcake@cupcake-${PI_MODEL}.local (password: cupcake123)"
    echo "4. Access web interface at http://cupcake-${PI_MODEL}.local"
    echo ""
    echo -e "${YELLOW}Security Note: Change default passwords immediately after first boot!${NC}"
}


if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_usage
    exit 0
fi


main "$@"