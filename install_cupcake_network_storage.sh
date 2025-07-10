#!/bin/bash

# Network Storage Extension for CUPCAKE Installation Scripts
# This script adds network storage support to existing installations

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo "=== CUPCAKE Network Storage Configuration ==="
echo "This script helps configure network storage for existing CUPCAKE deployments."
echo

# Detect existing deployment
if [[ -f "docker-compose.yml" ]]; then
    DEPLOYMENT_DIR="."
elif [[ -f "cupcake_deployment/docker-compose.yml" ]]; then
    DEPLOYMENT_DIR="cupcake_deployment"
elif [[ -f "cupcake_cloudflare_deployment/docker-compose.yml" ]]; then
    DEPLOYMENT_DIR="cupcake_cloudflare_deployment"
else
    echo "No existing CUPCAKE deployment found. Please run the main installation script first."
    exit 1
fi

log_info "Found deployment in: $DEPLOYMENT_DIR"

# Storage type selection
echo "Choose network storage type:"
echo "1) NFS (Network File System)"
echo "2) CIFS/SMB (Windows/Samba shares)"
echo "3) S3-compatible object storage"
echo "4) Convert back to local storage"
read -p "Choose storage type [1]: " STORAGE_TYPE
STORAGE_TYPE=${STORAGE_TYPE:-1}

case $STORAGE_TYPE in
    1)
        log_info "=== NFS Configuration ==="
        echo "Example: NFS server at 192.168.1.100 with exports:"
        echo "  /exports/cupcake/media (for user uploads)"
        echo "  /exports/cupcake/static (for Django static files)"
        echo
        read -p "NFS server IP/hostname: " NFS_SERVER
        read -p "Media export path: " NFS_MEDIA_PATH
        read -p "Static export path: " NFS_STATIC_PATH
        read -p "NFS version [4]: " NFS_VERSION
        NFS_VERSION=${NFS_VERSION:-4}
        
        # Test NFS connectivity
        log_info "Testing NFS connectivity..."
        if command -v showmount &> /dev/null; then
            if showmount -e "$NFS_SERVER" | grep -q "$NFS_MEDIA_PATH"; then
                log_success "NFS export found: $NFS_MEDIA_PATH"
            else
                log_warning "Could not verify NFS export. Continuing anyway."
            fi
        else
            log_warning "showmount not available. Cannot test NFS connectivity."
        fi
        
        # Generate NFS docker-compose volumes
        cat > "$DEPLOYMENT_DIR/volumes-network.yml" << EOF
# NFS Network Storage Configuration
# Include this in your docker-compose.yml volumes section

volumes:
  media_nfs:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=${NFS_SERVER},nfsvers=${NFS_VERSION},rsize=1048576,wsize=1048576,hard,intr"
      device: "${NFS_MEDIA_PATH}"
  static_nfs:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=${NFS_SERVER},nfsvers=${NFS_VERSION},rsize=1048576,wsize=1048576,hard,intr"
      device: "${NFS_STATIC_PATH}"
EOF
        
        VOLUME_REPLACE="s|./media:/media/|media_nfs:/media/|g; s|./staticfiles:/static/|static_nfs:/static/|g; s|./media:/app/media/|media_nfs:/app/media/|g; s|./staticfiles:/app/staticfiles/|static_nfs:/app/staticfiles/|g"
        ;;
        
    2)
        log_info "=== CIFS/SMB Configuration ==="
        echo "Example: SMB server at //192.168.1.100/cupcake with:"
        echo "  subdirectory 'media' for user uploads"
        echo "  subdirectory 'static' for Django static files"
        echo
        read -p "SMB server path (e.g., //192.168.1.100/cupcake): " SMB_SERVER
        read -p "Username: " SMB_USERNAME
        read -s -p "Password: " SMB_PASSWORD
        echo
        read -p "Domain [optional]: " SMB_DOMAIN
        
        # Test SMB connectivity
        log_info "Testing SMB connectivity..."
        if command -v smbclient &> /dev/null; then
            if smbclient -L "$SMB_SERVER" -U "$SMB_USERNAME%$SMB_PASSWORD" &> /dev/null; then
                log_success "SMB server accessible"
            else
                log_warning "Could not connect to SMB server. Check credentials."
            fi
        else
            log_warning "smbclient not available. Cannot test SMB connectivity."
        fi
        
        SMB_CREDENTIALS="username=${SMB_USERNAME},password=${SMB_PASSWORD}"
        if [[ -n "$SMB_DOMAIN" ]]; then
            SMB_CREDENTIALS="${SMB_CREDENTIALS},domain=${SMB_DOMAIN}"
        fi
        
        # Generate CIFS docker-compose volumes
        cat > "$DEPLOYMENT_DIR/volumes-network.yml" << EOF
# CIFS/SMB Network Storage Configuration
# Include this in your docker-compose.yml volumes section

volumes:
  media_cifs:
    driver: local
    driver_opts:
      type: cifs
      o: "${SMB_CREDENTIALS},uid=33,gid=33,iocharset=utf8"
      device: "${SMB_SERVER}/media"
  static_cifs:
    driver: local
    driver_opts:
      type: cifs
      o: "${SMB_CREDENTIALS},uid=33,gid=33,iocharset=utf8"
      device: "${SMB_SERVER}/static"
EOF
        
        VOLUME_REPLACE="s|./media:/media/|media_cifs:/media/|g; s|./staticfiles:/static/|static_cifs:/static/|g; s|./media:/app/media/|media_cifs:/app/media/|g; s|./staticfiles:/app/staticfiles/|static_cifs:/app/staticfiles/|g"
        ;;
        
    3)
        log_info "=== S3 Object Storage Configuration ==="
        echo "Compatible with AWS S3, MinIO, DigitalOcean Spaces, etc."
        echo
        read -p "S3 endpoint URL: " S3_ENDPOINT
        read -p "Bucket name: " S3_BUCKET
        read -p "Access key ID: " S3_ACCESS_KEY
        read -s -p "Secret access key: " S3_SECRET_KEY
        echo
        read -p "Region [us-east-1]: " S3_REGION
        S3_REGION=${S3_REGION:-us-east-1}
        
        # Test S3 connectivity
        log_info "Testing S3 connectivity..."
        if command -v aws &> /dev/null; then
            AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" aws s3 ls "s3://$S3_BUCKET" --endpoint-url "$S3_ENDPOINT" --region "$S3_REGION" &> /dev/null
            if [[ $? -eq 0 ]]; then
                log_success "S3 bucket accessible"
            else
                log_warning "Could not access S3 bucket. Check credentials and permissions."
            fi
        else
            log_warning "AWS CLI not available. Cannot test S3 connectivity."
        fi
        
        # Generate S3 docker-compose configuration
        cat > "$DEPLOYMENT_DIR/volumes-network.yml" << EOF
# S3 Object Storage Configuration
# Add this s3fs service to your docker-compose.yml

  s3fs:
    image: efrecon/s3fs:1.91
    privileged: true
    environment:
      - AWS_S3_ACCESS_KEY_ID=${S3_ACCESS_KEY}
      - AWS_S3_SECRET_ACCESS_KEY=${S3_SECRET_KEY}
      - AWS_S3_BUCKET=${S3_BUCKET}
      - AWS_S3_URL=${S3_ENDPOINT}
      - AWS_S3_REGION=${S3_REGION}
      - S3FS_ARGS=-o uid=33,gid=33,allow_other,use_cache=/tmp
    volumes:
      - media_s3:/mnt/s3:rshared
    networks:
      - cc-net
    restart: always

volumes:
  media_s3:
    external: true
  static_s3:
    external: true
EOF

        cat > "$DEPLOYMENT_DIR/s3-setup.sh" << EOF
#!/bin/bash
# S3 Storage Setup Script

# Create external volumes
docker volume create media_s3
docker volume create static_s3

# Start s3fs service
docker-compose up -d s3fs

echo "S3 storage setup complete. Restart your CUPCAKE services."
EOF
        chmod +x "$DEPLOYMENT_DIR/s3-setup.sh"
        
        VOLUME_REPLACE="s|./media:/media/|media_s3:/media/|g; s|./staticfiles:/static/|static_s3:/static/|g; s|./media:/app/media/|media_s3:/app/media/|g; s|./staticfiles:/app/staticfiles/|media_s3:/app/staticfiles/|g"
        ;;
        
    4)
        log_info "=== Converting back to local storage ==="
        
        # Backup data first
        read -p "Backup network storage to local first? [Y/n]: " BACKUP_FIRST
        if [[ "$BACKUP_FIRST" != "n" ]]; then
            log_info "Creating backup of network storage..."
            mkdir -p "$DEPLOYMENT_DIR/backup/media" "$DEPLOYMENT_DIR/backup/staticfiles"
            
            if docker-compose -f "$DEPLOYMENT_DIR/docker-compose.yml" exec cc cp -r /app/media/* /backup/media/ 2>/dev/null; then
                log_success "Media files backed up"
            else
                log_warning "Could not backup media files"
            fi
        fi
        
        VOLUME_REPLACE="s|media_[a-z]*:/media/|./media:/media/|g; s|static_[a-z]*:/static/|./staticfiles:/static/|g; s|media_[a-z]*:/app/media/|./media:/app/media/|g; s|[a-z]*_[a-z]*:/app/staticfiles/|./staticfiles:/app/staticfiles/|g"
        
        # Remove network storage configuration
        rm -f "$DEPLOYMENT_DIR/volumes-network.yml" "$DEPLOYMENT_DIR/s3-setup.sh"
        ;;
esac

# Apply volume changes to docker-compose.yml
if [[ "$STORAGE_TYPE" != "4" ]]; then
    log_info "Updating docker-compose.yml with network storage configuration..."
    
    # Backup original
    cp "$DEPLOYMENT_DIR/docker-compose.yml" "$DEPLOYMENT_DIR/docker-compose.yml.backup"
    
    # Apply volume replacements
    sed "$VOLUME_REPLACE" "$DEPLOYMENT_DIR/docker-compose.yml.backup" > "$DEPLOYMENT_DIR/docker-compose.yml"
    
    # Add network volumes to the end if not S3
    if [[ "$STORAGE_TYPE" != "3" ]]; then
        echo "" >> "$DEPLOYMENT_DIR/docker-compose.yml"
        cat "$DEPLOYMENT_DIR/volumes-network.yml" | grep -A 20 "volumes:" >> "$DEPLOYMENT_DIR/docker-compose.yml"
    fi
    
    log_success "Docker Compose configuration updated"
else
    log_info "Reverting to local storage..."
    
    # Backup and revert
    cp "$DEPLOYMENT_DIR/docker-compose.yml" "$DEPLOYMENT_DIR/docker-compose.yml.backup"
    sed "$VOLUME_REPLACE" "$DEPLOYMENT_DIR/docker-compose.yml.backup" > "$DEPLOYMENT_DIR/docker-compose.yml"
    
    log_success "Reverted to local storage"
fi

echo
echo "=== Network Storage Configuration Complete ==="
echo

case $STORAGE_TYPE in
    1)
        echo "NFS Configuration:"
        echo "  Server: $NFS_SERVER"
        echo "  Media: $NFS_MEDIA_PATH"
        echo "  Static: $NFS_STATIC_PATH"
        echo
        echo "Make sure your NFS server is running and exports are accessible."
        ;;
    2)
        echo "CIFS/SMB Configuration:"
        echo "  Server: $SMB_SERVER"
        echo "  Credentials configured for user: $SMB_USERNAME"
        echo
        echo "Make sure your SMB server is running and shares are accessible."
        ;;
    3)
        echo "S3 Object Storage Configuration:"
        echo "  Endpoint: $S3_ENDPOINT"
        echo "  Bucket: $S3_BUCKET"
        echo "  Region: $S3_REGION"
        echo
        echo "Run: cd $DEPLOYMENT_DIR && ./s3-setup.sh"
        echo "Then: docker-compose up -d"
        ;;
    4)
        echo "Local Storage:"
        echo "  Reverted to bind mounts: ./media and ./staticfiles"
        ;;
esac

echo
echo "Next steps:"
echo "1. Review the updated docker-compose.yml"
echo "2. Stop current services: docker-compose down"
echo "3. Start services: docker-compose up -d"
echo "4. Verify storage access in the application"
echo
echo "Backup saved as: $DEPLOYMENT_DIR/docker-compose.yml.backup"