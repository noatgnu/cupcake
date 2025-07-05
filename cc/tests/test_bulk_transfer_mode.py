"""
Tests for bulk transfer mode functionality

These tests verify that the import system correctly handles bulk transfer mode,
which imports data as-is without user-centric modifications like duplicate checking,
storage nomination, or import marking.
"""
import os
import time
import tempfile
import uuid
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from cc.models import (
    ProtocolModel, Session, Annotation, AnnotationFolder, Project,
    StorageObject, Reagent, StoredReagent, LabGroup, Instrument, InstrumentUsage
)
from cc.utils.user_data_export_revised import export_user_data_revised
from cc.utils.user_data_import_revised import import_user_data_revised, UserDataImporter


class BulkTransferModeTestCase(TransactionTestCase):
    """Base test case for bulk transfer mode testing"""
    
    def setUp(self):
        """Set up comprehensive test data for bulk transfer testing"""
        # Create unique timestamp for parallel test execution
        timestamp = str(int(time.time() * 1000))
        
        # Create export user with comprehensive data
        self.export_user = User.objects.create_user(
            username=f'export_bulk_{timestamp}',
            email=f'export_bulk_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create import user
        self.import_user = User.objects.create_user(
            username=f'import_bulk_{timestamp}',
            email=f'import_bulk_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create lab group
        self.lab_group = LabGroup.objects.create(
            name=f'Bulk Transfer Test Lab {timestamp}',
            description='Lab group for bulk transfer testing'
        )
        self.lab_group.users.add(self.export_user)
        
        # Create storage objects
        self.storage1 = StorageObject.objects.create(
            object_name='Original Freezer A',
            object_type='freezer',
            user=self.export_user
        )
        
        self.storage2 = StorageObject.objects.create(
            object_name='Original Freezer B',
            object_type='freezer',
            user=self.export_user
        )
        
        # Create reagents with specific names for duplicate testing
        self.reagent1 = Reagent.objects.create(
            name='Test Reagent Alpha',
            unit='mL'
        )
        
        self.reagent2 = Reagent.objects.create(
            name='Test Reagent Beta',
            unit='mg'
        )
        
        # Create stored reagents
        self.stored_reagent1 = StoredReagent.objects.create(
            reagent=self.reagent1,
            storage_object=self.storage1,
            quantity=100.0,
            notes='Original stored reagent 1',
            user=self.export_user
        )
        
        self.stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent2,
            storage_object=self.storage2,
            quantity=50.0,
            notes='Original stored reagent 2',
            user=self.export_user
        )
        
        # Create instrument
        self.instrument = Instrument.objects.create(
            name='Original Mass Spectrometer',
            description='Original instrument for testing',
            accepts_bookings=True
        )
        
        # Create project
        self.project = Project.objects.create(
            project_name='Original Test Project',
            project_description='Original project for bulk transfer testing',
            owner=self.export_user
        )
        
        # Create protocol
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Original Test Protocol',
            protocol_description='Original protocol for bulk transfer testing',
            user=self.export_user,
            enabled=True
        )
        
        # Create session
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.export_user,
            name='Original Test Session',
            enabled=True
        )
        self.session.protocols.add(self.protocol)
        self.project.sessions.add(self.session)
        
        # Create annotation folder
        self.folder = AnnotationFolder.objects.create(
            folder_name='Original Folder',
            session=self.session
        )
        
        # Create regular annotation
        self.annotation = Annotation.objects.create(
            annotation='Original test annotation',
            annotation_type='text',
            annotation_name='Original Annotation',
            user=self.export_user,
            session=self.session,
            folder=self.folder
        )
        
        # Create instrument annotation
        self.instrument_annotation = Annotation.objects.create(
            annotation='Original instrument booking details',
            annotation_type='instrument',
            annotation_name='Original Instrument Booking',
            user=self.export_user,
            session=self.session
        )
        
        # Create instrument usage
        self.instrument_usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            annotation=self.instrument_annotation,
            description='Original instrument usage',
            user=self.export_user
        )
    
    def create_test_export(self):
        """Create a test export ZIP with comprehensive data"""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = export_user_data_revised(self.export_user, temp_dir)
            
            # Read ZIP content
            with open(zip_path, 'rb') as f:
                return f.read()


class BulkTransferModeReagentTest(BulkTransferModeTestCase):
    """Test bulk transfer mode behavior for reagents"""
    
    def test_bulk_mode_imports_duplicate_reagents(self):
        """Test that bulk mode imports reagents even if duplicates exist"""
        # Create existing reagents with same names in import user's environment
        existing_reagent1 = Reagent.objects.create(
            name='Test Reagent Alpha',  # Same name as export data
            unit='mL'
        )
        existing_reagent2 = Reagent.objects.create(
            name='Test Reagent Beta',   # Same name as export data
            unit='mg'
        )
        
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode enabled
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=True
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # In bulk mode, new reagents should be created even if duplicates exist
            # We should now have 4 reagents total: 2 existing + 2 imported
            total_reagents = Reagent.objects.count()
            self.assertEqual(total_reagents, 4)
            
            # Verify that imported reagents don't have [IMPORTED] prefix in bulk mode
            imported_reagents = Reagent.objects.filter(
                name__in=['Test Reagent Alpha', 'Test Reagent Beta']
            ).exclude(id__in=[existing_reagent1.id, existing_reagent2.id])
            
            self.assertEqual(imported_reagents.count(), 2)
            
            # In bulk mode, names should be preserved exactly as exported
            for reagent in imported_reagents:
                self.assertNotIn('[IMPORTED]', reagent.name)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_user_mode_skips_duplicate_reagents(self):
        """Test that user mode skips duplicate reagents (for comparison)"""
        # Create existing reagents with same names
        existing_reagent1 = Reagent.objects.create(
            name='Test Reagent Alpha',
            unit='mL'
        )
        existing_reagent2 = Reagent.objects.create(
            name='Test Reagent Beta',
            unit='mg'
        )
        
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode disabled (default user mode)
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=False
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # In user mode, duplicate reagents should be skipped
            # We should still have only 2 reagents total
            total_reagents = Reagent.objects.count()
            self.assertEqual(total_reagents, 2)
            
            # Verify the existing reagents are unchanged
            self.assertTrue(Reagent.objects.filter(id=existing_reagent1.id).exists())
            self.assertTrue(Reagent.objects.filter(id=existing_reagent2.id).exists())
            
        finally:
            os.unlink(temp_zip_path)


class BulkTransferModeStorageTest(BulkTransferModeTestCase):
    """Test bulk transfer mode behavior for storage objects and stored reagents"""
    
    def test_bulk_mode_uses_original_storage_mappings(self):
        """Test that bulk mode uses original storage object relationships"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode enabled
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=True
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify storage objects were imported with original names
            imported_storage_objects = StorageObject.objects.filter(user=self.import_user)
            self.assertEqual(imported_storage_objects.count(), 2)
            
            # In bulk mode, storage object names should not have [IMPORTED] prefix
            storage_names = [obj.object_name for obj in imported_storage_objects]
            self.assertIn('Original Freezer A', storage_names)
            self.assertIn('Original Freezer B', storage_names)
            
            for name in storage_names:
                self.assertNotIn('[IMPORTED]', name)
            
            # Verify stored reagents were imported with original storage relationships
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 2)
            
            # In bulk mode, notes should not have [IMPORTED] prefix
            for stored_reagent in imported_stored_reagents:
                self.assertNotIn('[IMPORTED]', stored_reagent.notes)
                self.assertIn('Original stored reagent', stored_reagent.notes)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_user_mode_requires_storage_nomination(self):
        """Test that user mode requires storage nomination (for comparison)"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with user mode (no storage mappings provided)
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=False
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # In user mode without storage mappings, stored reagents should be skipped
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 0)
            
            # But storage objects should still be imported (they're just empty)
            imported_storage_objects = StorageObject.objects.filter(user=self.import_user)
            self.assertEqual(imported_storage_objects.count(), 2)
            
            # In user mode, storage object names should have [IMPORTED] prefix
            for storage_obj in imported_storage_objects:
                self.assertIn('[IMPORTED]', storage_obj.object_name)
            
        finally:
            os.unlink(temp_zip_path)


class BulkTransferModeInstrumentTest(BulkTransferModeTestCase):
    """Test bulk transfer mode behavior for instruments and annotations"""
    
    def test_bulk_mode_preserves_instrument_annotations(self):
        """Test that bulk mode preserves instrument annotations as-is"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode enabled
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=True
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify instrument was imported with original name
            imported_instruments = Instrument.objects.filter(
                name='Original Mass Spectrometer'
            )
            self.assertEqual(imported_instruments.count(), 1)
            imported_instrument = imported_instruments.first()
            
            # In bulk mode, instrument name should not have [IMPORTED] prefix
            self.assertNotIn('[IMPORTED]', imported_instrument.name)
            
            # Verify instrument annotation was preserved as instrument type
            instrument_annotations = Annotation.objects.filter(
                user=self.import_user,
                annotation_type='instrument'
            )
            self.assertEqual(instrument_annotations.count(), 1)
            
            instrument_annotation = instrument_annotations.first()
            self.assertEqual(instrument_annotation.annotation_type, 'instrument')
            self.assertNotIn('[IMPORTED]', instrument_annotation.annotation_name)
            self.assertEqual(instrument_annotation.annotation_name, 'Original Instrument Booking')
            
            # Verify instrument usage was created
            imported_usage = InstrumentUsage.objects.filter(
                user=self.import_user,
                instrument=imported_instrument,
                annotation=instrument_annotation
            )
            self.assertEqual(imported_usage.count(), 1)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_user_mode_converts_instrument_annotations(self):
        """Test that user mode converts instrument annotations when instruments disabled"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with user mode and instruments disabled
            import_options = {
                'instruments': False,  # Disable instrument import
                'annotations': True,
                'sessions': True,
                'protocols': True,
                'projects': True
            }
            
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                import_options=import_options,
                bulk_transfer_mode=False
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify no instruments were imported
            imported_instruments = Instrument.objects.filter(
                name__icontains='Original Mass Spectrometer'
            )
            self.assertEqual(imported_instruments.count(), 0)
            
            # Verify instrument annotation was converted to text
            text_annotations = Annotation.objects.filter(
                user=self.import_user,
                annotation_type='text'
            )
            
            # Should have at least one text annotation (converted from instrument)
            converted_annotation = None
            for annotation in text_annotations:
                if 'IMPORTED INSTRUMENT BOOKING' in annotation.annotation:
                    converted_annotation = annotation
                    break
            
            self.assertIsNotNone(converted_annotation)
            self.assertIn('[IMPORTED]', converted_annotation.annotation_name)
            self.assertIn('IMPORTED INSTRUMENT BOOKING', converted_annotation.annotation)
            
        finally:
            os.unlink(temp_zip_path)


class BulkTransferModeAnnotationTest(BulkTransferModeTestCase):
    """Test bulk transfer mode behavior for annotations"""
    
    def test_bulk_mode_preserves_annotation_names(self):
        """Test that bulk mode preserves original annotation names"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode enabled
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=True
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify annotations were imported with original names
            imported_annotations = Annotation.objects.filter(user=self.import_user)
            self.assertGreater(imported_annotations.count(), 0)
            
            # In bulk mode, annotation names should not have [IMPORTED] prefix
            for annotation in imported_annotations:
                if annotation.annotation_name:
                    self.assertNotIn('[IMPORTED]', annotation.annotation_name)
            
            # Verify specific annotations exist with original names
            original_annotation = Annotation.objects.filter(
                user=self.import_user,
                annotation_name='Original Annotation'
            ).first()
            self.assertIsNotNone(original_annotation)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_user_mode_adds_import_marking(self):
        """Test that user mode adds [IMPORTED] marking to annotations"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with user mode
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path, 
                bulk_transfer_mode=False
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify annotations were imported with [IMPORTED] prefix
            imported_annotations = Annotation.objects.filter(user=self.import_user)
            self.assertGreater(imported_annotations.count(), 0)
            
            # In user mode, annotation names should have [IMPORTED] prefix
            for annotation in imported_annotations:
                if annotation.annotation_name:
                    self.assertIn('[IMPORTED]', annotation.annotation_name)
            
            # Verify specific annotation has import marking
            imported_annotation = Annotation.objects.filter(
                user=self.import_user,
                annotation_name='[IMPORTED] Original Annotation'
            ).first()
            self.assertIsNotNone(imported_annotation)
            
        finally:
            os.unlink(temp_zip_path)


class BulkTransferModeAPITest(TestCase):
    """Test bulk transfer mode through API endpoints"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='api_test_user',
            email='api@test.com',
            password='testpass123'
        )
    
    def test_user_data_importer_initialization(self):
        """Test UserDataImporter initialization with bulk_transfer_mode"""
        with tempfile.NamedTemporaryFile(suffix='.zip') as temp_file:
            # Test with bulk_transfer_mode=True
            importer_bulk = UserDataImporter(
                self.user, 
                temp_file.name, 
                bulk_transfer_mode=True
            )
            self.assertTrue(importer_bulk.bulk_transfer_mode)
            
            # Test with bulk_transfer_mode=False (default)
            importer_user = UserDataImporter(
                self.user, 
                temp_file.name, 
                bulk_transfer_mode=False
            )
            self.assertFalse(importer_user.bulk_transfer_mode)
            
            # Test default behavior
            importer_default = UserDataImporter(self.user, temp_file.name)
            self.assertFalse(importer_default.bulk_transfer_mode)


class BulkTransferModeComparisonTest(BulkTransferModeTestCase):
    """Test comparing bulk transfer mode vs user mode side by side"""
    
    def test_bulk_vs_user_mode_comparison(self):
        """Test comprehensive comparison between bulk and user modes"""
        zip_content = self.create_test_export()
        
        # Create two separate import users for comparison
        bulk_user = User.objects.create_user(
            username=f'bulk_compare_{int(time.time() * 1000)}',
            email=f'bulk_compare_{int(time.time() * 1000)}@test.com',
            password='testpass123'
        )
        
        user_mode_user = User.objects.create_user(
            username=f'user_compare_{int(time.time() * 1000)}',
            email=f'user_compare_{int(time.time() * 1000)}@test.com',
            password='testpass123'
        )
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with bulk transfer mode
            bulk_result = import_user_data_revised(
                bulk_user, 
                temp_zip_path, 
                bulk_transfer_mode=True
            )
            
            # Import with user mode
            user_result = import_user_data_revised(
                user_mode_user, 
                temp_zip_path, 
                bulk_transfer_mode=False
            )
            
            # Both should succeed
            self.assertTrue(bulk_result['success'])
            self.assertTrue(user_result['success'])
            
            # Compare reagent behavior
            bulk_reagents = Reagent.objects.filter(name__in=['Test Reagent Alpha', 'Test Reagent Beta'])
            # In bulk mode, new reagents are created even if names exist
            # In user mode, would depend on whether duplicates exist
            
            # Compare storage object names
            bulk_storage = StorageObject.objects.filter(user=bulk_user)
            user_storage = StorageObject.objects.filter(user=user_mode_user)
            
            # Bulk mode: original names preserved
            bulk_names = [obj.object_name for obj in bulk_storage]
            for name in bulk_names:
                self.assertNotIn('[IMPORTED]', name)
            
            # User mode: [IMPORTED] prefix added
            user_names = [obj.object_name for obj in user_storage]
            for name in user_names:
                self.assertIn('[IMPORTED]', name)
            
            # Compare annotation names
            bulk_annotations = Annotation.objects.filter(user=bulk_user)
            user_annotations = Annotation.objects.filter(user=user_mode_user)
            
            # Bulk mode: original names preserved
            for annotation in bulk_annotations:
                if annotation.annotation_name and 'Original' in annotation.annotation_name:
                    self.assertNotIn('[IMPORTED]', annotation.annotation_name)
            
            # User mode: [IMPORTED] prefix added
            for annotation in user_annotations:
                if annotation.annotation_name:
                    self.assertIn('[IMPORTED]', annotation.annotation_name)
            
        finally:
            os.unlink(temp_zip_path)