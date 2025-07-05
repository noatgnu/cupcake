"""
Comprehensive tests for import tracking and reversion functionality
"""
import os
import json
import uuid
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from cc.models import (
    ImportTracker, ImportedObject, ImportedFile, ImportedRelationship,
    ProtocolModel, Project, Session, Annotation
)
from cc.utils.user_data_import_revised import (
    UserDataImporter, ImportReverter, 
    revert_user_data_import, list_user_imports
)


class ImportTrackerModelTest(TestCase):
    """Test the import tracking models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.import_id = uuid.uuid4()
    
    def test_import_tracker_creation(self):
        """Test creating an import tracker"""
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/path/to/archive.zip',
            archive_size_mb=10.5,
            import_options={'protocols': True, 'sessions': False},
            metadata={'version': '1.0'}
        )
        
        self.assertEqual(tracker.import_id, self.import_id)
        self.assertEqual(tracker.user, self.user)
        self.assertEqual(tracker.import_status, 'in_progress')
        self.assertTrue(tracker.can_revert)
        self.assertEqual(tracker.total_objects_created, 0)
    
    def test_imported_object_creation(self):
        """Test tracking imported objects"""
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
        
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        
        imported_obj = ImportedObject.objects.create(
            import_tracker=tracker,
            model_name='ProtocolModel',
            object_id=protocol.id,
            original_id=123,
            object_data={'protocol_title': 'Test Protocol'}
        )
        
        self.assertEqual(imported_obj.import_tracker, tracker)
        self.assertEqual(imported_obj.model_name, 'ProtocolModel')
        self.assertEqual(imported_obj.object_id, protocol.id)
        self.assertEqual(imported_obj.original_id, 123)
    
    def test_imported_file_creation(self):
        """Test tracking imported files"""
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
        
        imported_file = ImportedFile.objects.create(
            import_tracker=tracker,
            file_path='media/test/file.jpg',
            original_name='file.jpg',
            file_size_bytes=1024
        )
        
        self.assertEqual(imported_file.import_tracker, tracker)
        self.assertEqual(imported_file.file_path, 'media/test/file.jpg')
        self.assertEqual(imported_file.file_size_bytes, 1024)
    
    def test_imported_relationship_creation(self):
        """Test tracking imported relationships"""
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
        
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        
        imported_rel = ImportedRelationship.objects.create(
            import_tracker=tracker,
            from_model='ProtocolModel',
            from_object_id=protocol.id,
            to_model='User',
            to_object_id=self.user.id,
            relationship_field='editors'
        )
        
        self.assertEqual(imported_rel.import_tracker, tracker)
        self.assertEqual(imported_rel.from_model, 'ProtocolModel')
        self.assertEqual(imported_rel.to_model, 'User')
        self.assertEqual(imported_rel.relationship_field, 'editors')


class ImportTrackerFunctionalityTest(TestCase):
    """Test the import tracker functionality in the importer"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Use permanent test fixture archive
        fixtures_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
        self.archive_path = os.path.join(fixtures_dir, 'test_import_archive.zip')
        
        # Ensure the fixture exists
        if not os.path.exists(self.archive_path):
            raise FileNotFoundError(f"Test fixture not found: {self.archive_path}")
        
        # Mock importer for testing tracking functionality
        self.importer = UserDataImporter(self.user, self.archive_path)
        
        # Mock importer for bulk transfer mode testing
        self.bulk_importer = UserDataImporter(self.user, self.archive_path, bulk_transfer_mode=True)
    
    def test_initialize_import_tracker(self):
        """Test import tracker initialization"""
        metadata = {'version': '1.0', 'exported_by': 'testuser'}
        
        self.importer._initialize_import_tracker(metadata)
        
        self.assertIsNotNone(self.importer.import_tracker)
        self.assertEqual(self.importer.import_tracker.user, self.user)
        self.assertEqual(self.importer.import_tracker.import_status, 'in_progress')
        self.assertEqual(self.importer.import_tracker.metadata, metadata)
        self.assertTrue(self.importer.import_tracker.can_revert)
    
    def test_track_created_object(self):
        """Test object tracking functionality"""
        # Initialize tracker
        self.importer._initialize_import_tracker()
        
        # Create and track an object
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        
        self.importer._track_created_object(protocol, original_id=123)
        
        # Verify tracking
        self.importer.import_tracker.refresh_from_db()
        self.assertEqual(self.importer.import_tracker.total_objects_created, 1)
        
        imported_obj = ImportedObject.objects.get(
            import_tracker=self.importer.import_tracker,
            object_id=protocol.id
        )
        self.assertEqual(imported_obj.model_name, 'ProtocolModel')
        self.assertEqual(imported_obj.original_id, 123)
        self.assertIn('protocol_title', imported_obj.object_data)
    
    def test_track_created_file(self):
        """Test file tracking functionality"""
        # Initialize tracker
        self.importer._initialize_import_tracker()
        
        # Use permanent test fixture file
        test_file_path = 'test_files/test_tracking_file.txt'
        full_path = os.path.join(settings.MEDIA_ROOT, test_file_path)
        
        # Ensure test file exists or create it
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        test_content = b'Test file content for import tracking'
        if not os.path.exists(full_path):
            with open(full_path, 'wb') as f:
                f.write(test_content)
        
        # Get actual file size
        actual_size = os.path.getsize(full_path)
        
        # Track the file
        self.importer._track_created_file(test_file_path, 'test_tracking_file.txt')
        
        # Verify tracking
        self.importer.import_tracker.refresh_from_db()
        self.assertEqual(self.importer.import_tracker.total_files_imported, 1)
        
        imported_file = ImportedFile.objects.get(
            import_tracker=self.importer.import_tracker
        )
        self.assertEqual(imported_file.file_path, test_file_path)
        self.assertEqual(imported_file.original_name, 'test_tracking_file.txt')
        self.assertEqual(imported_file.file_size_bytes, actual_size)
    
    def test_track_created_relationship(self):
        """Test relationship tracking functionality"""
        # Initialize tracker
        self.importer._initialize_import_tracker()
        
        # Create objects for relationship
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        
        # Track a relationship
        self.importer._track_created_relationship(protocol, self.user, 'editors')
        
        # Verify tracking
        self.importer.import_tracker.refresh_from_db()
        self.assertEqual(self.importer.import_tracker.total_relationships_created, 1)
        
        imported_rel = ImportedRelationship.objects.get(
            import_tracker=self.importer.import_tracker
        )
        self.assertEqual(imported_rel.from_model, 'ProtocolModel')
        self.assertEqual(imported_rel.to_model, 'User')
        self.assertEqual(imported_rel.relationship_field, 'editors')
    
    def test_finalize_import_tracker_success(self):
        """Test finalizing import tracker on success"""
        self.importer._initialize_import_tracker()
        
        self.importer._finalize_import_tracker(True)
        
        self.importer.import_tracker.refresh_from_db()
        self.assertEqual(self.importer.import_tracker.import_status, 'completed')
        self.assertIsNotNone(self.importer.import_tracker.import_completed_at)
    
    def test_finalize_import_tracker_failure(self):
        """Test finalizing import tracker on failure"""
        self.importer._initialize_import_tracker()
        
        self.importer._finalize_import_tracker(False)
        
        self.importer.import_tracker.refresh_from_db()
        self.assertEqual(self.importer.import_tracker.import_status, 'failed')
        self.assertIsNotNone(self.importer.import_tracker.import_completed_at)
    
    def test_bulk_transfer_mode_initialization(self):
        """Test that bulk transfer mode is properly initialized"""
        # Test bulk transfer mode enabled
        self.assertTrue(self.bulk_importer.bulk_transfer_mode)
        
        # Test normal mode
        self.assertFalse(self.importer.bulk_transfer_mode)
    
    def test_bulk_transfer_mode_tracking_same_as_normal(self):
        """Test that bulk transfer mode uses same tracking as normal mode"""
        # Initialize both trackers
        self.importer._initialize_import_tracker()
        self.bulk_importer._initialize_import_tracker()
        
        # Create and track objects in both modes
        protocol1 = ProtocolModel.objects.create(
            protocol_title='Normal Mode Protocol',
            user=self.user
        )
        protocol2 = ProtocolModel.objects.create(
            protocol_title='Bulk Mode Protocol',
            user=self.user
        )
        
        self.importer._track_created_object(protocol1, original_id=123)
        self.bulk_importer._track_created_object(protocol2, original_id=456)
        
        # Verify both tracking systems work the same way
        self.importer.import_tracker.refresh_from_db()
        self.bulk_importer.import_tracker.refresh_from_db()
        
        self.assertEqual(self.importer.import_tracker.total_objects_created, 1)
        self.assertEqual(self.bulk_importer.import_tracker.total_objects_created, 1)
        
        # Verify tracked objects exist for both
        normal_tracked = ImportedObject.objects.get(
            import_tracker=self.importer.import_tracker,
            object_id=protocol1.id
        )
        bulk_tracked = ImportedObject.objects.get(
            import_tracker=self.bulk_importer.import_tracker,
            object_id=protocol2.id
        )
        
        self.assertEqual(normal_tracked.model_name, 'ProtocolModel')
        self.assertEqual(bulk_tracked.model_name, 'ProtocolModel')
    
    def test_initialize_import_tracker_missing_archive_fails(self):
        """Test that missing archive file causes proper failure (no graceful fallback)"""
        # Create importer with non-existent archive
        missing_archive_path = '/non/existent/archive.zip'
        importer = UserDataImporter(self.user, missing_archive_path)
        
        # This should fail because the archive doesn't exist
        with self.assertRaises(FileNotFoundError):
            importer._initialize_import_tracker()
    
    def test_track_created_file_missing_file_fails(self):
        """Test that missing file causes proper failure (no graceful fallback)"""
        # Initialize tracker
        self.importer._initialize_import_tracker()
        
        # Try to track a non-existent file
        non_existent_file = 'non/existent/file.txt'
        
        # This should fail because the file doesn't exist
        with self.assertRaises(FileNotFoundError):
            self.importer._track_created_file(non_existent_file, 'file.txt')


class ImportReverterTest(TransactionTestCase):
    """Test import reversion functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staff@example.com',
            password='staffpass',
            is_staff=True
        )
        
        # Create a completed import tracker
        self.import_tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed',
            total_objects_created=0,
            total_files_imported=0,
            total_relationships_created=0
        )
    
    def test_revert_import_success(self):
        """Test successful import reversion"""
        # Create objects to track
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        project = Project.objects.create(
            project_name='Test Project',
            owner=self.user
        )
        
        # Track the objects
        ImportedObject.objects.create(
            import_tracker=self.import_tracker,
            model_name='ProtocolModel',
            object_id=protocol.id,
            object_data={'protocol_title': 'Test Protocol'}
        )
        ImportedObject.objects.create(
            import_tracker=self.import_tracker,
            model_name='Project',
            object_id=project.id,
            object_data={'project_name': 'Test Project'}
        )
        
        # Add a relationship
        protocol.editors.add(self.user)
        ImportedRelationship.objects.create(
            import_tracker=self.import_tracker,
            from_model='ProtocolModel',
            from_object_id=protocol.id,
            to_model='User',
            to_object_id=self.user.id,
            relationship_field='editors'
        )
        
        # Update tracker stats
        self.import_tracker.total_objects_created = 2
        self.import_tracker.total_relationships_created = 1
        self.import_tracker.save()
        
        # Revert the import
        reverter = ImportReverter(self.import_tracker, self.user)
        result = reverter.revert_import()
        
        # Verify reversion success
        self.assertTrue(result['success'])
        self.assertEqual(result['stats']['objects_deleted'], 2)
        self.assertEqual(result['stats']['relationships_removed'], 1)
        
        # Verify objects were deleted
        self.assertFalse(ProtocolModel.objects.filter(id=protocol.id).exists())
        self.assertFalse(Project.objects.filter(id=project.id).exists())
        
        # Verify tracker status
        self.import_tracker.refresh_from_db()
        self.assertEqual(self.import_tracker.import_status, 'reverted')
        self.assertIsNotNone(self.import_tracker.reverted_at)
        self.assertEqual(self.import_tracker.reverted_by, self.user)
    
    def test_revert_already_reverted_import(self):
        """Test attempting to revert an already reverted import"""
        self.import_tracker.import_status = 'reverted'
        self.import_tracker.save()
        
        reverter = ImportReverter(self.import_tracker, self.user)
        result = reverter.revert_import()
        
        self.assertFalse(result['success'])
        self.assertIn('already been reverted', result['error'])
    
    def test_revert_cannot_revert_import(self):
        """Test attempting to revert an import that cannot be reverted"""
        self.import_tracker.can_revert = False
        self.import_tracker.revert_reason = 'Import contained critical system data'
        self.import_tracker.save()
        
        reverter = ImportReverter(self.import_tracker, self.user)
        result = reverter.revert_import()
        
        self.assertFalse(result['success'])
        self.assertIn('cannot be reverted', result['error'])
        self.assertIn('critical system data', result['error'])
    
    @patch('os.path.exists')
    @patch('os.remove')
    def test_revert_files(self, mock_remove, mock_exists):
        """Test file reversion"""
        mock_exists.return_value = True
        
        # Create tracked files
        ImportedFile.objects.create(
            import_tracker=self.import_tracker,
            file_path='media/test/file1.jpg',
            original_name='file1.jpg',
            file_size_bytes=1024
        )
        ImportedFile.objects.create(
            import_tracker=self.import_tracker,
            file_path='media/test/file2.jpg',
            original_name='file2.jpg',
            file_size_bytes=2048
        )
        
        self.import_tracker.total_files_imported = 2
        self.import_tracker.save()
        
        # Revert the import
        reverter = ImportReverter(self.import_tracker, self.user)
        result = reverter.revert_import()
        
        # Verify files were removed
        self.assertTrue(result['success'])
        self.assertEqual(result['stats']['files_deleted'], 2)
        self.assertEqual(mock_remove.call_count, 2)


class ImportManagementFunctionsTest(TestCase):
    """Test management functions for import tracking"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass'
        )
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staff@example.com',
            password='staffpass',
            is_staff=True
        )
    
    def test_revert_user_data_import_success(self):
        """Test the revert_user_data_import function"""
        # Create an import tracker
        import_tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed'
        )
        
        # Create a tracked object
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        ImportedObject.objects.create(
            import_tracker=import_tracker,
            model_name='ProtocolModel',
            object_id=protocol.id,
            object_data={'protocol_title': 'Test Protocol'}
        )
        
        import_tracker.total_objects_created = 1
        import_tracker.save()
        
        # Revert using the function
        result = revert_user_data_import(str(import_tracker.import_id), self.user)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['stats']['objects_deleted'], 1)
        
        # Verify object was deleted
        self.assertFalse(ProtocolModel.objects.filter(id=protocol.id).exists())
    
    def test_revert_user_data_import_permission_denied(self):
        """Test revert with insufficient permissions"""
        import_tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed'
        )
        
        # Try to revert with different user
        result = revert_user_data_import(str(import_tracker.import_id), self.other_user)
        
        self.assertFalse(result['success'])
        self.assertIn('Insufficient permissions', result['error'])
    
    def test_revert_user_data_import_staff_permission(self):
        """Test revert with staff permissions"""
        import_tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed'
        )
        
        # Create a tracked object
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        ImportedObject.objects.create(
            import_tracker=import_tracker,
            model_name='ProtocolModel',
            object_id=protocol.id,
            object_data={'protocol_title': 'Test Protocol'}
        )
        
        import_tracker.total_objects_created = 1
        import_tracker.save()
        
        # Staff user should be able to revert
        result = revert_user_data_import(str(import_tracker.import_id), self.staff_user)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['stats']['objects_deleted'], 1)
    
    def test_revert_user_data_import_not_found(self):
        """Test revert with non-existent import ID"""
        non_existent_id = str(uuid.uuid4())
        
        result = revert_user_data_import(non_existent_id, self.user)
        
        self.assertFalse(result['success'])
        self.assertIn('not found', result['error'])
    
    def test_list_user_imports(self):
        """Test listing user imports"""
        # Create multiple imports
        tracker1 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive1.zip',
            import_status='completed',
            total_objects_created=5
        )
        tracker2 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive2.zip',
            import_status='reverted',
            total_objects_created=3
        )
        tracker3 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.other_user,
            archive_path='/path/to/archive3.zip',
            import_status='completed',
            total_objects_created=2
        )
        
        # List imports for user (exclude reverted)
        imports = list_user_imports(self.user, include_reverted=False)
        
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]['import_id'], str(tracker1.import_id))
        self.assertEqual(imports[0]['import_status'], 'completed')
        self.assertEqual(imports[0]['total_objects_created'], 5)
    
    def test_list_user_imports_include_reverted(self):
        """Test listing user imports including reverted ones"""
        # Create multiple imports
        tracker1 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive1.zip',
            import_status='completed'
        )
        tracker2 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive2.zip',
            import_status='reverted'
        )
        
        # List all imports for user
        imports = list_user_imports(self.user, include_reverted=True)
        
        self.assertEqual(len(imports), 2)
        import_ids = [imp['import_id'] for imp in imports]
        self.assertIn(str(tracker1.import_id), import_ids)
        self.assertIn(str(tracker2.import_id), import_ids)


class RevertImportCommandTest(TestCase):
    """Test the revert_import management command"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.import_tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed',
            archive_size_mb=10.5,
            total_objects_created=1
        )
        
        # Create a tracked object
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        ImportedObject.objects.create(
            import_tracker=self.import_tracker,
            model_name='ProtocolModel',
            object_id=self.protocol.id,
            object_data={'protocol_title': 'Test Protocol'}
        )
    
    def test_list_imports_command(self):
        """Test the --list option"""
        with patch('builtins.input', return_value='y'):
            call_command('revert_import', '--list', '--list-user', 'testuser')
    
    def test_dry_run_command(self):
        """Test the --dry-run option"""
        call_command('revert_import', str(self.import_tracker.import_id), '--dry-run')
        
        # Verify object still exists after dry run
        self.assertTrue(ProtocolModel.objects.filter(id=self.protocol.id).exists())
        
        # Verify tracker status unchanged
        self.import_tracker.refresh_from_db()
        self.assertEqual(self.import_tracker.import_status, 'completed')
    
    @patch('builtins.input', return_value='y')
    def test_revert_command_with_confirmation(self, mock_input):
        """Test the revert command with user confirmation"""
        call_command('revert_import', str(self.import_tracker.import_id))
        
        # Verify object was deleted
        self.assertFalse(ProtocolModel.objects.filter(id=self.protocol.id).exists())
        
        # Verify tracker status
        self.import_tracker.refresh_from_db()
        self.assertEqual(self.import_tracker.import_status, 'reverted')
    
    def test_revert_command_invalid_import_id(self):
        """Test revert command with invalid import ID"""
        invalid_id = str(uuid.uuid4())
        
        with self.assertRaises(CommandError):
            call_command('revert_import', invalid_id)
    
    def test_revert_command_invalid_user(self):
        """Test revert command with invalid reverting user"""
        with self.assertRaises(CommandError):
            call_command('revert_import', str(self.import_tracker.import_id), '--reverting-user', 'invaliduser')


class IntegrationTest(TransactionTestCase):
    """Integration tests for the complete import tracking and reversion workflow"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Use permanent test fixture archive
        fixtures_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
        self.archive_path = os.path.join(fixtures_dir, 'test_integration_archive.zip')
        
        # Ensure the fixture exists
        if not os.path.exists(self.archive_path):
            raise FileNotFoundError(f"Test fixture not found: {self.archive_path}")
    
    @patch.object(UserDataImporter, '_extract_and_validate_archive')
    @patch.object(UserDataImporter, '_load_and_validate_metadata')
    @patch.object(UserDataImporter, '_connect_to_import_database')
    @patch.object(UserDataImporter, '_import_remote_hosts')
    @patch.object(UserDataImporter, '_import_lab_groups')
    @patch.object(UserDataImporter, '_import_storage_objects')
    @patch.object(UserDataImporter, '_import_reagents')
    @patch.object(UserDataImporter, '_import_stored_reagents')
    @patch.object(UserDataImporter, '_import_projects')
    @patch.object(UserDataImporter, '_import_protocols_accurate')
    @patch.object(UserDataImporter, '_import_sessions_accurate')
    @patch.object(UserDataImporter, '_import_annotations_accurate')
    @patch.object(UserDataImporter, '_import_instruments_accurate')
    @patch.object(UserDataImporter, '_import_tags_and_relationships')
    @patch.object(UserDataImporter, '_import_metadata_and_support')
    @patch.object(UserDataImporter, '_import_media_files')
    @patch.object(UserDataImporter, '_import_remaining_relationships')
    @patch.object(UserDataImporter, '_cleanup')
    @patch('os.path.getsize')
    def test_complete_import_and_revert_workflow(self, mock_getsize, mock_cleanup, *mock_methods):
        """Test the complete workflow from import to revert"""
        mock_getsize.return_value = 1024 * 1024  # 1MB
        
        # Mock the methods to do nothing but allow tracking
        for mock_method in mock_methods:
            mock_method.return_value = None
        
        # Mock metadata
        metadata = {'version': '1.0', 'exported_by': 'testuser'}
        mock_methods[1].return_value = metadata  # _load_and_validate_metadata
        
        # Create importer and run import
        importer = UserDataImporter(self.user, self.archive_path)
        
        # Simulate creating some objects during import
        def mock_protocol_import():
            protocol = ProtocolModel.objects.create(
                protocol_title='Test Protocol',
                user=self.user
            )
            importer._track_created_object(protocol, original_id=123)
            
            project = Project.objects.create(
                project_name='Test Project',
                owner=self.user
            )
            importer._track_created_object(project, original_id=456)
        
        mock_methods[10].side_effect = mock_protocol_import  # _import_protocols_accurate
        
        # Run the import
        result = importer.import_user_data()
        
        # Verify import was successful and tracked
        self.assertTrue(result['success'])
        self.assertIn('import_id', result)
        
        # Verify import tracker was created
        import_tracker = ImportTracker.objects.get(import_id=result['import_id'])
        self.assertEqual(import_tracker.user, self.user)
        self.assertEqual(import_tracker.import_status, 'completed')
        self.assertEqual(import_tracker.total_objects_created, 2)
        
        # Verify objects exist
        protocol = ProtocolModel.objects.get(protocol_title='Test Protocol')
        project = Project.objects.get(project_name='Test Project')
        
        # Verify tracking records exist
        tracked_objects = ImportedObject.objects.filter(import_tracker=import_tracker)
        self.assertEqual(tracked_objects.count(), 2)
        
        # Now revert the import
        revert_result = revert_user_data_import(result['import_id'], self.user)
        
        # Verify revert was successful
        self.assertTrue(revert_result['success'])
        self.assertEqual(revert_result['stats']['objects_deleted'], 2)
        
        # Verify objects were deleted
        self.assertFalse(ProtocolModel.objects.filter(id=protocol.id).exists())
        self.assertFalse(Project.objects.filter(id=project.id).exists())
        
        # Verify import tracker status
        import_tracker.refresh_from_db()
        self.assertEqual(import_tracker.import_status, 'reverted')
        self.assertIsNotNone(import_tracker.reverted_at)
        self.assertEqual(import_tracker.reverted_by, self.user)