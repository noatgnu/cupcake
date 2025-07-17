"""
Django management command to load cell types and cell lines for SDRF proteomics metadata.

This command downloads data from multiple authoritative sources:
- Cell Ontology (CL) from OBO Foundry
- Cellosaurus database for cell lines
- EBI Cell Line Ontology

Usage:
    python manage.py load_cell_types [--source SOURCE] [--update-existing]
    
Sources:
    - all: Download from all sources (default)
    - cl: Cell Ontology only
    - cellosaurus: Cellosaurus database only
    - manual: Use manual curated list only
"""

import requests
import json
import xml.etree.ElementTree as ET
from django.core.management.base import BaseCommand, CommandError
from cc.models import CellType
import time
import re


class Command(BaseCommand):
    help = 'Load cell types and cell lines for SDRF proteomics metadata'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='cl',
            choices=['all', 'cl', 'cellosaurus', 'manual'],
            help='Data source to use'
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing records'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=1000,
            help='Limit number of records to process (for testing)'
        )

    def handle(self, *args, **options):
        source = options['source']
        update_existing = options['update_existing']
        limit = options['limit']
        
        self.stdout.write(f'Loading cell types from source: {source}')
        
        total_created = 0
        total_updated = 0
        
        if source in ['all', 'cl']:
            created, updated = self.load_from_cell_ontology(update_existing, limit)
            total_created += created
            total_updated += updated
            
        if source in ['all', 'cellosaurus']:
            created, updated = self.load_from_cellosaurus(update_existing, limit)
            total_created += created
            total_updated += updated
            
        if source in ['all', 'manual']:
            created, updated = self.load_manual_cell_types(update_existing)
            total_created += created
            total_updated += updated
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully loaded {total_created} new and updated {total_updated} existing cell types.'
            )
        )

    def load_from_cell_ontology(self, update_existing=False, limit=1000):
        """Load cell types from Cell Ontology (CL) via OBO Foundry."""
        self.stdout.write('Loading from Cell Ontology (CL)...')
        
        # Cell Ontology OBO file URL
        cl_url = "http://purl.obolibrary.org/obo/cl.obo"
        
        try:
            response = requests.get(cl_url, timeout=60)
            response.raise_for_status()
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            # Parse OBO format
            current_term = {}
            in_term = False
            
            for line in response.text.split('\n'):
                line = line.strip()
                
                if line == '[Term]':
                    if current_term and processed < limit:
                        created, updated = self._process_cl_term(current_term, update_existing)
                        if created:
                            created_count += 1
                        if updated:
                            updated_count += 1
                        processed += 1
                        
                        if processed % 100 == 0:
                            self.stdout.write(f'Processed {processed} terms...')
                    
                    current_term = {}
                    in_term = True
                    
                elif line.startswith('[') and line.endswith(']'):
                    in_term = False
                    
                elif in_term and ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'id':
                        current_term['id'] = value
                    elif key == 'name':
                        current_term['name'] = value
                    elif key == 'def':
                        # Extract definition from quotes
                        match = re.search(r'"([^"]*)"', value)
                        if match:
                            current_term['definition'] = match.group(1)
                    elif key == 'synonym':
                        if 'synonyms' not in current_term:
                            current_term['synonyms'] = []
                        # Extract synonym from quotes
                        match = re.search(r'"([^"]*)"', value)
                        if match:
                            current_term['synonyms'].append(match.group(1))
                    elif key == 'is_obsolete':
                        current_term['obsolete'] = value.lower() == 'true'
            
            # Process last term
            if current_term and processed < limit:
                created, updated = self._process_cl_term(current_term, update_existing)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
            
            self.stdout.write(f'Cell Ontology: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading Cell Ontology: {e}'))
            return 0, 0

    def _process_cl_term(self, term_data, update_existing):
        """Process a single Cell Ontology term."""
        if term_data.get('obsolete', False):
            return False, False
            
        cl_id = term_data.get('id', '')
        name = term_data.get('name', '')
        definition = term_data.get('definition', '')
        synonyms = term_data.get('synonyms', [])
        
        # Skip if no name or not a cell type we want
        if not name or not cl_id.startswith('CL:'):
            return False, False
            
        # Filter for relevant cell types (basic filtering)
        cell_keywords = ['cell', 'blast', 'cyte', 'phage', 'neuron']
        if not any(keyword in name.lower() for keyword in cell_keywords):
            return False, False
        
        identifier = f"cl_{cl_id.replace(':', '_').lower()}"
        
        cell_data = {
            'identifier': identifier,
            'name': name,
            'description': definition,
            'cell_line': False,  # Cell Ontology is primarily for primary cell types
            'accession': cl_id,
            'synonyms': ';'.join(synonyms) if synonyms else ''
        }
        
        try:
            cell_type, created = CellType.objects.get_or_create(
                identifier=identifier,
                defaults=cell_data
            )
            
            if not created and update_existing:
                for key, value in cell_data.items():
                    setattr(cell_type, key, value)
                cell_type.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing {name}: {e}')
            return False, False

    def load_from_cellosaurus(self, update_existing=False, limit=1000):
        """Load cell lines from Cellosaurus database."""
        self.stdout.write('Loading from Cellosaurus...')
        
        # Cellosaurus XML download URL
        cellosaurus_url = "https://ftp.expasy.org/databases/cellosaurus/cellosaurus.xml"
        
        try:
            self.stdout.write('Downloading Cellosaurus database (this may take a while)...')
            response = requests.get(cellosaurus_url, timeout=300)
            response.raise_for_status()
            
            self.stdout.write('Parsing XML data...')
            root = ET.fromstring(response.content)
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            # Find all cell line entries
            for cell_line in root.findall('.//cell-line'):
                if processed >= limit:
                    break
                    
                created, updated = self._process_cellosaurus_cell_line(cell_line, update_existing)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
                processed += 1
                
                if processed % 100 == 0:
                    self.stdout.write(f'Processed {processed} cell lines...')
            
            self.stdout.write(f'Cellosaurus: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading Cellosaurus: {e}'))
            return 0, 0
        except ET.ParseError as e:
            self.stdout.write(self.style.ERROR(f'Error parsing Cellosaurus XML: {e}'))
            return 0, 0

    def _process_cellosaurus_cell_line(self, cell_line_element, update_existing):
        """Process a single Cellosaurus cell line entry."""
        try:
            # Extract basic information
            accession = cell_line_element.get('accession', '')
            name_elements = cell_line_element.findall('.//name[@type="identifier"]')
            name = name_elements[0].text if name_elements else ''
            
            if not name or not accession:
                return False, False
            
            # Extract synonyms
            synonym_elements = cell_line_element.findall('.//name[@type="synonym"]')
            synonyms = [elem.text for elem in synonym_elements if elem.text]
            
            # Extract organism
            organism_elements = cell_line_element.findall('.//species-list/species')
            organism = ''
            if organism_elements:
                org_elem = organism_elements[0]
                genus = org_elem.get('genus', '')
                species = org_elem.get('species', '')
                if genus and species:
                    organism = f"{genus} {species}"
            
            # Extract tissue/origin
            tissue_origin = ''
            derived_from = cell_line_element.findall('.//derived-from')
            if derived_from:
                tissue_origin = derived_from[0].get('site', '')
            
            # Extract disease context
            disease_context = ''
            disease_elements = cell_line_element.findall('.//disease-list/disease')
            if disease_elements:
                disease_context = disease_elements[0].get('terminology', '')
            
            # Extract comments for description
            description = ''
            comment_elements = cell_line_element.findall('.//comment-list/comment[@category="Characteristics"]')
            if comment_elements:
                description = comment_elements[0].text or ''
            
            identifier = f"cellosaurus_{accession.lower()}"
            
            cell_data = {
                'identifier': identifier,
                'name': name,
                'description': description,
                'cell_line': True,  # Cellosaurus is primarily cell lines
                'organism': organism,
                'tissue_origin': tissue_origin,
                'disease_context': disease_context,
                'accession': accession,
                'synonyms': ';'.join(synonyms) if synonyms else ''
            }
            
            cell_type, created = CellType.objects.get_or_create(
                identifier=identifier,
                defaults=cell_data
            )
            
            if not created and update_existing:
                for key, value in cell_data.items():
                    setattr(cell_type, key, value)
                cell_type.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing cell line: {e}')
            return False, False

    def load_manual_cell_types(self, update_existing=False):
        """Load manually curated cell types and cell lines commonly used in proteomics."""
        self.stdout.write('Loading manually curated cell types and cell lines...')
        
        # Common cell lines used in proteomics (high-priority for SDRF)
        cell_lines = [
            {
                'identifier': 'HEK293',
                'name': 'HEK293',
                'description': 'Human embryonic kidney 293 cells',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'kidney',
                'synonyms': 'HEK 293;293;HEK-293'
            },
            {
                'identifier': 'HeLa',
                'name': 'HeLa',
                'description': 'Human cervical cancer cell line',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'cervix',
                'disease_context': 'cervical cancer',
                'synonyms': 'HeLa cells;Hela'
            },
            {
                'identifier': 'MCF-7',
                'name': 'MCF-7',
                'description': 'Human breast cancer cell line',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'breast',
                'disease_context': 'breast cancer',
                'synonyms': 'MCF7;MCF 7'
            },
            {
                'identifier': 'A549',
                'name': 'A549',
                'description': 'Human lung cancer cell line',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'lung',
                'disease_context': 'lung cancer'
            },
            {
                'identifier': 'Jurkat',
                'name': 'Jurkat',
                'description': 'Human T lymphoblast cell line',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'blood',
                'disease_context': 'T cell leukemia',
                'synonyms': 'Jurkat cells'
            },
            {
                'identifier': 'U2OS',
                'name': 'U2OS',
                'description': 'Human osteosarcoma cell line',
                'cell_line': True,
                'organism': 'Homo sapiens',
                'tissue_origin': 'bone',
                'disease_context': 'osteosarcoma',
                'synonyms': 'U-2 OS'
            },
            {
                'identifier': 'COS-7',
                'name': 'COS-7',
                'description': 'African green monkey kidney fibroblast-like cell line',
                'cell_line': True,
                'organism': 'Chlorocebus aethiops',
                'tissue_origin': 'kidney',
                'synonyms': 'COS7;COS 7'
            },
            {
                'identifier': 'CHO',
                'name': 'CHO',
                'description': 'Chinese hamster ovary cell line',
                'cell_line': True,
                'organism': 'Cricetulus griseus',
                'tissue_origin': 'ovary',
                'synonyms': 'CHO cells;Chinese hamster ovary'
            },
            {
                'identifier': 'NIH3T3',
                'name': 'NIH3T3',
                'description': 'Mouse embryonic fibroblast cell line',
                'cell_line': True,
                'organism': 'Mus musculus',
                'tissue_origin': 'embryo',
                'synonyms': 'NIH 3T3;3T3;NIH-3T3'
            },
            {
                'identifier': 'PC12',
                'name': 'PC12',
                'description': 'Rat pheochromocytoma cell line',
                'cell_line': True,
                'organism': 'Rattus norvegicus',
                'tissue_origin': 'adrenal gland',
                'disease_context': 'pheochromocytoma',
                'synonyms': 'PC-12'
            }
        ]
        
        # Primary cell types commonly used in proteomics
        primary_cell_types = [
            {
                'identifier': 'epithelial_cell',
                'name': 'epithelial cell',
                'description': 'Cell that lines the surfaces and cavities of the body',
                'cell_line': False,
                'synonyms': 'epithelial;epithelium',
                'accession': 'CL:0000066'  # Cell Ontology
            },
            {
                'identifier': 'fibroblast',
                'name': 'fibroblast',
                'description': 'Connective tissue cell that synthesizes collagen and other matrix components',
                'cell_line': False,
                'synonyms': 'fibroblasts',
                'accession': 'CL:0000057'
            },
            {
                'identifier': 'macrophage',
                'name': 'macrophage',
                'description': 'Large phagocytic cell found in tissues',
                'cell_line': False,
                'synonyms': 'macrophages',
                'accession': 'CL:0000235'
            },
            {
                'identifier': 'lymphocyte',
                'name': 'lymphocyte',
                'description': 'White blood cell involved in immune responses',
                'cell_line': False,
                'synonyms': 'lymphocytes;T cell;B cell',
                'accession': 'CL:0000542'
            },
            {
                'identifier': 'neuron',
                'name': 'neuron',
                'description': 'Electrically excitable cell that processes and transmits information',
                'cell_line': False,
                'synonyms': 'neurons;nerve cell;neuronal cell',
                'accession': 'CL:0000540'
            },
            {
                'identifier': 'astrocyte',
                'name': 'astrocyte',
                'description': 'Star-shaped glial cell in the brain and spinal cord',
                'cell_line': False,
                'synonyms': 'astrocytes;astroglial cell',
                'accession': 'CL:0000127'
            },
            {
                'identifier': 'hepatocyte',
                'name': 'hepatocyte',
                'description': 'Main functional cell of the liver',
                'cell_line': False,
                'synonyms': 'hepatocytes;liver cell',
                'accession': 'CL:0000182'
            },
            {
                'identifier': 'keratinocyte',
                'name': 'keratinocyte',
                'description': 'Predominant cell type in the epidermis',
                'cell_line': False,
                'synonyms': 'keratinocytes',
                'accession': 'CL:0000312'
            },
            {
                'identifier': 'endothelial_cell',
                'name': 'endothelial cell',
                'description': 'Cell that lines the interior surface of blood vessels',
                'cell_line': False,
                'synonyms': 'endothelial;endothelium',
                'accession': 'CL:0000115'
            },
            {
                'identifier': 'stem_cell',
                'name': 'stem cell',
                'description': 'Undifferentiated cell capable of self-renewal and differentiation',
                'cell_line': False,
                'synonyms': 'stem cells;pluripotent cell',
                'accession': 'CL:0000034'
            },
            {
                'identifier': 'cancer_cell',
                'name': 'cancer cell',
                'description': 'Abnormal cell with uncontrolled growth',
                'cell_line': False,
                'synonyms': 'tumor cell;malignant cell;neoplastic cell',
                'accession': 'CL:0001064'
            }
        ]
        
        # Combine all cell types
        all_cell_types = cell_lines + primary_cell_types
        
        created_count = 0
        updated_count = 0
        
        for cell_data in all_cell_types:
            cell_type, created = CellType.objects.get_or_create(
                identifier=cell_data['identifier'],
                defaults=cell_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'Created: {cell_type.name}')
            else:
                # Update existing record
                for key, value in cell_data.items():
                    setattr(cell_type, key, value)
                cell_type.save()
                updated_count += 1
                self.stdout.write(f'Updated: {cell_type.name}')
        
        self.stdout.write(f'Manual curation: {created_count} created, {updated_count} updated')
        return created_count, updated_count