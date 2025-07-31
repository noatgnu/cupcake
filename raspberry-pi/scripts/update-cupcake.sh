#!/bin/bash
set -e

# CUPCAKE Raspberry Pi Update Script
# This script provides comprehensive update functionality for CUPCAKE Raspberry Pi installations

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CUPCAKE_DIR="/opt/cupcake"
CUPCAKE_USER="cupcake"
BACKUP_DIR="/opt/cupcake/backups"
LOG_FILE="/var/log/cupcake-update.log"
GIT_REPO_URL="https://github.com/Toasterson/cupcake.git"
UPDATE_LOCK_FILE="/tmp/cupcake-update.lock"

# Functions
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] INFO:${NC} $1" | tee -a "$LOG_FILE"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_lock() {
    if [ -f "$UPDATE_LOCK_FILE" ]; then
        log_error "Update already in progress (lock file exists: $UPDATE_LOCK_FILE)"
        log_error "If no update is running, remove the lock file: sudo rm $UPDATE_LOCK_FILE"
        exit 1
    fi
    
    # Create lock file
    touch "$UPDATE_LOCK_FILE"
    trap 'rm -f "$UPDATE_LOCK_FILE"' EXIT
}

show_help() {
    cat << EOF
CUPCAKE Raspberry Pi Update Script

Usage: $0 [OPTIONS] [COMMAND]

COMMANDS:
    system          Update system packages only
    cupcake         Update CUPCAKE application only
    full            Update both system and CUPCAKE (default)
    ontology        Update ontology databases only
    backup          Create backup of current installation
    restore         Restore from backup (interactive)
    status          Show current version information

OPTIONS:
    --branch BRANCH     Update to specific git branch (default: master)
    --backup           Create backup before update
    --no-restart       Don't restart services after update
    --force            Force update even if versions are same
    --dry-run          Show what would be updated without making changes
    --help             Show this help message

EXAMPLES:
    sudo $0                    # Full update with automatic backup
    sudo $0 system             # Update system packages only
    sudo $0 cupcake --branch dev  # Update CUPCAKE to dev branch
    sudo $0 --dry-run          # Preview what would be updated
    sudo $0 backup             # Create backup only
    sudo $0 status             # Show version information

EOF
}

get_current_version() {
    if [ -d "$CUPCAKE_DIR/app/.git" ]; then
        cd "$CUPCAKE_DIR/app"
        git rev-parse --short HEAD 2>/dev/null || echo "unknown"
    else
        echo "not-git"
    fi
}

get_current_branch() {
    if [ -d "$CUPCAKE_DIR/app/.git" ]; then
        cd "$CUPCAKE_DIR/app"
        git branch --show-current 2>/dev/null || echo "unknown"
    else
        echo "not-git"
    fi
}

check_internet() {
    log_info "Checking internet connectivity..."
    if ! ping -c 1 google.com &> /dev/null; then
        log_error "No internet connection available"
        exit 1
    fi
    log "Internet connectivity confirmed"
}

create_backup() {
    log "Creating backup of current CUPCAKE installation..."
    
    # Create backup directory
    mkdir -p "$BACKUP_DIR"
    
    # Generate backup filename with timestamp
    BACKUP_NAME="cupcake-backup-$(date +%Y%m%d-%H%M%S)"
    BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"
    
    # Create backup directory
    mkdir -p "$BACKUP_PATH"
    
    # Backup application files
    log_info "Backing up application files..."
    if [ -d "$CUPCAKE_DIR/app" ]; then
        cp -r "$CUPCAKE_DIR/app" "$BACKUP_PATH/" || {
            log_error "Failed to backup application files"
            return 1
        }
    fi
    
    # Backup configuration files
    log_info "Backing up configuration files..."
    mkdir -p "$BACKUP_PATH/config"
    
    # Backup nginx configuration
    if [ -f "/etc/nginx/sites-available/cupcake" ]; then
        cp "/etc/nginx/sites-available/cupcake" "$BACKUP_PATH/config/"
    fi
    
    # Backup systemd services
    cp /etc/systemd/system/cupcake-*.service "$BACKUP_PATH/config/" 2>/dev/null || true
    
    # Backup environment file
    if [ -f "$CUPCAKE_DIR/app/.env" ]; then
        cp "$CUPCAKE_DIR/app/.env" "$BACKUP_PATH/config/"
    fi
    
    # Create database backup
    log_info "Backing up PostgreSQL database..."
    if systemctl is-active --quiet postgresql; then
        su - postgres -c "pg_dump cupcake" > "$BACKUP_PATH/database-backup.sql" 2>/dev/null || {
            log_warning "Failed to create database backup"
        }
    fi
    
    # Create backup manifest
    cat > "$BACKUP_PATH/backup-info.txt" << EOF
CUPCAKE Backup Information
========================
Backup Date: $(date)
Backup Path: $BACKUP_PATH
Git Commit: $(get_current_version)
Git Branch: $(get_current_branch)
System: $(uname -a)
Python Version: $(python3 --version 2>/dev/null || echo "Not found")
Node Version: $(node --version 2>/dev/null || echo "Not found")
EOF
    
    # Compress backup
    log_info "Compressing backup..."
    cd "$BACKUP_DIR"
    tar -czf "${BACKUP_NAME}.tar.gz" "$BACKUP_NAME" && rm -rf "$BACKUP_NAME"
    
    log "✅ Backup created: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
    echo "$BACKUP_DIR/${BACKUP_NAME}.tar.gz"
}

list_backups() {
    log_info "Available backups:"
    if [ -d "$BACKUP_DIR" ] && [ "$(ls -A "$BACKUP_DIR")" ]; then
        ls -la "$BACKUP_DIR"/*.tar.gz 2>/dev/null | while read -r line; do
            echo "  $line"
        done
    else
        log_info "No backups found"
    fi
}

restore_backup() {
    log "Starting backup restoration process..."
    
    list_backups
    
    echo
    read -p "Enter backup filename (without path): " backup_file
    
    if [ ! -f "$BACKUP_DIR/$backup_file" ]; then
        log_error "Backup file not found: $BACKUP_DIR/$backup_file"
        exit 1
    fi
    
    log_warning "This will overwrite the current CUPCAKE installation!"
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log "Restore cancelled by user"
        exit 0
    fi
    
    # Stop services
    log_info "Stopping CUPCAKE services..."
    systemctl stop cupcake-* 2>/dev/null || true
    systemctl stop nginx 2>/dev/null || true
    
    # Extract backup
    log_info "Extracting backup..."
    cd "$BACKUP_DIR"
    tar -xzf "$backup_file"
    
    backup_name=$(basename "$backup_file" .tar.gz)
    
    # Restore application files
    if [ -d "$backup_name/app" ]; then
        log_info "Restoring application files..."
        rm -rf "$CUPCAKE_DIR/app"
        cp -r "$backup_name/app" "$CUPCAKE_DIR/"
        chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/app"
    fi
    
    # Restore configuration files
    if [ -d "$backup_name/config" ]; then
        log_info "Restoring configuration files..."
        
        # Restore nginx config
        if [ -f "$backup_name/config/cupcake" ]; then
            cp "$backup_name/config/cupcake" "/etc/nginx/sites-available/"
        fi
        
        # Restore systemd services
        cp "$backup_name/config/cupcake-"*.service /etc/systemd/system/ 2>/dev/null || true
        systemctl daemon-reload
        
        # Restore environment file
        if [ -f "$backup_name/config/.env" ]; then
            cp "$backup_name/config/.env" "$CUPCAKE_DIR/app/"
            chown "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/app/.env"
        fi
    fi
    
    # Restore database
    if [ -f "$backup_name/database-backup.sql" ]; then
        log_info "Restoring database..."
        read -p "Restore database? This will overwrite current data (yes/no): " restore_db
        if [ "$restore_db" = "yes" ]; then
            su - postgres -c "dropdb cupcake" 2>/dev/null || true
            su - postgres -c "createdb -O cupcake cupcake"
            su - postgres -c "psql cupcake < $BACKUP_DIR/$backup_name/database-backup.sql" || {
                log_warning "Database restore failed"
            }
        fi
    fi
    
    # Cleanup
    rm -rf "$backup_name"
    
    # Restart services
    log_info "Starting services..."
    systemctl start postgresql nginx
    systemctl start cupcake-*
    
    log "✅ Restore completed successfully"
}

update_system() {
    log "Updating system packages..."
    
    # Update package list
    apt-get update || {
        log_error "Failed to update package list"
        exit 1
    }
    
    # Upgrade packages
    apt-get upgrade -y || {
        log_error "Failed to upgrade packages"
        exit 1
    }
    
    # Clean up
    apt-get autoremove -y
    apt-get autoclean
    
    log "✅ System packages updated successfully"
}

update_cupcake() {
    local branch="${1:-master}"
    local force_update="${2:-false}"
    
    log "Updating CUPCAKE application to branch: $branch"
    
    if [ ! -d "$CUPCAKE_DIR/app" ]; then
        log_error "CUPCAKE installation not found at $CUPCAKE_DIR/app"
        exit 1
    fi
    
    cd "$CUPCAKE_DIR/app"
    
    # Check if it's a git repository
    if [ ! -d ".git" ]; then
        log_error "CUPCAKE directory is not a git repository"
        log_info "Consider reinstalling CUPCAKE or cloning from repository"
        exit 1
    fi
    
    # Store current version
    current_version=$(get_current_version)
    current_branch=$(get_current_branch)
    
    log_info "Current version: $current_version (branch: $current_branch)"
    
    # Fetch latest changes
    log_info "Fetching latest changes..."
    sudo -u "$CUPCAKE_USER" git fetch origin || {
        log_error "Failed to fetch from remote repository"
        exit 1
    }
    
    # Switch to target branch if different
    if [ "$branch" != "$current_branch" ]; then
        log_info "Switching to branch: $branch"
        sudo -u "$CUPCAKE_USER" git checkout "$branch" || {
            log_error "Failed to switch to branch: $branch"
            exit 1
        }
    fi
    
    # Get latest version on target branch
    latest_version=$(sudo -u "$CUPCAKE_USER" git rev-parse --short "origin/$branch")
    
    log_info "Latest version: $latest_version"
    
    # Check if update is needed
    if [ "$current_version" = "$latest_version" ] && [ "$force_update" != "true" ]; then
        log "✅ CUPCAKE is already up to date"
        return 0
    fi
    
    # Stop services before update
    log_info "Stopping CUPCAKE services..."
    systemctl stop cupcake-* 2>/dev/null || true
    
    # Pull latest changes
    log_info "Pulling latest changes..."
    sudo -u "$CUPCAKE_USER" git pull origin "$branch" || {
        log_error "Failed to pull latest changes"
        exit 1
    }
    
    # Update Python dependencies
    log_info "Updating Python dependencies..."
    cd "$CUPCAKE_DIR/app"
    sudo -u "$CUPCAKE_USER" python3 -m pip install --upgrade pip
    sudo -u "$CUPCAKE_USER" python3 -m pip install -r requirements.txt --upgrade || {
        log_warning "Some Python dependencies failed to update"
    }
    
    # Update Node dependencies (if package.json exists)
    if [ -f "package.json" ]; then
        log_info "Updating Node.js dependencies..."
        sudo -u "$CUPCAKE_USER" npm install || {
            log_warning "Failed to update Node.js dependencies"
        }
        
        # Build frontend if needed
        if [ -f "angular.json" ] || [ -d "src" ]; then
            log_info "Building frontend..."
            sudo -u "$CUPCAKE_USER" npm run build || {
                log_warning "Frontend build failed"
            }
        fi
    fi
    
    # Run database migrations
    log_info "Running database migrations..."
    sudo -u "$CUPCAKE_USER" python3 manage.py migrate || {
        log_error "Database migrations failed"
        exit 1
    }
    
    # Collect static files
    log_info "Collecting static files..."
    sudo -u "$CUPCAKE_USER" python3 manage.py collectstatic --noinput || {
        log_warning "Static file collection failed"
    }
    
    # Update file permissions
    chown -R "$CUPCAKE_USER:$CUPCAKE_USER" "$CUPCAKE_DIR/app"
    
    new_version=$(get_current_version)
    log "✅ CUPCAKE updated from $current_version to $new_version"
}

update_ontology() {
    log "Updating ontology databases..."
    
    cd "$CUPCAKE_DIR/app"
    
    # Check available ontology commands
    available_commands=$(sudo -u "$CUPCAKE_USER" python3 manage.py help | grep "load_" | awk '{print $1}' | grep -E "(species|tissue|subcellular_location|human_disease|ms_term|ms_mod)" || true)
    
    if [ -z "$available_commands" ]; then
        log_warning "No ontology loading commands found"
        return 0
    fi
    
    log_info "Available ontology commands: $available_commands"
    
    # Update each ontology
    for cmd in $available_commands; do
        log_info "Updating $cmd..."
        sudo -u "$CUPCAKE_USER" python3 manage.py "$cmd" --update || {
            log_warning "Failed to update $cmd"
        }
    done
    
    log "✅ Ontology databases updated"
}

restart_services() {
    log "Restarting CUPCAKE services..."
    
    # Restart core services
    systemctl daemon-reload
    systemctl restart postgresql || log_warning "Failed to restart PostgreSQL"
    systemctl restart nginx || log_warning "Failed to restart nginx"
    
    # Restart CUPCAKE services
    systemctl start cupcake-* || log_warning "Some CUPCAKE services failed to start"
    
    # Wait a moment for services to start
    sleep 3
    
    # Check service status
    log_info "Checking service status..."
    
    services_ok=true
    for service in postgresql nginx; do
        if systemctl is-active --quiet "$service"; then
            log "✅ $service is running"
        else
            log_error "❌ $service is not running"
            services_ok=false
        fi
    done
    
    # Check CUPCAKE services
    cupcake_services=$(systemctl list-units --type=service --state=active | grep cupcake- | awk '{print $1}' || true)
    if [ -n "$cupcake_services" ]; then
        log_info "Active CUPCAKE services: $cupcake_services"
    else
        log_warning "No active CUPCAKE services found"
    fi
    
    if [ "$services_ok" = "true" ]; then
        log "✅ All core services are running"
    else
        log_warning "Some services may need attention"
    fi
}

show_status() {
    log "CUPCAKE Raspberry Pi Status Report"
    echo "================================="
    
    # System information
    echo "System Information:"
    echo "  OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"')"
    echo "  Kernel: $(uname -r)"
    echo "  Architecture: $(uname -m)"
    echo "  Uptime: $(uptime -p)"
    echo "  Memory: $(free -h | awk '/Mem:/ {print $3 "/" $2}')"
    echo "  Disk Space: $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')"
    echo
    
    # CUPCAKE version information
    echo "CUPCAKE Information:"
    echo "  Version: $(get_current_version)"
    echo "  Branch: $(get_current_branch)"
    echo "  Install Path: $CUPCAKE_DIR/app"
    
    if [ -d "$CUPCAKE_DIR/app" ]; then
        cd "$CUPCAKE_DIR/app"
        if [ -d ".git" ]; then
            echo "  Last Commit: $(git log -1 --format='%h - %s (%cr)' 2>/dev/null || echo 'Unable to read')"
            echo "  Remote URL: $(git remote get-url origin 2>/dev/null || echo 'Not available')"
        fi
    fi
    echo
    
    # Service status
    echo "Service Status:"
    for service in postgresql nginx redis-server; do
        if systemctl is-active --quiet "$service" 2>/dev/null; then
            echo "  ✅ $service: Running"
        else
            echo "  ❌ $service: Not running"
        fi
    done
    
    # CUPCAKE services
    cupcake_services=$(systemctl list-units --type=service | grep cupcake- | awk '{print $1}' || true)
    if [ -n "$cupcake_services" ]; then
        echo "  CUPCAKE Services:"
        echo "$cupcake_services" | while read -r service; do
            if systemctl is-active --quiet "$service"; then
                echo "    ✅ $service: Running"
            else
                echo "    ❌ $service: Not running"
            fi
        done
    fi
    echo
    
    # Network information
    echo "Network Information:"
    echo "  Hostname: $(hostname)"
    echo "  IP Address: $(hostname -I | awk '{print $1}')"
    echo "  Access URL: http://$(hostname).local"
    echo
    
    # Backup information
    echo "Backup Information:"
    if [ -d "$BACKUP_DIR" ] && [ "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        backup_count=$(ls "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)
        latest_backup=$(ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -1)
        echo "  Available Backups: $backup_count"
        if [ -n "$latest_backup" ]; then
            echo "  Latest Backup: $(basename "$latest_backup")"
            echo "  Created: $(stat -c %y "$latest_backup" | cut -d' ' -f1-2)"
        fi
    else
        echo "  Available Backups: 0"
    fi
}

# Parse command line arguments
BRANCH="master"
CREATE_BACKUP="auto"
RESTART_SERVICES="true"
FORCE_UPDATE="false"
DRY_RUN="false"
COMMAND="full"

while [[ $# -gt 0 ]]; do
    case $1 in
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --backup)
            CREATE_BACKUP="true"
            shift
            ;;
        --no-restart)
            RESTART_SERVICES="false"
            shift
            ;;
        --force)
            FORCE_UPDATE="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        system|cupcake|full|ontology|backup|restore|status)
            COMMAND="$1"
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Main script execution
main() {
    # Initialize logging
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    
    log "=== CUPCAKE Update Script Started ==="
    log "Command: $COMMAND"
    log "Branch: $BRANCH"
    log "Backup: $CREATE_BACKUP"
    log "Restart Services: $RESTART_SERVICES"
    log "Force Update: $FORCE_UPDATE"
    log "Dry Run: $DRY_RUN"
    
    # Handle different commands
    case $COMMAND in
        status)
            show_status
            ;;
        backup)
            check_root
            create_backup
            ;;
        restore)
            check_root
            check_lock
            restore_backup
            ;;
        system)
            check_root
            check_lock
            if [ "$DRY_RUN" = "true" ]; then
                log "DRY RUN: Would update system packages"
                apt list --upgradable
            else
                check_internet
                update_system
            fi
            ;;
        cupcake)
            check_root
            check_lock
            if [ "$DRY_RUN" = "true" ]; then
                log "DRY RUN: Would update CUPCAKE to branch $BRANCH"
                if [ -d "$CUPCAKE_DIR/app/.git" ]; then
                    cd "$CUPCAKE_DIR/app"
                    sudo -u "$CUPCAKE_USER" git fetch origin 2>/dev/null || true
                    current=$(get_current_version)
                    latest=$(sudo -u "$CUPCAKE_USER" git rev-parse --short "origin/$BRANCH" 2>/dev/null || echo "unknown")
                    log "Current: $current, Latest: $latest"
                fi
            else
                check_internet
                if [ "$CREATE_BACKUP" = "auto" ] || [ "$CREATE_BACKUP" = "true" ]; then
                    create_backup
                fi
                update_cupcake "$BRANCH" "$FORCE_UPDATE"
                if [ "$RESTART_SERVICES" = "true" ]; then
                    restart_services
                fi
            fi
            ;;
        ontology)
            check_root
            check_lock
            if [ "$DRY_RUN" = "true" ]; then
                log "DRY RUN: Would update ontology databases"
            else
                check_internet
                update_ontology
            fi
            ;;
        full)
            check_root
            check_lock
            if [ "$DRY_RUN" = "true" ]; then
                log "DRY RUN: Would perform full update (system + CUPCAKE)"
                apt list --upgradable
                if [ -d "$CUPCAKE_DIR/app/.git" ]; then
                    cd "$CUPCAKE_DIR/app"
                    sudo -u "$CUPCAKE_USER" git fetch origin 2>/dev/null || true
                    current=$(get_current_version)
                    latest=$(sudo -u "$CUPCAKE_USER" git rev-parse --short "origin/$BRANCH" 2>/dev/null || echo "unknown")
                    log "CUPCAKE - Current: $current, Latest: $latest"
                fi
            else
                check_internet
                if [ "$CREATE_BACKUP" = "auto" ] || [ "$CREATE_BACKUP" = "true" ]; then
                    create_backup
                fi
                update_system
                update_cupcake "$BRANCH" "$FORCE_UPDATE"
                if [ "$RESTART_SERVICES" = "true" ]; then
                    restart_services
                fi
            fi
            ;;
        *)
            log_error "Unknown command: $COMMAND"
            show_help
            exit 1
            ;;
    esac
    
    log "=== CUPCAKE Update Script Completed ==="
}

# Run main function
main "$@"