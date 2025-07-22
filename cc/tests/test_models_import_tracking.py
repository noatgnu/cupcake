"""
Tests for import tracking models: ImportTracker, ImportedObject, ImportedFile, ImportedRelationship
"""
import uuid
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from cc.models import (
    ImportTracker, ImportedObject, ImportedFile, ImportedRelationship,
    ProtocolModel, Annotation, MetadataColumn
)


class ImportTrackerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('import_testuser', 'import_test@example.com', 'password')
        self.reverter_user = User.objects.create_user('reverter', 'reverter@example.com', 'password')
    
    def test_import_tracker_creation(self):
        """Test basic import tracker creation"""
        import_id = uuid.uuid4()
        tracker = ImportTracker.objects.create(
            import_id=import_id,
            user=self.user,
            archive_path='/path/to/archive.zip',
            archive_size_mb=15.5,
            import_options={'mode': 'full', 'overwrite': False},
            metadata={'source': 'test_import', 'version': '1.0'}
        )
        
        self.assertEqual(tracker.import_id, import_id)
        self.assertEqual(tracker.user, self.user)
        self.assertEqual(tracker.archive_path, '/path/to/archive.zip')
        self.assertEqual(tracker.archive_size_mb, 15.5)
        self.assertEqual(tracker.import_status, 'in_progress')  # Default status
        self.assertTrue(tracker.can_revert)  # Default should be True
        self.assertEqual(tracker.import_options['mode'], 'full')
        self.assertEqual(tracker.metadata['source'], 'test_import')
        self.assertEqual(tracker.total_objects_created, 0)  # Default
        self.assertEqual(tracker.total_files_imported, 0)  # Default
        self.assertEqual(tracker.total_relationships_created, 0)  # Default
        self.assertIsNotNone(tracker.import_started_at)
        self.assertIsNone(tracker.import_completed_at)
        self.assertIsNone(tracker.reverted_at)
        self.assertIsNone(tracker.reverted_by)
    
    def test_import_tracker_status_choices(self):
        """Test valid import status choices"""
        valid_statuses = ['in_progress', 'completed', 'failed', 'reverted']
        import_id = uuid.uuid4()
        
        for status in valid_statuses:
            tracker = ImportTracker.objects.create(
                import_id=import_id,
                user=self.user,
                archive_path=f'/path/to/archive_{status}.zip',
                import_status=status
            )
            # Change import_id for next iteration to avoid unique constraint
            import_id = uuid.uuid4()
            self.assertEqual(tracker.import_status, status)
    
    def test_import_tracker_completion(self):
        """Test marking import as completed"""
        tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
        
        # Simulate completion
        tracker.import_status = 'completed'
        tracker.import_completed_at = timezone.now()
        tracker.total_objects_created = 25
        tracker.total_files_imported = 10
        tracker.total_relationships_created = 15
        tracker.save()
        
        self.assertEqual(tracker.import_status, 'completed')
        self.assertIsNotNone(tracker.import_completed_at)
        self.assertEqual(tracker.total_objects_created, 25)
        self.assertEqual(tracker.total_files_imported, 10)
        self.assertEqual(tracker.total_relationships_created, 15)
    
    def test_import_tracker_reversion(self):
        """Test import reversion functionality"""
        tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed'
        )
        
        # Simulate reversion
        tracker.import_status = 'reverted'
        tracker.can_revert = False
        tracker.revert_reason = 'User requested rollback'
        tracker.reverted_at = timezone.now()
        tracker.reverted_by = self.reverter_user
        tracker.save()
        
        self.assertEqual(tracker.import_status, 'reverted')
        self.assertFalse(tracker.can_revert)
        self.assertEqual(tracker.revert_reason, 'User requested rollback')
        self.assertIsNotNone(tracker.reverted_at)
        self.assertEqual(tracker.reverted_by, self.reverter_user)
    
    def test_import_tracker_string_representation(self):
        """Test import tracker string representation"""
        import_id = uuid.uuid4()
        tracker = ImportTracker.objects.create(
            import_id=import_id,
            user=self.user,
            archive_path='/path/to/archive.zip',
            import_status='completed'
        )
        
        expected_str = f"Import {import_id} - {self.user.username} - completed"
        self.assertEqual(str(tracker), expected_str)
    
    def test_import_tracker_ordering(self):
        """Test import tracker ordering (should be by -import_started_at)"""
        import1 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive1.zip'
        )
        
        # Create second import slightly later
        import2 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive2.zip'
        )
        
        trackers = ImportTracker.objects.all()
        self.assertEqual(list(trackers), [import2, import1])  # Most recent first
    
    def test_import_tracker_unique_import_id(self):
        """Test unique constraint on import_id"""
        import_id = uuid.uuid4()
        
        ImportTracker.objects.create(
            import_id=import_id,
            user=self.user,
            archive_path='/path/to/archive1.zip'
        )
        
        # Try to create another tracker with same import_id
        with self.assertRaises(Exception):  # Should raise IntegrityError
            ImportTracker.objects.create(
                import_id=import_id,
                user=self.user,
                archive_path='/path/to/archive2.zip'
            )


class ImportedObjectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('object_testuser', 'object_test@example.com', 'password')
        self.tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
    
    def test_imported_object_creation(self):
        """Test basic imported object creation"""
        object_data = {
            'name': 'Test Protocol',
            'description': 'A test protocol from import',
            'original_fields': ['title', 'description', 'steps']
        }
        
        imported_obj = ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='ProtocolModel',
            object_id=123,
            original_id=456,
            object_data=object_data
        )
        
        self.assertEqual(imported_obj.import_tracker, self.tracker)
        self.assertEqual(imported_obj.model_name, 'ProtocolModel')
        self.assertEqual(imported_obj.object_id, 123)
        self.assertEqual(imported_obj.original_id, 456)
        self.assertEqual(imported_obj.object_data['name'], 'Test Protocol')
        self.assertIsNotNone(imported_obj.created_at)
    
    def test_imported_object_without_original_id(self):
        """Test imported object creation without original_id"""
        imported_obj = ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='Annotation',
            object_id=789,
            object_data={'annotation': 'Test annotation'}
        )
        
        self.assertIsNone(imported_obj.original_id)
        self.assertEqual(imported_obj.object_id, 789)
    
    def test_imported_object_string_representation(self):
        """Test imported object string representation"""
        imported_obj = ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='MetadataColumn',
            object_id=999,
            object_data={'name': 'Sample ID'}
        )
        
        expected_str = f"MetadataColumn(999) from import {self.tracker.import_id}"
        self.assertEqual(str(imported_obj), expected_str)
    
    def test_imported_object_unique_constraint(self):
        """Test unique constraint on (import_tracker, model_name, object_id)"""
        ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='ProtocolModel',
            object_id=123,
            object_data={'name': 'Test'}
        )
        
        # Try to create another with same constraint fields
        with self.assertRaises(Exception):  # Should raise IntegrityError
            ImportedObject.objects.create(
                import_tracker=self.tracker,
                model_name='ProtocolModel',
                object_id=123,
                object_data={'name': 'Test Duplicate'}
            )
    
    def test_imported_object_ordering(self):
        """Test imported object ordering (should be by created_at)"""
        obj1 = ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='ProtocolModel',
            object_id=1,
            object_data={'name': 'First'}
        )
        
        obj2 = ImportedObject.objects.create(
            import_tracker=self.tracker,
            model_name='ProtocolModel',
            object_id=2,
            object_data={'name': 'Second'}
        )
        
        objects = ImportedObject.objects.filter(import_tracker=self.tracker)
        self.assertEqual(list(objects), [obj1, obj2])  # Oldest first


class ImportedFileTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('file_testuser', 'file_test@example.com', 'password')
        self.tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
    
    def test_imported_file_creation(self):
        """Test basic imported file creation"""
        imported_file = ImportedFile.objects.create(
            import_tracker=self.tracker,
            file_path='/media/uploads/imported_file.pdf',
            original_name='research_data.pdf',
            file_size_bytes=1048576  # 1MB
        )
        
        self.assertEqual(imported_file.import_tracker, self.tracker)
        self.assertEqual(imported_file.file_path, '/media/uploads/imported_file.pdf')
        self.assertEqual(imported_file.original_name, 'research_data.pdf')
        self.assertEqual(imported_file.file_size_bytes, 1048576)
        self.assertIsNotNone(imported_file.created_at)
    
    def test_imported_file_string_representation(self):
        """Test imported file string representation"""
        imported_file = ImportedFile.objects.create(
            import_tracker=self.tracker,
            file_path='/media/uploads/test.jpg',
            original_name='test_image.jpg',
            file_size_bytes=512000
        )
        
        expected_str = f"File test_image.jpg from import {self.tracker.import_id}"
        self.assertEqual(str(imported_file), expected_str)
    
    def test_imported_file_ordering(self):
        """Test imported file ordering (should be by created_at)"""
        file1 = ImportedFile.objects.create(
            import_tracker=self.tracker,
            file_path='/media/uploads/file1.txt',
            original_name='file1.txt',
            file_size_bytes=1000
        )
        
        file2 = ImportedFile.objects.create(
            import_tracker=self.tracker,
            file_path='/media/uploads/file2.txt',
            original_name='file2.txt',
            file_size_bytes=2000
        )
        
        files = ImportedFile.objects.filter(import_tracker=self.tracker)
        self.assertEqual(list(files), [file1, file2])  # Oldest first


class ImportedRelationshipTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rel_testuser', 'rel_test@example.com', 'password')
        self.tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
    
    def test_imported_relationship_creation(self):
        """Test basic imported relationship creation"""
        relationship = ImportedRelationship.objects.create(
            import_tracker=self.tracker,
            from_model='ProtocolModel',
            from_object_id=123,
            to_model='MetadataColumn',
            to_object_id=456,
            relationship_field='metadata_columns'
        )
        
        self.assertEqual(relationship.import_tracker, self.tracker)
        self.assertEqual(relationship.from_model, 'ProtocolModel')
        self.assertEqual(relationship.from_object_id, 123)
        self.assertEqual(relationship.to_model, 'MetadataColumn')
        self.assertEqual(relationship.to_object_id, 456)
        self.assertEqual(relationship.relationship_field, 'metadata_columns')
        self.assertIsNotNone(relationship.created_at)
    
    def test_imported_relationship_string_representation(self):
        """Test imported relationship string representation"""
        relationship = ImportedRelationship.objects.create(
            import_tracker=self.tracker,
            from_model='InstrumentJob',
            from_object_id=789,
            to_model='SamplePool',
            to_object_id=101,
            relationship_field='sample_pools'
        )
        
        expected_str = "InstrumentJob(789) -> SamplePool(101)"
        self.assertEqual(str(relationship), expected_str)
    
    def test_imported_relationship_ordering(self):
        """Test imported relationship ordering (should be by created_at)"""
        rel1 = ImportedRelationship.objects.create(
            import_tracker=self.tracker,
            from_model='ProtocolModel',
            from_object_id=1,
            to_model='MetadataColumn',
            to_object_id=1,
            relationship_field='metadata_columns'
        )
        
        rel2 = ImportedRelationship.objects.create(
            import_tracker=self.tracker,
            from_model='ProtocolModel',
            from_object_id=1,
            to_model='MetadataColumn',
            to_object_id=2,
            relationship_field='metadata_columns'
        )
        
        relationships = ImportedRelationship.objects.filter(import_tracker=self.tracker)
        self.assertEqual(list(relationships), [rel1, rel2])  # Oldest first


class ImportTrackingIntegrationTest(TestCase):
    """Integration tests for import tracking models working together"""
    
    def setUp(self):
        self.user = User.objects.create_user('integration_testuser', 'integration_test@example.com', 'password')
        
    def test_complete_import_tracking_workflow(self):
        """Test complete import tracking workflow"""
        # 1. Create import tracker
        import_id = uuid.uuid4()
        tracker = ImportTracker.objects.create(
            import_id=import_id,
            user=self.user,
            archive_path='/path/to/test_archive.zip',
            archive_size_mb=25.7,
            import_options={'mode': 'selective', 'preserve_ids': True},
            metadata={'source_system': 'external_lab', 'export_version': '2.1'}
        )
        
        # 2. Create some imported objects
        protocol_obj = ImportedObject.objects.create(
            import_tracker=tracker,
            model_name='ProtocolModel',
            object_id=100,
            original_id=50,
            object_data={
                'protocol_title': 'Imported Protocol',
                'protocol_description': 'A protocol imported from external system',
                'steps_count': 5
            }
        )
        
        annotation_obj = ImportedObject.objects.create(
            import_tracker=tracker,
            model_name='Annotation',
            object_id=200,
            original_id=75,
            object_data={
                'annotation': 'Imported experimental data',
                'metadata_count': 3
            }
        )
        
        metadata_obj = ImportedObject.objects.create(
            import_tracker=tracker,
            model_name='MetadataColumn',
            object_id=300,
            original_id=150,
            object_data={
                'name': 'Sample Type',
                'value': 'Protein Extract',
                'type': 'choice'
            }
        )
        
        # 3. Create imported files
        pdf_file = ImportedFile.objects.create(
            import_tracker=tracker,
            file_path='/media/imports/protocol_document.pdf',
            original_name='protocol_v2.pdf',
            file_size_bytes=2097152  # 2MB
        )
        
        image_file = ImportedFile.objects.create(
            import_tracker=tracker,
            file_path='/media/imports/experimental_setup.jpg',
            original_name='setup_photo.jpg',
            file_size_bytes=524288  # 512KB
        )
        
        # 4. Create relationships
        protocol_annotation_rel = ImportedRelationship.objects.create(
            import_tracker=tracker,
            from_model='ProtocolModel',
            from_object_id=100,
            to_model='Annotation',
            to_object_id=200,
            relationship_field='annotations'
        )
        
        annotation_metadata_rel = ImportedRelationship.objects.create(
            import_tracker=tracker,
            from_model='Annotation',
            from_object_id=200,
            to_model='MetadataColumn',
            to_object_id=300,
            relationship_field='metadata_columns'
        )
        
        # 5. Update tracker statistics
        tracker.total_objects_created = 3
        tracker.total_files_imported = 2
        tracker.total_relationships_created = 2
        tracker.import_status = 'completed'
        tracker.import_completed_at = timezone.now()
        tracker.save()
        
        # Verify the complete workflow
        self.assertEqual(tracker.import_status, 'completed')
        self.assertEqual(tracker.total_objects_created, 3)
        self.assertEqual(tracker.total_files_imported, 2)
        self.assertEqual(tracker.total_relationships_created, 2)
        
        # Verify reverse relationships work
        imported_objects = tracker.imported_objects.all()
        imported_files = tracker.imported_files.all()
        imported_relationships = tracker.imported_relationships.all()
        
        self.assertEqual(imported_objects.count(), 3)
        self.assertEqual(imported_files.count(), 2)
        self.assertEqual(imported_relationships.count(), 2)
        
        # Verify specific objects
        self.assertIn(protocol_obj, imported_objects)
        self.assertIn(annotation_obj, imported_objects)
        self.assertIn(metadata_obj, imported_objects)
        
        self.assertIn(pdf_file, imported_files)
        self.assertIn(image_file, imported_files)
        
        self.assertIn(protocol_annotation_rel, imported_relationships)
        self.assertIn(annotation_metadata_rel, imported_relationships)
        
        # Test querying by model type
        protocol_objects = imported_objects.filter(model_name='ProtocolModel')
        self.assertEqual(protocol_objects.count(), 1)
        self.assertEqual(protocol_objects.first().object_id, 100)
        
        # Test querying relationships by model
        protocol_relationships = imported_relationships.filter(from_model='ProtocolModel')
        self.assertEqual(protocol_relationships.count(), 1)
        
    def test_import_cascade_deletion(self):
        """Test that related objects are deleted when tracker is deleted"""
        tracker = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/archive.zip'
        )
        
        # Create related objects
        obj = ImportedObject.objects.create(
            import_tracker=tracker,
            model_name='ProtocolModel',
            object_id=1,
            object_data={'name': 'test'}
        )
        
        file = ImportedFile.objects.create(
            import_tracker=tracker,
            file_path='/test/file.txt',
            original_name='file.txt',
            file_size_bytes=1000
        )
        
        rel = ImportedRelationship.objects.create(
            import_tracker=tracker,
            from_model='ProtocolModel',
            from_object_id=1,
            to_model='MetadataColumn',
            to_object_id=1,
            relationship_field='metadata_columns'
        )
        
        obj_id = obj.id
        file_id = file.id
        rel_id = rel.id
        
        # Delete tracker
        tracker.delete()
        
        # Related objects should be deleted due to CASCADE
        with self.assertRaises(ImportedObject.DoesNotExist):
            ImportedObject.objects.get(id=obj_id)
        
        with self.assertRaises(ImportedFile.DoesNotExist):
            ImportedFile.objects.get(id=file_id)
        
        with self.assertRaises(ImportedRelationship.DoesNotExist):
            ImportedRelationship.objects.get(id=rel_id)
    
    def test_import_tracking_by_user(self):
        """Test filtering imports by user"""
        user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
        
        # Create imports for both users
        import1 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/user1_archive.zip'
        )
        
        import2 = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=user2,
            archive_path='/path/to/user2_archive.zip'
        )
        
        # Query by user
        user1_imports = ImportTracker.objects.filter(user=self.user)
        user2_imports = ImportTracker.objects.filter(user=user2)
        
        self.assertEqual(user1_imports.count(), 1)
        self.assertEqual(user2_imports.count(), 1)
        self.assertIn(import1, user1_imports)
        self.assertIn(import2, user2_imports)
    
    def test_import_status_filtering(self):
        """Test filtering imports by status"""
        # Create imports with different statuses
        completed_import = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/completed.zip',
            import_status='completed'
        )
        
        failed_import = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/failed.zip',
            import_status='failed'
        )
        
        in_progress_import = ImportTracker.objects.create(
            import_id=uuid.uuid4(),
            user=self.user,
            archive_path='/path/to/in_progress.zip',
            import_status='in_progress'
        )
        
        # Query by status
        completed_imports = ImportTracker.objects.filter(import_status='completed')
        failed_imports = ImportTracker.objects.filter(import_status='failed')
        active_imports = ImportTracker.objects.filter(import_status='in_progress')
        
        self.assertEqual(completed_imports.count(), 1)
        self.assertEqual(failed_imports.count(), 1)
        self.assertEqual(active_imports.count(), 1)
        
        self.assertIn(completed_import, completed_imports)
        self.assertIn(failed_import, failed_imports)
        self.assertIn(in_progress_import, active_imports)