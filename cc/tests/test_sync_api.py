"""
Tests for sync-related API endpoints
"""

import json
from unittest.mock import Mock, patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.authtoken.models import Token

from cc.models import RemoteHost, ProtocolModel


class RemoteHostAPITestCase(TestCase):
    """Test cases for RemoteHost API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test-remote.local',
            host_port=8000,
            host_protocol='http',
            host_description='Test remote host'
        )
        
        # Set up a test token
        self.remote_host.encrypt_token('test-token-12345')
        self.remote_host.save()
    
    def test_list_remote_hosts(self):
        """Test listing remote hosts"""
        url = reverse('remotehost-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['host_name'], 'test-remote.local')
        self.assertEqual(response.data[0]['host_url'], 'http://test-remote.local:8000')
    
    def test_create_remote_host(self):
        """Test creating a new remote host"""
        url = reverse('remotehost-list')
        data = {
            'host_name': 'new-remote.local',
            'host_port': 9000,
            'host_protocol': 'https',
            'host_description': 'New test remote',
            'host_token': 'new-test-token'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['host_name'], 'new-remote.local')
        self.assertEqual(response.data['host_url'], 'https://new-remote.local:9000')
        
        # Verify token was encrypted and not returned
        self.assertNotIn('host_token', response.data)
        
        # Verify object was created
        new_host = RemoteHost.objects.get(host_name='new-remote.local')
        self.assertIsNotNone(new_host.host_token)
        self.assertEqual(new_host.decrypt_token(), 'new-test-token')
    
    def test_create_remote_host_validation_errors(self):
        """Test validation errors when creating remote host"""
        url = reverse('remotehost-list')
        
        # Test invalid port
        data = {
            'host_name': 'test.local',
            'host_port': 70000,  # Invalid port
            'host_protocol': 'http'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('host_port', response.data)
        
        # Test invalid protocol
        data = {
            'host_name': 'test.local',
            'host_port': 8000,
            'host_protocol': 'ftp'  # Invalid protocol
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('host_protocol', response.data)
        
        # Test invalid hostname
        data = {
            'host_name': '',  # Empty hostname
            'host_port': 8000,
            'host_protocol': 'http'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('host_name', response.data)
    
    def test_update_remote_host(self):
        """Test updating a remote host"""
        url = reverse('remotehost-detail', kwargs={'pk': self.remote_host.pk})
        data = {
            'host_name': 'updated-remote.local',
            'host_port': 9000,
            'host_protocol': 'https',
            'host_description': 'Updated description'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['host_name'], 'updated-remote.local')
        self.assertEqual(response.data['host_url'], 'https://updated-remote.local:9000')
        
        # Verify database was updated
        self.remote_host.refresh_from_db()
        self.assertEqual(self.remote_host.host_name, 'updated-remote.local')
    
    def test_delete_remote_host(self):
        """Test deleting a remote host"""
        url = reverse('remotehost-detail', kwargs={'pk': self.remote_host.pk})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify object was deleted
        self.assertFalse(RemoteHost.objects.filter(pk=self.remote_host.pk).exists())
    
    def test_unauthenticated_access(self):
        """Test that unauthenticated users cannot access endpoints"""
        client = APIClient()  # No authentication
        url = reverse('remotehost-list')
        
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    @patch('cc.utils.sync_auth.SyncAuthenticator')
    def test_test_connection_success(self, mock_auth_class):
        """Test successful connection test"""
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.test_connection.return_value = {
            'success': True,
            'message': 'Connection successful',
            'response_time': 0.5,
            'host_name': 'test-remote.local',
            'url': 'http://test-remote.local:8000/api/'
        }
        mock_auth.__enter__ = Mock(return_value=mock_auth)
        mock_auth.__exit__ = Mock(return_value=None)
        mock_auth_class.return_value = mock_auth
        
        url = reverse('remotehost-test-connection', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['status'], 'connected')
        self.assertEqual(response.data['response_time'], 0.5)
    
    @patch('cc.utils.sync_auth.SyncAuthenticator')
    def test_test_connection_failure(self, mock_auth_class):
        """Test connection test failure"""
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.test_connection.return_value = {
            'success': False,
            'error': 'timeout',
            'message': 'Connection timed out',
            'host_name': 'test-remote.local'
        }
        mock_auth.__enter__ = Mock(return_value=mock_auth)
        mock_auth.__exit__ = Mock(return_value=None)
        mock_auth_class.return_value = mock_auth
        
        url = reverse('remotehost-test-connection', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_408_REQUEST_TIMEOUT)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['status'], 'timeout')
    
    @patch('cc.utils.sync_auth.test_remote_host_auth')
    def test_test_authentication_success(self, mock_test_auth):
        """Test successful authentication test"""
        mock_test_auth.return_value = {
            'success': True,
            'host_name': 'test-remote.local',
            'tests': {
                'connection': {'success': True},
                'authentication': {'success': True},
                'api_access': {'success': True}
            }
        }
        
        url = reverse('remotehost-test-authentication', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('results', response.data)
    
    @patch('cc.utils.sync_auth.test_remote_host_auth')
    def test_test_authentication_failure(self, mock_test_auth):
        """Test authentication test failure"""
        mock_test_auth.return_value = {
            'success': False,
            'host_name': 'test-remote.local',
            'tests': {
                'connection': {'success': True},
                'authentication': {'success': False, 'error': 'invalid_token'}
            }
        }
        
        url = reverse('remotehost-test-authentication', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
    
    @patch('cc.services.sync_service.SyncService')
    def test_sync_status(self, mock_sync_service_class):
        """Test sync status endpoint"""
        # Mock sync service
        mock_sync_service = Mock()
        mock_sync_service.get_sync_status.return_value = {
            'success': True,
            'status': {
                'remote_host': {
                    'id': self.remote_host.id,
                    'name': 'test-remote.local'
                },
                'synced_objects': {
                    'protocol': 5,
                    'project': 3
                },
                'total_synced': 8
            }
        }
        mock_sync_service.__enter__ = Mock(return_value=mock_sync_service)
        mock_sync_service.__exit__ = Mock(return_value=None)
        mock_sync_service_class.return_value = mock_sync_service
        
        url = reverse('remotehost-sync-status', kwargs={'pk': self.remote_host.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['sync_status']['total_synced'], 8)
    
    @patch('cc.services.sync_service.SyncService')
    def test_sync_pull_success(self, mock_sync_service_class):
        """Test successful sync pull"""
        # Mock sync service
        mock_sync_service = Mock()
        mock_sync_service.pull_all_data.return_value = {
            'success': True,
            'remote_host': 'test-remote.local',
            'models': {
                'protocol': {
                    'import_result': {
                        'imported_count': 2,
                        'updated_count': 1,
                        'skipped_count': 0
                    }
                }
            },
            'summary': {
                'total_pulled': 2,
                'total_updated': 1,
                'total_skipped': 0,
                'total_errors': 0
            }
        }
        mock_sync_service.__enter__ = Mock(return_value=mock_sync_service)
        mock_sync_service.__exit__ = Mock(return_value=None)
        mock_sync_service_class.return_value = mock_sync_service
        
        url = reverse('remotehost-sync-pull', kwargs={'pk': self.remote_host.pk})
        data = {
            'models': ['protocol'],
            'limit': 10
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('results', response.data)
        
        # Verify sync service was called with correct parameters
        mock_sync_service.pull_all_data.assert_called_once_with(
            models=['protocol'],
            limit_per_model=10
        )
    
    @patch('cc.services.sync_service.SyncService')
    def test_sync_pull_with_errors(self, mock_sync_service_class):
        """Test sync pull with errors"""
        # Mock sync service
        mock_sync_service = Mock()
        mock_sync_service.pull_all_data.return_value = {
            'success': False,
            'remote_host': 'test-remote.local',
            'models': {
                'protocol': {
                    'error': 'Connection failed'
                }
            },
            'summary': {
                'total_pulled': 0,
                'total_updated': 0,
                'total_skipped': 0,
                'total_errors': 1
            }
        }
        mock_sync_service.__enter__ = Mock(return_value=mock_sync_service)
        mock_sync_service.__exit__ = Mock(return_value=None)
        mock_sync_service_class.return_value = mock_sync_service
        
        url = reverse('remotehost-sync-pull', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_207_MULTI_STATUS)
        self.assertFalse(response.data['success'])
        self.assertIn('results', response.data)
    
    @patch('cc.services.sync_service.SyncService')
    def test_sync_pull_authentication_error(self, mock_sync_service_class):
        """Test sync pull with authentication error"""
        from cc.utils.sync_auth import SyncAuthError
        
        mock_sync_service = Mock()
        mock_sync_service.pull_all_data.side_effect = SyncAuthError('Invalid token')
        mock_sync_service.__enter__ = Mock(return_value=mock_sync_service)
        mock_sync_service.__exit__ = Mock(return_value=None)
        mock_sync_service_class.return_value = mock_sync_service
        
        url = reverse('remotehost-sync-pull', kwargs={'pk': self.remote_host.pk})
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'authentication_failed')
    
    def test_connection_summary(self):
        """Test connection summary endpoint"""
        # Create additional remote host
        RemoteHost.objects.create(
            host_name='another-remote.local',
            host_port=8001,
            host_protocol='https',
            host_description='Another test host'
        )
        
        url = reverse('remotehost-connection-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_hosts'], 2)
        self.assertEqual(len(response.data['hosts']), 2)
        
        # Check first host data
        host_data = response.data['hosts'][0]
        self.assertIn('id', host_data)
        self.assertIn('name', host_data)
        self.assertIn('url', host_data)
        self.assertIn('status', host_data)


class SyncIntegrationTestCase(TestCase):
    """Integration tests for sync functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test-remote.local',
            host_port=8000,
            host_protocol='http',
            host_description='Test remote host'
        )
        
        # Set up a test token
        self.remote_host.encrypt_token('test-token-12345')
        self.remote_host.save()
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_end_to_end_sync_flow(self, mock_auth_class):
        """Test complete sync flow from API call to data import"""
        # Mock authenticator and responses
        mock_session = Mock()
        mock_auth = Mock()
        mock_auth.session = mock_session
        mock_auth.authenticate.return_value = {'success': True, 'message': 'OK'}
        mock_auth_class.return_value = mock_auth
        
        # Mock protocol data response
        protocol_response = Mock()
        protocol_response.status_code = 200
        protocol_response.json.return_value = {
            'results': [
                {
                    'id': 1,
                    'protocol_title': 'Remote Protocol',
                    'protocol_description': 'A protocol from remote host',
                    'updated_at': '2024-01-15T10:00:00Z',
                    'enabled': True
                }
            ]
        }
        
        # Mock other model responses (empty)
        empty_response = Mock()
        empty_response.status_code = 200
        empty_response.json.return_value = {'results': []}
        
        # Configure mock session to return appropriate responses
        def mock_get(url, params=None):
            if 'protocol' in url and 'protocol_step' not in url and 'protocol_section' not in url:
                return protocol_response
            else:
                return empty_response
        
        mock_session.get.side_effect = mock_get
        
        # Perform sync via API
        url = reverse('remotehost-sync-pull', kwargs={'pk': self.remote_host.pk})
        data = {'models': ['protocol'], 'limit': 10}
        
        response = self.client.post(url, data, format='json')
        
        # Verify API response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        
        # Verify data was imported
        protocol = ProtocolModel.objects.get(remote_id=1, remote_host=self.remote_host)
        self.assertEqual(protocol.protocol_title, 'Remote Protocol')
        self.assertTrue(protocol.is_vaulted)
        self.assertEqual(protocol.user, self.user)
        
        # Verify sync results
        results = response.data['results']
        self.assertEqual(results['summary']['total_pulled'], 1)
        self.assertIn('protocol', results['models'])
    
    def test_sync_with_existing_vaulted_data(self):
        """Test that sync respects vaulting system"""
        # Create existing vaulted protocol
        ProtocolModel.objects.create(
            protocol_title='Existing Vaulted Protocol',
            protocol_description='Already in vault',
            user=self.user,
            remote_id=999,
            remote_host=self.remote_host,
            is_vaulted=True
        )
        
        # Test sync status endpoint
        with patch('cc.services.sync_service.SyncService') as mock_sync_service_class:
            mock_sync_service = Mock()
            mock_sync_service.get_sync_status.return_value = {
                'success': True,
                'status': {
                    'remote_host': {
                        'id': self.remote_host.id,
                        'name': 'test-remote.local'
                    },
                    'synced_objects': {
                        'protocol': 1,
                        'project': 0
                    },
                    'total_synced': 1
                }
            }
            mock_sync_service.__enter__ = Mock(return_value=mock_sync_service)
            mock_sync_service.__exit__ = Mock(return_value=None)
            mock_sync_service_class.return_value = mock_sync_service
            
            url = reverse('remotehost-sync-status', kwargs={'pk': self.remote_host.pk})
            response = self.client.get(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['sync_status']['synced_objects']['protocol'], 1)
            self.assertEqual(response.data['sync_status']['total_synced'], 1)