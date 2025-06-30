"""
Tests for sharing and permission models: DocumentPermission, sharing logic
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from cc.models import (
    Annotation, AnnotationFolder, DocumentPermission, Session,
    LabGroup
)


class DocumentPermissionTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'password')
        self.shared_user = User.objects.create_user('shared', 'shared@example.com', 'password')
        self.viewer_user = User.objects.create_user('viewer', 'viewer@example.com', 'password')
        
        # Create lab group
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='A test lab group'
        )
        self.lab_group.users.add(self.shared_user)
        
        # Create shared document folder
        self.shared_folder = AnnotationFolder.objects.create(
            folder_name='Shared Documents',
            is_shared_document_folder=True
        )
        
        # Create annotation in shared folder
        self.annotation = Annotation.objects.create(
            annotation='Test shared document',
            annotation_name='test_document.pdf',
            annotation_type='file',
            user=self.owner,
            folder=self.shared_folder
        )
    
    def test_document_permission_creation_for_annotation(self):
        """Test creating document permission for annotation"""
        permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            can_download=True,
            can_edit=False,
            can_delete=False,
            shared_by=self.owner
        )
        
        self.assertEqual(permission.annotation, self.annotation)
        self.assertEqual(permission.user, self.shared_user)
        self.assertTrue(permission.can_view)
        self.assertTrue(permission.can_download)
        self.assertFalse(permission.can_edit)
        self.assertFalse(permission.can_delete)
        self.assertEqual(permission.access_count, 0)
        self.assertFalse(permission.is_expired)
    
    def test_document_permission_creation_for_folder(self):
        """Test creating document permission for folder"""
        permission = DocumentPermission.objects.create(
            folder=self.shared_folder,
            user=self.shared_user,
            can_view=True,
            can_edit=True,
            shared_by=self.owner
        )
        
        self.assertEqual(permission.folder, self.shared_folder)
        self.assertEqual(permission.user, self.shared_user)
        self.assertTrue(permission.can_view)
        self.assertTrue(permission.can_edit)
    
    def test_document_permission_creation_for_lab_group(self):
        """Test creating document permission for lab group"""
        permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            lab_group=self.lab_group.group_name,
            lab_group_id=self.lab_group.id,
            can_view=True,
            can_download=True,
            shared_by=self.owner
        )
        
        self.assertEqual(permission.lab_group, self.lab_group.group_name)
        self.assertEqual(permission.lab_group_id, self.lab_group.id)
    
    def test_document_permission_expiration(self):
        """Test document permission expiration logic"""
        # Create permission that expires in the past
        past_time = timezone.now() - timedelta(hours=1)
        permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            expires_at=past_time,
            shared_by=self.owner
        )
        
        # is_expired should be True for expired permissions
        permission.refresh_from_db()
        self.assertTrue(permission.is_expired)
        
        # Create permission that expires in the future
        future_time = timezone.now() + timedelta(hours=1)
        permission2 = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.viewer_user,
            can_view=True,
            expires_at=future_time,
            shared_by=self.owner
        )
        
        # is_expired should be False for future expiration
        permission2.refresh_from_db()
        self.assertFalse(permission2.is_expired)
    
    def test_document_permission_validation_annotation_or_folder(self):
        """Test that permission must have either annotation OR folder, not both"""
        # Should work with annotation only
        permission1 = DocumentPermission(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            shared_by=self.owner
        )
        # This should not raise an error
        permission1.full_clean()
        permission1.save()
        
        # Should work with folder only
        permission2 = DocumentPermission(
            folder=self.shared_folder,
            user=self.viewer_user,
            can_view=True,
            shared_by=self.owner
        )
        # This should not raise an error
        permission2.full_clean()
        permission2.save()
        
        # Should fail with both annotation and folder
        permission3 = DocumentPermission(
            annotation=self.annotation,
            folder=self.shared_folder,
            user=self.shared_user,
            can_view=True,
            shared_by=self.owner
        )
        
        with self.assertRaises(ValidationError):
            permission3.full_clean()
    
    def test_access_count_tracking(self):
        """Test access count increment functionality"""
        permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            shared_by=self.owner
        )
        
        self.assertEqual(permission.access_count, 0)
        self.assertIsNone(permission.last_accessed)
        
        # Simulate access
        original_time = timezone.now()
        permission.access_count += 1
        permission.last_accessed = original_time
        permission.save()
        
        permission.refresh_from_db()
        self.assertEqual(permission.access_count, 1)
        self.assertIsNotNone(permission.last_accessed)
    
    def test_user_can_access_annotation_with_folder_inheritance(self):
        """Test the complex permission checking method"""
        # Create folder permission
        folder_permission = DocumentPermission.objects.create(
            folder=self.shared_folder,
            user=self.shared_user,
            can_view=True,
            can_download=True,
            can_edit=False,
            shared_by=self.owner
        )
        
        # Test direct access through folder inheritance
        can_view = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_view'
        )
        self.assertTrue(can_view)
        
        can_download = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_download'
        )
        self.assertTrue(can_download)
        
        can_edit = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_edit'
        )
        self.assertFalse(can_edit)
        
        # Test with direct annotation permission (should override folder)
        annotation_permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            can_download=False,  # Override folder permission
            can_edit=True,       # Override folder permission
            shared_by=self.owner
        )
        
        # Direct annotation permission should take precedence
        can_download_direct = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_download'
        )
        self.assertFalse(can_download_direct)  # Should be False from direct permission
        
        can_edit_direct = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_edit'
        )
        self.assertTrue(can_edit_direct)  # Should be True from direct permission
    
    def test_lab_group_permission_inheritance(self):
        """Test permission inheritance through lab groups"""
        # Create lab group permission
        lab_permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            lab_group=self.lab_group.group_name,
            lab_group_id=self.lab_group.id,
            can_view=True,
            can_download=True,
            shared_by=self.owner
        )
        
        # shared_user is in the lab_group, so should have access
        can_view = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_view'
        )
        self.assertTrue(can_view)
        
        # viewer_user is not in the lab_group, so should not have access
        can_view_other = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.viewer_user, self.annotation, 'can_view'
        )
        self.assertFalse(can_view_other)
    
    def test_expired_permission_ignored(self):
        """Test that expired permissions are ignored"""
        # Create expired permission
        past_time = timezone.now() - timedelta(hours=1)
        expired_permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            expires_at=past_time,
            shared_by=self.owner
        )
        
        # Should not have access due to expiration
        can_view = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_view'
        )
        self.assertFalse(can_view)
    
    def test_owner_always_has_access(self):
        """Test that annotation owner always has access"""
        # Owner should have access even without explicit permissions
        can_view = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.owner, self.annotation, 'can_view'
        )
        self.assertTrue(can_view)
        
        can_edit = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.owner, self.annotation, 'can_edit'
        )
        self.assertTrue(can_edit)
        
        can_delete = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.owner, self.annotation, 'can_delete'
        )
        self.assertTrue(can_delete)
    
    def test_permission_hierarchy_annotation_over_folder(self):
        """Test that direct annotation permissions override folder permissions"""
        # Create folder permission that allows download
        folder_permission = DocumentPermission.objects.create(
            folder=self.shared_folder,
            user=self.shared_user,
            can_view=True,
            can_download=True,
            shared_by=self.owner
        )
        
        # Create annotation permission that denies download
        annotation_permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            can_download=False,  # Override folder permission
            shared_by=self.owner
        )
        
        # Should respect annotation permission (False) over folder permission (True)
        can_download = DocumentPermission.user_can_access_annotation_with_folder_inheritance(
            self.shared_user, self.annotation, 'can_download'
        )
        self.assertFalse(can_download)
    
    def test_annotation_permission_check_integration(self):
        """Test integration with Annotation.check_for_right method"""
        # Create shared document permission
        permission = DocumentPermission.objects.create(
            annotation=self.annotation,
            user=self.shared_user,
            can_view=True,
            can_edit=False,
            can_delete=False,
            shared_by=self.owner
        )
        
        # Test through Annotation.check_for_right method
        can_view = self.annotation.check_for_right(self.shared_user, 'view')
        can_edit = self.annotation.check_for_right(self.shared_user, 'edit')
        can_delete = self.annotation.check_for_right(self.shared_user, 'delete')
        
        self.assertTrue(can_view)
        self.assertFalse(can_edit)
        self.assertFalse(can_delete)


class SharedDocumentSecurityTest(TestCase):
    """Test shared document security integration"""
    
    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'password')
        self.authorized_user = User.objects.create_user('auth', 'auth@example.com', 'password')
        self.unauthorized_user = User.objects.create_user('unauth', 'unauth@example.com', 'password')
        
        # Create shared document folder
        self.shared_folder = AnnotationFolder.objects.create(
            folder_name='Shared Documents',
            is_shared_document_folder=True
        )
        
        # Create regular folder (not shared document)
        self.regular_folder = AnnotationFolder.objects.create(
            folder_name='Regular Folder',
            is_shared_document_folder=False
        )
        
        # Create annotations
        self.shared_annotation = Annotation.objects.create(
            annotation='Shared document',
            annotation_name='shared_doc.pdf',
            folder=self.shared_folder,
            user=self.owner
        )
        
        self.regular_annotation = Annotation.objects.create(
            annotation='Regular annotation',
            annotation_name='regular_doc.pdf',
            folder=self.regular_folder,
            user=self.owner
        )
        
        # Create permission for shared document
        DocumentPermission.objects.create(
            annotation=self.shared_annotation,
            user=self.authorized_user,
            can_view=True,
            can_download=True,
            shared_by=self.owner
        )
    
    def test_shared_document_permission_enforcement(self):
        """Test that shared document permissions are properly enforced"""
        # Shared document should use DocumentPermission logic
        self.assertTrue(
            self.shared_annotation.check_for_right(self.owner, 'view')
        )
        self.assertTrue(
            self.shared_annotation.check_for_right(self.authorized_user, 'view')
        )
        self.assertFalse(
            self.shared_annotation.check_for_right(self.unauthorized_user, 'view')
        )
    
    def test_regular_annotation_permission_fallback(self):
        """Test that regular annotations use original permission logic"""
        # Regular annotation should not use DocumentPermission logic
        # (would need session or other permissions)
        self.assertTrue(
            self.regular_annotation.check_for_right(self.owner, 'view')
        )
        # Other users would need session access for regular annotations
        self.assertFalse(
            self.regular_annotation.check_for_right(self.authorized_user, 'view')
        )
    
    def test_shared_document_folder_identification(self):
        """Test proper identification of shared document folders"""
        self.assertTrue(self.shared_folder.is_shared_document_folder)
        self.assertFalse(self.regular_folder.is_shared_document_folder)
        
        # Annotations should inherit folder type
        self.assertTrue(
            self.shared_annotation.folder.is_shared_document_folder
        )
        self.assertFalse(
            self.regular_annotation.folder.is_shared_document_folder
        )