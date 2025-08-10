#!/bin/bash




set -e


PI_MODEL="${1:-pi5}"
IMAGE_VERSION="${2:-$(date +%Y-%m-%d)}"
ENABLE_SSH="${3:-1}"


VERSION="1.0.0"
BUILD_DATE=$(date -Iseconds)


if [[ "$PI_MODEL" != "pi4" && "$PI_MODEL" != "pi5" ]]; then
    echo "Error: PI_MODEL must be 'pi4' or 'pi5'"
    echo "Usage: $0 [pi4|pi5] [version] [enable_ssh]"
    echo "Example: $0 pi5 v1.0.0 1"
    exit 1
fi


detect_build_dir() {
    local required_gb=20
    local best_dir=""
    local max_space=0

    
    local dirs=("$HOME/build" "/tmp/build" "./build" "/opt/build")

    for dir in "${dirs[@]}"; do
        local parent_dir=$(dirname "$dir")
        if [ -d "$parent_dir" ] && [ -w "$parent_dir" ]; then
            local available_gb=$(df "$parent_dir" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}')
            if [ "$available_gb" -gt "$max_space" ]; then
                max_space=$available_gb
                best_dir=$dir
            fi
        fi
    done

    
    if [ -z "$best_dir" ] || [ "$max_space" -lt "$required_gb" ]; then
        best_dir="./cupcake-build"
        max_space=$(df . 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}' || echo 0)
    fi

    if [ "$max_space" -lt "$required_gb" ]; then
        warn "Only ${max_space}GB available, but ${required_gb}GB recommended"
        warn "Build may fail if space runs out"
    fi

    echo "$best_dir"
}



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


detect_target_pi_specs() {
    log "Determining target Pi specifications for $PI_MODEL..."

    
    if [[ "$PI_MODEL" == "pi4" ]]; then
        PI_MODEL_NUM="4"
        PI_RAM_MB="4096"  
        PI_CORES="4"
        GPU_MEM="64"
        HOSTNAME="cupcake-pi4"
        IMG_SIZE="8G"
        WHISPER_MODEL="base.en"
        WHISPER_THREADS="4"
    else
        PI_MODEL_NUM="5"
        PI_RAM_MB="8192"  
        PI_CORES="4"
        GPU_MEM="128"
        HOSTNAME="cupcake-pi5"
        IMG_SIZE="10G"
        WHISPER_MODEL="small.en"
        WHISPER_THREADS="6"
    fi

    info "Target specs: $PI_MODEL with ${PI_RAM_MB}MB RAM, $PI_CORES cores"
    info "Whisper config: $WHISPER_MODEL model, $WHISPER_THREADS threads"
    info "Image size: $IMG_SIZE"
}


BUILD_DIR=$(detect_build_dir)
PI_GEN_DIR="$BUILD_DIR/pi-gen"
CUPCAKE_DIR="$(dirname "$(readlink -f "$0")")/.."
CONFIG_DIR="./config"
SCRIPTS_DIR="./scripts"
ASSETS_DIR="./assets"


detect_target_pi_specs


check_prerequisites() {
    log "Checking prerequisites..."
    
    
    if ! command -v apt &> /dev/null; then
        error "This script requires a Debian/Ubuntu system with apt package manager"
    fi
    
    
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root"
    fi
    
    
    log "Installing pi-gen dependencies..."
    sudo apt-get update
    sudo apt-get install -y \
        qemu-user-static \
        debootstrap git \
        parted kpartx fdisk gdisk \
        dosfstools e2fsprogs \
        zip xz-utils \
        python3 python3-pip \
        binfmt-support \
        rsync \
        quilt \
        libarchive-tools \
        arch-test \
        coreutils \
        zerofree \
        tar \
        whois \
        grep \
        libcap2-bin \
        xxd \
        file \
        kmod \
        bc \
        pigz
    
    
    if ! dpkg -l | grep -q "^ii  binfmt-support "; then
        log "Installing binfmt-support package..."
        sudo apt-get install -y binfmt-support
    fi
    
    
    if systemctl list-unit-files | grep -q "binfmt-support.service"; then
        sudo systemctl enable binfmt-support || warn "Could not enable binfmt-support service"
        sudo systemctl start binfmt-support || warn "Could not start binfmt-support service"
    fi
    
    
    local available_space=$(df . | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 8388608 ]]; then 
        error "Need at least 8GB free disk space for image building"
    fi
    
    log "Prerequisites check completed"
}


setup_pi_gen() {
    log "Setting up pi-gen..."
    
    if [[ ! -d "$PI_GEN_DIR" ]]; then
        info "Cloning pi-gen repository..."
        git clone https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
    else
        info "Updating pi-gen repository..."
        cd "$PI_GEN_DIR"
        git pull origin master
        cd ..
    fi
    
    
    cp -r "$CONFIG_DIR/pi-gen-config/"* "$PI_GEN_DIR/" 2>/dev/null || true
    
    log "pi-gen setup completed"
}


prepare_build() {
    log "Preparing build environment..."
    
    
    mkdir -p "$BUILD_DIR"
    
    log "Build environment prepared"
}


configure_pi_gen() {
    log "Configuring pi-gen settings for $PI_MODEL..."
    
    
    local pi_model_num=""
    local gpu_mem=""
    local hostname=""
    
    if [[ "$PI_MODEL" == "pi4" ]]; then
        pi_model_num="4"
        gpu_mem="64"
        hostname="cupcake-pi4"
    else
        pi_model_num="5"
        gpu_mem="128"
        hostname="cupcake-pi5"
    fi
    
    cat > "$PI_GEN_DIR/config" << EOF

IMG_NAME="cupcake-$PI_MODEL-$IMAGE_VERSION"
IMG_DATE="$(date +%Y-%m-%d)"
RELEASE="bookworm"
DEPLOY_COMPRESSION="xz"


PI_MODEL="$pi_model_num"
ARCH="arm64"


ENABLE_SSH=$ENABLE_SSH
DISABLE_SPLASH=1
DISABLE_FIRST_BOOT_USER_RENAME=1


STAGE_LIST="stage0 stage1 stage2 stage-cupcake"


WORK_DIR="${BUILD_DIR}/pi-gen/work"


SKIP_IMAGES="stage0,stage1,stage2"


TIMEZONE_DEFAULT="UTC"
KEYBOARD_KEYMAP="us"
KEYBOARD_LAYOUT="English (US)"


FIRST_USER_NAME="cupcake"
FIRST_USER_PASS="cupcake123"  
HOSTNAME="$hostname"


GPU_MEM=$gpu_mem





EOF
    
    log "pi-gen configuration completed for $PI_MODEL"
}


create_custom_stage() {
    log "Creating custom CUPCAKE stage..."
    
    local stage_dir="$PI_GEN_DIR/stage-cupcake"
    
    
    rm -rf "$stage_dir"
    mkdir -p "$stage_dir/00-install-cupcake"
    local files_dir="$stage_dir/00-install-cupcake/files"
    mkdir -p "$files_dir"
    
    
    if [ -d "$CONFIG_DIR/pi-gen-config/stage-cupcake" ]; then
        cp "$CONFIG_DIR/pi-gen-config/stage-cupcake/"* "$stage_dir/" 2>/dev/null || true
    fi
    
    
    
    touch "$stage_dir/EXPORT_IMAGE"
    
    
    
    
    
    if [ ! -f "$stage_dir/SKIP" ]; then
        
        :
    fi
    
    
    cat > "$stage_dir/STAGE_INFO" << 'EOF'



EOF
    
    
    if [ -d "$CONFIG_DIR/system" ]; then
        info "Copying system configuration files..."
        cp -r "$CONFIG_DIR/system/"* "$files_dir/" 2>/dev/null || true
    else
        warn "System config directory not found: $CONFIG_DIR/system"
    fi
    
    
    if [ -d "$SCRIPTS_DIR" ]; then
        info "Copying deployment scripts..."
        mkdir -p "$files_dir/opt/cupcake/scripts"
        cp "$SCRIPTS_DIR/"* "$files_dir/opt/cupcake/scripts/" 2>/dev/null || true
        chmod +x "$files_dir/opt/cupcake/scripts/"* 2>/dev/null || true
    else
        warn "Scripts directory not found: $SCRIPTS_DIR"
        mkdir -p "$files_dir/opt/cupcake/scripts"
    fi
    
    
    if [ -d "$CONFIG_DIR" ]; then
        info "Copying configuration files..."
        mkdir -p "$files_dir/opt/cupcake/config"
        cp -r "$CONFIG_DIR/"* "$files_dir/opt/cupcake/config/" 2>/dev/null || true
    else
        warn "Config directory not found: $CONFIG_DIR"
        mkdir -p "$files_dir/opt/cupcake/config"
    fi
    
    
    info "Copying CUPCAKE source code..."
    mkdir -p "$files_dir/opt/cupcake/src"
    
    
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='.git' \
              --exclude='node_modules' \
              --exclude='venv' \
              --exclude='env' \
              --exclude='.env' \
              --exclude='build' \
              --exclude='dist' \
              --exclude='raspberry-pi' \
              "$CUPCAKE_DIR/" "$files_dir/opt/cupcake/src/"
    
    
    if [ -d "$ASSETS_DIR" ]; then
        info "Copying assets..."
        mkdir -p "$files_dir/opt/cupcake/assets"
        cp -r "$ASSETS_DIR/"* "$files_dir/opt/cupcake/assets/" 2>/dev/null || true
    else
        warn "Assets directory not found: $ASSETS_DIR"
        mkdir -p "$files_dir/opt/cupcake/assets"
    fi
    
    log "Stage files prepared"

    
    cat > "$stage_dir/prerun.sh" << 'EOF'
#!/bin/bash -e




if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi

echo "CUPCAKE stage prerun completed - rootfs ready"
EOF
    chmod +x "$stage_dir/prerun.sh"
    
    
    cat > "$stage_dir/00-install-cupcake/01-run.sh" << 'EOF'
#!/bin/bash -e


log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

warn() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1"
}

error() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1"
    exit 1
}

info() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}


log "Starting CUPCAKE installation..."
log "ROOTFS_DIR: ${ROOTFS_DIR}"


if [ -z "${ROOTFS_DIR}" ]; then
    error "ROOTFS_DIR not set - this script must run within pi-gen context"
fi

if [ ! -d "${ROOTFS_DIR}" ]; then
    error "ROOTFS_DIR does not exist: ${ROOTFS_DIR} - prerun.sh script didn't work correctly"
fi

log "ROOTFS_DIR validated: ${ROOTFS_DIR}"


if [ -d "files" ]; then
    log "Copying configuration files..."
    info "Files directory structure:"
    find files -type f | head -10
    
    
    if [ "$(ls -A files 2>/dev/null)" ]; then
        cp -r files/* "${ROOTFS_DIR}/" || {
            error "Failed to copy files to ${ROOTFS_DIR}"
        }
        log "Successfully copied configuration files"
    else
        info "Files directory is empty, nothing to copy"
    fi
else
    info "No files directory found, skipping file copy"
    info "This is normal if no system configuration files need to be copied"
fi


log "Installing system packages..."
on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive


apt-get update


apt-get install -y \
    postgresql postgresql-contrib postgresql-client \
    redis-server \
    nginx \
    python3 python3-pip python3-venv python3-dev \
    build-essential libpq-dev libffi-dev libssl-dev \
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    git curl wget unzip htop nvme-cli \
    supervisor

log "System packages installed successfully"
CHROOT_EOF


setup_frontend() {
    log "Setting up frontend..."
    
    
    if [ -z "${ROOTFS_DIR}" ]; then
        error "ROOTFS_DIR is not set in frontend setup"
    fi
    
    local frontend_source=""
    local use_prebuilt=false
    
    
    local prebuilt_locations=(
        "${PREBUILT_FRONTEND_DIR}"                    
        "../raspberry-pi/frontend-dist"               
        "./frontend-dist"                             
        "../frontend-dist"                            
    )
    
    for location in "${prebuilt_locations[@]}"; do
        if [ -n "$location" ] && [ -d "$location" ] && [ "$(ls -A "$location" 2>/dev/null)" ]; then
            frontend_source="$location"
            use_prebuilt=true
            break
        fi
    done
    
    
    if [ "${USE_PREBUILT_FRONTEND}" = "1" ] && [ "$use_prebuilt" = false ]; then
        warn "USE_PREBUILT_FRONTEND=1 but no pre-built frontend found"
        info "Attempting to pre-build frontend using prebuild-frontend.sh..."
        
        
        if [ -f "./prebuild-frontend.sh" ]; then
            ./prebuild-frontend.sh --hostname "$HOSTNAME" --output-dir "./frontend-dist"
            if [ -d "./frontend-dist" ]; then
                frontend_source="./frontend-dist"
                use_prebuilt=true
                log "Successfully pre-built frontend"
            else
                warn "Pre-build script completed but no output found"
            fi
        else
            warn "prebuild-frontend.sh not found, will build in QEMU"
        fi
    fi
    
    if [ "$use_prebuilt" = true ]; then
        log "Using pre-built frontend from: $frontend_source"
        
        
        mkdir -p "${ROOTFS_DIR}/opt/cupcake/frontend"
        cp -r "$frontend_source"/* "${ROOTFS_DIR}/opt/cupcake/frontend/"
        
        
        if [ -f "$frontend_source/.build-info" ]; then
            cp "$frontend_source/.build-info" "${ROOTFS_DIR}/opt/cupcake/frontend/"
            info "Frontend build info:"
            cat "$frontend_source/.build-info" | grep -E "(BUILD_DATE|BUILD_PLATFORM|NODE_VERSION)" || true
        fi
        
        
        on_chroot << 'CHROOT_EOF'
export DEBIAN_FRONTEND=noninteractive


apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Pre-built frontend integration completed"
CHROOT_EOF
        
        log "Pre-built frontend integration completed"
    else
        warn "Building frontend from source in QEMU (this will be slow)..."
        on_chroot << 'CHROOT_EOF'

curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "Node.js installed, version: $(node --version)"


echo "Building CUPCAKE Angular frontend..."
cd /tmp
git clone https://github.com/noatgnu/cupcake-ng.git
cd cupcake-ng


sed -i 's;https://cupcake.proteo.info;http://cupcake-pi.local;g' src/environments/environment.ts
sed -i 's;http://localhost;http://cupcake-pi.local;g' src/environments/environment.ts


export NODE_OPTIONS="--max-old-space-size=1024"
npm install --no-optional
npm run build --prod


mkdir -p /opt/cupcake/frontend
cp -r dist/browser/* /opt/cupcake/frontend/


cd /
rm -rf /tmp/cupcake-ng


apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Frontend build completed"
CHROOT_EOF
        
        log "QEMU frontend build completed"
    fi
}


setup_frontend


if [ -n "${ROOTFS_DIR}" ] && [ -d "${ROOTFS_DIR}/opt/cupcake/scripts" ]; then
    log "Setting script permissions..."
    chmod +x "${ROOTFS_DIR}/opt/cupcake/scripts/"* || warn "Failed to set script permissions"
else
    warn "Cannot set script permissions - ROOTFS_DIR not set or scripts directory not found"
fi


on_chroot << 'CHROOT_EOF'


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

CHROOT_EOF


log "Setting up Pi Imager advanced configuration support..."


cat > "${ROOTFS_DIR}/usr/local/bin/cupcake-firstrun.sh" << 'CUPCAKE_FIRSTRUN_EOF'
#!/bin/bash



log_cupcake() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] CUPCAKE: $1" | tee -a /var/log/cupcake-firstrun.log
}

log_cupcake "Starting CUPCAKE first-run configuration..."


PRIMARY_USER=$(getent passwd 1000 | cut -d: -f1 2>/dev/null || echo "cupcake")
log_cupcake "Primary user detected: $PRIMARY_USER"


CURRENT_HOSTNAME=$(hostname)
log_cupcake "Current hostname: $CURRENT_HOSTNAME"


CUPCAKE_CONFIG_DIR="/opt/cupcake/config"
if [ -d "$CUPCAKE_CONFIG_DIR" ]; then
    log_cupcake "Updating CUPCAKE configuration for hostname: $CURRENT_HOSTNAME"
    
    
    find "$CUPCAKE_CONFIG_DIR" -type f -name "*.conf" -o -name "*.yml" -o -name "*.json" | while read -r config_file; do
        if grep -q "cupcake-pi.local\|cupcake-pi4.local\|cupcake-pi5.local" "$config_file" 2>/dev/null; then
            log_cupcake "Updating hostname references in: $config_file"
            sed -i "s/cupcake-pi\([45]\)\?\.local/${CURRENT_HOSTNAME}.local/g" "$config_file"
        fi
    done
fi


log_cupcake "Setting CUPCAKE ownership to user: $PRIMARY_USER"
chown -R "$PRIMARY_USER:$PRIMARY_USER" /opt/cupcake/data /opt/cupcake/logs /opt/cupcake/media 2>/dev/null || true
chown -R "$PRIMARY_USER:$PRIMARY_USER" /var/log/cupcake 2>/dev/null || true


log_cupcake "Setting up CUPCAKE Django superuser..."
cd /opt/cupcake/src


cat > /tmp/create_superuser.py << 'SUPERUSER_EOF'
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()


username = os.environ.get('CUPCAKE_ADMIN_USER', 'admin')
email = os.environ.get('CUPCAKE_ADMIN_EMAIL', f'{username}@{os.environ.get("HOSTNAME", "localhost")}.local')
password = os.environ.get('CUPCAKE_ADMIN_PASSWORD', 'cupcake123')

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"Created CUPCAKE superuser: {username}")
else:
    print(f"CUPCAKE superuser already exists: {username}")
SUPERUSER_EOF


export CUPCAKE_ADMIN_USER="$PRIMARY_USER"
export CUPCAKE_ADMIN_EMAIL="${PRIMARY_USER}@${CURRENT_HOSTNAME}.local"
export HOSTNAME="$CURRENT_HOSTNAME"


log_cupcake "CUPCAKE superuser will be created on first service start"


cat > /etc/systemd/system/cupcake-firstrun.service << 'SERVICE_EOF'
[Unit]
Description=CUPCAKE First-run Configuration
After=postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=oneshot
User=root
ExecStartPre=/usr/local/bin/cupcake-manual-config.sh
ExecStart=/usr/local/bin/cupcake-firstrun.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl enable cupcake-firstrun.service

log_cupcake "CUPCAKE first-run configuration completed"
CUPCAKE_FIRSTRUN_EOF

chmod +x "${ROOTFS_DIR}/usr/local/bin/cupcake-firstrun.sh"


cat > "${ROOTFS_DIR}/usr/local/bin/cupcake-manual-config.sh" << 'MANUAL_CONFIG_EOF'
#!/bin/bash



log_config() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] CONFIG: $1" | tee -a /var/log/cupcake-config.log
}


if [ -f /boot/cupcake-config.txt ]; then
    log_config "Processing manual CUPCAKE configuration..."
    
    
    source /boot/cupcake-config.txt
    
    
    if [ -n "$CUPCAKE_ADMIN_USER" ]; then
        log_config "Setting CUPCAKE admin user: $CUPCAKE_ADMIN_USER"
        echo "CUPCAKE_ADMIN_USER=$CUPCAKE_ADMIN_USER" >> /etc/environment
    fi
    
    if [ -n "$CUPCAKE_ADMIN_PASSWORD" ]; then
        log_config "Setting CUPCAKE admin password"
        echo "CUPCAKE_ADMIN_PASSWORD=$CUPCAKE_ADMIN_PASSWORD" >> /etc/environment
    fi
    
    if [ -n "$CUPCAKE_ADMIN_EMAIL" ]; then
        log_config "Setting CUPCAKE admin email: $CUPCAKE_ADMIN_EMAIL"  
        echo "CUPCAKE_ADMIN_EMAIL=$CUPCAKE_ADMIN_EMAIL" >> /etc/environment
    fi
    
    
    if [ -n "$CUPCAKE_HOSTNAME" ]; then
        log_config "Setting hostname: $CUPCAKE_HOSTNAME"
        echo "$CUPCAKE_HOSTNAME" > /etc/hostname
        sed -i "s/127.0.1.1.*/127.0.1.1\t$CUPCAKE_HOSTNAME/g" /etc/hosts
    fi
    
    
    if [ -n "$CUPCAKE_DB_PASSWORD" ]; then
        log_config "Setting database password"
        echo "CUPCAKE_DB_PASSWORD=$CUPCAKE_DB_PASSWORD" >> /etc/environment
    fi
    
    
    rm -f /boot/cupcake-config.txt
    log_config "Manual configuration completed and removed"
fi


if [ -f /boot/cupcake-ssh-keys.txt ]; then
    log_config "Installing SSH keys..."
    
    
    PRIMARY_USER=$(getent passwd 1000 | cut -d: -f1 2>/dev/null || echo "cupcake")
    USER_HOME=$(eval echo "~$PRIMARY_USER")
    
    
    mkdir -p "$USER_HOME/.ssh"
    chmod 700 "$USER_HOME/.ssh"
    
    
    cat /boot/cupcake-ssh-keys.txt >> "$USER_HOME/.ssh/authorized_keys"
    chmod 600 "$USER_HOME/.ssh/authorized_keys"
    chown -R "$PRIMARY_USER:$PRIMARY_USER" "$USER_HOME/.ssh"
    
    
    rm -f /boot/cupcake-ssh-keys.txt
    log_config "SSH keys installed and removed"
fi


if [ -f /boot/cupcake-ssl-config.txt ]; then
    log_config "Processing SSL configuration..."
    source /boot/cupcake-ssl-config.txt
    
    if [ "$CUPCAKE_ENABLE_SSL" = "true" ]; then
        log_config "Enabling self-signed SSL"
        echo "CUPCAKE_ENABLE_SSL=true" >> /etc/environment
        echo "CUPCAKE_SSL_COUNTRY=${CUPCAKE_SSL_COUNTRY:-US}" >> /etc/environment
        echo "CUPCAKE_SSL_STATE=${CUPCAKE_SSL_STATE:-California}" >> /etc/environment
        echo "CUPCAKE_SSL_CITY=${CUPCAKE_SSL_CITY:-Berkeley}" >> /etc/environment
        echo "CUPCAKE_SSL_ORG=${CUPCAKE_SSL_ORG:-CUPCAKE Lab}" >> /etc/environment
    fi
    
    rm -f /boot/cupcake-ssl-config.txt
    log_config "SSL configuration processed and removed"
fi


if [ -f /boot/cupcake-domain-config.txt ]; then
    log_config "Processing domain configuration..."
    source /boot/cupcake-domain-config.txt
    
    if [ -n "$CUPCAKE_DOMAIN" ]; then
        log_config "Setting custom domain: $CUPCAKE_DOMAIN"
        echo "CUPCAKE_DOMAIN=$CUPCAKE_DOMAIN" >> /etc/environment
        
        if [ "$CUPCAKE_ENABLE_LETSENCRYPT" = "true" ]; then
            log_config "Enabling Let's Encrypt"
            echo "CUPCAKE_ENABLE_LETSENCRYPT=true" >> /etc/environment
            echo "CUPCAKE_ADMIN_EMAIL=${CUPCAKE_ADMIN_EMAIL}" >> /etc/environment
        fi
    fi
    
    rm -f /boot/cupcake-domain-config.txt
    log_config "Domain configuration processed and removed"
fi


if [ -f /boot/cupcake-tunnel-config.txt ]; then
    log_config "Processing Cloudflare tunnel configuration..."
    source /boot/cupcake-tunnel-config.txt
    
    if [ "$CUPCAKE_CLOUDFLARE_TUNNEL" = "true" ]; then
        log_config "Enabling Cloudflare tunnel"
        echo "CUPCAKE_CLOUDFLARE_TUNNEL=true" >> /etc/environment
        echo "CUPCAKE_TUNNEL_TOKEN=$CUPCAKE_TUNNEL_TOKEN" >> /etc/environment
        echo "CUPCAKE_TUNNEL_DOMAIN=$CUPCAKE_TUNNEL_DOMAIN" >> /etc/environment
    fi
    
    rm -f /boot/cupcake-tunnel-config.txt
    log_config "Cloudflare tunnel configuration processed and removed"
fi

log_config "Manual configuration processing completed"
MANUAL_CONFIG_EOF

chmod +x "${ROOTFS_DIR}/usr/local/bin/cupcake-manual-config.sh"


mkdir -p "${ROOTFS_DIR}/usr/lib/raspberrypi-sys-mods"
cat > "${ROOTFS_DIR}/usr/lib/raspberrypi-sys-mods/cupcake_imager_custom" << 'IMAGER_CUSTOM_EOF'
#!/bin/bash



case "$1" in
    set_hostname)
        
        echo "$2" > /etc/hostname
        sed -i "s/127.0.1.1.*/127.0.1.1\t$2/g" /etc/hosts
        
        
        if [ -f /opt/cupcake/config/nginx/cupcake.conf ]; then
            sed -i "s/server_name .*/server_name $2.local;/g" /opt/cupcake/config/nginx/cupcake.conf
        fi
        ;;
    set_cupcake_admin)
        
        echo "CUPCAKE_ADMIN_USER=$2" >> /etc/environment
        ;;
    set_cupcake_admin_password)
        
        echo "CUPCAKE_ADMIN_PASSWORD=$2" >> /etc/environment
        ;;
esac
IMAGER_CUSTOM_EOF

chmod +x "${ROOTFS_DIR}/usr/lib/raspberrypi-sys-mods/cupcake_imager_custom"


cat > "${ROOTFS_DIR}/usr/local/bin/cupcake-ssl-setup.sh" << 'SSL_SETUP_EOF'
#!/bin/bash



log_ssl() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] SSL: $1" | tee -a /var/log/cupcake-ssl.log
}


source /etc/environment

HOSTNAME=$(hostname)
SSL_DIR="/opt/cupcake/ssl"
NGINX_SSL_DIR="/etc/nginx/ssl"


mkdir -p "$SSL_DIR" "$NGINX_SSL_DIR"


generate_self_signed() {
    log_ssl "Generating self-signed certificate for $HOSTNAME.local"
    
    
    openssl genrsa -out "$SSL_DIR/cupcake.key" 2048
    
    
    openssl req -new -key "$SSL_DIR/cupcake.key" -out "$SSL_DIR/cupcake.csr" -subj "/C=${CUPCAKE_SSL_COUNTRY:-US}/ST=${CUPCAKE_SSL_STATE:-California}/L=${CUPCAKE_SSL_CITY:-Berkeley}/O=${CUPCAKE_SSL_ORG:-CUPCAKE Lab}/CN=$HOSTNAME.local"
    
    
    cat > "$SSL_DIR/cert_extensions.conf" <<EOF
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $HOSTNAME.local
DNS.2 = $HOSTNAME
DNS.3 = localhost
IP.1 = 127.0.0.1
EOF
    
    
    openssl x509 -req -days 365 -in "$SSL_DIR/cupcake.csr" -signkey "$SSL_DIR/cupcake.key" -out "$SSL_DIR/cupcake.crt" -extensions v3_req -extfile "$SSL_DIR/cert_extensions.conf"
    
    
    rm -f "$SSL_DIR/cert_extensions.conf"
    
    
    cp "$SSL_DIR/cupcake.crt" "$NGINX_SSL_DIR/"
    cp "$SSL_DIR/cupcake.key" "$NGINX_SSL_DIR/"
    
    
    chown -R root:root "$SSL_DIR" "$NGINX_SSL_DIR"
    chmod 600 "$SSL_DIR/cupcake.key" "$NGINX_SSL_DIR/cupcake.key"
    chmod 644 "$SSL_DIR/cupcake.crt" "$NGINX_SSL_DIR/cupcake.crt"
    
    log_ssl "Self-signed certificate generated successfully"
}


setup_letsencrypt() {
    log_ssl "Setting up Let's Encrypt for domain: $CUPCAKE_DOMAIN"
    
    
    if ! command -v certbot &> /dev/null; then
        log_ssl "Installing certbot..."
        apt-get update
        apt-get install -y certbot python3-certbot-nginx
    fi
    
    
    certbot --nginx -d "$CUPCAKE_DOMAIN" --non-interactive --agree-tos --email "$CUPCAKE_ADMIN_EMAIL"
    
    
    (crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | crontab -
    
    log_ssl "Let's Encrypt certificate configured successfully"
}


setup_cloudflare_tunnel() {
    log_ssl "Setting up Cloudflare tunnel for domain: $CUPCAKE_TUNNEL_DOMAIN"
    
    
    curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
    dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
    
    
    cat > /etc/systemd/system/cloudflare-tunnel.service << 'TUNNEL_EOF'
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token ${CUPCAKE_TUNNEL_TOKEN}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
TUNNEL_EOF
    
    
    systemctl enable cloudflare-tunnel.service
    systemctl start cloudflare-tunnel.service
    
    log_ssl "Cloudflare tunnel configured successfully"
}


if [ "$CUPCAKE_ENABLE_SSL" = "true" ]; then
    generate_self_signed
    
    
    cat > /etc/nginx/sites-available/cupcake-ssl << 'NGINX_SSL_EOF'
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name _;
    
    ssl_certificate /etc/nginx/ssl/cupcake.crt;
    ssl_certificate_key /etc/nginx/ssl/cupcake.key;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    root /opt/cupcake/frontend;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /cert {
        alias /opt/cupcake/ssl/cupcake.crt;
        add_header Content-Type application/x-x509-ca-cert;
        add_header Content-Disposition 'attachment; filename="cupcake-$hostname.crt"';
    }
}
NGINX_SSL_EOF
    
    
    ln -sf /etc/nginx/sites-available/cupcake-ssl /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
elif [ "$CUPCAKE_ENABLE_LETSENCRYPT" = "true" ]; then
    setup_letsencrypt
    
elif [ "$CUPCAKE_CLOUDFLARE_TUNNEL" = "true" ]; then
    setup_cloudflare_tunnel
    
fi


systemctl restart nginx

log_ssl "SSL setup completed"
SSL_SETUP_EOF

chmod +x "${ROOTFS_DIR}/usr/local/bin/cupcake-ssl-setup.sh"


cat > "${ROOTFS_DIR}/etc/systemd/system/cupcake-ssl-setup.service" << 'SSL_SERVICE_EOF'
[Unit]
Description=CUPCAKE SSL Setup
After=network.target nginx.service
Wants=nginx.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/cupcake-ssl-setup.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SSL_SERVICE_EOF


on_chroot << 'CHROOT_EOF'
systemctl enable cupcake-ssl-setup.service
CHROOT_EOF

log "CUPCAKE stage completed successfully"
EOF

    chmod +x "$stage_dir/00-install-cupcake/01-run.sh"
    
    
    mkdir -p "$stage_dir/02-boot-config"
    
    cat > "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
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

EOF

    
    if [[ "$PI_MODEL" == "pi4" ]]; then
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTEOF'


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
BOOTEOF
EOF
    else
        cat >> "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh" << 'EOF'
cat >> "${BOOT_CONFIG}" << 'BOOTEOF'


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
BOOTEOF
EOF
    fi
    
    chmod +x "$stage_dir/02-boot-config/01-${PI_MODEL}-config.sh"

    log "Custom CUPCAKE stage created with $PI_MODEL optimizations"
}


main() {
    log "Starting CUPCAKE Pi image build for $PI_MODEL..."

    
    check_prerequisites
    setup_pi_gen
    prepare_build
    configure_pi_gen
    create_custom_stage

    
    log "Starting pi-gen Docker build process..."
    cd "$PI_GEN_DIR"

    
    
    
    
    
    
    log "Using Docker-based pi-gen build (resolves QEMU/timing issues)"
    
    
    export PRESERVE_CONTAINER=0
    export CONTINUE=0
    
    
    sudo ./build-docker.sh

    log "Pi image build completed successfully!"
    log "Output images available in: $PI_GEN_DIR/deploy/"

    
    if [ -d "$PI_GEN_DIR/deploy" ]; then
        info "Generated images:"
        ls -la "$PI_GEN_DIR/deploy/"*.img* 2>/dev/null || true
        ls -la "$PI_GEN_DIR/deploy/"*.zip 2>/dev/null || true
    fi
}


main "$@"
