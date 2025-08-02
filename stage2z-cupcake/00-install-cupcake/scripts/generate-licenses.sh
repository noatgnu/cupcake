#!/bin/bash -e
# Generate package license information

set -euo pipefail

# Source environment variables
set -a  # automatically export all variables
source /etc/environment.d/cupcake.conf
set +a  # stop automatically exporting

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

echo 'Generating package license information...'

# Install pip-licenses for license extraction
pip install pip-licenses --quiet

# Generate license information in multiple formats
echo 'Extracting package licenses...'
pip-licenses --format=json --output-file=/opt/cupcake/release-info/package_licenses.json --with-urls --with-description --with-authors
pip-licenses --format=plain --output-file=/opt/cupcake/release-info/package_licenses.txt --with-urls --with-description --with-authors

# Generate detailed package information
pip list --format=json > /opt/cupcake/release-info/installed_packages.json
pip list > /opt/cupcake/release-info/installed_packages.txt

echo 'Package license information generated successfully!'
