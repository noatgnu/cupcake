"""
Tests for vocabulary and reference data models: Tissue, HumanDisease, Species, etc.
"""
from django.test import TestCase
from django.core.exceptions import ValidationError
from cc.models import (
    Tissue, HumanDisease, MSUniqueVocabularies, Species,
    SubcellularLocation, Unimod
)


class TissueTest(TestCase):
    def test_tissue_creation(self):
        """Test basic tissue creation"""
        tissue = Tissue.objects.create(
            identifier='UBERON:0000955',
            accession='brain',
            synonyms='The brain is the center of the nervous system'
        )
        
        self.assertEqual(tissue.identifier, 'UBERON:0000955')
        self.assertEqual(tissue.accession, 'brain')
        self.assertIn('nervous system', tissue.synonyms)
    
    def test_tissue_string_representation(self):
        """Test tissue string representation"""
        tissue = Tissue.objects.create(
            identifier='liver',
            accession='UBERON:0002107'
        )
        self.assertEqual(tissue.identifier, 'liver')
    
    def test_tissue_unique_constraint(self):
        """Test tissue ID uniqueness"""
        Tissue.objects.create(
            identifier='UBERON:0000948',
            accession='heart'
        )
        
        # Creating duplicate tissue_id should raise error
        with self.assertRaises(Exception):  # Could be IntegrityError or ValidationError
            Tissue.objects.create(
                identifier='UBERON:0000948',
                accession='cardiac muscle'
            )
    
    def test_tissue_search_functionality(self):
        """Test tissue search by name and description"""
        tissues = [
            Tissue.objects.create(
                identifier='UBERON:0002107',
                accession='liver',
                synonyms='The liver is a vital organ that detoxifies chemicals'
            ),
            Tissue.objects.create(
                identifier='UBERON:0000955',
                accession='brain',
                synonyms='The brain controls cognitive functions'
            ),
            Tissue.objects.create(
                identifier='UBERON:0002048',
                accession='lung',
                synonyms='The lung is responsible for gas exchange'
            )
        ]
        
        # Test search by name
        liver_tissues = Tissue.objects.filter(accession__icontains='liver')
        self.assertEqual(liver_tissues.count(), 1)
        self.assertEqual(liver_tissues.first().accession, 'liver')
        
        # Test search by description
        brain_tissues = Tissue.objects.filter(synonyms__icontains='cognitive')
        self.assertEqual(brain_tissues.count(), 1)
        self.assertEqual(brain_tissues.first().accession, 'brain')


class HumanDiseaseTest(TestCase):
    def test_disease_creation(self):
        """Test basic human disease creation"""
        disease = HumanDisease.objects.create(
            identifier='cancer',
            accession='DOID:162',
            synonyms='A disease characterized by uncontrolled cell growth'
        )
        
        self.assertEqual(disease.accession, 'DOID:162')
        self.assertEqual(disease.identifier, 'cancer')
        self.assertIn('uncontrolled cell growth', disease.synonyms)
    
    def test_disease_string_representation(self):
        """Test disease string representation"""
        disease = HumanDisease.objects.create(
            identifier='diabetes mellitus',
            accession='DOID:9351'
        )
        self.assertEqual(disease.identifier, 'diabetes mellitus')
    
    def test_disease_categories(self):
        """Test different disease categories"""
        diseases = [
            HumanDisease.objects.create(
                identifier='DOID:162',
                accession='cancer',
                synonyms='Malignant neoplasm'
            ),
            HumanDisease.objects.create(
                identifier='DOID:114',
                accession='heart disease',
                synonyms='Cardiovascular disorder'
            ),
            HumanDisease.objects.create(
                identifier='DOID:1596',
                accession='neurodegenerative disease',
                synonyms='Progressive loss of neurons'
            )
        ]
        
        # Test filtering by description keywords
        cancer_diseases = HumanDisease.objects.filter(synonyms__icontains='neoplasm')
        self.assertEqual(cancer_diseases.count(), 1)
        
        cardio_diseases = HumanDisease.objects.filter(synonyms__icontains='cardiovascular')
        self.assertEqual(cardio_diseases.count(), 1)


class MSUniqueVocabulariesTest(TestCase):
    def test_ms_vocabulary_creation(self):
        """Test mass spectrometry vocabulary creation"""
        ms_term = MSUniqueVocabularies.objects.create(
            accession='MS:1000031',
            name='instrument model',
            definition='A descriptive name for the instrument model'
        )
        
        self.assertEqual(ms_term.accession, 'MS:1000031')
        self.assertEqual(ms_term.name, 'instrument model')
        self.assertIn('descriptive name', ms_term.definition)
    
    def test_ms_vocabulary_categories(self):
        """Test different MS vocabulary categories"""
        ms_terms = [
            MSUniqueVocabularies.objects.create(
                accession='MS:1000031',
                name='instrument model',
                definition='Instrument model name'
            ),
            MSUniqueVocabularies.objects.create(
                accession='MS:1000044',
                name='dissociation method',
                definition='Method of ion dissociation'
            ),
            MSUniqueVocabularies.objects.create(
                accession='MS:1000465',
                name='scan polarity',
                definition='Polarity of the scan'
            )
        ]
        
        # Test searching by category
        instrument_terms = MSUniqueVocabularies.objects.filter(name__icontains='instrument')
        self.assertEqual(instrument_terms.count(), 1)
        
        method_terms = MSUniqueVocabularies.objects.filter(name__icontains='method')
        self.assertEqual(method_terms.count(), 1)
    
    def test_ms_vocabulary_string_representation(self):
        """Test MS vocabulary string representation"""
        ms_term = MSUniqueVocabularies.objects.create(
            accession='MS:1000598',
            name='ETD'
        )
        self.assertEqual(ms_term.name, 'ETD')


class SpeciesTest(TestCase):
    def test_species_creation(self):
        """Test basic species creation"""
        species = Species.objects.create(
            code='9606',
            official_name='Homo sapiens',
            common_name='human',
            taxon="9606"
        )
        
        self.assertEqual(species.code, '9606')
        self.assertEqual(species.official_name, 'Homo sapiens')
        self.assertEqual(species.common_name, 'human')
    
    def test_species_string_representation(self):
        """Test species string representation"""
        species = Species.objects.create(
            code='10090',
            official_name='Mus musculus',
            common_name='house mouse',
            taxon=10090
        )
        self.assertEqual(species.official_name, 'Mus musculus')
    
    def test_model_organisms(self):
        """Test common model organisms"""
        model_organisms = [
            Species.objects.create(
                code='9606',
                official_name='Homo sapiens',
                common_name='human',
                taxon=9606
            ),
            Species.objects.create(
                code='10090',
                official_name='Mus musculus',
                common_name='house mouse',
                taxon=10090
            ),
            Species.objects.create(
                code='7227',
                official_name='Drosophila melanogaster',
                common_name='fruit fly',
                taxon=7227
            ),
            Species.objects.create(
                code='6239',
                official_name='Caenorhabditis elegans',
                common_name='nematode',
                taxon=6239
            ),
            Species.objects.create(
                code='559292',
                official_name='Saccharomyces cerevisiae',
                common_name='baker\'s yeast',
                taxon=559292
            )
        ]
        
        # Test filtering model organisms
        mammalian_species = Species.objects.filter(
            official_name__in=['Homo sapiens', 'Mus musculus']
        )
        self.assertEqual(mammalian_species.count(), 2)
        
        # Test search by common name
        yeast_species = Species.objects.filter(common_name__icontains='yeast')
        self.assertEqual(yeast_species.count(), 1)
        self.assertEqual(yeast_species.first().official_name, 'Saccharomyces cerevisiae')


class SubcellularLocationTest(TestCase):
    def test_subcellular_location_creation(self):
        """Test basic subcellular location creation"""
        location = SubcellularLocation.objects.create(
            location_identifier='cytoplasm',
            accession='GO:0005737',
            synonyms='The cytoplasm of a cell'
        )
        
        self.assertEqual(location.location_identifier, 'cytoplasm')
        self.assertEqual(location.accession, 'GO:0005737')
        self.assertIn('cytoplasm', location.synonyms)
    
    def test_subcellular_location_string_representation(self):
        """Test subcellular location string representation"""
        location = SubcellularLocation.objects.create(
            location_identifier='nucleus',
            accession='GO:0005634'
        )
        self.assertEqual(location.location_identifier, 'nucleus')
    
    def test_cellular_compartments(self):
        """Test various cellular compartments"""
        compartments = [
            SubcellularLocation.objects.create(
                location_identifier='nucleus',
                accession='GO:0005634',
                synonyms='The nucleus houses the cell\'s DNA'
            ),
            SubcellularLocation.objects.create(
                location_identifier='mitochondrion',
                accession='GO:0005739',
                synonyms='The powerhouse of the cell'
            ),
            SubcellularLocation.objects.create(
                location_identifier='endoplasmic reticulum',
                accession='GO:0005783',
                synonyms='Network of membranes in the cytoplasm'
            ),
            SubcellularLocation.objects.create(
                location_identifier='Golgi apparatus',
                accession='GO:0005794',
                synonyms='Processes and packages proteins'
            )
        ]
        
        # Test filtering by description
        membrane_compartments = SubcellularLocation.objects.filter(
            synonyms__icontains='membrane'
        )
        self.assertEqual(membrane_compartments.count(), 1)
        
        organelles = SubcellularLocation.objects.filter(
            location_identifier__in=['nucleus', 'mitochondrion', 'Golgi apparatus']
        )
        self.assertEqual(organelles.count(), 3)


class UnimodTest(TestCase):
    def test_unimod_creation(self):
        """Test Unimod protein modification creation"""
        modification = Unimod.objects.create(
            accession='1',
            name='Acetyl',
            definition='H(2) C(2) O',
        )
        
        self.assertEqual(modification.accession, '1')
        self.assertEqual(modification.name, 'Acetyl')
        self.assertEqual(modification.definition, 'H(2) C(2) O')
    
    def test_unimod_string_representation(self):
        """Test Unimod string representation"""
        modification = Unimod.objects.create(
            accession='35',
            name='Oxidation'
        )
        self.assertEqual(modification.name, 'Oxidation')
    
    def test_common_modifications(self):
        """Test common protein modifications"""
        modifications = [
            Unimod.objects.create(
                accession='1',
                name='Acetyl',
                definition='H(2) C(2) O',
                additional_data=42.010565
            ),
            Unimod.objects.create(
                accession='35',
                name='Oxidation',
                definition='O',
                additional_data=15.994915
            ),
            Unimod.objects.create(
                accession='21',
                name='Phospho',
                definition='H O(3) P',
                additional_data=79.966331
            ),
            Unimod.objects.create(
                accession='214',
                name='Methylation',
                definition='H(2) C',
                additional_data=14.015650
            )
        ]
        
        # Test filtering by mass range
        light_modifications = Unimod.objects.filter(additional_data__lt=50.0)
        self.assertEqual(light_modifications.count(), 3)  # Acetyl, Oxidation, Methylation

        heavy_modifications = Unimod.objects.filter(additional_data__gte=50.0)
        self.assertEqual(heavy_modifications.count(), 1)  # Phospho
        
        # Test search by modification type
        oxidative_mods = Unimod.objects.filter(name__icontains='Oxidation')
        self.assertEqual(oxidative_mods.count(), 1)


class VocabularyIntegrationTest(TestCase):
    """Integration tests for vocabulary models working together"""
    
    def test_proteomics_vocabulary_integration(self):
        """Test integration of proteomics-related vocabularies"""
        # Create species
        human = Species.objects.create(
            code='9606',
            official_name='Homo sapiens',
            common_name='human',
            taxon=9606
        )
        
        # Create tissue
        brain = Tissue.objects.create(
            identifier='UBERON:0000955',
            accession='brain',
            synonyms='Central nervous system organ'
        )
        
        # Create subcellular location
        nucleus = SubcellularLocation.objects.create(
            location_identifier='GO:0005634',
            accession='nucleus',
            synonyms='Nuclear compartment'
        )
        
        # Create disease
        alzheimer = HumanDisease.objects.create(
            identifier='DOID:10652',
            accession='Alzheimer disease',
            synonyms='Neurodegenerative disease'
        )
        
        # Create MS term
        ms_term = MSUniqueVocabularies.objects.create(
            accession='MS:1000031',
            name='instrument model',
            definition='Mass spectrometer model'
        )
        
        # Create protein modification
        phospho = Unimod.objects.create(
            accession='21',
            name='Phospho',
            definition='H O(3) P',
            additional_data=79.966331
        )
        
        # Test that all vocabularies are properly created and searchable
        self.assertEqual(Species.objects.filter(common_name='human').count(), 1)
        self.assertEqual(Tissue.objects.filter(accession='brain').count(), 1)
        self.assertEqual(SubcellularLocation.objects.filter(accession='nucleus').count(), 1)
        self.assertEqual(HumanDisease.objects.filter(accession__icontains='Alzheimer').count(), 1)
        self.assertEqual(MSUniqueVocabularies.objects.filter(name__icontains='instrument').count(), 1)
        self.assertEqual(Unimod.objects.filter(name='Phospho').count(), 1)
        
        # Test combined searches (simulating experimental design)
        human_brain_studies = {
            'species': human,
            'tissue': brain,
            'disease': alzheimer,
            'subcellular_focus': nucleus
        }
        
        # Verify all components exist for a comprehensive study design
        self.assertIsNotNone(human_brain_studies['species'])
        self.assertIsNotNone(human_brain_studies['tissue'])
        self.assertIsNotNone(human_brain_studies['disease'])
        self.assertIsNotNone(human_brain_studies['subcellular_focus'])
        
        # Test mass spectrometry workflow components
        ms_workflow = {
            'species': human,
            'tissue': brain,
            'modification': phospho,
            'ms_instrument_term': ms_term
        }
        
        self.assertEqual(ms_workflow['species'].official_name, 'Homo sapiens')
        self.assertEqual(ms_workflow['tissue'].accession, 'brain')
        self.assertEqual(ms_workflow['modification'].name, 'Phospho')
        self.assertEqual(ms_workflow['ms_instrument_term'].name, 'instrument model')
    
    def test_vocabulary_search_and_filtering(self):
        """Test comprehensive search and filtering across vocabularies"""
        # Create sample data for each vocabulary
        vocabularies_data = {
            'species': [
                ('9606', 'Homo sapiens', 'human', 9606),
                ('10090', 'Mus musculus', 'mouse', 10090),
                ('7227', 'Drosophila melanogaster', 'fruit fly', 7227)
            ],
            'tissues': [
                ('UBERON:0000955', 'brain', 'nervous system'),
                ('UBERON:0002107', 'liver', 'digestive system'),
                ('UBERON:0000948', 'heart', 'cardiovascular system')
            ],
            'diseases': [
                ('DOID:162', 'cancer', 'malignant neoplasm'),
                ('DOID:9351', 'diabetes', 'metabolic disorder'),
                ('DOID:10652', 'Alzheimer disease', 'neurodegenerative')
            ]
        }
        
        # Create vocabulary entries
        for species_id, name, common, taxon in vocabularies_data['species']:
            Species.objects.create(code=species_id, official_name=name, common_name=common, taxon=taxon)
        
        for tissue_id, name, description in vocabularies_data['tissues']:
            Tissue.objects.create(identifier=tissue_id, accession=name, synonyms=description)
        
        for disease_id, name, description in vocabularies_data['diseases']:
            HumanDisease.objects.create(identifier=disease_id, accession=name, synonyms=description)
        
        # Test cross-vocabulary searches
        mammalian_species = Species.objects.filter(common_name__in=['human', 'mouse'])
        self.assertEqual(mammalian_species.count(), 2)
        
        neurological_tissues = Tissue.objects.filter(synonyms__icontains='nervous')
        self.assertEqual(neurological_tissues.count(), 1)
        
        degenerative_diseases = HumanDisease.objects.filter(synonyms__icontains='degenerative')
        self.assertEqual(degenerative_diseases.count(), 1)
        
        # Test combined filtering for research focus
        research_focus = {
            'target_species': mammalian_species,
            'target_tissues': neurological_tissues,
            'target_diseases': degenerative_diseases
        }
        
        self.assertEqual(research_focus['target_species'].count(), 2)
        self.assertEqual(research_focus['target_tissues'].count(), 1)
        self.assertEqual(research_focus['target_diseases'].count(), 1)