#!/bin/bash
set -e

LOG_FILE="/var/log/cupcake/first-boot.log"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "$(date): Starting CUPCAKE first boot setup..."

cd /opt/cupcake/app

# Wait for services
while ! pg_isready -h localhost -p 5432 -U cupcake; do sleep 2; done
while ! redis-cli ping > /dev/null 2>&1; do sleep 2; done

# Activate virtual environment
source /opt/cupcake/venv/bin/activate

# Set environment variables
export DJANGO_SETTINGS_MODULE=cupcake.settings
export DATABASE_URL=postgresql://cupcake:cupcake123@localhost/cupcake_db
export REDIS_URL=redis://localhost:6379/0

# Run Django setup
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

# Create admin user
python manage.py shell << 'PYEOF'
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@cupcake.local', 'cupcake123')
    print('Admin user created: admin / cupcake123')
PYEOF

# Set permissions
chown -R cupcake:cupcake /opt/cupcake /var/log/cupcake /var/lib/cupcake

echo "$(date): CUPCAKE first boot setup completed successfully"
systemctl disable cupcake-setup.service
