"""
Tests for ontology models: CellType, MondoDisease, UberonAnatomy, NCBITaxonomy, ChEBICompound, PSIMSOntology
"""
from django.test import TestCase
from django.db import IntegrityError
from cc.models import (
    CellType, MondoDisease, UberonAnatomy, NCBITaxonomy, 
    ChEBICompound, PSIMSOntology
)


class CellTypeModelTest(TestCase):
    def test_cell_type_creation(self):
        """Test basic cell type creation"""
        cell_type = CellType.objects.create(
            identifier='CL:0000066',
            name='epithelial cell',
            description='A cell that is usually found in a two-dimensional sheet',
            cell_line=False,
            organism='Homo sapiens',
            tissue_origin='epithelium',
            accession='CL:0000066'
        )
        
        self.assertEqual(cell_type.identifier, 'CL:0000066')
        self.assertEqual(cell_type.name, 'epithelial cell')
        self.assertFalse(cell_type.cell_line)
        self.assertEqual(cell_type.organism, 'Homo sapiens')
        self.assertEqual(cell_type.tissue_origin, 'epithelium')
        self.assertEqual(cell_type.accession, 'CL:0000066')
        self.assertIsNotNone(cell_type.created_at)
        self.assertIsNotNone(cell_type.updated_at)
    
    def test_cell_line_creation(self):
        """Test cell line creation"""
        cell_line = CellType.objects.create(
            identifier='HeLa',
            name='HeLa',
            description='Immortalized cell line derived from cervical cancer cells',
            cell_line=True,
            organism='Homo sapiens',
            tissue_origin='cervix',
            disease_context='cervical adenocarcinoma',
            synonyms='CCL-2; ATCC CCL-2'
        )
        
        self.assertEqual(cell_line.identifier, 'HeLa')
        self.assertTrue(cell_line.cell_line)
        self.assertEqual(cell_line.disease_context, 'cervical adenocarcinoma')
        self.assertEqual(cell_line.synonyms, 'CCL-2; ATCC CCL-2')
    
    def test_cell_type_str_representation(self):
        """Test cell type string representation"""
        cell_type = CellType.objects.create(
            identifier='CL:0000000',
            name='cell'
        )
        self.assertEqual(str(cell_type), 'cell')
    
    def test_cell_type_unique_identifier(self):
        """Test that cell type identifiers are unique"""
        CellType.objects.create(
            identifier='CL:0000001',
            name='cell type 1'
        )
        
        with self.assertRaises(IntegrityError):
            CellType.objects.create(
                identifier='CL:0000001',  # Same identifier
                name='different name'
            )
    
    def test_cell_type_ordering(self):
        """Test cell type ordering by name"""
        cell_z = CellType.objects.create(identifier='CL:0000003', name='z cell')
        cell_a = CellType.objects.create(identifier='CL:0000001', name='a cell')
        cell_m = CellType.objects.create(identifier='CL:0000002', name='m cell')
        
        cell_types = list(CellType.objects.all())
        self.assertEqual(cell_types[0], cell_a)
        self.assertEqual(cell_types[1], cell_m)
        self.assertEqual(cell_types[2], cell_z)


class MondoDiseaseModelTest(TestCase):
    def test_mondo_disease_creation(self):
        """Test basic MONDO disease creation"""
        disease = MondoDisease.objects.create(
            identifier='MONDO:0007256',
            name='Alzheimer disease',
            definition='A dementia that is characterized by memory lapses, confusion, emotional instability',
            synonyms='Alzheimer disease; dementia, Alzheimer type; AD',
            xrefs='DOID:10652; OMIM:104300; UMLS:C0002395',
            parent_terms='MONDO:0001627; MONDO:0005071'
        )
        
        self.assertEqual(disease.identifier, 'MONDO:0007256')
        self.assertEqual(disease.name, 'Alzheimer disease')
        self.assertIn('dementia', disease.definition)
        self.assertIn('AD', disease.synonyms)
        self.assertIn('DOID:10652', disease.xrefs)
        self.assertIn('MONDO:0001627', disease.parent_terms)
        self.assertFalse(disease.obsolete)
        self.assertIsNone(disease.replacement_term)
    
    def test_mondo_disease_obsolete(self):
        """Test obsolete MONDO disease with replacement"""
        obsolete_disease = MondoDisease.objects.create(
            identifier='MONDO:0000001',
            name='obsolete disease',
            obsolete=True,
            replacement_term='MONDO:0000002'
        )
        
        self.assertTrue(obsolete_disease.obsolete)
        self.assertEqual(obsolete_disease.replacement_term, 'MONDO:0000002')
    
    def test_mondo_disease_str_representation(self):
        """Test MONDO disease string representation"""
        disease = MondoDisease.objects.create(
            identifier='MONDO:0005148',
            name='type 2 diabetes mellitus'
        )
        
        expected_str = 'type 2 diabetes mellitus (MONDO:0005148)'
        self.assertEqual(str(disease), expected_str)
    
    def test_mondo_disease_ordering(self):
        """Test MONDO disease ordering by name"""
        disease_z = MondoDisease.objects.create(identifier='MONDO:0000003', name='z disease')
        disease_a = MondoDisease.objects.create(identifier='MONDO:0000001', name='a disease')
        disease_m = MondoDisease.objects.create(identifier='MONDO:0000002', name='m disease')
        
        diseases = list(MondoDisease.objects.all())
        self.assertEqual(diseases[0], disease_a)
        self.assertEqual(diseases[1], disease_m)
        self.assertEqual(diseases[2], disease_z)


class UberonAnatomyModelTest(TestCase):
    def test_uberon_anatomy_creation(self):
        """Test basic UBERON anatomy creation"""
        anatomy = UberonAnatomy.objects.create(
            identifier='UBERON:0000948',
            name='heart',
            definition='A myogenic muscular organ found in the cardiovascular system',
            synonyms='cardiac organ; heart muscle',
            xrefs='FMA:7088; MA:0000072',
            parent_terms='UBERON:0001062',
            part_of='UBERON:0001009',
            develops_from='UBERON:0004141'
        )
        
        self.assertEqual(anatomy.identifier, 'UBERON:0000948')
        self.assertEqual(anatomy.name, 'heart')
        self.assertIn('myogenic muscular', anatomy.definition)
        self.assertIn('cardiac organ', anatomy.synonyms)
        self.assertEqual(anatomy.parent_terms, 'UBERON:0001062')
        self.assertEqual(anatomy.part_of, 'UBERON:0001009')
        self.assertEqual(anatomy.develops_from, 'UBERON:0004141')
        self.assertFalse(anatomy.obsolete)
    
    def test_uberon_anatomy_str_representation(self):
        """Test UBERON anatomy string representation"""
        anatomy = UberonAnatomy.objects.create(
            identifier='UBERON:0002107',
            name='liver'
        )
        
        expected_str = 'liver (UBERON:0002107)'
        self.assertEqual(str(anatomy), expected_str)
    
    def test_uberon_anatomy_developmental_relationships(self):
        """Test developmental relationship fields"""
        anatomy = UberonAnatomy.objects.create(
            identifier='UBERON:0000955',
            name='brain',
            develops_from='UBERON:0001017; UBERON:0001016',
            part_of='UBERON:0001017'
        )
        
        self.assertIn('UBERON:0001017', anatomy.develops_from)
        self.assertIn('UBERON:0001016', anatomy.develops_from)
        self.assertEqual(anatomy.part_of, 'UBERON:0001017')


class NCBITaxonomyModelTest(TestCase):
    def test_ncbi_taxonomy_creation(self):
        """Test basic NCBI taxonomy creation"""
        taxon = NCBITaxonomy.objects.create(
            tax_id=9606,
            scientific_name='Homo sapiens',
            common_name='human',
            synonyms='modern man',
            rank='species',
            parent_tax_id=9605,
            lineage='cellular organisms; Eukaryota; Opisthokonta; Metazoa; Eumetazoa; Bilateria; Deuterostomia; Chordata; Craniata; Vertebrata; Gnathostomata; Teleostomi; Euteleostomi; Sarcopterygii; Dipnotetrapodomorpha; Tetrapoda; Amniota; Mammalia; Theria; Eutheria; Boreoeutheria; Euarchontoglires; Primates; Haplorrhini; Simiiformes; Catarrhini; Hominoidea; Hominidae; Homininae; Homo',
            genetic_code=1,
            mitochondrial_genetic_code=2
        )
        
        self.assertEqual(taxon.tax_id, 9606)
        self.assertEqual(taxon.scientific_name, 'Homo sapiens')
        self.assertEqual(taxon.common_name, 'human')
        self.assertEqual(taxon.rank, 'species')
        self.assertEqual(taxon.parent_tax_id, 9605)
        self.assertIn('Primates', taxon.lineage)
        self.assertEqual(taxon.genetic_code, 1)
        self.assertEqual(taxon.mitochondrial_genetic_code, 2)
    
    def test_ncbi_taxonomy_str_representation_with_common_name(self):
        """Test NCBI taxonomy string representation with common name"""
        taxon = NCBITaxonomy.objects.create(
            tax_id=10090,
            scientific_name='Mus musculus',
            common_name='house mouse'
        )
        
        expected_str = 'Mus musculus (house mouse) [10090]'
        self.assertEqual(str(taxon), expected_str)
    
    def test_ncbi_taxonomy_str_representation_without_common_name(self):
        """Test NCBI taxonomy string representation without common name"""
        taxon = NCBITaxonomy.objects.create(
            tax_id=83333,
            scientific_name='Escherichia coli K-12'
        )
        
        expected_str = 'Escherichia coli K-12 [83333]'
        self.assertEqual(str(taxon), expected_str)
    
    def test_ncbi_taxonomy_ordering(self):
        """Test NCBI taxonomy ordering by scientific name"""
        taxon_z = NCBITaxonomy.objects.create(tax_id=3, scientific_name='Zebra fish')
        taxon_a = NCBITaxonomy.objects.create(tax_id=1, scientific_name='Arabidopsis')
        taxon_m = NCBITaxonomy.objects.create(tax_id=2, scientific_name='Mus musculus')
        
        taxa = list(NCBITaxonomy.objects.all())
        self.assertEqual(taxa[0], taxon_a)
        self.assertEqual(taxa[1], taxon_m)
        self.assertEqual(taxa[2], taxon_z)


class ChEBICompoundModelTest(TestCase):
    def test_chebi_compound_creation(self):
        """Test basic ChEBI compound creation"""
        compound = ChEBICompound.objects.create(
            identifier='CHEBI:15377',
            name='water',
            definition='An oxygen hydride consisting of an oxygen atom that is covalently bonded to two hydrogen atoms.',
            synonyms='H2O; dihydrogen oxide; oxidane',
            formula='H2O',
            mass=18.01528,
            charge=0,
            inchi='InChI=1S/H2O/h1H2',
            smiles='O',
            parent_terms='CHEBI:33579; CHEBI:5585',
            roles='solvent; polar solvent'
        )
        
        self.assertEqual(compound.identifier, 'CHEBI:15377')
        self.assertEqual(compound.name, 'water')
        self.assertIn('oxygen hydride', compound.definition)
        self.assertIn('H2O', compound.synonyms)
        self.assertEqual(compound.formula, 'H2O')
        self.assertEqual(compound.mass, 18.01528)
        self.assertEqual(compound.charge, 0)
        self.assertEqual(compound.smiles, 'O')
        self.assertIn('solvent', compound.roles)
        self.assertFalse(compound.obsolete)
    
    def test_chebi_compound_charged(self):
        """Test charged ChEBI compound"""
        compound = ChEBICompound.objects.create(
            identifier='CHEBI:29101',
            name='sodium(1+)',
            formula='Na',
            charge=1,
            mass=22.98977
        )
        
        self.assertEqual(compound.charge, 1)
        self.assertEqual(compound.mass, 22.98977)
    
    def test_chebi_compound_str_representation(self):
        """Test ChEBI compound string representation"""
        compound = ChEBICompound.objects.create(
            identifier='CHEBI:16236',
            name='ethanol'
        )
        
        expected_str = 'ethanol (CHEBI:16236)'
        self.assertEqual(str(compound), expected_str)
    
    def test_chebi_compound_obsolete(self):
        """Test obsolete ChEBI compound"""
        compound = ChEBICompound.objects.create(
            identifier='CHEBI:00001',
            name='obsolete compound',
            obsolete=True,
            replacement_term='CHEBI:00002'
        )
        
        self.assertTrue(compound.obsolete)
        self.assertEqual(compound.replacement_term, 'CHEBI:00002')


class PSIMSOntologyModelTest(TestCase):
    def test_psims_ontology_creation(self):
        """Test basic PSI-MS ontology creation"""
        term = PSIMSOntology.objects.create(
            identifier='MS:1000031',
            name='instrument model',
            definition='Instrument model name not including the vendor\'s name.',
            synonyms='instrument model name',
            parent_terms='MS:1000463',
            category='instrument'
        )
        
        self.assertEqual(term.identifier, 'MS:1000031')
        self.assertEqual(term.name, 'instrument model')
        self.assertIn('model name', term.definition)
        self.assertEqual(term.synonyms, 'instrument model name')
        self.assertEqual(term.parent_terms, 'MS:1000463')
        self.assertEqual(term.category, 'instrument')
        self.assertFalse(term.obsolete)
    
    def test_psims_ontology_method_category(self):
        """Test PSI-MS ontology method category"""
        method_term = PSIMSOntology.objects.create(
            identifier='MS:1000044',
            name='dissociation method',
            definition='Fragmentation method used for dissociation or fragmentation.',
            category='method',
            parent_terms='MS:1000456'
        )
        
        self.assertEqual(method_term.category, 'method')
    
    def test_psims_ontology_str_representation(self):
        """Test PSI-MS ontology string representation"""
        term = PSIMSOntology.objects.create(
            identifier='MS:1000579',
            name='MS1 spectrum'
        )
        
        expected_str = 'MS1 spectrum (MS:1000579)'
        self.assertEqual(str(term), expected_str)


class OntologyIntegrationTest(TestCase):
    """Integration tests for ontology models"""
    
    def test_create_comprehensive_ontology_data(self):
        """Test creating comprehensive ontology data for proteomics"""
        
        # Create taxonomy
        human = NCBITaxonomy.objects.create(
            tax_id=9606,
            scientific_name='Homo sapiens',
            common_name='human',
            rank='species'
        )
        
        # Create cell type
        hepatocyte = CellType.objects.create(
            identifier='CL:0000182',
            name='hepatocyte',
            description='The main cell type of the liver',
            organism='Homo sapiens',
            tissue_origin='liver'
        )
        
        # Create disease
        cancer = MondoDisease.objects.create(
            identifier='MONDO:0004992',
            name='cancer',
            definition='A disease characterized by uncontrolled cellular proliferation'
        )
        
        # Create anatomy
        liver = UberonAnatomy.objects.create(
            identifier='UBERON:0002107',
            name='liver',
            definition='A digestive organ'
        )
        
        # Create chemical compound
        glucose = ChEBICompound.objects.create(
            identifier='CHEBI:17234',
            name='glucose',
            formula='C6H12O6',
            mass=180.156
        )
        
        # Create MS term
        ms_term = PSIMSOntology.objects.create(
            identifier='MS:1000579',
            name='MS1 spectrum',
            category='spectrum'
        )
        
        # Verify all created successfully
        self.assertEqual(human.tax_id, 9606)
        self.assertEqual(hepatocyte.name, 'hepatocyte')
        self.assertEqual(cancer.name, 'cancer')
        self.assertEqual(liver.name, 'liver')
        self.assertEqual(glucose.formula, 'C6H12O6')
        self.assertEqual(ms_term.category, 'spectrum')
    
    def test_ontology_search_functionality(self):
        """Test searching across ontology models"""
        
        # Create test data with searchable terms
        CellType.objects.create(
            identifier='CL:0000066',
            name='epithelial cell',
            synonyms='epithelium cell'
        )
        
        MondoDisease.objects.create(
            identifier='MONDO:0005148',
            name='diabetes mellitus',
            synonyms='diabetes; DM'
        )
        
        ChEBICompound.objects.create(
            identifier='CHEBI:17234',
            name='glucose',
            synonyms='dextrose; D-glucose'
        )
        
        # Search for terms containing 'cell'
        cell_types = CellType.objects.filter(name__icontains='cell')
        self.assertEqual(cell_types.count(), 1)
        self.assertEqual(cell_types.first().name, 'epithelial cell')
        
        # Search for terms containing 'diabetes'
        diseases = MondoDisease.objects.filter(name__icontains='diabetes')
        self.assertEqual(diseases.count(), 1)
        
        # Search in synonyms
        glucose_compounds = ChEBICompound.objects.filter(synonyms__icontains='dextrose')
        self.assertEqual(glucose_compounds.count(), 1)
        self.assertEqual(glucose_compounds.first().name, 'glucose')
    
    def test_ontology_relationships(self):
        """Test ontology parent-child relationships"""
        
        # Create parent disease
        parent_disease = MondoDisease.objects.create(
            identifier='MONDO:0000001',
            name='parent disease'
        )
        
        # Create child disease with parent reference
        child_disease = MondoDisease.objects.create(
            identifier='MONDO:0000002',
            name='child disease',
            parent_terms='MONDO:0000001'
        )
        
        # Verify relationship
        self.assertIn(parent_disease.identifier, child_disease.parent_terms)
        
        # Test anatomy part_of relationship
        organ = UberonAnatomy.objects.create(
            identifier='UBERON:0000001',
            name='organ'
        )
        
        tissue = UberonAnatomy.objects.create(
            identifier='UBERON:0000002',
            name='tissue',
            part_of='UBERON:0000001'
        )
        
        self.assertEqual(tissue.part_of, organ.identifier)
    
    def test_ontology_data_validation(self):
        """Test ontology data validation and constraints"""
        
        # Test unique identifiers
        CellType.objects.create(identifier='CL:0000001', name='test cell 1')
        
        with self.assertRaises(IntegrityError):
            CellType.objects.create(identifier='CL:0000001', name='test cell 2')
        
        # Test primary key constraints for NCBI taxonomy
        NCBITaxonomy.objects.create(tax_id=9606, scientific_name='Homo sapiens')
        
        with self.assertRaises(IntegrityError):
            NCBITaxonomy.objects.create(tax_id=9606, scientific_name='Different name')
        
        # Test PSI-MS primary key constraint
        PSIMSOntology.objects.create(identifier='MS:1000001', name='test term 1')
        
        with self.assertRaises(IntegrityError):
            PSIMSOntology.objects.create(identifier='MS:1000001', name='test term 2')
    
    def test_ontology_bulk_operations(self):
        """Test bulk operations on ontology models"""
        
        # Bulk create cell types
        cell_types = [
            CellType(identifier=f'CL:{i:07d}', name=f'cell type {i}')
            for i in range(1, 101)
        ]
        CellType.objects.bulk_create(cell_types)
        
        self.assertEqual(CellType.objects.count(), 100)
        
        # Bulk create compounds
        compounds = [
            ChEBICompound(identifier=f'CHEBI:{i}', name=f'compound {i}')
            for i in range(1, 51)
        ]
        ChEBICompound.objects.bulk_create(compounds)
        
        self.assertEqual(ChEBICompound.objects.count(), 50)
        
        # Test bulk filtering
        filtered_cells = CellType.objects.filter(name__endswith('0')[:10])
        self.assertEqual(len(list(filtered_cells)), 10)
    
    def test_ontology_model_meta_attributes(self):
        """Test model meta attributes like verbose names and ordering"""
        
        # Test verbose names
        self.assertEqual(CellType._meta.verbose_name, 'Cell Type')
        self.assertEqual(CellType._meta.verbose_name_plural, 'Cell Types')
        
        self.assertEqual(MondoDisease._meta.verbose_name, 'MONDO Disease')
        self.assertEqual(MondoDisease._meta.verbose_name_plural, 'MONDO Diseases')
        
        # Test app labels
        self.assertEqual(CellType._meta.app_label, 'cc')
        self.assertEqual(MondoDisease._meta.app_label, 'cc')
        self.assertEqual(UberonAnatomy._meta.app_label, 'cc')
        self.assertEqual(NCBITaxonomy._meta.app_label, 'cc')
        self.assertEqual(ChEBICompound._meta.app_label, 'cc')
        self.assertEqual(PSIMSOntology._meta.app_label, 'cc')
        
        # Test ordering (should be by name for most models)
        cell_z = CellType.objects.create(identifier='CL:0000003', name='z cell')
        cell_a = CellType.objects.create(identifier='CL:0000001', name='a cell')
        
        cells = list(CellType.objects.all())
        self.assertEqual(cells[0].name, 'a cell')  # Should be first due to ordering
        self.assertEqual(cells[1].name, 'z cell')


class OntologyPerformanceTest(TestCase):
    """Performance-related tests for ontology models"""
    
    def test_ontology_index_usage(self):
        """Test that appropriate database indexes exist and are used"""
        
        # Create test data to simulate index usage
        for i in range(100):
            CellType.objects.create(
                identifier=f'CL:{i:07d}',
                name=f'cell type {i}',
                organism='Homo sapiens' if i % 2 == 0 else 'Mus musculus'
            )
        
        # These queries should benefit from indexes
        human_cells = CellType.objects.filter(organism='Homo sapiens')
        self.assertEqual(human_cells.count(), 50)
        
        # Name-based search (should use ordering index)
        specific_cell = CellType.objects.filter(name='cell type 50')
        self.assertEqual(specific_cell.count(), 1)
        
        # Primary key lookup (always indexed)
        cell_by_id = CellType.objects.get(identifier='CL:0000050')
        self.assertEqual(cell_by_id.name, 'cell type 50')
    
    def test_large_synonym_fields(self):
        """Test handling of large synonym fields"""
        
        # Create entry with large synonym field
        large_synonyms = '; '.join([f'synonym_{i}' for i in range(1000)])
        
        compound = ChEBICompound.objects.create(
            identifier='CHEBI:99999',
            name='test compound with many synonyms',
            synonyms=large_synonyms
        )
        
        # Verify it was stored and retrieved correctly
        retrieved = ChEBICompound.objects.get(identifier='CHEBI:99999')
        self.assertEqual(len(retrieved.synonyms.split('; ')), 1000)
        self.assertIn('synonym_500', retrieved.synonyms)