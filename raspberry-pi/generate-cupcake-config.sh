#!/bin/bash

# CUPCAKE Configuration Generator
# Creates configuration files for manual setup of CUPCAKE Pi image

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

# Function to prompt for input with default
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    
    echo -n "$prompt [$default]: "
    read -r input
    if [ -z "$input" ]; then
        eval "$var_name=\"$default\""
    else
        eval "$var_name=\"$input\""
    fi
}

# Function to prompt for password
prompt_password() {
    local prompt="$1"
    local var_name="$2"
    
    echo -n "$prompt: "
    read -rs password
    echo
    eval "$var_name=\"$password\""
}

# Show header
cat << 'EOF'
╔═══════════════════════════════════════════════════════╗
║              CUPCAKE Configuration Generator          ║
║                                                       ║
║  This tool helps you create configuration files      ║
║  for customizing your CUPCAKE Pi image deployment    ║
╚═══════════════════════════════════════════════════════╝

EOF

info "This tool will create configuration files for your CUPCAKE Pi deployment"
echo "You can either use Raspberry Pi Imager's advanced options (recommended)"
echo "or create manual configuration files for advanced customization."
echo

# Ask configuration method
echo "Configuration methods:"
echo "1) Use Raspberry Pi Imager advanced options (recommended)"
echo "2) Create manual configuration files" 
echo "3) Show example configurations and exit"
echo
read -p "Choose method (1-3): " method

case "$method" in
    1)
        cat << 'EOF'

🎯 RECOMMENDED: Raspberry Pi Imager Advanced Options

1. Open Raspberry Pi Imager
2. Select your CUPCAKE image file
3. Click the gear icon (⚙️) or press Ctrl+Shift+X
4. Configure these settings:

   📝 Hostname: your-lab-name (e.g., cupcake-lab, biolab-pi)
   👤 Username: your-username (becomes CUPCAKE admin)
   🔐 Password: your-password (becomes CUPCAKE admin password)
   🌐 WiFi: Configure if needed
   🔑 SSH: Enable with password authentication

5. Save and flash your SD card
6. Boot your Pi - CUPCAKE will be ready!

Your CUPCAKE will be accessible at:
• Web: http://your-hostname.local
• SSH: ssh your-username@your-hostname.local
• Admin: Login with your-username/your-password

EOF
        exit 0
        ;;
    2)
        info "Creating manual configuration files..."
        ;;
    3)
        cat << 'EOF'

📋 EXAMPLE CONFIGURATIONS

Example cupcake-config.txt:
────────────────────────────
# CUPCAKE Admin Configuration
CUPCAKE_ADMIN_USER=labadmin
CUPCAKE_ADMIN_PASSWORD=secure_password_123
CUPCAKE_ADMIN_EMAIL=labadmin@mylab.local

# System Configuration
CUPCAKE_HOSTNAME=mylab-pi

# Database Configuration (optional)
CUPCAKE_DB_PASSWORD=db_secure_password

# Feature Flags (optional)
CUPCAKE_ENABLE_REGISTRATION=false
CUPCAKE_DEBUG_MODE=false

Example cupcake-ssh-keys.txt:
────────────────────────────
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ... user@laptop
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... user@desktop

Usage:
1. Create these files after flashing with Raspberry Pi Imager
2. Place them in the boot partition (visible in Windows/macOS)
3. Boot your Pi - files will be processed and removed for security

EOF
        exit 0
        ;;
    *)
        error "Invalid choice. Please run the script again."
        ;;
esac

# Collect configuration information
echo
info "Collecting CUPCAKE configuration information..."
echo "Press Enter to use defaults, or type custom values."
echo

# Admin user configuration
prompt_with_default "CUPCAKE admin username" "admin" "ADMIN_USER"
prompt_password "CUPCAKE admin password" "ADMIN_PASSWORD"

if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="cupcake123"
    warn "Using default password: cupcake123 (CHANGE THIS AFTER SETUP!)"
fi

prompt_with_default "CUPCAKE admin email" "${ADMIN_USER}@cupcake.local" "ADMIN_EMAIL"

# System configuration
prompt_with_default "Hostname (without .local)" "cupcake-pi" "HOSTNAME"
prompt_with_default "Database password" "cupcake_db_$(date +%s)" "DB_PASSWORD"

# Feature configuration
echo
info "Optional feature configuration:"
prompt_with_default "Enable user registration (true/false)" "false" "ENABLE_REGISTRATION"
prompt_with_default "Enable debug mode (true/false)" "false" "DEBUG_MODE"

# SSH key configuration
echo
read -p "Do you want to configure SSH keys? (y/N): " setup_ssh
if [[ "$setup_ssh" =~ ^[Yy]$ ]]; then
    echo "Please provide your SSH public keys (one per line, empty line to finish):"
    SSH_KEYS=""
    while true; do
        read -r key
        if [ -z "$key" ]; then
            break
        fi
        SSH_KEYS="$SSH_KEYS$key\n"
    done
fi

# Output directory
OUTPUT_DIR="./cupcake-config-files"
mkdir -p "$OUTPUT_DIR"

# Generate cupcake-config.txt
log "Generating cupcake-config.txt..."
cat > "$OUTPUT_DIR/cupcake-config.txt" << EOF
# CUPCAKE Custom Configuration
# Generated on $(date)
# Place this file in the boot partition after flashing

# Admin user configuration
CUPCAKE_ADMIN_USER=$ADMIN_USER
CUPCAKE_ADMIN_PASSWORD=$ADMIN_PASSWORD
CUPCAKE_ADMIN_EMAIL=$ADMIN_EMAIL

# System configuration
CUPCAKE_HOSTNAME=$HOSTNAME

# Database configuration
CUPCAKE_DB_PASSWORD=$DB_PASSWORD

# Feature flags
CUPCAKE_ENABLE_REGISTRATION=$ENABLE_REGISTRATION
CUPCAKE_DEBUG_MODE=$DEBUG_MODE

# Security note: This file will be automatically removed after processing
EOF

# Generate SSH keys file if provided
if [ -n "$SSH_KEYS" ]; then
    log "Generating cupcake-ssh-keys.txt..."
    echo -e "$SSH_KEYS" > "$OUTPUT_DIR/cupcake-ssh-keys.txt"
fi

# Generate instructions
log "Generating setup instructions..."
cat > "$OUTPUT_DIR/SETUP_INSTRUCTIONS.txt" << EOF
CUPCAKE Pi Image Setup Instructions
Generated on $(date)

CONFIGURATION FILES CREATED:
- cupcake-config.txt: Main configuration file
$([ -n "$SSH_KEYS" ] && echo "- cupcake-ssh-keys.txt: SSH public keys")

SETUP STEPS:
1. Flash your SD card with Raspberry Pi Imager using the CUPCAKE image
2. After flashing, mount the SD card on your computer
3. Copy the configuration files to the boot partition (the one visible in Windows/macOS):
   - Copy cupcake-config.txt to the root of the boot partition
$([ -n "$SSH_KEYS" ] && echo "   - Copy cupcake-ssh-keys.txt to the root of the boot partition")
4. Safely eject the SD card
5. Insert into your Raspberry Pi and boot

AFTER BOOT:
- Your Pi will be accessible at: http://$HOSTNAME.local
- SSH access: ssh $ADMIN_USER@$HOSTNAME.local
- CUPCAKE admin login: $ADMIN_USER / [your password]
- Configuration files will be automatically processed and removed for security

SECURITY NOTES:
- Change default passwords immediately after setup
- The configuration files contain sensitive information
- Files are automatically deleted after processing
- Consider using SSH keys instead of passwords for SSH access

TROUBLESHOOTING:
- If hostname doesn't resolve, try the IP address
- Check service status: sudo systemctl status cupcake-*
- View logs: sudo journalctl -u cupcake-* -f
- Configuration logs: /var/log/cupcake-config.log
EOF

# Create a README
cat > "$OUTPUT_DIR/README.md" << EOF
# CUPCAKE Pi Configuration Files

This directory contains configuration files for your CUPCAKE Pi deployment.

## Quick Setup

1. **Flash Image**: Use Raspberry Pi Imager to flash the CUPCAKE image to your SD card
2. **Copy Files**: Copy \`cupcake-config.txt\` (and optionally \`cupcake-ssh-keys.txt\`) to the boot partition
3. **Boot Pi**: Insert SD card and power on your Raspberry Pi
4. **Access CUPCAKE**: Navigate to \`http://$HOSTNAME.local\`

## Security

⚠️ **Important**: These files contain sensitive information including passwords. 
Keep them secure and delete them after use. The Pi will automatically remove them after processing.

## Configuration Summary

- **Hostname**: $HOSTNAME.local
- **Admin User**: $ADMIN_USER
- **Web Access**: http://$HOSTNAME.local
- **SSH Access**: ssh $ADMIN_USER@$HOSTNAME.local

For detailed instructions, see \`SETUP_INSTRUCTIONS.txt\`.
EOF

# Summary
echo
log "Configuration files generated successfully!"
info "Files created in: $OUTPUT_DIR/"
echo
echo "Files created:"
echo "├── cupcake-config.txt         # Main configuration"
[ -n "$SSH_KEYS" ] && echo "├── cupcake-ssh-keys.txt       # SSH public keys"
echo "├── SETUP_INSTRUCTIONS.txt    # Detailed setup steps"
echo "└── README.md                 # Quick reference"
echo
info "Next steps:"
echo "1. Flash your CUPCAKE image with Raspberry Pi Imager"
echo "2. Copy cupcake-config.txt to the boot partition of the SD card"
[ -n "$SSH_KEYS" ] && echo "3. Copy cupcake-ssh-keys.txt to the boot partition"
echo "$([ -n "$SSH_KEYS" ] && echo "4" || echo "3"). Boot your Pi and access CUPCAKE at http://$HOSTNAME.local"
echo
warn "Keep these configuration files secure - they contain passwords!"
info "The files will be automatically removed from the Pi after processing."