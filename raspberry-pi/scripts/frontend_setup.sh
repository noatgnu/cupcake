#!/bin/bash

# CUPCAKE Pi Build - Frontend Setup
# Handles frontend building and preparation

# Source logging functions
source "$(dirname "${BASH_SOURCE[0]}")/logging.sh"

setup_frontend() {
    log "Setting up CUPCAKE frontend for Pi deployment..."
    
    local files_dir="$1"
    if [ -z "$files_dir" ]; then
        error "Files directory not provided to setup_frontend"
    fi
    
    # Check if we should use pre-built frontend
    if [ "$USE_PREBUILT_FRONTEND" = "1" ]; then
        log "Using pre-built frontend from ./frontend-dist"
        
        if [ -d "./frontend-dist" ]; then
            log "Copying pre-built frontend to stage..."
            cp -r ./frontend-dist "$files_dir/opt/cupcake/frontend"
            log "✓ Pre-built frontend copied successfully"
            return 0
        else
            warn "Pre-built frontend not found, falling back to build process"
        fi
    fi
    
    # Build frontend using the prebuild script
    log "Building frontend using prebuild script..."
    
    # Ensure prebuild script exists and is executable
    if [ ! -f "./prebuild-frontend.sh" ]; then
        error "prebuild-frontend.sh not found"
    fi
    
    chmod +x ./prebuild-frontend.sh
    
    # Run the prebuild script with Pi-specific hostname
    local pi_hostname="${HOSTNAME:-cupcake-pi}.local"
    if ! bash ./prebuild-frontend.sh --hostname "$pi_hostname" --output-dir ./frontend-build-output; then
        error "Frontend build failed"
    fi
    
    # Copy built frontend to stage
    if [ -d "./frontend-build-output" ]; then
        log "Copying built frontend to stage..."
        mkdir -p "$files_dir/opt/cupcake"
        cp -r ./frontend-build-output "$files_dir/opt/cupcake/frontend"
        
        # Clean up build output
        rm -rf ./frontend-build-output
        
        log "✓ Frontend built and copied successfully"
    else
        error "Frontend build output not found"
    fi
    
    # Create frontend service configuration
    create_frontend_service "$files_dir"
}

create_frontend_service() {
    local files_dir="$1"
    
    log "Creating frontend service configuration..."
    
    # Create nginx configuration for frontend
    mkdir -p "$files_dir/etc/nginx/sites-available"
    mkdir -p "$files_dir/etc/nginx/sites-enabled"
    
    cat > "$files_dir/etc/nginx/sites-available/cupcake-frontend" <<'EOF'
server {
    listen 80;
    server_name _;
    
    root /opt/cupcake/frontend;
    index index.html;
    
    # Handle Angular routing
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Static files caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
EOF
    
    # Enable the site
    ln -sf /etc/nginx/sites-available/cupcake-frontend "$files_dir/etc/nginx/sites-enabled/"
    
    # Remove default nginx site
    rm -f "$files_dir/etc/nginx/sites-enabled/default"
    
    log "Frontend service configuration created"
}

verify_frontend_build() {
    local files_dir="$1"
    local frontend_dir="$files_dir/opt/cupcake/frontend"
    
    log "Verifying frontend build..."
    
    if [ ! -d "$frontend_dir" ]; then
        error "Frontend directory not found: $frontend_dir"
    fi
    
    if [ ! -f "$frontend_dir/index.html" ]; then
        error "Frontend index.html not found"
    fi
    
    # Check for essential frontend files
    local essential_files=(
        "index.html"
        "main*.js"
        "polyfills*.js"
        "runtime*.js"
    )
    
    for pattern in "${essential_files[@]}"; do
        if ! ls "$frontend_dir"/$pattern 1> /dev/null 2>&1; then
            warn "Frontend file pattern not found: $pattern"
        fi
    done
    
    # Calculate frontend size
    local size_kb=$(du -sk "$frontend_dir" | cut -f1)
    local size_mb=$((size_kb / 1024))
    
    info "Frontend verification complete - Size: ${size_mb}MB"
    
    if [ "$size_mb" -lt 1 ]; then
        warn "Frontend seems unusually small (${size_mb}MB) - check build"
    fi
    
    log "✓ Frontend build verified successfully"
}