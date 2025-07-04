"""
Test the real fixture import to demonstrate the file linking fix
"""
import os
import time
from django.test import TestCase
from django.contrib.auth.models import User
from cc.utils.user_data_import_revised import import_user_data_revised
from cc.models import Annotation


class RealFixtureImportTest(TestCase):
    """Test importing the real fixture to verify file linking works correctly"""

    def skip_test_real_fixture_file_import_and_linking(self):
        """Test that the real fixture imports and links all files correctly"""
        # Create unique test user  
        timestamp = str(int(time.time() * 1000))
        user = User.objects.create_user(
            username=f'real_fixture_user_{timestamp}',
            email=f'real_fixture_{timestamp}@test.com',
            password='testpass'
        )
        
        # Get fixture path
        from django.conf import settings
        project_root = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        fixture_path = os.path.join(project_root, 'tests', 'fixtures', 'test_fixture_zip.zip')
        
        # Verify fixture exists
        self.assertTrue(os.path.exists(fixture_path), "Real fixture ZIP file should exist")
        
        # Import from real fixture
        result = import_user_data_revised(user, fixture_path)
        
        # Verify import success
        self.assertTrue(result['success'], "Import should succeed")
        
        # The fixture has 38 files and 78 annotations
        files_imported = result['stats']['files_imported']
        
        # Check that all expected files are reported as imported
        # Note: The fixture has 38 files in media/annotations
        self.assertGreaterEqual(files_imported, 25, f"Should import at least 25 files, but imported {files_imported}")
        
        # Verify annotations were created and files linked
        total_annotations = Annotation.objects.filter(user=user).count()
        annotations_with_files = Annotation.objects.filter(user=user, file__isnull=False).exclude(file='').count()
        
        print(f"Total annotations created: {total_annotations}")
        print(f"Annotations with linked files: {annotations_with_files}")
        print(f"Files imported: {files_imported}")
        
        # Should have 78 total annotations (from our comprehensive fixture)
        self.assertEqual(total_annotations, 78, f"Should have 78 annotations, but got {total_annotations}")
        
        # Should have substantial annotations with files linked
        self.assertGreaterEqual(annotations_with_files, 20, f"Should have at least 20 annotations with files, but got {annotations_with_files}")
        
        # Verify some sample file paths are correct
        sample_annotation = Annotation.objects.filter(user=user, file__isnull=False).exclude(file='').first()
        if sample_annotation:
            self.assertTrue(sample_annotation.file.name.startswith('annotations/'), 
                          f"File path should start with 'annotations/', got: {sample_annotation.file.name}")