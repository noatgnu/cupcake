#!/bin/bash -e
# Generate ontology statistics for release

set -euo pipefail

# Source environment variables
set -a  # automatically export all variables
source /etc/environment.d/cupcake.conf
set +a  # stop automatically exporting

cd /opt/cupcake/app && source /opt/cupcake/venv/bin/activate

# Set Python path
export PYTHONPATH=/opt/cupcake/app

echo 'Generating ontology statistics for release...'

python manage.py shell <<'PYEOF'
import json
import os
try:
    from cc.models import (
        MondoDisease, UberonAnatomy, NCBITaxonomy, ChEBICompound, PSIMSOntology,
        Species, Unimod, Tissue, HumanDisease, MSUniqueVocabularies,
        SubcellularLocation, CellType
    )
    print("Successfully imported Django models")
except Exception as e:
    print(f"ERROR importing models: {e}")
    raise

try:
    stats = {
        'ontology_statistics': {
            'MONDO_Disease_Ontology': MondoDisease.objects.count(),
            'UBERON_Anatomy': UberonAnatomy.objects.count(),
            'NCBI_Taxonomy': NCBITaxonomy.objects.count(),
            'ChEBI_Compounds': ChEBICompound.objects.count(),
            'PSI_MS_Ontology': PSIMSOntology.objects.count(),
            'UniProt_Species': Species.objects.count(),
            'UniMod_Modifications': Unimod.objects.count(),
            'UniProt_Tissues': Tissue.objects.count(),
            'UniProt_Human_Diseases': HumanDisease.objects.count(),
            'MS_Unique_Vocabularies': MSUniqueVocabularies.objects.count(),
            'Subcellular_Locations': SubcellularLocation.objects.count(),
            'Cell_Types': CellType.objects.count()
        },
        'total_records': sum([
            MondoDisease.objects.count(),
            UberonAnatomy.objects.count(),
            NCBITaxonomy.objects.count(),
            ChEBICompound.objects.count(),
            PSIMSOntology.objects.count(),
            Species.objects.count(),
            Unimod.objects.count(),
            Tissue.objects.count(),
            HumanDisease.objects.count(),
            MSUniqueVocabularies.objects.count(),
            SubcellularLocation.objects.count(),
            CellType.objects.count()
        ])
    }

    # Save to file for GitHub release
    os.makedirs('/opt/cupcake/release-info', exist_ok=True)
    with open('/opt/cupcake/release-info/ontology_statistics.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print('Ontology statistics generated successfully!')
    print(f'Total ontology records: {stats["total_records"]:,}')
    print(f'Stats keys created: {list(stats.keys())}')
    print(f'JSON file will contain: total_records = {stats["total_records"]}')

except Exception as e:
    print(f"ERROR generating ontology statistics: {e}")
    print("Creating minimal stats file to prevent build failure")
    stats = {
        'ontology_statistics': {},
        'total_records': 0
    }
    os.makedirs('/opt/cupcake/release-info', exist_ok=True)
    with open('/opt/cupcake/release-info/ontology_statistics.json', 'w') as f:
        json.dump(stats, f, indent=2)
    raise
PYEOF

# Verify the ontology statistics file was created
if [ ! -f "/opt/cupcake/release-info/ontology_statistics.json" ]; then
    echo "❌ ERROR: ontology_statistics.json was not created!"
    echo "The ontology statistics generation failed silently."
    exit 1
else
    echo "✅ ontology_statistics.json created successfully"
    echo "File size: $(du -k /opt/cupcake/release-info/ontology_statistics.json | cut -f1)K"
fi
