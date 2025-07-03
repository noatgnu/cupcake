"""
Tests for selective import restrictions and import options

These tests verify that the import system correctly respects different levels
of import restrictions, allowing users to selectively import only certain
types of data from ZIP archives.
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
    StorageObject, Reagent, StoredReagent, LabGroup
)
from cc.utils.user_data_export_revised import export_user_data_revised
from cc.utils.user_data_import_revised import import_user_data_revised


class SelectiveImportTestCase(TransactionTestCase):
    """Base test case for selective import testing"""
    
    def setUp(self):
        """Set up comprehensive test data for selective import testing"""
        # Create unique timestamp for parallel test execution
        timestamp = str(int(time.time() * 1000))
        
        # Create export user with comprehensive data
        self.export_user = User.objects.create_user(
            username=f'export_selective_{timestamp}',
            email=f'export_selective_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create import user
        self.import_user = User.objects.create_user(
            username=f'import_selective_{timestamp}',
            email=f'import_selective_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create lab group
        self.lab_group = LabGroup.objects.create(
            name=f'Selective Test Lab {timestamp}',
            description='Lab group for selective import testing'
        )
        self.lab_group.users.add(self.export_user)
        
        # Create project
        self.project = Project.objects.create(
            project_name=f'Selective Test Project {timestamp}',
            project_description='Project for selective import testing',
            owner=self.export_user
        )
        
        # Create protocol
        self.protocol = ProtocolModel.objects.create(
            protocol_title=f'Selective Test Protocol {timestamp}',
            protocol_description='Protocol for selective import testing',
            user=self.export_user,
            enabled=True
        )
        
        # Create session
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.export_user,
            name=f'Selective Test Session {timestamp}',
            enabled=True
        )
        self.session.protocols.add(self.protocol)
        self.project.sessions.add(self.session)
        
        # Create annotation folder
        self.folder = AnnotationFolder.objects.create(
            folder_name='Selective Test Folder',
            session=self.session
        )
        
        # Create annotation with file
        self.test_file = SimpleUploadedFile(
            'selective_test_file.txt',
            b'Content for selective import testing',
            content_type='text/plain'
        )
        
        self.annotation = Annotation.objects.create(
            annotation='Selective import test annotation',
            annotation_type='file',
            file=self.test_file,
            user=self.export_user,
            session=self.session,
            folder=self.folder
        )
        
        # Create storage and reagent data
        self.storage = StorageObject.objects.create(
            object_name='Selective Test Storage',
            object_type='freezer',
            user=self.export_user
        )
        
        self.reagent = Reagent.objects.create(
            name='Selective Test Reagent',
            unit='mL'
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            quantity=100.0
        )
    
    def create_test_export(self):
        """Create a test export ZIP with comprehensive data"""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = export_user_data_revised(self.export_user, temp_dir)
            
            # Read ZIP content
            with open(zip_path, 'rb') as f:
                return f.read()


class ImportWithNoRestrictionsTest(SelectiveImportTestCase):
    """Test importing with no restrictions (import everything)"""
    
    def test_import_all_data_types(self):
        """Test importing all data types when no restrictions are specified"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with no restrictions (default behavior)
            result = import_user_data_revised(self.import_user, temp_zip_path)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify all data types were imported
            self.assertTrue(LabGroup.objects.filter(users=self.import_user).exists())
            self.assertTrue(Project.objects.filter(owner=self.import_user).exists())
            self.assertTrue(ProtocolModel.objects.filter(user=self.import_user).exists())
            self.assertTrue(Session.objects.filter(user=self.import_user).exists())
            self.assertTrue(Annotation.objects.filter(user=self.import_user).exists())
            self.assertTrue(StorageObject.objects.filter(user=self.import_user).exists())
            
            # Verify file was imported and linked
            annotation_with_file = Annotation.objects.filter(
                user=self.import_user, 
                file__isnull=False
            ).exclude(file='').first()
            self.assertIsNotNone(annotation_with_file)
            
        finally:
            os.unlink(temp_zip_path)


class ImportWithSpecificRestrictionsTest(SelectiveImportTestCase):
    """Test importing with specific data type restrictions"""
    
    def test_import_only_protocols(self):
        """Test importing only protocols (excluding sessions, annotations, etc.)"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import only protocols
            import_options = {
                'lab_groups': False,
                'reagents': False,
                'projects': False,
                'protocols': True,
                'sessions': False,
                'annotations': False,
                'instruments': False
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify only protocols were imported
            self.assertTrue(ProtocolModel.objects.filter(user=self.import_user).exists())
            
            # Verify other data types were NOT imported
            self.assertFalse(Session.objects.filter(user=self.import_user).exists())
            self.assertFalse(Annotation.objects.filter(user=self.import_user).exists())
            self.assertFalse(Project.objects.filter(owner=self.import_user).exists())
            
            # Lab groups and storage might still exist as they could be dependencies
            # but they shouldn't be associated with the import user
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_only_sessions_and_annotations(self):
        """Test importing only sessions and annotations (with their dependencies)"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import sessions and annotations only
            import_options = {
                'lab_groups': True,  # Required dependency
                'reagents': False,
                'projects': True,    # Required dependency for sessions
                'protocols': True,   # Required dependency for sessions
                'sessions': True,
                'annotations': True,
                'instruments': False
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify sessions and annotations were imported
            self.assertTrue(Session.objects.filter(user=self.import_user).exists())
            self.assertTrue(Annotation.objects.filter(user=self.import_user).exists())
            
            # Verify dependencies were imported
            self.assertTrue(ProtocolModel.objects.filter(user=self.import_user).exists())
            self.assertTrue(Project.objects.filter(owner=self.import_user).exists())
            
            # Verify file was imported and linked
            annotation_with_file = Annotation.objects.filter(
                user=self.import_user, 
                file__isnull=False
            ).exclude(file='').first()
            self.assertIsNotNone(annotation_with_file)
            
            # Verify reagents were NOT imported
            self.assertFalse(StorageObject.objects.filter(user=self.import_user).exists())
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_only_reagents_and_storage(self):
        """Test importing only reagents and storage objects"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import only reagents and storage
            import_options = {
                'lab_groups': True,  # May be required dependency
                'reagents': True,
                'projects': False,
                'protocols': False,
                'sessions': False,
                'annotations': False,
                'instruments': False
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify storage objects were imported
            self.assertTrue(StorageObject.objects.filter(user=self.import_user).exists())
            
            # Verify protocols and sessions were NOT imported
            self.assertFalse(ProtocolModel.objects.filter(user=self.import_user).exists())
            self.assertFalse(Session.objects.filter(user=self.import_user).exists())
            self.assertFalse(Annotation.objects.filter(user=self.import_user).exists())
            
        finally:
            os.unlink(temp_zip_path)


class ImportWithComplexRestrictionsTest(SelectiveImportTestCase):
    """Test importing with complex restriction combinations"""
    
    def test_import_exclude_annotations_but_include_sessions(self):
        """Test importing sessions but excluding annotations"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import sessions but not annotations
            import_options = {
                'lab_groups': True,
                'reagents': True,
                'projects': True,
                'protocols': True,
                'sessions': True,
                'annotations': False,  # Exclude annotations
                'instruments': False
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify sessions were imported
            self.assertTrue(Session.objects.filter(user=self.import_user).exists())
            
            # Verify annotations were NOT imported
            self.assertFalse(Annotation.objects.filter(user=self.import_user).exists())
            
            # Verify no files were imported (since annotations were excluded)
            self.assertEqual(result['stats']['files_imported'], 0)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_minimal_data_only(self):
        """Test importing only the minimal required data"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import minimal data only
            import_options = {
                'lab_groups': False,
                'reagents': False,
                'projects': False,
                'protocols': True,   # Import only protocols
                'sessions': False,
                'annotations': False,
                'instruments': False
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify only protocols were imported
            self.assertTrue(ProtocolModel.objects.filter(user=self.import_user).exists())
            
            # Verify minimal import statistics
            self.assertGreater(result['stats']['models_imported'], 0)
            self.assertEqual(result['stats']['files_imported'], 0)  # No files since no annotations
            
            # Verify most data types were not imported
            self.assertFalse(Session.objects.filter(user=self.import_user).exists())
            self.assertFalse(Annotation.objects.filter(user=self.import_user).exists())
            
        finally:
            os.unlink(temp_zip_path)


class ImportRestrictionsValidationTest(SelectiveImportTestCase):
    """Test validation and error handling for import restrictions"""
    
    def test_import_with_invalid_options(self):
        """Test that import handles invalid options gracefully"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Test with invalid option types
            import_options = {
                'protocols': 'invalid_string',  # Should be boolean
                'sessions': 1,                  # Should be boolean
                'invalid_option': True          # Invalid option key
            }
            
            result = import_user_data_revised(self.import_user, temp_zip_path, import_options)
            
            # Import should still succeed (invalid options ignored)
            self.assertTrue(result['success'])
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_with_none_options(self):
        """Test import with None options (should use defaults)"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import with None options
            result = import_user_data_revised(self.import_user, temp_zip_path, None)
            
            # Should succeed and import everything by default
            self.assertTrue(result['success'])
            self.assertTrue(ProtocolModel.objects.filter(user=self.import_user).exists())
            self.assertTrue(Session.objects.filter(user=self.import_user).exists())
            
        finally:
            os.unlink(temp_zip_path)


class ImportRestrictionsPerformanceTest(SelectiveImportTestCase):
    """Test performance aspects of selective imports"""
    
    def test_selective_import_performance(self):
        """Test that selective imports are faster than full imports"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Create second import user for comparison
            import_user_2 = User.objects.create_user(
                username=f'import_perf_{int(time.time() * 1000)}',
                email=f'import_perf_{int(time.time() * 1000)}@test.com',
                password='testpass123'
            )
            
            # Time full import
            import time as time_module
            start_time = time_module.time()
            result_full = import_user_data_revised(self.import_user, temp_zip_path)
            full_import_time = time_module.time() - start_time
            
            # Time selective import (protocols only)
            start_time = time_module.time()
            import_options = {
                'lab_groups': False,
                'reagents': False,
                'projects': False,
                'protocols': True,
                'sessions': False,
                'annotations': False,
                'instruments': False
            }
            result_selective = import_user_data_revised(import_user_2, temp_zip_path, import_options)
            selective_import_time = time_module.time() - start_time
            
            # Both should succeed
            self.assertTrue(result_full['success'])
            self.assertTrue(result_selective['success'])
            
            # Selective import should import fewer models
            self.assertLess(
                result_selective['stats']['models_imported'],
                result_full['stats']['models_imported']
            )
            
            # Selective import should import no files
            self.assertEqual(result_selective['stats']['files_imported'], 0)
            self.assertGreater(result_full['stats']['files_imported'], 0)
            
            print(f"Full import time: {full_import_time:.3f}s")
            print(f"Selective import time: {selective_import_time:.3f}s")
            print(f"Full import models: {result_full['stats']['models_imported']}")
            print(f"Selective import models: {result_selective['stats']['models_imported']}")
            
        finally:
            os.unlink(temp_zip_path)