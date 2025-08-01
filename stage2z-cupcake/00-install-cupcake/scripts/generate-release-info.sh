#!/bin/bash -e
# Create comprehensive release info file

set -euo pipefail

# Source environment variables
set -a  # automatically export all variables
source /etc/environment.d/cupcake.conf
set +a  # stop automatically exporting

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

echo 'Creating comprehensive release info file...'

python <<'PYEOF'
import json
import os
from datetime import datetime

# Load ontology statistics (should always exist at this point)
with open('/opt/cupcake/release-info/ontology_statistics.json', 'r') as f:
    ontology_stats = json.load(f)
print("Successfully loaded ontology statistics")
print(f"Keys in ontology_stats: {list(ontology_stats.keys())}")
if 'total_records' not in ontology_stats:
    print("ERROR: 'total_records' key missing from ontology statistics!")
    print(f"Available keys: {list(ontology_stats.keys())}")
    raise KeyError("total_records key not found in ontology statistics")

# Load package info
with open('/opt/cupcake/release-info/installed_packages.json', 'r') as f:
    packages = json.load(f)

# Create comprehensive release info
release_info = {
    'build_date': datetime.now().isoformat(),
    'cupcake_version': 'ARM64 Pi Build',
    'ontology_databases': ontology_stats['ontology_statistics'],
    'total_ontology_records': ontology_stats['total_records'],
    'python_packages': {
        'total_packages': len(packages),
        'packages': {pkg['name']: pkg['version'] for pkg in packages}
    },
    'system_info': {
        'architecture': 'ARM64 (aarch64)',
        'target_platform': 'Raspberry Pi 4/5',
        'python_version': '3.11',
        'django_version': 'unknown'
    }
}

# Find Django version separately to avoid complex nested expressions
for pkg in packages:
    if pkg['name'].lower() == 'django':
        release_info['system_info']['django_version'] = pkg['version']
        break

# Save comprehensive info
with open('/opt/cupcake/release-info/release_info.json', 'w') as f:
    json.dump(release_info, f, indent=2)

print('Release information generated successfully!')
PYEOF

echo 'Comprehensive release info file created successfully!'
