#!/bin/bash -e
# Setup shared memory for multiprocessing in chroot environment

set -euo pipefail

# Source environment variables
set -a  # automatically export all variables
source /etc/environment.d/cupcake.conf
set +a  # stop automatically exporting

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

# Set Python path and prepare for ontology loading
export PYTHONPATH=/opt/cupcake/app

# Fix multiprocessing semaphore access in chroot environment
echo "Configuring shared memory for multiprocessing in chroot..."

# Ensure /dev/shm exists with correct permissions
mkdir -p /dev/shm
chmod 1777 /dev/shm

# Mount tmpfs on /dev/shm if not already mounted (required for POSIX semaphores)
if ! mountpoint -q /dev/shm 2>/dev/null; then
    mount -t tmpfs tmpfs /dev/shm -o size=512m,mode=1777 || {
        echo "WARNING: Could not mount /dev/shm, multiprocessing may fail"
    }
fi

# Fix /run/shm symlink issues that can cause permission problems
if [ -L "/run/shm" ]; then
    rm -f /run/shm
fi
mkdir -p /run/shm
chmod 1777 /run/shm

echo "✓ Shared memory configured for multiprocessing"
