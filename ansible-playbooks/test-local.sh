#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CONTAINER_NAME="cupcake-ansible-test"
TEST_OS="${TEST_OS:-ubuntu:22.04}"
CLEANUP_ON_EXIT="${CLEANUP_ON_EXIT:-true}"
log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} ✅ $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')]${NC} ⚠️  $1"
}

error() {
    echo -e "${RED}[$(date +'%H:%M:%S')]${NC} ❌ $1"
}

cleanup() {
    if [[ "$CLEANUP_ON_EXIT" == "true" ]]; then
        log "Cleaning up test environment..."
        docker stop $CONTAINER_NAME >/dev/null 2>&1 || true
        docker rm $CONTAINER_NAME >/dev/null 2>&1 || true
        success "Cleanup completed"
    else
        warn "Container $CONTAINER_NAME left running for manual inspection"
        log "Connect with: docker exec -it $CONTAINER_NAME bash"
        log "Stop with: docker stop $CONTAINER_NAME && docker rm $CONTAINER_NAME"
    fi
}

trap cleanup EXIT

check_prerequisites() {
    log "Checking prerequisites..."
    
    if ! command -v docker >/dev/null 2>&1; then
        error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! command -v ansible-playbook >/dev/null 2>&1; then
        error "Ansible is not installed or not in PATH"
        echo "Install with: pip install ansible"
        exit 1
    fi
    
    success "Prerequisites check passed"
}

setup_container() {
    log "Setting up test container with $TEST_OS..."
    
    docker stop $CONTAINER_NAME >/dev/null 2>&1 || true
    docker rm $CONTAINER_NAME >/dev/null 2>&1 || true
    docker run -d \
        --name $CONTAINER_NAME \
        --privileged \
        --cgroupns host \
        --tmpfs /tmp \
        --tmpfs /run \
        --tmpfs /run/lock \
        --volume /sys/fs/cgroup:/sys/fs/cgroup:rw \
        --volume "$SCRIPT_DIR/../":/workspace \
        --workdir /workspace \
        --publish 8080:80 \
        --publish 8000:8000 \
        $TEST_OS \
        sleep infinity
    
    success "Container started"
    
    log "Configuring container environment..."
    docker exec $CONTAINER_NAME bash -c "
        apt-get update >/dev/null 2>&1 && 
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            openssh-server sudo python3 python3-pip systemd systemd-sysv dbus \
            ca-certificates curl gnupg lsb-release \
            >/dev/null 2>&1 &&
        systemctl enable ssh >/dev/null 2>&1 &&
        useradd -m -s /bin/bash -G sudo testuser &&
        echo 'testuser:testpass' | chpasswd &&
        echo 'testuser ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/testuser &&
        mkdir -p /home/testuser/.ssh &&
        chmod 700 /home/testuser/.ssh &&
        service ssh start >/dev/null 2>&1
    "
    
    success "Container environment configured"
}

setup_ssh() {
    log "Setting up SSH access..."
    
    if [[ ! -f ~/.ssh/cupcake_test_rsa ]]; then
        ssh-keygen -t rsa -b 2048 -f ~/.ssh/cupcake_test_rsa -N "" -C "cupcake-test-key"
    fi
    
    CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $CONTAINER_NAME)
    docker exec $CONTAINER_NAME bash -c "
        echo '$(cat ~/.ssh/cupcake_test_rsa.pub)' >> /home/testuser/.ssh/authorized_keys &&
        chmod 600 /home/testuser/.ssh/authorized_keys &&
        chown -R testuser:testuser /home/testuser/.ssh
    "
    cat > ~/.ssh/cupcake_test_config << EOF
Host cupcake-test
    HostName $CONTAINER_IP
    User testuser
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    IdentityFile ~/.ssh/cupcake_test_rsa
    LogLevel ERROR
EOF
    
    log "Waiting for SSH to be ready..."
    timeout 30 bash -c "
        until ssh -F ~/.ssh/cupcake_test_config cupcake-test 'echo SSH Ready' >/dev/null 2>&1; do 
            sleep 1
        done
    "
    
    success "SSH access configured"
}

create_inventory() {
    log "Creating test inventory..."
    
    CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $CONTAINER_NAME)
    
    cat > test-inventory.yml << EOF
all:
  hosts:
    cupcake-test:
      ansible_host: $CONTAINER_IP
      ansible_user: testuser
      ansible_ssh_private_key_file: ~/.ssh/cupcake_test_rsa
      ansible_python_interpreter: /usr/bin/python3
      ansible_ssh_common_args: '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR'
      
      cupcake_db_password: "test_secure_password_123"
      cupcake_secret_key: "test_django_secret_key_$(date +%s)"
      cupcake_admin_password: "test_admin_password_123"
      cupcake_version: "latest"
      django_debug: false
      django_allowed_hosts: "localhost,127.0.0.1,*.local,cupcake-test,test.cupcake.local"
EOF
    
    success "Test inventory created"
}

run_tests() {
    log "Running Ansible tests..."
    
    log "Testing Ansible connectivity..."
    if ansible all -i test-inventory.yml -m ping; then
        success "Ansible connectivity test passed"
    else
        error "Ansible connectivity test failed"
        return 1
    fi
    
    log "Running syntax check..."
    if ansible-playbook --syntax-check cupcake-standalone.yml; then
        success "Syntax check passed"
    else
        error "Syntax check failed"
        return 1
    fi
    
    log "Running dry run (check mode)..."
    if ansible-playbook -i test-inventory.yml cupcake-standalone.yml --check --diff; then
        success "Dry run completed successfully"
    else
        warn "Dry run had issues (this might be expected)"
    fi
    
    log "Running actual deployment (this may take 10-15 minutes)..."
    if timeout 1800 ansible-playbook -i test-inventory.yml cupcake-standalone.yml -v; then
        success "Deployment completed successfully"
    else
        error "Deployment failed"
        return 1
    fi
}

run_validation() {
    log "Running post-deployment validation..."
    
    if docker exec $CONTAINER_NAME bash -c "cd /workspace && chmod +x ansible-playbooks/validate-deployment.sh && ./ansible-playbooks/validate-deployment.sh"; then
        success "Validation passed"
    else
        error "Validation failed"
        return 1
    fi
    
    log "Testing web server access..."
    for i in {1..5}; do
        if docker exec $CONTAINER_NAME curl -f -s http://localhost/ >/dev/null; then
            success "Web server is responding (attempt $i)"
            break
        else
            warn "Web server not responding, attempt $i/5"
            sleep 5
        fi
        
        if [[ $i -eq 5 ]]; then
            error "Web server failed to respond after 5 attempts"
            return 1
        fi
    done
    
    log "Testing database connectivity..."
    if docker exec $CONTAINER_NAME sudo -u postgres psql -d cupcake -c "SELECT 'Database test OK' as result;" >/dev/null; then
        success "Database connectivity test passed"
    else
        error "Database connectivity test failed"
        return 1
    fi
}

show_logs() {
    log "Showing service status and recent logs..."
    
    echo
    log "=== Service Status ==="
    docker exec $CONTAINER_NAME systemctl status cupcake-web cupcake-worker postgresql redis-server nginx --no-pager -l || true
    
    echo
    log "=== Recent CUPCAKE Logs ==="
    docker exec $CONTAINER_NAME journalctl -u cupcake-web -u cupcake-worker --no-pager -n 20 || true
    
    echo
    log "=== Nginx Error Logs ==="
    docker exec $CONTAINER_NAME tail -20 /var/log/nginx/cupcake_error.log 2>/dev/null || warn "No nginx error log found"
}

main() {
    echo -e "${BLUE}"
    cat << "EOF"
🧁 CUPCAKE Ansible Local Testing
===============================
EOF
    echo -e "${NC}"
    
    log "Starting local Ansible testing with OS: $TEST_OS"
    log "Container name: $CONTAINER_NAME"
    
    check_prerequisites
    setup_container
    setup_ssh  
    create_inventory
    
    if run_tests; then
        success "All tests passed!"
        
        if run_validation; then
            success "Validation passed!"
            
            echo
            success "🎉 CUPCAKE deployment test completed successfully!"
            echo
            log "Access the test deployment:"
            log "  Web UI: http://localhost:8080"
            log "  Django Admin: http://localhost:8080/admin"
            log "  API: http://localhost:8080/api/"
            echo
            log "Default credentials:"
            log "  Username: admin"
            log "  Password: test_admin_password_123"
            echo
            log "Container management:"
            log "  Connect: docker exec -it $CONTAINER_NAME bash"
            log "  Logs: docker logs $CONTAINER_NAME"
            
            # Keep container running if requested
            if [[ "$CLEANUP_ON_EXIT" != "true" ]]; then
                echo
                warn "Container will remain running for manual inspection"
                log "To cleanup later: docker stop $CONTAINER_NAME && docker rm $CONTAINER_NAME"
                trap - EXIT
            fi
        else
            error "Validation failed"
            show_logs
            exit 1
        fi
    else
        error "Tests failed"
        show_logs
        exit 1
    fi
}

show_help() {
    cat << EOF
CUPCAKE Ansible Local Testing Script

Usage: $0 [OPTIONS]

Options:
    -h, --help          Show this help message
    -o, --os OS         Set target OS (default: ubuntu:22.04)
                        Examples: ubuntu:20.04, ubuntu:22.04, debian:11, debian:12
    -k, --keep          Keep container running after tests (for manual inspection)
    --no-cleanup        Same as --keep

Environment Variables:
    TEST_OS             Target OS for testing (default: ubuntu:22.04)
    CLEANUP_ON_EXIT     Whether to cleanup container on exit (default: true)

Examples:
    # Basic test with Ubuntu 22.04
    $0

    # Test with Debian 11
    $0 --os debian:11

    # Test and keep container for inspection
    $0 --keep

    # Test with environment variable
    TEST_OS=ubuntu:20.04 $0

Prerequisites:
    - Docker installed and running
    - Ansible installed (pip install ansible)
    - Internet connection for package downloads

The script will:
    1. Create a Docker container with the specified OS
    2. Configure SSH access and Ansible connectivity  
    3. Run syntax checks and dry run tests
    4. Deploy CUPCAKE using the Ansible playbook
    5. Validate the deployment
    6. Show results and access information

EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -o|--os)
            TEST_OS="$2"
            shift 2
            ;;
        -k|--keep|--no-cleanup)
            CLEANUP_ON_EXIT="false"
            shift
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

main