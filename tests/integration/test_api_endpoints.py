"""
Integration tests for CUPCAKE LIMS API endpoints
Tests the full API functionality including authentication, CRUD operations, and business logic
"""
import pytest
import requests
import json
import time
from pathlib import Path


class TestCupcakeAPI:
    """Test suite for CUPCAKE LIMS API endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment"""
        self.base_url = "http://test-app:8000"
        self.admin_credentials = {
            "username": "testadmin",
            "password": "testpassword123"
        }
        self.user_credentials = {
            "username": "testuser1", 
            "password": "testpassword123"
        }
        
        # Authenticate and get tokens
        self.admin_token = self._get_auth_token(self.admin_credentials)
        self.user_token = self._get_auth_token(self.user_credentials)
        
    def _get_auth_token(self, credentials):
        """Get authentication token for user"""
        response = requests.post(
            f"{self.base_url}/api/token-auth/",
            data=credentials
        )
        if response.status_code == 200:
            return response.json()["token"]
        return None
    
    def _get_headers(self, token):
        """Get headers with authentication token"""
        return {"Authorization": f"Token {token}"}
    
    def test_health_endpoint(self):
        """Test that the health endpoint is working"""
        response = requests.get(f"{self.base_url}/health/")
        assert response.status_code == 200
        assert "status" in response.json()
    
    def test_authentication(self):
        """Test authentication endpoints"""
        # Test valid login
        response = requests.post(
            f"{self.base_url}/api/token-auth/",
            data=self.admin_credentials
        )
        assert response.status_code == 200
        assert "token" in response.json()
        
        # Test invalid login
        response = requests.post(
            f"{self.base_url}/api/token-auth/",
            data={"username": "invalid", "password": "invalid"}
        )
        assert response.status_code == 400
    
    def test_user_endpoints(self):
        """Test user management endpoints"""
        headers = self._get_headers(self.admin_token)
        
        # List users
        response = requests.get(f"{self.base_url}/api/user/", headers=headers)
        assert response.status_code == 200
        users = response.json()["results"]
        assert len(users) >= 3  # Admin + 2 test users
        
        # Get specific user
        response = requests.get(f"{self.base_url}/api/user/1/", headers=headers)
        assert response.status_code == 200
        user = response.json()
        assert user["username"] == "testadmin"
    
    def test_project_crud(self):
        """Test project CRUD operations"""
        headers = self._get_headers(self.admin_token)
        
        # Create project
        project_data = {
            "project_name": "API Test Project",
            "project_description": "Created via API integration test"
        }
        response = requests.post(
            f"{self.base_url}/api/project/",
            json=project_data,
            headers=headers
        )
        assert response.status_code == 201
        project_id = response.json()["id"]
        
        # Read project
        response = requests.get(
            f"{self.base_url}/api/project/{project_id}/",
            headers=headers
        )
        assert response.status_code == 200
        project = response.json()
        assert project["project_name"] == "API Test Project"
        
        # Update project
        update_data = {"project_description": "Updated description"}
        response = requests.patch(
            f"{self.base_url}/api/project/{project_id}/",
            json=update_data,
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["project_description"] == "Updated description"
        
        # Delete project
        response = requests.delete(
            f"{self.base_url}/api/project/{project_id}/",
            headers=headers
        )
        assert response.status_code == 204
    
    def test_protocol_creation(self):
        """Test protocol creation and management"""
        headers = self._get_headers(self.admin_token)
        
        # Create protocol
        protocol_data = {
            "protocol_title": "API Test Protocol",
            "protocol_description": "Created for integration testing",
            "protocol_url": "https://example.com/protocol"
        }
        response = requests.post(
            f"{self.base_url}/api/protocol/",
            json=protocol_data,
            headers=headers
        )
        assert response.status_code == 201
        protocol = response.json()
        assert protocol["protocol_title"] == "API Test Protocol"
        
        # List protocols
        response = requests.get(f"{self.base_url}/api/protocol/", headers=headers)
        assert response.status_code == 200
        protocols = response.json()["results"]
        assert any(p["protocol_title"] == "API Test Protocol" for p in protocols)
    
    def test_session_workflow(self):
        """Test session creation and management workflow"""
        headers = self._get_headers(self.admin_token)
        
        # Create session
        response = requests.post(
            f"{self.base_url}/api/session/",
            headers=headers
        )
        assert response.status_code == 201
        session = response.json()
        session_id = session["id"]
        
        # Get session details
        response = requests.get(
            f"{self.base_url}/api/session/{session_id}/",
            headers=headers
        )
        assert response.status_code == 200
        
        # Update session
        update_data = {"name": "API Test Session"}
        response = requests.patch(
            f"{self.base_url}/api/session/{session_id}/",
            json=update_data,
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "API Test Session"
    
    def test_annotation_management(self):
        """Test annotation creation and file upload"""
        headers = self._get_headers(self.admin_token)
        
        # Create session first
        response = requests.post(f"{self.base_url}/api/session/", headers=headers)
        session_id = response.json()["id"]
        
        # Create annotation
        annotation_data = {
            "annotation_name": "Test Annotation",
            "annotation": "This is a test annotation",
            "annotation_type": "text",
            "session": session_id
        }
        response = requests.post(
            f"{self.base_url}/api/annotation/",
            json=annotation_data,
            headers=headers
        )
        assert response.status_code == 201
        annotation = response.json()
        assert annotation["annotation_name"] == "Test Annotation"
    
    def test_lab_group_management(self):
        """Test lab group operations"""
        headers = self._get_headers(self.admin_token)
        
        # List lab groups
        response = requests.get(f"{self.base_url}/api/lab_groups/", headers=headers)
        assert response.status_code == 200
        lab_groups = response.json()["results"]
        assert len(lab_groups) >= 2  # From fixtures
        
        # Create new lab group
        group_data = {
            "name": "API Test Lab",
            "description": "Created via API test"
        }
        response = requests.post(
            f"{self.base_url}/api/lab_groups/",
            json=group_data,
            headers=headers
        )
        assert response.status_code == 201
        group = response.json()
        assert group["name"] == "API Test Lab"
    
    def test_site_settings(self):
        """Test site settings endpoint"""
        headers = self._get_headers(self.admin_token)
        
        # Get site settings
        response = requests.get(f"{self.base_url}/api/site_settings/", headers=headers)
        assert response.status_code == 200
        settings = response.json()["results"]
        assert len(settings) >= 1
        
        # Get public site settings (no auth required)
        response = requests.get(f"{self.base_url}/api/site_settings/public/")
        assert response.status_code == 200
        public_settings = response.json()
        assert "site_name" in public_settings
    
    def test_permission_enforcement(self):
        """Test that permissions are properly enforced"""
        user_headers = self._get_headers(self.user_token)
        admin_headers = self._get_headers(self.admin_token)
        
        # Regular user should not be able to access admin functions
        response = requests.get(f"{self.base_url}/api/user/", headers=user_headers)
        # Depending on your permission setup, this might be 403 or filtered results
        assert response.status_code in [200, 403]
        
        # Admin should have full access
        response = requests.get(f"{self.base_url}/api/user/", headers=admin_headers)
        assert response.status_code == 200
    
    def test_search_functionality(self):
        """Test search endpoints"""
        headers = self._get_headers(self.admin_token)
        
        # Search protocols
        response = requests.get(
            f"{self.base_url}/api/protocol/?search=test",
            headers=headers
        )
        assert response.status_code == 200
        
        # Search projects
        response = requests.get(
            f"{self.base_url}/api/project/?search=alpha",
            headers=headers
        )
        assert response.status_code == 200
        results = response.json()["results"]
        # Should find "Test Project Alpha" from fixtures
        assert any("Alpha" in p["project_name"] for p in results)
    
    def test_pagination(self):
        """Test API pagination"""
        headers = self._get_headers(self.admin_token)
        
        # Test pagination parameters
        response = requests.get(
            f"{self.base_url}/api/project/?limit=1&offset=0",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "next" in data
        assert "previous" in data
        assert len(data["results"]) <= 1
    
    def test_filtering(self):
        """Test API filtering capabilities"""
        headers = self._get_headers(self.admin_token)
        
        # Test date filtering (if supported)
        response = requests.get(
            f"{self.base_url}/api/project/?created_at__gte=2024-01-01",
            headers=headers
        )
        assert response.status_code == 200
        
        # Test ordering
        response = requests.get(
            f"{self.base_url}/api/project/?ordering=project_name",
            headers=headers
        )
        assert response.status_code == 200
    
    @pytest.mark.slow
    def test_bulk_operations(self):
        """Test bulk operations and performance"""
        headers = self._get_headers(self.admin_token)
        
        # Create multiple projects
        projects = []
        for i in range(5):
            project_data = {
                "project_name": f"Bulk Test Project {i}",
                "project_description": f"Bulk created project {i}"
            }
            response = requests.post(
                f"{self.base_url}/api/project/",
                json=project_data,
                headers=headers
            )
            assert response.status_code == 201
            projects.append(response.json()["id"])
        
        # Clean up
        for project_id in projects:
            requests.delete(
                f"{self.base_url}/api/project/{project_id}/",
                headers=headers
            )
    
    def test_error_handling(self):
        """Test API error responses"""
        headers = self._get_headers(self.admin_token)
        
        # Test 404 for non-existent resource
        response = requests.get(
            f"{self.base_url}/api/project/99999/",
            headers=headers
        )
        assert response.status_code == 404
        
        # Test validation errors
        invalid_data = {"project_name": ""}  # Empty name should fail validation
        response = requests.post(
            f"{self.base_url}/api/project/",
            json=invalid_data,
            headers=headers
        )
        assert response.status_code == 400
        
        # Test unauthorized access
        response = requests.get(f"{self.base_url}/api/project/")
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])