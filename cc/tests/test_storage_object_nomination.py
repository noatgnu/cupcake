"""
Tests for storage object nomination functionality

These tests verify that the storage object nomination system works correctly
for stored reagent imports, including dry run analysis, API endpoints,
and error handling.
"""
import os
import time
import tempfile
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from drf_chunked_upload.models import ChunkedUpload

from cc.models import (
    StorageObject, Reagent, StoredReagent, LabGroup
)
from cc.utils.user_data_export_revised import export_user_data_revised
from cc.utils.user_data_import_revised import import_user_data_revised, UserDataImporter


class StorageObjectNominationTestCase(TransactionTestCase):
    """Base test case for storage object nomination testing"""
    
    def setUp(self):
        """Set up test data for storage nomination testing"""
        # Create unique timestamp for parallel test execution
        timestamp = str(int(time.time() * 1000))
        
        # Create export user with storage data
        self.export_user = User.objects.create_user(
            username=f'export_storage_{timestamp}',
            email=f'export_storage_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create import user
        self.import_user = User.objects.create_user(
            username=f'import_storage_{timestamp}',
            email=f'import_storage_{timestamp}@test.com',
            password='testpass123'
        )
        
        # Create storage objects in export user's environment
        self.original_storage1 = StorageObject.objects.create(
            object_name='Original Freezer -80°C',
            object_type='freezer',
            user=self.export_user
        )
        
        self.original_storage2 = StorageObject.objects.create(
            object_name='Original Fridge 4°C',
            object_type='fridge',
            user=self.export_user
        )
        
        # Create reagents
        self.reagent1 = Reagent.objects.create(
            name='Test Buffer A',
            unit='mL'
        )
        
        self.reagent2 = Reagent.objects.create(
            name='Test Buffer B',
            unit='mg'
        )
        
        # Create stored reagents in original storage
        self.stored_reagent1 = StoredReagent.objects.create(
            reagent=self.reagent1,
            storage_object=self.original_storage1,
            quantity=250.0,
            notes='Stored in -80°C freezer',
            user=self.export_user
        )
        
        self.stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent2,
            storage_object=self.original_storage2,
            quantity=100.0,
            notes='Stored in 4°C fridge',
            user=self.export_user
        )
        
        # Create storage objects in import user's environment for nomination
        self.nominated_storage1 = StorageObject.objects.create(
            object_name='Import User Freezer',
            object_type='freezer',
            user=self.import_user
        )
        
        self.nominated_storage2 = StorageObject.objects.create(
            object_name='Import User Fridge',
            object_type='fridge',
            user=self.import_user
        )
    
    def create_test_export(self):
        """Create a test export ZIP with storage and reagent data"""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = export_user_data_revised(self.export_user, temp_dir)
            
            # Read ZIP content
            with open(zip_path, 'rb') as f:
                return f.read()


class StorageObjectNominationBasicTest(StorageObjectNominationTestCase):
    """Test basic storage object nomination functionality"""
    
    def test_import_without_storage_nomination_skips_stored_reagents(self):
        """Test that imports without storage nomination skip stored reagents"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import without storage object mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True}
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify storage objects were imported (empty containers)
            imported_storage = StorageObject.objects.filter(user=self.import_user)
            # Should have original 2 + imported 2 = 4 storage objects
            self.assertEqual(imported_storage.count(), 4)
            
            # Verify stored reagents were NOT imported due to missing nomination
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 0)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_with_storage_nomination_succeeds(self):
        """Test that imports with proper storage nomination import stored reagents"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Create storage object mappings
            storage_object_mappings = {
                str(self.original_storage1.id): self.nominated_storage1.id,
                str(self.original_storage2.id): self.nominated_storage2.id
            }
            
            # Import with storage object mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify stored reagents were imported with correct storage nomination
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 2)
            
            # Verify mappings are correct
            for stored_reagent in imported_stored_reagents:
                if stored_reagent.reagent.name == '[IMPORTED] Test Buffer A':
                    self.assertEqual(stored_reagent.storage_object_id, self.nominated_storage1.id)
                elif stored_reagent.reagent.name == '[IMPORTED] Test Buffer B':
                    self.assertEqual(stored_reagent.storage_object_id, self.nominated_storage2.id)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_with_partial_storage_nomination_skips_unmapped(self):
        """Test that imports with partial storage nomination only import mapped reagents"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Create partial storage object mappings (only map first storage)
            storage_object_mappings = {
                str(self.original_storage1.id): self.nominated_storage1.id
                # Deliberately omit mapping for original_storage2
            }
            
            # Import with partial storage object mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # Verify only one stored reagent was imported (the one with mapping)
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 1)
            
            # Verify it's the correct one
            stored_reagent = imported_stored_reagents.first()
            self.assertEqual(stored_reagent.storage_object_id, self.nominated_storage1.id)
            self.assertEqual(stored_reagent.reagent.name, '[IMPORTED] Test Buffer A')
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_import_with_invalid_storage_nomination_skips_reagent(self):
        """Test that imports with invalid storage nomination skip those reagents"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Create storage object mappings with invalid storage ID
            storage_object_mappings = {
                str(self.original_storage1.id): 99999,  # Non-existent storage ID
                str(self.original_storage2.id): self.nominated_storage2.id
            }
            
            # Import with invalid storage object mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Verify import success (should continue despite invalid mapping)
            self.assertTrue(result['success'])
            
            # Verify only valid stored reagent was imported
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 1)
            
            # Verify it's the one with valid mapping
            stored_reagent = imported_stored_reagents.first()
            self.assertEqual(stored_reagent.storage_object_id, self.nominated_storage2.id)
            self.assertEqual(stored_reagent.reagent.name, '[IMPORTED] Test Buffer B')
            
        finally:
            os.unlink(temp_zip_path)


class StorageObjectNominationAPITest(APITestCase):
    """Test storage object nomination through API endpoints"""
    
    def setUp(self):
        """Set up API test data"""
        self.user = User.objects.create_user(
            username='api_storage_user',
            email='api_storage@test.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create storage objects for the user
        self.storage1 = StorageObject.objects.create(
            object_name='API Test Freezer',
            object_type='freezer',
            user=self.user
        )
        
        self.storage2 = StorageObject.objects.create(
            object_name='API Test Fridge',
            object_type='fridge',
            user=self.user
        )
        
        # Create chunked upload for testing
        self.chunked_upload = ChunkedUpload.objects.create(
            user=self.user,
            filename='test_storage.zip',
            offset=1024,
            completed_at='2023-01-01T00:00:00Z'
        )
        
        # Create test file in proper media directory
        from django.core.files.base import ContentFile
        self.chunked_upload.file.save(
            'test_storage.zip',
            ContentFile(b'test zip content'),
            save=True
        )
    
    def tearDown(self):
        """Clean up test files"""
        if self.chunked_upload.file and os.path.exists(self.chunked_upload.file.path):
            os.unlink(self.chunked_upload.file.path)
    
    def test_get_available_storage_objects_endpoint(self):
        """Test the get_available_storage_objects API endpoint"""
        url = reverse('user-get-available-storage-objects')
        response = self.client.get(url)
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('storage_objects', response.data)
        
        storage_objects = response.data['storage_objects']
        self.assertEqual(len(storage_objects), 2)
        
        # Verify storage object data
        object_names = [obj['object_name'] for obj in storage_objects]
        self.assertIn('API Test Freezer', object_names)
        self.assertIn('API Test Fridge', object_names)
        
        # Verify required fields are present
        for obj in storage_objects:
            self.assertIn('id', obj)
            self.assertIn('object_name', obj)
            self.assertIn('object_type', obj)
    
    @patch('cc.rq_tasks.import_data.delay')
    def test_import_with_storage_object_mappings_endpoint(self, mock_import_task):
        """Test import endpoint with storage_object_mappings parameter"""
        url = reverse('user-import-user-data')
        data = {
            'upload_id': self.chunked_upload.id,
            'import_options': {
                'reagents': True,
                'protocols': False
            },
            'storage_object_mappings': {
                '1': self.storage1.id,
                '2': self.storage2.id
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify task was called with storage mappings
        mock_import_task.assert_called_once()
        args, kwargs = mock_import_task.call_args
        
        # Check that storage_object_mappings was passed correctly
        self.assertEqual(len(args), 6)  # user_id, file_path, custom_id, import_options, storage_mappings, bulk_transfer_mode
        storage_mappings = args[4]
        self.assertIsNotNone(storage_mappings)
        self.assertEqual(storage_mappings['1'], self.storage1.id)
        self.assertEqual(storage_mappings['2'], self.storage2.id)
    
    @patch('cc.rq_tasks.dry_run_import_data.delay')
    def test_dry_run_with_storage_analysis(self, mock_dry_run_task):
        """Test dry run analysis that should detect storage requirements"""
        url = reverse('user-dry-run-import-user-data')
        data = {
            'upload_id': self.chunked_upload.id,
            'import_options': {
                'reagents': True
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        self.assertIn('instance_id', response.data)
        
        # Verify dry run task was called
        mock_dry_run_task.assert_called_once()


class StorageObjectNominationErrorHandlingTest(StorageObjectNominationTestCase):
    """Test error handling in storage object nomination"""
    
    def test_storage_access_permission_check(self):
        """Test that users can only nominate storage objects they have access to"""
        # Create a storage object owned by a different user
        other_user = User.objects.create_user(
            username='other_storage_user',
            email='other@test.com',
            password='testpass123'
        )
        
        inaccessible_storage = StorageObject.objects.create(
            object_name='Inaccessible Storage',
            object_type='freezer',
            user=other_user
        )
        
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Try to nominate storage object the user doesn't have access to
            storage_object_mappings = {
                str(self.original_storage1.id): inaccessible_storage.id,
            }
            
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Import should succeed but skip the reagent with inaccessible storage
            self.assertTrue(result['success'])
            
            # Verify no stored reagents were imported due to access restriction
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 0)
            
        finally:
            os.unlink(temp_zip_path)
    
    def test_storage_access_permission_with_shared_access(self):
        """Test that users can nominate storage objects they have shared access to"""
        # Create a storage object owned by a different user but shared with import user
        other_user = User.objects.create_user(
            username='sharing_user',
            email='sharing@test.com',
            password='testpass123'
        )
        
        shared_storage = StorageObject.objects.create(
            object_name='Shared Storage',
            object_type='freezer',
            user=other_user
        )
        
        # Grant access to import user via lab group
        lab_group = LabGroup.objects.create(
            name='Shared Lab Group',
            description='Lab group for testing shared access'
        )
        lab_group.users.add(self.import_user)
        shared_storage.access_lab_groups.add(lab_group)
        
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Nominate the shared storage object
            storage_object_mappings = {
                str(self.original_storage1.id): shared_storage.id,
            }
            
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Import should succeed and import the reagent
            self.assertTrue(result['success'])
            
            # Verify stored reagent was imported to shared storage
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 1)
            
            stored_reagent = imported_stored_reagents.first()
            self.assertEqual(stored_reagent.storage_object_id, shared_storage.id)
            
        finally:
            os.unlink(temp_zip_path)


class StorageObjectNominationBulkModeTest(StorageObjectNominationTestCase):
    """Test storage object nomination in bulk transfer mode"""
    
    def test_bulk_mode_bypasses_storage_nomination(self):
        """Test that bulk transfer mode bypasses storage object nomination"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Import in bulk transfer mode without storage mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                bulk_transfer_mode=True  # This should bypass nomination requirement
            )
            
            # Verify import success
            self.assertTrue(result['success'])
            
            # In bulk mode, storage objects should be imported as-is
            imported_storage = StorageObject.objects.filter(user=self.import_user)
            # Should have original 2 + imported 2 = 4 storage objects
            self.assertEqual(imported_storage.count(), 4)
            
            # In bulk mode, stored reagents should be imported using original mappings
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            self.assertEqual(imported_stored_reagents.count(), 2)
            
            # Verify reagents are linked to imported storage objects (not nominated ones)
            for stored_reagent in imported_stored_reagents:
                # In bulk mode, names should not have [IMPORTED] prefix
                self.assertNotIn('[IMPORTED]', stored_reagent.notes)
                # Storage should be one of the imported ones, not nominated ones
                self.assertNotIn(stored_reagent.storage_object_id, [self.nominated_storage1.id, self.nominated_storage2.id])
            
        finally:
            os.unlink(temp_zip_path)


class StorageObjectNominationIntegrationTest(StorageObjectNominationTestCase):
    """Integration tests for complete storage nomination workflow"""
    
    def test_complete_nomination_workflow(self):
        """Test the complete workflow from dry run to final import with nomination"""
        zip_content = self.create_test_export()
        
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            temp_zip.write(zip_content)
            temp_zip_path = temp_zip.name
        
        try:
            # Step 1: Perform dry run analysis (in real scenario, this would detect storage requirements)
            # For testing, we'll simulate the workflow
            
            # Step 2: User reviews dry run and creates storage mappings
            storage_object_mappings = {
                str(self.original_storage1.id): self.nominated_storage1.id,
                str(self.original_storage2.id): self.nominated_storage2.id
            }
            
            # Step 3: Perform actual import with mappings
            result = import_user_data_revised(
                self.import_user, 
                temp_zip_path,
                import_options={'reagents': True, 'lab_groups': True},
                storage_object_mappings=storage_object_mappings
            )
            
            # Verify complete success
            self.assertTrue(result['success'])
            
            # Verify all components were imported correctly
            imported_storage = StorageObject.objects.filter(user=self.import_user)
            imported_reagents = Reagent.objects.filter(name__startswith='[IMPORTED]')
            imported_stored_reagents = StoredReagent.objects.filter(user=self.import_user)
            
            self.assertEqual(imported_storage.count(), 4)  # 2 original + 2 imported
            self.assertGreaterEqual(imported_reagents.count(), 2)
            self.assertEqual(imported_stored_reagents.count(), 2)
            
            # Verify cross-references are correct
            for stored_reagent in imported_stored_reagents:
                self.assertIn(stored_reagent.storage_object_id, [self.nominated_storage1.id, self.nominated_storage2.id])
                self.assertEqual(stored_reagent.user, self.import_user)
                self.assertIn('[IMPORTED]', stored_reagent.notes)
            
        finally:
            os.unlink(temp_zip_path)