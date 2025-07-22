"""
Tests for metadata and configuration models: MetadataColumn, MetadataTableTemplate, Preset, Tag
"""
import json

from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from cc.models import (
    MetadataColumn, MetadataTableTemplate, Preset, FavouriteMetadataOption,
    Tag, ProtocolTag, StepTag, ProtocolModel, ProtocolStep, Annotation,
    Instrument, StoredReagent, Reagent, LabGroup, StorageObject
)


class MetadataColumnTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('metadata_testuser', 'metadata_test@example.com', 'password')
        self.annotation = Annotation.objects.create(
            annotation='Test annotation',
            user=self.user
        )
        
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test instrument in Lab A'
        )
        
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
    
    def test_metadata_column_creation(self):
        """Test basic metadata column creation"""
        metadata = MetadataColumn.objects.create(
            name='Sample ID',
            value='SAMPLE-001',
            type='text',
            annotation=self.annotation
        )
        
        self.assertEqual(metadata.name, 'Sample ID')
        self.assertEqual(metadata.value, 'SAMPLE-001')
        self.assertEqual(metadata.type, 'text')
        self.assertEqual(metadata.annotation, self.annotation)
        self.assertFalse(metadata.hidden)
        self.assertFalse(metadata.auto_generated)
    
    def test_metadata_column_types(self):
        """Test different metadata column types"""
        valid_types = ['text', 'number', 'date', 'boolean', 'choice', 'file', 'url']
        
        for col_type in valid_types:
            metadata = MetadataColumn.objects.create(
                name=f'Test {col_type}',
                value='test_value',
                type=col_type,
                annotation=self.annotation
            )
            self.assertEqual(metadata.type, col_type)
    
    def test_metadata_column_for_instrument(self):
        """Test metadata column attached to instrument"""
        metadata = MetadataColumn.objects.create(
            name='Instrument Setting',
            value='High Resolution',
            type='text',
            instrument=self.instrument
        )
        
        self.assertEqual(metadata.instrument, self.instrument)
        self.assertIsNone(metadata.annotation)
    
    def test_metadata_column_for_protocol(self):
        """Test metadata column attached to protocol"""
        metadata = MetadataColumn.objects.create(
            name='Protocol Version',
            value='2.1',
            type='text',
            protocol=self.protocol
        )
        
        self.assertEqual(metadata.protocol, self.protocol)
        self.assertIsNone(metadata.annotation)
    
    def test_metadata_column_modifiers(self):
        """Test metadata column modifiers"""
        metadata = MetadataColumn.objects.create(
            name='Temperature',
            value='25°C',
            type='text',
            modifiers='{"unit": "celsius", "precision": 1}',
            annotation=self.annotation
        )
        
        self.assertEqual(metadata.modifiers, '{"unit": "celsius", "precision": 1}')
    
    def test_auto_generated_metadata(self):
        """Test auto-generated metadata columns"""
        metadata = MetadataColumn.objects.create(
            name='Creation Timestamp',
            value='2024-01-15T10:30:00Z',
            type='date',
            auto_generated=True,
            hidden=True,
            annotation=self.annotation
        )
        
        self.assertTrue(metadata.auto_generated)
        self.assertTrue(metadata.hidden)


class MetadataTableTemplateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('template_testuser', 'template_test@example.com', 'password')
    
    def test_template_creation(self):
        """Test basic metadata table template creation"""
        template = MetadataTableTemplate.objects.create(
            name='Sample Information Template',
            user=self.user
        )
        
        self.assertEqual(template.name, 'Sample Information Template')
        self.assertEqual(template.name, 'Sample Information Template')
        self.assertEqual(template.user, self.user)
        self.assertTrue(template.enabled)
    
    def test_template_with_columns(self):
        """Test template with predefined columns"""
        template = MetadataTableTemplate.objects.create(
            name='Analysis Template',
            user=self.user
        )
        
        self.assertEqual(template.name, 'Analysis Template')
        self.assertEqual(template.user, self.user)
    
    def test_template_field_mask_mapping(self):
        """Test field mask mapping functionality"""
        mapping_data = [
            {'name': 'sample_id', 'mask': 'Sample ID'},
            {'name': 'concentration', 'mask': 'Concentration (mg/mL)'},
            {'name': 'date_analyzed', 'mask': 'Analysis Date'}
        ]
        
        template = MetadataTableTemplate.objects.create(
            name='Mapped Template',
            user=self.user,
            field_mask_mapping=json.dumps(mapping_data)
        )
        
        parsed_mapping = json.loads(template.field_mask_mapping)
        self.assertEqual(len(parsed_mapping), 3)
        
        # Check each mapping entry
        sample_id_mapping = next(m for m in parsed_mapping if m['name'] == 'sample_id')
        self.assertEqual(sample_id_mapping['mask'], 'Sample ID')
        
        concentration_mapping = next(m for m in parsed_mapping if m['name'] == 'concentration')
        self.assertEqual(concentration_mapping['mask'], 'Concentration (mg/mL)')
    
    def test_template_field_mask_mapping_empty(self):
        """Test template with empty field mask mapping"""
        template = MetadataTableTemplate.objects.create(
            name='No Mapping Template',
            user=self.user,
            field_mask_mapping=None
        )
        
        self.assertIsNone(template.field_mask_mapping)
    
    def test_template_field_mask_mapping_json_structure(self):
        """Test field mask mapping with complex JSON structure"""
        complex_mapping = [
            {
                'name': 'organism_part',
                'mask': 'Organism Part',
                'description': 'SDRF organism part field',
                'required': True
            },
            {
                'name': 'disease',
                'mask': 'Disease',
                'description': 'SDRF disease field',
                'required': False
            }
        ]
        
        template = MetadataTableTemplate.objects.create(
            name='Complex Mapping Template',
            user=self.user,
            field_mask_mapping=json.dumps(complex_mapping)
        )
        
        parsed_mapping = json.loads(template.field_mask_mapping)
        organism_mapping = next(m for m in parsed_mapping if m['name'] == 'organism_part')
        
        self.assertEqual(organism_mapping['mask'], 'Organism Part')
        self.assertEqual(organism_mapping['description'], 'SDRF organism part field')
        self.assertTrue(organism_mapping['required'])


class PresetTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('preset_testuser', 'preset_test@example.com', 'password')
    
    def test_preset_creation(self):
        """Test basic preset creation"""
        preset = Preset.objects.create(
            name='My Analysis Preset',
            user=self.user,
            description='Analysis preset'
        )
        
        self.assertEqual(preset.name, 'My Analysis Preset')
        self.assertEqual(preset.user, self.user)
        self.assertEqual(preset.name, 'My Analysis Preset')
        self.assertIn('Analysis', preset.description)
    
    def test_preset_types(self):
        """Test different preset types"""
        valid_types = ['analysis', 'instrument', 'protocol', 'reagent', 'general']
        
        for preset_type in valid_types:
            preset = Preset.objects.create(
                name=f'{preset_type.capitalize()} Preset',
                user=self.user,
                description=f'{preset_type} preset'
            )
            self.assertIn(preset_type, preset.description)


class FavouriteMetadataOptionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('favourite_testuser', 'favourite_test@example.com', 'password')
    
    def test_favourite_option_creation(self):
        """Test favourite metadata option creation"""
        favourite = FavouriteMetadataOption.objects.create(
            user=self.user,
            name='Tissue Type',
            value='Heart',
            type='choice',
            is_global=False
        )
        
        self.assertEqual(favourite.user, self.user)
        self.assertEqual(favourite.name, 'Tissue Type')
        self.assertEqual(favourite.value, 'Heart')
        self.assertEqual(favourite.type, 'choice')
        self.assertFalse(favourite.is_global)
    
    def test_global_favourite_option(self):
        """Test global favourite metadata option"""
        favourite = FavouriteMetadataOption.objects.create(
            user=self.user,
            name='Common Units',
            value='mg/mL',
            type='text',
            is_global=True
        )
        
        self.assertTrue(favourite.is_global)


class TagTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tag_testuser', 'tag_test@example.com', 'password')
    
    def test_tag_creation(self):
        """Test basic tag creation"""
        tag = Tag.objects.create(
            tag='Mass Spectrometry'
        )
        
        self.assertEqual(tag.tag, 'Mass Spectrometry')
    
    def test_tag_string_representation(self):
        """Test tag string representation"""
        tag = Tag.objects.create(
            tag='Proteomics'
        )
        self.assertEqual(str(tag), 'Proteomics')


class ProtocolTagTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('protocol_tag_testuser', 'protocol_tag_test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.tag = Tag.objects.create(
            tag='Quantitative'
        )
    
    def test_protocol_tag_creation(self):
        """Test linking tags to protocols"""
        protocol_tag = ProtocolTag.objects.create(
            protocol=self.protocol,
            tag=self.tag
        )
        
        self.assertEqual(protocol_tag.protocol, self.protocol)
        self.assertEqual(protocol_tag.tag, self.tag)
    
    def test_protocol_multiple_tags(self):
        """Test protocol with multiple tags"""
        tag2 = Tag.objects.create(
            tag='High Throughput'
        )
        
        ProtocolTag.objects.create(protocol=self.protocol, tag=self.tag)
        ProtocolTag.objects.create(protocol=self.protocol, tag=tag2)
        
        protocol_tags = ProtocolTag.objects.filter(protocol=self.protocol)
        self.assertEqual(protocol_tags.count(), 2)


class StepTagTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('step_tag_testuser', 'step_tag_test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_description='Test Step'
        )
        self.tag = Tag.objects.create(
            tag='Critical Step'
        )
    
    def test_step_tag_creation(self):
        """Test linking tags to protocol steps"""
        step_tag = StepTag.objects.create(
            step=self.step,
            tag=self.tag
        )
        
        self.assertEqual(step_tag.step, self.step)
        self.assertEqual(step_tag.tag, self.tag)


class MetadataIntegrationTest(TestCase):
    """Integration tests for metadata-related models working together"""
    
    def setUp(self):
        self.user = User.objects.create_user('integration_testuser', 'integration_test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Integration Test Protocol',
            protocol_description='Test protocol for metadata integration',
            user=self.user
        )
        self.annotation = Annotation.objects.create(
            annotation='Test annotation with metadata',
            user=self.user
        )
        
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
        
        self.reagent = Reagent.objects.create(
            name='Test Reagent',
            unit='mL'
        )
        
        self.storage = StorageObject.objects.create(
            object_name='Test Storage',
            object_type='freezer',
            user=self.user
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            quantity=100.0,
            user=self.user
        )
    
    def test_complete_metadata_workflow(self):
        """Test complete metadata workflow with templates and columns"""
        # 1. Create metadata template
        template = MetadataTableTemplate.objects.create(
            name='Sample Analysis Template',
            user=self.user
        )
        
        # 2. Create metadata columns for annotation
        metadata_columns = [
            MetadataColumn.objects.create(
                name='Sample ID',
                value='SAMPLE-001',
                type='text',
                annotation=self.annotation
            ),
            MetadataColumn.objects.create(
                name='Concentration',
                value='2.5',
                type='number',
                modifiers='{"unit": "mg/mL"}',
                annotation=self.annotation
            ),
            MetadataColumn.objects.create(
                name='pH',
                value='7.4',
                type='number',
                annotation=self.annotation
            ),
            MetadataColumn.objects.create(
                name='Analysis Date',
                value='2024-01-15',
                type='date',
                auto_generated=True,
                annotation=self.annotation
            )
        ]
        
        # 3. Create metadata columns for stored reagent
        reagent_metadata = MetadataColumn.objects.create(
            name='Storage Temperature',
            value='-20°C',
            type='text',
            stored_reagent=self.stored_reagent
        )
        
        # 4. Create user preset
        preset = Preset.objects.create(
            name='My Analysis Preferences',
            user=self.user,
            description='Analysis preset for templates'
        )
        
        # 5. Create favourite metadata options
        favourites = [
            FavouriteMetadataOption.objects.create(
                user=self.user,
                name='Sample Type',
                value='Protein Extract',
                type='choice'
            ),
            FavouriteMetadataOption.objects.create(
                user=self.user,
                name='Common Concentrations',
                value='1.0 mg/mL',
                type='number',
                is_global=True
            )
        ]
        
        # 6. Create tags for organization
        analysis_tag = Tag.objects.create(
            tag='Quantitative Analysis'
        )
        
        ProtocolTag.objects.create(
            protocol=self.protocol,
            tag=analysis_tag
        )
        
        # Verify the complete workflow
        self.assertEqual(template.name, 'Sample Analysis Template')
        self.assertEqual(len(metadata_columns), 4)
        self.assertEqual(
            MetadataColumn.objects.filter(annotation=self.annotation).count(), 
            4
        )
        self.assertEqual(reagent_metadata.stored_reagent, self.stored_reagent)
        self.assertIn('Analysis', preset.description)
        self.assertEqual(
            FavouriteMetadataOption.objects.filter(user=self.user).count(),
            2
        )
        self.assertEqual(
            ProtocolTag.objects.filter(protocol=self.protocol).count(),
            1
        )
        
        # Test metadata retrieval and filtering
        annotation_metadata = MetadataColumn.objects.filter(annotation=self.annotation)
        required_metadata = annotation_metadata.filter(name='Sample ID')
        auto_generated = annotation_metadata.filter(auto_generated=True)
        
        self.assertEqual(annotation_metadata.count(), 4)
        self.assertEqual(required_metadata.count(), 1)
        self.assertEqual(auto_generated.count(), 1)
        self.assertEqual(auto_generated.first().name, 'Analysis Date')
    
    def test_metadata_column_relationships(self):
        """Test metadata columns attached to different model types"""
        # Create metadata for different model types
        annotation_meta = MetadataColumn.objects.create(
            name='Annotation Meta',
            value='test_value',
            type='text',
            annotation=self.annotation
        )
        
        protocol_meta = MetadataColumn.objects.create(
            name='Protocol Meta',
            value='protocol_value',
            type='text',
            protocol=self.protocol
        )
        
        reagent_meta = MetadataColumn.objects.create(
            name='Reagent Meta',
            value='reagent_value',
            type='text',
            stored_reagent=self.stored_reagent
        )
        
        # Verify relationships
        self.assertEqual(annotation_meta.annotation, self.annotation)
        self.assertIsNone(annotation_meta.protocol)
        self.assertIsNone(annotation_meta.stored_reagent)
        
        self.assertEqual(protocol_meta.protocol, self.protocol)
        self.assertIsNone(protocol_meta.annotation)
        self.assertIsNone(protocol_meta.stored_reagent)
        
        self.assertEqual(reagent_meta.stored_reagent, self.stored_reagent)
        self.assertIsNone(reagent_meta.annotation)
        self.assertIsNone(reagent_meta.protocol)
        
        # Test reverse relationships
        self.assertIn(annotation_meta, self.annotation.metadata_columns.all())
        self.assertIn(protocol_meta, self.protocol.metadata_columns.all())
        self.assertIn(reagent_meta, self.stored_reagent.metadata_columns.all())