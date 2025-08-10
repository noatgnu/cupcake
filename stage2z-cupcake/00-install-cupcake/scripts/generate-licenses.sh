#!/bin/bash -e

set -euo pipefail

set -a  
source /etc/environment.d/cupcake.conf
set +a  

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

echo 'Generating package license information...'

pip install pip-licenses --quiet

echo 'Extracting package licenses...'
pip-licenses --format=json --output-file=/opt/cupcake/release-info/package_licenses.json --with-urls --with-description --with-authors
pip-licenses --format=plain --output-file=/opt/cupcake/release-info/package_licenses.txt --with-urls --with-description --with-authors

pip list --format=json > /opt/cupcake/release-info/installed_packages.json
pip list > /opt/cupcake/release-info/installed_packages.txt

echo 'Package license information generated successfully!'
