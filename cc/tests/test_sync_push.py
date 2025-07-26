"""
Tests for bidirectional sync (push functionality)
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from cc.models import RemoteHost, ProtocolModel, Project
from cc.services.sync_service import SyncService, SyncError
from cc.utils.sync_auth import SyncAuthenticator


class SyncPushServiceTests(TestCase):
    """Test cases for SyncService push functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test.remote.com',
            host_port=443,
            host_protocol='https',
            host_description='Test remote host',
            host_token='encrypted_test_token'
        )
        
        # Create test protocol
        self.protocol = ProtocolModel.objects.create(
            title='Test Protocol',
            description='Test description',
            user=self.user,
            enabled=True,
            is_vaulted=False  # Local protocol, not synced
        )
        
        # Create test project  
        self.project = Project.objects.create(
            project_name='Test Project',
            project_description='Test project description',
            user=self.user,
            is_vaulted=False  # Local project, not synced
        )
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_push_single_object_create_success(self, mock_auth_class):
        """Test successful creation of new object on remote"""
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.session = Mock()
        mock_auth.base_url = 'https://test.remote.com'
        mock_auth_class.return_value = mock_auth
        
        # Mock successful creation response
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'id': 123, 'title': 'Test Protocol'}
        mock_auth.session.get.return_value = Mock(status_code=404)  # Object doesn't exist
        mock_auth.session.post.return_value = mock_response
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service._push_single_object(
                self.protocol, 'protocol', 'timestamp'
            )
            
            self.assertTrue(result['success'])
            self.assertEqual(result['action'], 'created')
            self.assertEqual(result['local_id'], self.protocol.id)
            self.assertEqual(result['remote_id'], 123)
            
            # Verify protocol was updated with remote ID
            self.protocol.refresh_from_db()
            self.assertEqual(self.protocol.remote_id, 123)
            self.assertEqual(self.protocol.remote_host, self.remote_host)
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_push_single_object_update_success(self, mock_auth_class):
        """Test successful update of existing object on remote"""
        # Set up protocol with remote ID
        self.protocol.remote_id = 123
        self.protocol.remote_host = self.remote_host
        self.protocol.save()
        
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.session = Mock()
        mock_auth.base_url = 'https://test.remote.com'
        mock_auth_class.return_value = mock_auth
        
        # Mock existing object and successful update
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            'id': 123,
            'title': 'Old Title',
            'updated_at': '2024-01-01T00:00:00Z'
        }
        mock_auth.session.get.return_value = mock_get_response
        
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_auth.session.put.return_value = mock_put_response
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service._push_single_object(
                self.protocol, 'protocol', 'timestamp'
            )
            
            self.assertTrue(result['success'])
            self.assertEqual(result['action'], 'updated')
            self.assertEqual(result['local_id'], self.protocol.id)
            self.assertEqual(result['remote_id'], 123)
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_push_conflict_timestamp_strategy(self, mock_auth_class):
        """Test conflict resolution with timestamp strategy"""
        # Set up protocol modified yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        self.protocol.updated_at = yesterday
        self.protocol.remote_id = 123
        self.protocol.save()
        
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.session = Mock()
        mock_auth.base_url = 'https://test.remote.com'
        mock_auth_class.return_value = mock_auth
        
        # Mock remote object that's newer
        today = datetime.now(timezone.utc)
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            'id': 123,
            'title': 'Remote Title',
            'updated_at': today.isoformat()
        }
        mock_auth.session.get.return_value = mock_get_response
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service._push_single_object(
                self.protocol, 'protocol', 'timestamp'
            )
            
            self.assertEqual(result['action'], 'skipped')
            self.assertTrue(result['has_conflict'])
            self.assertEqual(result['conflict_type'], 'remote_newer')
            self.assertEqual(result['reason'], 'Remote object is newer')
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_push_conflict_force_strategy(self, mock_auth_class):
        """Test conflict resolution with force_push strategy"""
        # Set up protocol modified yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        self.protocol.updated_at = yesterday
        self.protocol.remote_id = 123
        self.protocol.save()
        
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.session = Mock()
        mock_auth.base_url = 'https://test.remote.com'
        mock_auth_class.return_value = mock_auth
        
        # Mock remote object that's newer
        today = datetime.now(timezone.utc)
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            'id': 123,
            'title': 'Remote Title',
            'updated_at': today.isoformat()
        }
        mock_auth.session.get.return_value = mock_get_response
        
        # Mock successful force update
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_auth.session.put.return_value = mock_put_response
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service._push_single_object(
                self.protocol, 'protocol', 'force_push'
            )
            
            self.assertTrue(result['success'])
            self.assertEqual(result['action'], 'updated')
    
    def test_get_local_objects_to_push(self):
        """Test filtering local objects for push"""
        # Create vaulted protocol (should be excluded)
        vaulted_protocol = ProtocolModel.objects.create(
            title='Vaulted Protocol',
            description='From remote',
            user=self.user,
            enabled=True,
            is_vaulted=True,
            remote_id=456,
            remote_host=self.remote_host
        )
        
        # Create another user's protocol (should be excluded)
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com'
        )
        other_protocol = ProtocolModel.objects.create(
            title='Other User Protocol',
            description='Not accessible',
            user=other_user,
            enabled=True,
            is_vaulted=False
        )
        
        with SyncService(self.remote_host, self.user) as sync_service:
            objects = sync_service._get_local_objects_to_push('protocol')
            
            # Should only include the local user's non-vaulted protocol
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].id, self.protocol.id)
    
    def test_get_local_objects_modified_since(self):
        """Test filtering by modification date"""
        # Create protocol modified yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        old_protocol = ProtocolModel.objects.create(
            title='Old Protocol',
            description='Modified yesterday',
            user=self.user,
            enabled=True,
            is_vaulted=False
        )
        old_protocol.updated_at = yesterday
        old_protocol.save()
        
        # Test filter with modified_since = today
        today = datetime.now(timezone.utc)
        
        with SyncService(self.remote_host, self.user) as sync_service:
            objects = sync_service._get_local_objects_to_push(
                'protocol', 
                modified_since=today
            )
            
            # Should only include protocols modified today (self.protocol)
            protocol_ids = [obj.id for obj in objects]
            self.assertIn(self.protocol.id, protocol_ids)
            self.assertNotIn(old_protocol.id, protocol_ids)
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_push_model_data_success(self, mock_auth_class):
        """Test pushing multiple objects of one model"""
        # Create additional protocol
        protocol2 = ProtocolModel.objects.create(
            title='Test Protocol 2',
            description='Second test protocol',
            user=self.user,
            enabled=True,
            is_vaulted=False
        )
        
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.session = Mock()
        mock_auth.base_url = 'https://test.remote.com'
        mock_auth_class.return_value = mock_auth
        
        # Mock successful creation responses
        mock_auth.session.get.side_effect = [
            Mock(status_code=404),  # First protocol doesn't exist
            Mock(status_code=404)   # Second protocol doesn't exist
        ]
        
        create_responses = [
            Mock(status_code=201, json=lambda: {'id': 123}),
            Mock(status_code=201, json=lambda: {'id': 124})
        ]
        mock_auth.session.post.side_effect = create_responses
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service.push_model_data(
                'protocol', 
                [self.protocol, protocol2], 
                'timestamp'
            )
            
            self.assertTrue(result['success'])
            self.assertEqual(result['pushed_count'], 2)
            self.assertEqual(result['updated_count'], 0)
            self.assertEqual(result['skipped_count'], 0)
            self.assertEqual(len(result['conflicts']), 0)
            self.assertEqual(len(result['errors']), 0)


class SyncPushAPITests(APITestCase):
    """Test cases for sync push API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test.remote.com',
            host_port=443,
            host_protocol='https',
            host_description='Test remote host',
            host_token='encrypted_test_token'
        )
        
        # Create test protocol
        self.protocol = ProtocolModel.objects.create(
            title='Test Protocol',
            description='Test description',
            user=self.user,
            enabled=True,
            is_vaulted=False
        )
    
    @patch('cc.services.sync_service.SyncService.push_local_changes')
    @patch('cc.services.sync_service.SyncService.authenticate')
    def test_sync_push_api_success(self, mock_auth, mock_push):
        """Test successful sync push via API"""
        # Mock successful authentication
        mock_auth.return_value = {'success': True, 'message': 'Authenticated'}
        
        # Mock successful push
        mock_push.return_value = {
            'success': True,
            'remote_host': 'test.remote.com',
            'models': {
                'protocol': {
                    'pushed_count': 1,
                    'updated_count': 0,
                    'skipped_count': 0,
                    'conflicts': [],
                    'errors': []
                }
            },
            'summary': {
                'total_pushed': 1,
                'total_updated': 0,
                'total_skipped': 0,
                'total_conflicts': 0,
                'total_errors': 0
            }
        }
        
        url = f'/api/remote_hosts/{self.remote_host.id}/sync-push/'
        data = {
            'models': ['protocol'],
            'conflict_strategy': 'timestamp',
            'limit': 10
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('Successfully pushed data', response.data['message'])
        self.assertEqual(response.data['results']['summary']['total_pushed'], 1)
    
    @patch('cc.services.sync_service.SyncService.push_local_changes')
    @patch('cc.services.sync_service.SyncService.authenticate')
    def test_sync_push_api_with_conflicts(self, mock_auth, mock_push):
        """Test sync push with conflicts returns 207 status"""
        # Mock successful authentication
        mock_auth.return_value = {'success': True, 'message': 'Authenticated'}
        
        # Mock push with conflicts
        mock_push.return_value = {
            'success': True,
            'remote_host': 'test.remote.com',
            'models': {
                'protocol': {
                    'pushed_count': 0,
                    'updated_count': 0,
                    'skipped_count': 1,
                    'conflicts': [{
                        'local_id': 1,
                        'remote_id': 123,
                        'conflict_type': 'remote_newer',
                        'reason': 'Remote object is newer'
                    }],
                    'errors': []
                }
            },
            'summary': {
                'total_pushed': 0,
                'total_updated': 0,
                'total_skipped': 1,
                'total_conflicts': 1,
                'total_errors': 0
            }
        }
        
        url = f'/api/remote_hosts/{self.remote_host.id}/sync-push/'
        data = {
            'models': ['protocol'],
            'conflict_strategy': 'timestamp'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_207_MULTI_STATUS)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['results']['summary']['total_conflicts'], 1)
    
    def test_sync_push_api_invalid_conflict_strategy(self):
        """Test API validation for invalid conflict strategy"""
        url = f'/api/remote_hosts/{self.remote_host.id}/sync-push/'
        data = {
            'conflict_strategy': 'invalid_strategy'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'invalid_conflict_strategy')
    
    def test_sync_push_api_invalid_date_format(self):
        """Test API validation for invalid modified_since format"""
        url = f'/api/remote_hosts/{self.remote_host.id}/sync-push/'
        data = {
            'modified_since': 'invalid-date'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'invalid_date_format')
    
    def test_sync_push_api_authentication_required(self):
        """Test that API requires authentication"""
        self.client.credentials()  # Remove authentication
        
        url = f'/api/remote_hosts/{self.remote_host.id}/sync-push/'
        response = self.client.post(url, {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SyncPushCommandTests(TestCase):
    """Test cases for sync_push management command"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test.remote.com',
            host_port=443,
            host_protocol='https',
            host_description='Test remote host',
            host_token='encrypted_test_token'
        )
        
        # Create test protocol
        self.protocol = ProtocolModel.objects.create(
            title='Test Protocol',
            description='Test description',
            user=self.user,
            enabled=True,
            is_vaulted=False
        )
    
    @patch('cc.services.sync_service.SyncService.authenticate')
    def test_command_test_auth_success(self, mock_auth):
        """Test command with --test-auth flag"""
        from django.core.management import call_command
        from io import StringIO
        
        # Mock successful authentication
        mock_auth.return_value = {'success': True, 'message': 'Authenticated'}
        
        out = StringIO()
        call_command(
            'sync_push',
            str(self.remote_host.id),
            str(self.user.id),
            '--test-auth',
            stdout=out
        )
        
        output = out.getvalue()
        self.assertIn('Authentication successful', output)
        mock_auth.assert_called_once()
    
    @patch('cc.services.sync_service.SyncService.push_local_changes')
    @patch('cc.services.sync_service.SyncService.authenticate')
    def test_command_full_push(self, mock_auth, mock_push):
        """Test command with full push"""
        from django.core.management import call_command
        from io import StringIO
        
        # Mock successful authentication
        mock_auth.return_value = {'success': True, 'message': 'Authenticated'}
        
        # Mock successful push
        mock_push.return_value = {
            'success': True,
            'remote_host': 'test.remote.com',
            'models': {},
            'summary': {
                'total_pushed': 1,
                'total_updated': 0,
                'total_skipped': 0,
                'total_conflicts': 0,
                'total_errors': 0
            }
        }
        
        out = StringIO()
        call_command(
            'sync_push',
            str(self.remote_host.id),
            str(self.user.id),
            '--models', 'protocol',
            '--verbose',
            stdout=out
        )
        
        output = out.getvalue()
        self.assertIn('Push completed successfully', output)
        self.assertIn('Created: 1', output)
        mock_push.assert_called_once()