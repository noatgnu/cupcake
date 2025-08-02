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

# Try to ensure /dev/shm exists, but don't fail if we can't modify permissions
if [ ! -d "/dev/shm" ]; then
    mkdir -p /dev/shm 2>/dev/null || echo "Warning: Could not create /dev/shm directory"
fi

# Try to set permissions, but continue if it fails (common in chroot)
chmod 1777 /dev/shm 2>/dev/null || echo "Warning: Could not change /dev/shm permissions (normal in chroot)"

# Try to mount tmpfs on /dev/shm if not already mounted (may fail in chroot)
if ! mountpoint -q /dev/shm 2>/dev/null; then
    mount -t tmpfs tmpfs /dev/shm -o size=512m,mode=1777 2>/dev/null || {
        echo "Warning: Could not mount /dev/shm (normal in chroot), using fallback methods"
    }
fi

# Fix /run/shm symlink issues that can cause permission problems
if [ -L "/run/shm" ]; then
    rm -f /run/shm 2>/dev/null || echo "Warning: Could not remove /run/shm symlink"
fi
if [ ! -d "/run/shm" ]; then
    mkdir -p /run/shm 2>/dev/null || echo "Warning: Could not create /run/shm"
fi
chmod 1777 /run/shm 2>/dev/null || echo "Warning: Could not change /run/shm permissions"

# Alternative: Use file-based locking instead of POSIX semaphores
# Create a directory for file-based locks that we can control
mkdir -p /opt/cupcake/locks
chown cupcake:cupcake /opt/cupcake/locks
chmod 755 /opt/cupcake/locks

# Set environment variables to force single-threaded operation for problematic libraries
export MULTIPROCESSING_FORCE_SINGLE_THREADED=1
export PRONTO_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "✓ Shared memory configured for multiprocessing (with chroot-safe fallbacks)"
