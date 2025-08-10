#!/bin/bash

set -e

CUPCAKE_HOME="/opt/cupcake"
CUPCAKE_USER="cupcake"

echo "🧁 CUPCAKE Deployment Validation"
echo "================================"

if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root or with sudo"
   exit 1
fi

echo "✅ Running validation checks..."
echo

echo "🔍 Checking system user..."
if id "$CUPCAKE_USER" &>/dev/null; then
    echo "✅ User '$CUPCAKE_USER' exists"
else
    echo "❌ User '$CUPCAKE_USER' does not exist"
    exit 1
fi

echo "🔍 Checking directory structure..."
REQUIRED_DIRS=(
    "$CUPCAKE_HOME"
    "$CUPCAKE_HOME/app"
    "$CUPCAKE_HOME/venv"
    "$CUPCAKE_HOME/scripts"
    "$CUPCAKE_HOME/frontend"
    "$CUPCAKE_HOME/media"
    "$CUPCAKE_HOME/logs"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [[ -d "$dir" ]]; then
        echo "✅ Directory exists: $dir"
    else
        echo "❌ Directory missing: $dir"
        exit 1
    fi
done

echo "🔍 Checking critical files..."
REQUIRED_FILES=(
    "$CUPCAKE_HOME/app/manage.py"
    "$CUPCAKE_HOME/venv/bin/activate"
    "$CUPCAKE_HOME/scripts/cupcake-boot-service.sh"
    "/etc/environment.d/cupcake.conf"
    "/etc/systemd/system/cupcake-web.service"
    "/etc/systemd/system/cupcake-worker.service"
    "/etc/systemd/system/cupcake-boot.service"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        echo "✅ File exists: $file"
    else
        echo "❌ File missing: $file"
        exit 1
    fi
done

echo "🔍 Checking systemd services..."
SERVICES=(
    "postgresql"
    "redis-server"
    "nginx"
    "cupcake-web"
    "cupcake-worker"
)

for service in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$service"; then
        echo "✅ Service running: $service"
    else
        echo "⚠️  Service not running: $service"
        echo "   Status: $(systemctl is-active "$service" 2>/dev/null || echo 'unknown')"
    fi
done

echo "🔍 Checking network connectivity..."
if curl -f -s http://localhost/health/ >/dev/null 2>&1; then
    echo "✅ Web server responding on localhost"
else
    echo "⚠️  Web server not responding on localhost"
    echo "   Checking if nginx is serving frontend..."
    if curl -f -s http://localhost/ >/dev/null 2>&1; then
        echo "✅ Nginx serving frontend"
    else
        echo "❌ Nginx not responding"
    fi
fi

echo "🔍 Checking database connection..."
if sudo -u postgres psql -d cupcake -c "SELECT 1;" >/dev/null 2>&1; then
    echo "✅ Database connection working"
else
    echo "❌ Database connection failed"
fi

echo "🔍 Checking Python environment..."
if sudo -u "$CUPCAKE_USER" bash -c "cd $CUPCAKE_HOME/app && source $CUPCAKE_HOME/venv/bin/activate && python -c 'import django; print(f\"Django {django.get_version()}\")'"; then
    echo "✅ Python environment working"
else
    echo "❌ Python environment issues"
fi

echo "🔍 Checking disk space..."
DISK_USAGE=$(df -h "$CUPCAKE_HOME" | awk 'NR==2 {print $5}' | sed 's/%//')
if [[ $DISK_USAGE -lt 90 ]]; then
    echo "✅ Disk space OK (${DISK_USAGE}% used)"
else
    echo "⚠️  Disk space high (${DISK_USAGE}% used)"
fi

echo "🔍 Checking recent logs..."
if journalctl -u cupcake-web --since "5 minutes ago" --no-pager -q | grep -q "ERROR\|CRITICAL"; then
    echo "⚠️  Errors found in cupcake-web logs (last 5 minutes)"
    echo "   Run: journalctl -u cupcake-web --since \"5 minutes ago\""
else
    echo "✅ No recent errors in cupcake-web logs"
fi

echo "🔍 Checking frontend files..."
if [[ -f "$CUPCAKE_HOME/frontend/index.html" ]]; then
    echo "✅ Frontend files present"
    FRONTEND_FILES=$(find "$CUPCAKE_HOME/frontend" -type f | wc -l)
    echo "   Found $FRONTEND_FILES files"
else
    echo "❌ Frontend files missing"
fi

echo
echo "🎉 Validation Complete!"
echo "======================="

FAILED_CHECKS=0
if ! id "$CUPCAKE_USER" &>/dev/null; then ((FAILED_CHECKS++)); fi
for dir in "${REQUIRED_DIRS[@]}"; do
    if [[ ! -d "$dir" ]]; then ((FAILED_CHECKS++)); fi
done
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then ((FAILED_CHECKS++)); fi
done

echo "📊 Summary:"
echo "   ✅ Successful checks: $((${#REQUIRED_DIRS[@]} + ${#REQUIRED_FILES[@]} + 1 - FAILED_CHECKS))"
echo "   ❌ Failed checks: $FAILED_CHECKS"

if [[ $FAILED_CHECKS -eq 0 ]]; then
    echo
    echo "🎉 CUPCAKE deployment appears to be successful!"
    echo
    echo "🌐 Access your CUPCAKE instance:"
    echo "   Web Interface: http://$(hostname -f)/"
    echo "   Admin Panel:   http://$(hostname -f)/admin"
    echo
    echo "🔧 Management commands:"
    echo "   Check status:  systemctl status cupcake-*"
    echo "   View logs:     journalctl -f -u cupcake-web"
    echo "   Update:        cupcake-update"
    echo
    echo "🔒 Security reminders:"
    echo "   1. Change default passwords"
    echo "   2. Configure firewall (ufw)"
    echo "   3. Setup SSL certificates"
    echo "   4. Review /etc/environment.d/cupcake.conf"
else
    echo
    echo "⚠️  Some issues were detected. Please review the output above."
    echo "   Check logs: journalctl -u cupcake-*"
    echo "   Ansible docs: see README.md in ansible-playbooks/"
    exit 1
fi