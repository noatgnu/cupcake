# CUPCAKE Native Installation Guide

This guide provides instructions for installing CUPCAKE without Docker on lower power systems. The native installation is designed for systems with limited resources where Docker overhead might be problematic.

## System Requirements

### Minimum Requirements
- **OS**: Ubuntu 20.04+ or Debian 11+
- **RAM**: 2GB (minimum), 4GB recommended
- **Storage**: 5GB free space (minimum), 10GB recommended
- **CPU**: 1 core (minimum), 2+ cores recommended

### Supported Operating Systems
- Ubuntu 20.04 LTS, 22.04 LTS, 24.04 LTS
- Debian 11 (Bullseye), 12 (Bookworm)

## Architecture Overview

The native installation consists of the following components:

### Core Services
- **PostgreSQL 14**: Database server
- **Redis**: Cache and message broker
- **Nginx**: Web server and reverse proxy
- **Gunicorn**: WSGI server for Django application
- **systemd**: Service management

### Optional Workers
- **Background Worker**: General task processing
- **Document Export Worker**: Protocol document generation
- **Data Import Worker**: Bulk data import processing
- **OCR Worker**: Optical Character Recognition (optional)
- **Transcription Worker**: Audio transcription with Whisper (optional)

### Directory Structure
```
/opt/cupcake/
├── app/           # Django application
├── venv/          # Python virtual environment
├── media/         # User uploaded files
└── static/        # Static web assets

/var/log/cupcake/  # Application logs
```

## Quick Installation

1. **Download and run the installation script:**
   ```bash
   wget https://raw.githubusercontent.com/noatgnu/cupcake/main/install_cupcake_native.sh
   chmod +x install_cupcake_native.sh
   ./install_cupcake_native.sh
   ```

2. **Follow the interactive prompts to configure:**
   - Hostname (e.g., localhost or your domain)
   - Web server port (default: 8080)
   - Database credentials
   - Optional features (OCR, Whisper, Workers)
   - Admin user credentials

3. **Access your installation:**
   - Web Interface: `http://your-hostname:port`
   - Admin Interface: `http://your-hostname:port/admin`

## Manual Installation Steps

If you prefer to install manually or need to customize the installation:

### 1. System Package Installation

```bash
# Update package lists
sudo apt update

# Install core packages
sudo apt install -y \
    python3 python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib postgresql-client \
    redis-server nginx git curl wget \
    build-essential pkg-config libpq-dev \
    libssl-dev libffi-dev libjpeg-dev libpng-dev \
    ffmpeg supervisor openssl bc

# Install Node.js for frontend building
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Optional: Install OCR packages
sudo apt install -y tesseract-ocr tesseract-ocr-eng
```

### 2. Database Setup

```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql << EOF
CREATE USER cupcake_user WITH PASSWORD 'your_password';
CREATE DATABASE cupcake_db OWNER cupcake_user;
GRANT ALL PRIVILEGES ON DATABASE cupcake_db TO cupcake_user;
ALTER USER cupcake_user CREATEDB;
EOF
```

### 3. Redis Configuration

```bash
# Configure Redis with password
sudo sed -i 's/^# requirepass foobared/requirepass redis/' /etc/redis/redis.conf
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

### 4. Application Setup

```bash
# Create system user
sudo useradd --system --shell /bin/bash --home-dir /opt/cupcake --create-home cupcake

# Create directories
sudo mkdir -p /opt/cupcake/{app,venv,media,static} /var/log/cupcake
sudo chown -R cupcake:cupcake /opt/cupcake
sudo chown -R cupcake:www-data /var/log/cupcake

# Clone and install application
sudo -u cupcake git clone https://github.com/noatgnu/cupcake.git /opt/cupcake/app
sudo -u cupcake python3 -m venv /opt/cupcake/venv
sudo -u cupcake /opt/cupcake/venv/bin/pip install -r /opt/cupcake/app/requirements.txt
sudo -u cupcake /opt/cupcake/venv/bin/pip install gunicorn
```

### 5. Frontend Build

```bash
# Build Angular frontend
git clone https://github.com/noatgnu/cupcake-ng.git /tmp/cupcake-ng
cd /tmp/cupcake-ng

# Update environment configuration
sed -i 's;https://cupcake.proteo.info;http://localhost:8080;g' src/environments/environment.ts

# Build and install
npm install
npm run build
sudo cp -r dist/browser/* /opt/cupcake/static/
sudo chown -R cupcake:www-data /opt/cupcake/static
```

### 6. Configuration Files

Create `/opt/cupcake/app/local_settings.py`:

```python
DEBUG = False
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'your-hostname']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'cupcake_db',
        'USER': 'cupcake_user',
        'PASSWORD': 'your_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {'password': 'redis'}
        }
    }
}

SECRET_KEY = 'your-secret-key'
STATIC_ROOT = '/opt/cupcake/static'
MEDIA_ROOT = '/opt/cupcake/media'

# Feature flags
USE_COTURN = False
USE_WHISPER = True  # Set to False if not needed
USE_OCR = True      # Set to False if not needed
USE_LLM = False
```

### 7. Service Configuration

Create systemd service files for automatic startup and management. See the installation script for complete service definitions.

### 8. Database Initialization

```bash
cd /opt/cupcake/app
sudo -u cupcake /opt/cupcake/venv/bin/python manage.py migrate
sudo -u cupcake /opt/cupcake/venv/bin/python manage.py collectstatic --noinput
sudo -u cupcake /opt/cupcake/venv/bin/python manage.py createsuperuser
```

## Management Commands

After installation, use the `cupcake` command for management:

### Service Control
```bash
cupcake start       # Start all services
cupcake stop        # Stop all services
cupcake restart     # Restart all services
cupcake status      # Show service status
cupcake logs        # View live logs
```

### Django Management
```bash
cupcake django createsuperuser    # Create admin user
cupcake django shell              # Django shell
cupcake django migrate            # Run migrations
cupcake django collectstatic      # Collect static files
```

### Maintenance
```bash
cupcake backup      # Create database backup
cupcake update      # Update from git repository
```

### Manual Service Control
```bash
# Start/stop individual services
sudo systemctl start cupcake-web.service
sudo systemctl start cupcake-worker.service
sudo systemctl start cupcake-docx-worker.service
sudo systemctl start cupcake-import-worker.service
sudo systemctl start cupcake-ocr-worker.service
sudo systemctl start cupcake-transcribe-worker.service

# Check service status
sudo systemctl status cupcake-web.service

# View service logs
sudo journalctl -u cupcake-web.service -f
```

## Configuration

### Environment Variables
Configuration is primarily handled through Django settings. Key settings in `local_settings.py`:

- `DEBUG`: Set to `False` for production
- `ALLOWED_HOSTS`: List of allowed hostnames
- `DATABASES`: PostgreSQL connection settings
- `SECRET_KEY`: Django secret key (generate with `openssl rand -base64 32`)
- Feature flags: `USE_WHISPER`, `USE_OCR`, `USE_LLM`, `USE_COTURN`

### Nginx Configuration
The Nginx configuration is located at `/etc/nginx/sites-available/cupcake`. Key settings:

- `listen`: Web server port
- `server_name`: Hostname
- `client_max_body_size`: Maximum upload size
- Proxy settings for API endpoints

### Resource Usage Settings
For lower power systems, you can adjust:

- **Gunicorn workers**: Reduce from 4 to 2 in the systemd service file
- **Database connections**: Set `CONN_MAX_AGE` in Django settings
- **Cache timeout**: Adjust Redis cache settings
- **Worker concurrency**: Limit concurrent background tasks

## Troubleshooting

### Common Issues

1. **Services won't start**
   ```bash
   # Check service status
   sudo systemctl status cupcake-web.service
   
   # Check logs
   sudo journalctl -u cupcake-web.service -n 50
   ```

2. **Database connection errors**
   ```bash
   # Test database connection
   sudo -u cupcake /opt/cupcake/venv/bin/python -c "
   import psycopg2
   conn = psycopg2.connect(
       host='localhost',
       database='cupcake_db',
       user='cupcake_user',
       password='your_password'
   )
   print('Database connection successful')
   "
   ```

3. **Permission issues**
   ```bash
   # Fix file permissions
   sudo chown -R cupcake:cupcake /opt/cupcake
   sudo chown -R cupcake:www-data /var/log/cupcake
   sudo chmod -R 755 /opt/cupcake/media /opt/cupcake/static
   ```

4. **Frontend not loading**
   ```bash
   # Check Nginx configuration
   sudo nginx -t
   
   # Restart Nginx
   sudo systemctl restart nginx
   
   # Check if static files are properly collected
   sudo -u cupcake /opt/cupcake/venv/bin/python /opt/cupcake/app/manage.py collectstatic --noinput
   ```

### Performance Optimization

For lower power systems:

1. **Reduce worker processes**:
   Edit `/etc/systemd/system/cupcake-web.service` and change `--workers 4` to `--workers 2`

2. **Optimize PostgreSQL**:
   Edit `/etc/postgresql/*/main/postgresql.conf`:
   ```
   shared_buffers = 128MB
   effective_cache_size = 512MB
   work_mem = 4MB
   maintenance_work_mem = 64MB
   ```

3. **Disable unnecessary workers**:
   ```bash
   sudo systemctl disable cupcake-ocr-worker.service
   sudo systemctl disable cupcake-transcribe-worker.service
   ```

### Log Locations

- **Django logs**: `/var/log/cupcake/django.log`
- **Gunicorn access logs**: `/var/log/cupcake/access.log`
- **Gunicorn error logs**: `/var/log/cupcake/error.log`
- **System logs**: `sudo journalctl -u cupcake-web.service`

## Security Considerations

1. **Database security**:
   - Use strong passwords
   - Limit PostgreSQL connections to localhost
   - Regular backups

2. **Web server security**:
   - Use HTTPS in production (configure SSL certificates)
   - Set appropriate file permissions
   - Regular system updates

3. **Application security**:
   - Keep Django and dependencies updated
   - Use strong SECRET_KEY
   - Monitor logs for suspicious activity

## Backup and Recovery

### Database Backup
```bash
# Create backup
sudo -u postgres pg_dump cupcake_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore backup
sudo -u postgres psql cupcake_db < backup_file.sql
```

### File Backup
```bash
# Backup media files
tar -czf media_backup_$(date +%Y%m%d_%H%M%S).tar.gz /opt/cupcake/media

# Backup configuration
tar -czf config_backup_$(date +%Y%m%d_%H%M%S).tar.gz /opt/cupcake/app/local_settings.py /etc/nginx/sites-available/cupcake
```

## Upgrading

To upgrade to a newer version:

```bash
# Automated upgrade
cupcake update

# Manual upgrade
cd /opt/cupcake/app
sudo -u cupcake git pull
sudo -u cupcake /opt/cupcake/venv/bin/pip install -r requirements.txt
sudo -u cupcake /opt/cupcake/venv/bin/python manage.py migrate
sudo -u cupcake /opt/cupcake/venv/bin/python manage.py collectstatic --noinput
cupcake restart
```

## Uninstallation

To completely remove CUPCAKE:

```bash
# Stop services
cupcake stop

# Disable services
sudo systemctl disable cupcake-web.service
sudo systemctl disable cupcake-worker.service
sudo systemctl disable cupcake-docx-worker.service
sudo systemctl disable cupcake-import-worker.service
sudo systemctl disable cupcake-ocr-worker.service
sudo systemctl disable cupcake-transcribe-worker.service

# Remove service files
sudo rm /etc/systemd/system/cupcake-*.service
sudo systemctl daemon-reload

# Remove application files
sudo rm -rf /opt/cupcake
sudo rm -rf /var/log/cupcake

# Remove Nginx configuration
sudo rm /etc/nginx/sites-available/cupcake
sudo rm /etc/nginx/sites-enabled/cupcake
sudo systemctl restart nginx

# Remove database (optional)
sudo -u postgres dropdb cupcake_db
sudo -u postgres dropuser cupcake_user

# Remove user
sudo userdel cupcake

# Remove management command
sudo rm /usr/local/bin/cupcake
```

## Support

For issues and support:

- **GitHub Issues**: https://github.com/noatgnu/cupcake/issues
- **Documentation**: Check the main CUPCAKE documentation
- **Logs**: Always check service logs when reporting issues

Remember to include relevant log output and system information when reporting issues.