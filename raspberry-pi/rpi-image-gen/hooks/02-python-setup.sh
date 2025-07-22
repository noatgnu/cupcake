#!/bin/bash
# CUPCAKE Python Environment Setup Hook
# Installs Python dependencies and sets up virtual environment

set -e

echo ">>> CUPCAKE: Setting up Python environment..."

# Create Python virtual environment for CUPCAKE
sudo -u cupcake python3 -m venv /opt/cupcake/venv
source /opt/cupcake/venv/bin/activate

# Upgrade pip and setuptools
python -m pip install --upgrade pip setuptools wheel

# Install CUPCAKE Python dependencies
cat > /tmp/cupcake-requirements.txt << EOF
Django>=4.2,<5.0
djangorestframework>=3.14.0
django-cors-headers>=4.0.0
psycopg2-binary>=2.9.5
redis>=4.5.0
celery>=5.2.0
gunicorn>=20.1.0
uvicorn[standard]>=0.20.0
channels>=4.0.0
channels-redis>=4.1.0
django-extensions>=3.2.0
python-decouple>=3.7
Pillow>=9.4.0
pandas>=1.5.0
numpy>=1.24.0
scipy>=1.10.0
matplotlib>=3.6.0
openpyxl>=3.1.0
requests>=2.28.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
python-magic>=0.4.27
cryptography>=39.0.0
PyJWT>=2.6.0
django-filter>=22.1
drf-spectacular>=0.25.0
python-multipart>=0.0.5
aiofiles>=22.1.0
fastapi>=0.95.0
pydantic>=1.10.0
sqlalchemy>=2.0.0
alembic>=1.10.0
watchdog>=3.0.0
pytz>=2023.3
EOF

# Install Python packages
pip install -r /tmp/cupcake-requirements.txt

# Install additional scientific packages for laboratory use
pip install \
    biopython \
    scikit-learn \
    seaborn \
    plotly \
    bokeh \
    jupyterlab \
    ipython

# Clean up
rm /tmp/cupcake-requirements.txt
deactivate

# Set up Python path configuration
cat > /opt/cupcake/.pythonrc << EOF
# CUPCAKE Python environment configuration
import sys
import os

# Add CUPCAKE modules to Python path
sys.path.insert(0, '/opt/cupcake/src')
sys.path.insert(0, '/opt/cupcake/lib/python')

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings.production')
EOF

chown cupcake:cupcake /opt/cupcake/.pythonrc

# Create activation script for easy environment loading
cat > /opt/cupcake/activate << 'EOF'
#!/bin/bash
# CUPCAKE environment activation script

export CUPCAKE_HOME=/opt/cupcake
export CUPCAKE_DATA=/var/lib/cupcake
export CUPCAKE_LOGS=/var/log/cupcake

# Activate Python virtual environment
source /opt/cupcake/venv/bin/activate

# Set Django settings
export DJANGO_SETTINGS_MODULE=cupcake.settings.production

# Add CUPCAKE to PATH
export PATH="$CUPCAKE_HOME/bin:$PATH"

# Load Python configuration
export PYTHONSTARTUP=/opt/cupcake/.pythonrc

echo "CUPCAKE environment activated"
echo "Python virtual environment: $(which python)"
echo "Django version: $(python -c 'import django; print(django.get_version())')"
EOF

chmod +x /opt/cupcake/activate
chown cupcake:cupcake /opt/cupcake/activate

# Create convenient symlink
ln -sf /opt/cupcake/activate /usr/local/bin/cupcake-env

echo ">>> CUPCAKE: Python environment setup completed successfully"
echo ">>> Use 'source /opt/cupcake/activate' or 'cupcake-env' to activate the environment"