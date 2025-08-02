#!/bin/bash -e
# Load CUPCAKE ontologies and databases

set -euo pipefail

# Source environment variables
set -a  # automatically export all variables
source /etc/environment.d/cupcake.conf
set +a  # stop automatically exporting

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

# Set Python path
export PYTHONPATH=/opt/cupcake/app

# Configure multiprocessing for chroot environment
# Force single-threaded operation to avoid POSIX semaphore permission issues
export MULTIPROCESSING_FORCE_SINGLE_THREADED=1
export PRONTO_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "Multiprocessing configured for chroot environment (single-threaded mode)"

# Load main ontologies (MONDO, UBERON, NCBI, ChEBI, PSI-MS)
echo 'Loading main ontologies (MONDO, UBERON, NCBI, ChEBI with proteomics filter, PSI-MS)...'
python manage.py load_ontologies --chebi-filter proteomics

# Load UniProt species data
echo 'Loading UniProt species data...'
python manage.py load_species

# Load MS modifications (Unimod)
echo 'Loading MS modifications (Unimod)...'
python manage.py load_ms_mod

# Load UniProt tissue data
echo 'Loading UniProt tissue data...'
python manage.py load_tissue

# Load UniProt human disease data
echo 'Loading UniProt human disease data...'
python manage.py load_human_disease

# Load MS terminology and vocabularies
echo 'Loading MS terminology and vocabularies...'
python manage.py load_ms_term

# Load UniProt subcellular location data
echo 'Loading UniProt subcellular location data...'
python manage.py load_subcellular_location

# Load cell types and cell lines
echo 'Loading cell types and cell lines...'
python manage.py load_cell_types --source cl

echo 'All ontologies loaded successfully!'
