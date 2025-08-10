#!/bin/bash -e


set -euo pipefail


set -a  
source /etc/environment.d/cupcake.conf
set +a  

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate


export PYTHONPATH=/opt/cupcake/app


echo "Configuring shared memory for multiprocessing in chroot..."


if [ ! -d "/dev/shm" ]; then
    mkdir -p /dev/shm 2>/dev/null || echo "Warning: Could not create /dev/shm directory"
fi


chmod 1777 /dev/shm 2>/dev/null || echo "Warning: Could not change /dev/shm permissions (normal in chroot)"


if ! mountpoint -q /dev/shm 2>/dev/null; then
    mount -t tmpfs tmpfs /dev/shm -o size=512m,mode=1777 2>/dev/null || {
        echo "Warning: Could not mount /dev/shm (normal in chroot), using fallback methods"
    }
fi


if [ -L "/run/shm" ]; then
    rm -f /run/shm 2>/dev/null || echo "Warning: Could not remove /run/shm symlink"
fi
if [ ! -d "/run/shm" ]; then
    mkdir -p /run/shm 2>/dev/null || echo "Warning: Could not create /run/shm"
fi
chmod 1777 /run/shm 2>/dev/null || echo "Warning: Could not change /run/shm permissions"



mkdir -p /opt/cupcake/locks
chown cupcake:cupcake /opt/cupcake/locks
chmod 755 /opt/cupcake/locks


export MULTIPROCESSING_FORCE_SINGLE_THREADED=1
export PRONTO_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "✓ Shared memory configured for multiprocessing (with chroot-safe fallbacks)"
