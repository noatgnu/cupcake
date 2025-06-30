#!/usr/bin/env python
"""
Test script to validate shared document security measures
"""
import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth.models import User
from cc.models import Annotation, AnnotationFolder, DocumentPermission

def test_shared_document_permissions():
    """
    Test that shared document permissions are properly enforced
    """
    print("Testing shared document security measures...")
    
    # Create test users
    owner = User.objects.create_user('owner', 'owner@test.com', 'password')
    authorized_user = User.objects.create_user('auth_user', 'auth@test.com', 'password') 
    unauthorized_user = User.objects.create_user('unauth_user', 'unauth@test.com', 'password')
    
    # Create shared document folder
    shared_folder = AnnotationFolder.objects.create(
        folder_name="Test Shared Folder",
        is_shared_document_folder=True
    )
    
    # Create annotation in shared folder
    annotation = Annotation.objects.create(
        annotation="Test shared document",
        annotation_name="test_doc.pdf",
        folder=shared_folder,
        user=owner
    )
    
    # Create permission for authorized user
    permission = DocumentPermission.objects.create(
        annotation=annotation,
        user=authorized_user,
        can_view=True,
        can_download=True,
        can_edit=False,
        can_delete=False,
        shared_by=owner
    )
    
    print(f"Created annotation {annotation.id} in shared folder")
    print(f"Granted permissions to {authorized_user.username}")
    
    # Test permission checks
    print("\nTesting permission checks:")
    
    # Owner should have access
    can_view_owner = annotation.check_for_right(owner, "view")
    can_edit_owner = annotation.check_for_right(owner, "edit")
    print(f"Owner can view: {can_view_owner}")
    print(f"Owner can edit: {can_edit_owner}")
    
    # Authorized user should have view/download access only
    can_view_auth = annotation.check_for_right(authorized_user, "view")
    can_edit_auth = annotation.check_for_right(authorized_user, "edit")
    can_delete_auth = annotation.check_for_right(authorized_user, "delete")
    print(f"Authorized user can view: {can_view_auth}")
    print(f"Authorized user can edit: {can_edit_auth}")
    print(f"Authorized user can delete: {can_delete_auth}")
    
    # Unauthorized user should have no access
    can_view_unauth = annotation.check_for_right(unauthorized_user, "view")
    can_edit_unauth = annotation.check_for_right(unauthorized_user, "edit")
    print(f"Unauthorized user can view: {can_view_unauth}")
    print(f"Unauthorized user can edit: {can_edit_unauth}")
    
    # Cleanup
    annotation.delete()
    shared_folder.delete()
    owner.delete()
    authorized_user.delete()
    unauthorized_user.delete()
    
    print("\nTest completed successfully!")
    
    # Validate results
    assert can_view_owner == True, "Owner should be able to view"
    assert can_edit_owner == True, "Owner should be able to edit"
    assert can_view_auth == True, "Authorized user should be able to view"
    assert can_edit_auth == False, "Authorized user should not be able to edit"
    assert can_delete_auth == False, "Authorized user should not be able to delete"
    assert can_view_unauth == False, "Unauthorized user should not be able to view"
    assert can_edit_unauth == False, "Unauthorized user should not be able to edit"
    
    print("All security assertions passed!")

if __name__ == "__main__":
    test_shared_document_permissions()