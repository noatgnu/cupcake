"""
Comprehensive ontology loading system for SDRF-proteomics metadata.

This command downloads and loads multiple authoritative ontology resources:
- MONDO Disease Ontology (diseases)
- UBERON Anatomy (tissues/organs) 
- NCBI Taxonomy (organisms)
- ChEBI (chemical compounds)
- PSI-MS Ontology (mass spectrometry terms)

Usage:
    python manage.py load_ontologies [--ontology ONTOLOGY] [--update-existing] [--limit N]
    
Ontologies:
    - all: Load all ontologies (default)
    - mondo: MONDO Disease Ontology
    - uberon: UBERON Anatomy 
    - ncbi: NCBI Taxonomy
    - chebi: ChEBI Compounds
    - psims: PSI-MS Ontology
"""

import requests
import json
import gzip
import xml.etree.ElementTree as ET
from django.core.management.base import BaseCommand, CommandError
from cc.models import MondoDisease, UberonAnatomy, NCBITaxonomy, ChEBICompound, PSIMSOntology
import time
import re
from pathlib import Path
import tempfile


class OBOParser:
    """Generic OBO format parser for ontology files."""
    
    def __init__(self):
        self.current_term = {}
        self.terms = []
        
    def parse_obo_content(self, content):
        """Parse OBO format content and return list of terms."""
        self.terms = []
        self.current_term = {}
        in_term = False
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line == '[Term]':
                if self.current_term:
                    self.terms.append(self.current_term.copy())
                self.current_term = {}
                in_term = True
                
            elif line.startswith('[') and line.endswith(']'):
                if self.current_term:
                    self.terms.append(self.current_term.copy())
                in_term = False
                
            elif in_term and ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'id':
                    self.current_term['id'] = value
                elif key == 'name':
                    self.current_term['name'] = value
                elif key == 'def':
                    # Extract definition from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        self.current_term['definition'] = match.group(1)
                elif key == 'synonym':
                    if 'synonyms' not in self.current_term:
                        self.current_term['synonyms'] = []
                    # Extract synonym from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        self.current_term['synonyms'].append(match.group(1))
                elif key == 'is_a':
                    if 'is_a' not in self.current_term:
                        self.current_term['is_a'] = []
                    # Extract just the ID (before any comments)
                    parent_id = value.split('!')[0].strip()
                    self.current_term['is_a'].append(parent_id)
                elif key == 'part_of':
                    if 'part_of' not in self.current_term:
                        self.current_term['part_of'] = []
                    parent_id = value.split('!')[0].strip()
                    self.current_term['part_of'].append(parent_id)
                elif key == 'xref':
                    if 'xrefs' not in self.current_term:
                        self.current_term['xrefs'] = []
                    self.current_term['xrefs'].append(value)
                elif key == 'is_obsolete':
                    self.current_term['obsolete'] = value.lower() == 'true'
                elif key == 'replaced_by':
                    self.current_term['replaced_by'] = value
        
        # Add last term
        if self.current_term:
            self.terms.append(self.current_term.copy())
            
        return self.terms


class Command(BaseCommand):
    help = 'Load comprehensive ontologies for SDRF proteomics metadata'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ontology',
            type=str,
            default='all',
            choices=['all', 'mondo', 'uberon', 'ncbi', 'chebi', 'psims'],
            help='Ontology to load'
        )
        parser.add_argument(
            '--chebi-filter',
            type=str,
            default='all',
            choices=['all', 'proteomics', 'metabolomics', 'lipidomics'],
            help='Filter ChEBI compounds by research area'
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing records'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of records to process'
        )
        parser.add_argument(
            '--skip-large',
            action='store_true',
            help='Skip large ontologies (NCBI, ChEBI) for testing'
        )

    def handle(self, *args, **options):
        ontology = options['ontology']
        update_existing = options['update_existing']
        limit = options['limit']
        skip_large = options['skip_large']
        chebi_filter = options['chebi_filter']
        
        self.stdout.write(f'Loading ontology: {ontology}')
        if ontology in ['all', 'chebi'] and chebi_filter != 'all':
            self.stdout.write(f'ChEBI filter: {chebi_filter}')
        
        total_created = 0
        total_updated = 0
        
        if ontology in ['all', 'mondo']:
            created, updated = self.load_mondo_disease(update_existing, limit)
            total_created += created
            total_updated += updated
            
        if ontology in ['all', 'uberon']:
            created, updated = self.load_uberon_anatomy(update_existing, limit)
            total_created += created
            total_updated += updated
            
        if ontology in ['all', 'ncbi'] and not skip_large:
            created, updated = self.load_ncbi_taxonomy(update_existing, limit)
            total_created += created
            total_updated += updated
            
        if ontology in ['all', 'chebi'] and not skip_large:
            created, updated = self.load_chebi_compounds(update_existing, limit, chebi_filter)
            total_created += created
            total_updated += updated
            
        if ontology in ['all', 'psims']:
            created, updated = self.load_psims_ontology(update_existing, limit)
            total_created += created
            total_updated += updated
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully loaded {total_created} new and updated {total_updated} existing terms.'
            )
        )

    def load_mondo_disease(self, update_existing=False, limit=10000):
        """Load MONDO Disease Ontology."""
        self.stdout.write('Loading MONDO Disease Ontology...')
        
        mondo_url = "http://purl.obolibrary.org/obo/mondo.obo"
        
        try:
            response = requests.get(mondo_url, timeout=120)
            response.raise_for_status()
            
            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            for term_data in terms:
                if limit is not None and processed >= limit:
                    break
                    
                if not term_data.get('id', '').startswith('MONDO:'):
                    continue
                    
                created, updated = self._process_mondo_term(term_data, update_existing)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
                processed += 1
                
                if processed % 500 == 0:
                    self.stdout.write(f'Processed {processed} MONDO terms...')
            
            self.stdout.write(f'MONDO: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading MONDO: {e}'))
            return 0, 0

    def _process_mondo_term(self, term_data, update_existing):
        """Process a single MONDO term."""
        if term_data.get('obsolete', False):
            return False, False
            
        identifier = term_data.get('id', '')
        name = term_data.get('name', '')
        definition = term_data.get('definition', '')
        synonyms = term_data.get('synonyms', [])
        xrefs = term_data.get('xrefs', [])
        parent_terms = term_data.get('is_a', [])
        replacement = term_data.get('replaced_by', '')
        
        if not name or not identifier:
            return False, False
        
        disease_data = {
            'identifier': identifier,
            'name': name,
            'definition': definition,
            'synonyms': ';'.join(synonyms) if synonyms else '',
            'xrefs': ';'.join(xrefs) if xrefs else '',
            'parent_terms': ';'.join(parent_terms) if parent_terms else '',
            'replacement_term': replacement
        }
        
        try:
            disease, created = MondoDisease.objects.get_or_create(
                identifier=identifier,
                defaults=disease_data
            )
            
            if not created and update_existing:
                for key, value in disease_data.items():
                    setattr(disease, key, value)
                disease.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing {name}: {e}')
            return False, False

    def load_uberon_anatomy(self, update_existing=False, limit=10000):
        """Load UBERON Anatomy Ontology."""
        self.stdout.write('Loading UBERON Anatomy Ontology...')
        
        uberon_url = "http://purl.obolibrary.org/obo/uberon.obo"
        
        try:
            response = requests.get(uberon_url, timeout=120)
            response.raise_for_status()
            
            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            for term_data in terms:
                if limit is not None and processed >= limit:
                    break
                    
                if not term_data.get('id', '').startswith('UBERON:'):
                    continue
                    
                created, updated = self._process_uberon_term(term_data, update_existing)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
                processed += 1
                
                if processed % 500 == 0:
                    self.stdout.write(f'Processed {processed} UBERON terms...')
            
            self.stdout.write(f'UBERON: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading UBERON: {e}'))
            return 0, 0

    def _process_uberon_term(self, term_data, update_existing):
        """Process a single UBERON term."""
        if term_data.get('obsolete', False):
            return False, False
            
        identifier = term_data.get('id', '')
        name = term_data.get('name', '')
        definition = term_data.get('definition', '')
        synonyms = term_data.get('synonyms', [])
        xrefs = term_data.get('xrefs', [])
        parent_terms = term_data.get('is_a', [])
        part_of = term_data.get('part_of', [])
        replacement = term_data.get('replaced_by', '')
        
        if not name or not identifier:
            return False, False
        
        anatomy_data = {
            'identifier': identifier,
            'name': name,
            'definition': definition,
            'synonyms': ';'.join(synonyms) if synonyms else '',
            'xrefs': ';'.join(xrefs) if xrefs else '',
            'parent_terms': ';'.join(parent_terms) if parent_terms else '',
            'part_of': ';'.join(part_of) if part_of else '',
            'replacement_term': replacement
        }
        
        try:
            anatomy, created = UberonAnatomy.objects.get_or_create(
                identifier=identifier,
                defaults=anatomy_data
            )
            
            if not created and update_existing:
                for key, value in anatomy_data.items():
                    setattr(anatomy, key, value)
                anatomy.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing {name}: {e}')
            return False, False

    def load_ncbi_taxonomy(self, update_existing=False, limit=10000):
        """Load NCBI Taxonomy data."""
        self.stdout.write('Loading NCBI Taxonomy...')
        
        # NCBI taxonomy files
        names_url = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"
        
        try:
            self.stdout.write('Downloading NCBI taxonomy data (this may take a while)...')
            response = requests.get(names_url, timeout=300)
            response.raise_for_status()
            
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                # Save and extract the tar.gz file
                tar_path = Path(temp_dir) / "taxdump.tar.gz"
                with open(tar_path, 'wb') as f:
                    f.write(response.content)
                
                # Extract using Python (cross-platform)
                import tarfile
                with tarfile.open(tar_path, 'r:gz') as tar:
                    tar.extractall(temp_dir)
                
                # Process names.dmp and nodes.dmp
                names_file = Path(temp_dir) / "names.dmp"
                nodes_file = Path(temp_dir) / "nodes.dmp"
                
                created_count, updated_count = self._process_ncbi_files(
                    names_file, nodes_file, update_existing, limit
                )
            
            self.stdout.write(f'NCBI Taxonomy: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error processing NCBI Taxonomy: {e}'))
            return 0, 0

    def _process_ncbi_files(self, names_file, nodes_file, update_existing, limit):
        """Process NCBI taxonomy names and nodes files."""
        # First, load nodes data for taxonomy hierarchy
        nodes_data = {}
        with open(nodes_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = [p.strip() for p in line.split('\t|\t')]
                if len(parts) >= 3:
                    tax_id = int(parts[0])
                    parent_tax_id = int(parts[1])
                    rank = parts[2]
                    nodes_data[tax_id] = {
                        'parent_tax_id': parent_tax_id if parent_tax_id != tax_id else None,
                        'rank': rank
                    }
        
        # Then process names
        taxa_data = {}
        with open(names_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = [p.strip() for p in line.split('\t|\t')]
                if len(parts) >= 4:
                    tax_id = int(parts[0])
                    name = parts[1]
                    name_class = parts[3].rstrip('\t|')
                    
                    if tax_id not in taxa_data:
                        taxa_data[tax_id] = {
                            'scientific_name': '',
                            'common_name': '',
                            'synonyms': []
                        }
                    
                    if name_class == 'scientific name':
                        taxa_data[tax_id]['scientific_name'] = name
                    elif name_class == 'genbank common name':
                        taxa_data[tax_id]['common_name'] = name
                    elif name_class in ['synonym', 'common name']:
                        taxa_data[tax_id]['synonyms'].append(name)
        
        # Create taxonomy records
        created_count = 0
        updated_count = 0
        processed = 0
        
        for tax_id, data in taxa_data.items():
            if limit is not None and processed >= limit:
                break
                
            if not data['scientific_name']:
                continue
                
            node_info = nodes_data.get(tax_id, {})
            
            taxonomy_data = {
                'tax_id': tax_id,
                'scientific_name': data['scientific_name'],
                'common_name': data['common_name'] or None,
                'synonyms': ';'.join(data['synonyms']) if data['synonyms'] else '',
                'rank': node_info.get('rank', ''),
                'parent_tax_id': node_info.get('parent_tax_id')
            }
            
            try:
                taxonomy, created = NCBITaxonomy.objects.get_or_create(
                    tax_id=tax_id,
                    defaults=taxonomy_data
                )
                
                if not created and update_existing:
                    for key, value in taxonomy_data.items():
                        setattr(taxonomy, key, value)
                    taxonomy.save()
                    updated_count += 1
                elif created:
                    created_count += 1
                    
                processed += 1
                
                if processed % 1000 == 0:
                    self.stdout.write(f'Processed {processed} taxa...')
                    
            except Exception as e:
                self.stdout.write(f'Error processing tax_id {tax_id}: {e}')
        
        return created_count, updated_count

    def load_chebi_compounds(self, update_existing=False, limit=10000, chebi_filter='all'):
        """Load ChEBI compound ontology."""
        self.stdout.write('Loading ChEBI compounds...')
        
        chebi_url = "http://purl.obolibrary.org/obo/chebi.obo"
        
        try:
            response = requests.get(chebi_url, timeout=300)
            response.raise_for_status()
            
            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            for term_data in terms:
                if limit is not None and processed >= limit:
                    break
                    
                if not term_data.get('id', '').startswith('CHEBI:'):
                    continue
                    
                created, updated = self._process_chebi_term(term_data, update_existing, chebi_filter)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
                processed += 1
                
                if processed % 1000 == 0:
                    self.stdout.write(f'Processed {processed} ChEBI terms...')
            
            self.stdout.write(f'ChEBI: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading ChEBI: {e}'))
            return 0, 0

    def _process_chebi_term(self, term_data, update_existing, chebi_filter='all'):
        """Process a single ChEBI term."""
        if term_data.get('obsolete', False):
            return False, False
            
        identifier = term_data.get('id', '')
        name = term_data.get('name', '')
        definition = term_data.get('definition', '')
        synonyms = term_data.get('synonyms', [])
        parent_terms = term_data.get('is_a', [])
        replacement = term_data.get('replaced_by', '')
        
        if not name or not identifier:
            return False, False
        
        # Apply ChEBI filtering based on research area
        if chebi_filter != 'all':
            if not self._matches_chebi_filter(name, definition, synonyms, chebi_filter):
                return False, False

        compound_data = {
            'identifier': identifier,
            'name': name,
            'definition': definition,
            'synonyms': ';'.join(synonyms) if synonyms else '',
            'parent_terms': ';'.join(parent_terms) if parent_terms else '',
            'replacement_term': replacement
        }
        
        try:
            compound, created = ChEBICompound.objects.get_or_create(
                identifier=identifier,
                defaults=compound_data
            )
            
            if not created and update_existing:
                for key, value in compound_data.items():
                    setattr(compound, key, value)
                compound.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing {name}: {e}')
            return False, False

    def _matches_chebi_filter(self, name, definition, synonyms, chebi_filter):
        """Check if a ChEBI term matches the specified research area filter."""
        search_text = f"{name.lower()} {definition.lower()} {' '.join(synonyms).lower()}"
        
        if chebi_filter == 'proteomics':
            proteomics_keywords = [
                'protein', 'peptide', 'amino acid', 'trypsin', 'enzyme', 'protease',
                'buffer', 'tris', 'bicine', 'hepes', 'bis-tris', 'tricine',
                'urea', 'thiourea', 'guanidine', 'dtt', 'tcep', 'iodoacetamide',
                'acetonitrile', 'formic acid', 'trifluoroacetic acid', 'acetic acid',
                'methanol', 'water', 'ammonium', 'bicarbonate', 'phosphate',
                'detergent', 'sds', 'triton', 'tween', 'chaps', 'deoxycholate',
                'reagent', 'modifier', 'labeling', 'tag', 'dye', 'fluorophore',
                'crosslink', 'digest', 'reduction', 'alkylation', 'derivatization'
            ]
            return any(keyword in search_text for keyword in proteomics_keywords)
            
        elif chebi_filter == 'metabolomics':
            metabolomics_keywords = [
                'metabolite', 'lipid', 'fatty acid', 'steroid', 'hormone',
                'nucleotide', 'nucleoside', 'sugar', 'carbohydrate', 'glucose',
                'amino acid', 'organic acid', 'carboxylic acid', 'phenolic',
                'alkaloid', 'flavonoid', 'terpenoid', 'polyketide',
                'vitamin', 'cofactor', 'coenzyme', 'prostaglandin',
                'neurotransmitter', 'bile acid', 'sphingolipid',
                'phospholipid', 'glycerolipid', 'cholesterol', 'ceramide'
            ]
            return any(keyword in search_text for keyword in metabolomics_keywords)
            
        elif chebi_filter == 'lipidomics':
            lipidomics_keywords = [
                'lipid', 'fatty acid', 'phospholipid', 'sphingolipid',
                'glycerolipid', 'sterol', 'cholesterol', 'ceramide',
                'phosphatidyl', 'lyso', 'plasmalogen', 'cardiolipin',
                'triglyceride', 'diglyceride', 'monoglyceride',
                'sphingomyelin', 'glucosylceramide', 'galactosylceramide',
                'phosphatidic acid', 'phosphatidylcholine', 'phosphatidylethanolamine',
                'phosphatidylserine', 'phosphatidylinositol', 'phosphatidylglycerol',
                'arachidonic acid', 'oleic acid', 'palmitic acid', 'stearic acid',
                'linoleic acid', 'docosahexaenoic acid', 'eicosapentaenoic acid'
            ]
            return any(keyword in search_text for keyword in lipidomics_keywords)
            
        return True  # Default case, shouldn't reach here

    def load_psims_ontology(self, update_existing=False, limit=10000):
        """Load PSI-MS Ontology."""
        self.stdout.write('Loading PSI-MS Ontology...')
        
        psims_url = "http://purl.obolibrary.org/obo/ms.obo"
        
        try:
            response = requests.get(psims_url, timeout=120)
            response.raise_for_status()
            
            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)
            
            created_count = 0
            updated_count = 0
            processed = 0
            
            for term_data in terms:
                if limit is not None and processed >= limit:
                    break
                    
                if not term_data.get('id', '').startswith('MS:'):
                    continue
                    
                created, updated = self._process_psims_term(term_data, update_existing)
                if created:
                    created_count += 1
                if updated:
                    updated_count += 1
                processed += 1
                
                if processed % 500 == 0:
                    self.stdout.write(f'Processed {processed} PSI-MS terms...')
            
            self.stdout.write(f'PSI-MS: {created_count} created, {updated_count} updated')
            return created_count, updated_count
            
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error downloading PSI-MS: {e}'))
            return 0, 0

    def _process_psims_term(self, term_data, update_existing):
        """Process a single PSI-MS term."""
        if term_data.get('obsolete', False):
            return False, False
            
        identifier = term_data.get('id', '')
        name = term_data.get('name', '')
        definition = term_data.get('definition', '')
        synonyms = term_data.get('synonyms', [])
        parent_terms = term_data.get('is_a', [])
        replacement = term_data.get('replaced_by', '')
        
        if not name or not identifier:
            return False, False
        
        # Determine category based on parent terms or name
        category = 'other'
        if any('instrument' in parent.lower() for parent in parent_terms):
            category = 'instrument'
        elif any('method' in parent.lower() or 'technique' in parent.lower() for parent in parent_terms):
            category = 'method'
        elif 'instrument' in name.lower():
            category = 'instrument'
        elif any(keyword in name.lower() for keyword in ['method', 'technique', 'mode']):
            category = 'method'
        
        ontology_data = {
            'identifier': identifier,
            'name': name,
            'definition': definition,
            'synonyms': ';'.join(synonyms) if synonyms else '',
            'parent_terms': ';'.join(parent_terms) if parent_terms else '',
            'category': category,
            'replacement_term': replacement
        }
        
        try:
            ontology_term, created = PSIMSOntology.objects.get_or_create(
                identifier=identifier,
                defaults=ontology_data
            )
            
            if not created and update_existing:
                for key, value in ontology_data.items():
                    setattr(ontology_term, key, value)
                ontology_term.save()
                return False, True
                
            return created, False
            
        except Exception as e:
            self.stdout.write(f'Error processing {name}: {e}')
            return False, False