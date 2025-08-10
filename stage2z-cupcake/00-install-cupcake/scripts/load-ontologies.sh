#!/bin/bash -e


set -euo pipefail


set -a  
source /etc/environment.d/cupcake.conf
set +a  

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate


export PYTHONPATH=/opt/cupcake/app



export MULTIPROCESSING_FORCE_SINGLE_THREADED=1
export PRONTO_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "Multiprocessing configured for chroot environment (single-threaded mode)"


cat > /opt/cupcake/app/patch_multiprocessing.py << 'MPEOF'
"""
Patch multiprocessing to work in chroot environments where POSIX semaphores fail.
This module completely replaces multiprocessing pools with single-threaded equivalents.
"""
import os
import sys
import multiprocessing
import multiprocessing.pool


os.environ['PRONTO_THREADS'] = '1'


_OriginalPool = multiprocessing.pool.Pool
_OriginalThreadPool = multiprocessing.pool.ThreadPool

class FakePool:
    """Single-threaded replacement for multiprocessing.Pool that works in chroot"""
    def __init__(self, *args, **kwargs):
        self.processes = 1
        
    def __enter__(self):
        return self
        
    def __exit__(self, *args):
        pass
        
    def map(self, func, iterable, chunksize=None):
        return [func(item) for item in iterable]
        
    def starmap(self, func, iterable, chunksize=None):
        return [func(*args) for args in iterable]
        
    def apply_async(self, func, args=(), kwds={}, callback=None, error_callback=None):
        try:
            result = func(*args, **kwds)
            if callback:
                callback(result)
            return FakeAsyncResult(result)
        except Exception as e:
            if error_callback:
                error_callback(e)
            raise
            
    def close(self):
        pass
        
    def join(self):
        pass

class FakeAsyncResult:
    """Single-threaded replacement for AsyncResult"""
    def __init__(self, result):
        self._result = result
        
    def get(self, timeout=None):
        return self._result
        
    def ready(self):
        return True
        
    def successful(self):
        return True


multiprocessing.Pool = FakePool
multiprocessing.pool.Pool = FakePool
multiprocessing.pool.ThreadPool = FakePool

print("✓ Multiprocessing patched for chroot compatibility")
MPEOF


echo 'Loading main ontologies (MONDO, UBERON, NCBI, ChEBI with proteomics filter, PSI-MS)...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_ontologies --chebi-filter proteomics


echo 'Loading UniProt species data...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_species


echo 'Loading MS modifications (Unimod)...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_ms_mod


echo 'Loading UniProt tissue data...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_tissue


echo 'Loading UniProt human disease data...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_human_disease


echo 'Loading MS terminology and vocabularies...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_ms_term


echo 'Loading UniProt subcellular location data...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_subcellular_location


echo 'Loading cell types and cell lines...'
python -c "import patch_multiprocessing; exec(open('manage.py').read())" load_cell_types --source cl

echo 'All ontologies loaded successfully!'
