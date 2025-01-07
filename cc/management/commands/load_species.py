import re

import requests
from django.core.management.base import BaseCommand
from cc.models import Species

def parse_uniprot_species(file_path: str = None):
    Species.objects.all().delete()
    species = {}
    if not file_path:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/speclist.txt"
        response = requests.get(url)
        file = response.text.split("\n")
    else:
        file = open(file_path, 'rt')

    for line in file:
        match = re.match(r'^(\w+)\s+[VABEO]\s+(\d+):\s+N=(.*)$', line)
        if match:
            if species:
                if species['synonym'] == 'Synonym':
                    species = {}
                else:
                    Species.objects.create(**species)
            species = {
                'code': match.group(1),
                'taxon': int(match.group(2)),
                'official_name': match.group(3),
                'common_name': None,
                'synonym': None
            }
        else:
            # Match the continuation line for common name or synonym
            match = re.match(r'^\s+C=(.*)$', line)
            if match:
                species['common_name'] = match.group(1)
            match = re.match(r'^\s+S=(.*)$', line)
            if match:
                species['synonym'] = match.group(1)

    if not isinstance(file, list):
        file.close()


class Command(BaseCommand):
    help = 'Load UniProt controlled vocabulary species data into the database.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, nargs='?', help='The path to the species data file.')

    def handle(self, *args, **options):
        file_path = options['file']
        parse_uniprot_species(file_path)
