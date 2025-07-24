"""
Tests for the sync service functionality
"""

import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from requests.exceptions import RequestException, Timeout

from cc.models import RemoteHost, ProtocolModel, Project, StoredReagent
from cc.services.sync_service import SyncService, SyncError
from cc.utils.sync_auth import SyncAuthenticator, SyncAuthError


class SyncServiceTestCase(TestCase):
    """Test cases for SyncService"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.remote_host = RemoteHost.objects.create(
            host_name='test-remote.local',
            host_port=8000,
            host_protocol='http',
            host_description='Test remote host'
        )
        
        # Set up a test token
        self.remote_host.encrypt_token('test-token-12345')
        self.remote_host.save()
    
    def test_sync_service_initialization(self):
        """Test SyncService initialization"""
        with SyncService(self.remote_host, self.user) as sync_service:
            self.assertEqual(sync_service.remote_host, self.remote_host)
            self.assertEqual(sync_service.importing_user, self.user)
            self.assertIsNotNone(sync_service.authenticator)
            self.assertEqual(sync_service.sync_stats['pulled_objects'], 0)
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_authenticate_success(self, mock_auth_class):
        """Test successful authentication"""
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.authenticate.return_value = {
            'success': True,
            'message': 'Authentication successful'
        }
        mock_auth_class.return_value = mock_auth
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service.authenticate()
            
            self.assertTrue(result['success'])
            self.assertEqual(result['message'], 'Authentication successful')
            mock_auth.authenticate.assert_called_once()
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_authenticate_failure(self, mock_auth_class):
        """Test authentication failure"""
        # Mock authenticator
        mock_auth = Mock()
        mock_auth.authenticate.return_value = {
            'success': False,
            'message': 'Invalid token'
        }
        mock_auth_class.return_value = mock_auth
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            with self.assertRaises(SyncAuthError):
                sync_service.authenticate()
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_pull_model_data_success(self, mock_auth_class):
        """Test successful model data pulling"""
        # Mock authenticator and session
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'results': [
                {
                    'id': 1,
                    'protocol_title': 'Test Protocol',
                    'protocol_description': 'Test Description',
                    'updated_at': timezone.now().isoformat()
                },
                {
                    'id': 2,
                    'protocol_title': 'Another Protocol',
                    'protocol_description': 'Another Description',
                    'updated_at': timezone.now().isoformat()
                }
            ]
        }
        mock_session.get.return_value = mock_response
        
        mock_auth = Mock()
        mock_auth.session = mock_session
        mock_auth_class.return_value = mock_auth
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service.pull_model_data('protocol')
            
            self.assertTrue(result['success'])
            self.assertEqual(result['model_name'], 'protocol')
            self.assertEqual(result['count'], 2)
            self.assertEqual(len(result['objects']), 2)
            
            # Verify API call
            mock_session.get.assert_called_once_with(
                'http://test-remote.local:8000/api/protocol/',
                params={}
            )
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_pull_model_data_with_filters(self, mock_auth_class):
        """Test model data pulling with filters"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'results': []}
        mock_session.get.return_value = mock_response
        
        mock_auth = Mock()
        mock_auth.session = mock_session
        mock_auth_class.return_value = mock_auth
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            filters = {'enabled': True}
            limit = 10
            
            sync_service.pull_model_data('protocol', filters=filters, limit=limit)
            
            # Verify API call with parameters
            mock_session.get.assert_called_once_with(
                'http://test-remote.local:8000/api/protocol/',
                params={'enabled': True, 'limit': 10}
            )
    
    def test_pull_model_data_invalid_model(self):
        """Test pulling data for invalid model"""
        with SyncService(self.remote_host, self.user) as sync_service:
            with self.assertRaises(SyncError) as context:
                sync_service.pull_model_data('invalid_model')
            
            self.assertIn("Model 'invalid_model' is not syncable", str(context.exception))
    
    def test_import_objects_create_new(self):
        """Test importing new objects"""
        remote_objects = [
            {
                'id': 1,
                'protocol_title': 'Test Protocol',
                'protocol_description': 'Test Description',
                'updated_at': timezone.now().isoformat()
            }
        ]
        
        with SyncService(self.remote_host, self.user) as sync_service:
            result = sync_service.import_objects('protocol', remote_objects)
            
            self.assertTrue(result['success'])
            self.assertEqual(result['imported_count'], 1)
            self.assertEqual(result['updated_count'], 0)
            self.assertEqual(result['skipped_count'], 0)
            
            # Verify object was created
            protocol = ProtocolModel.objects.get(remote_id=1, remote_host=self.remote_host)
            self.assertEqual(protocol.protocol_title, 'Test Protocol')
            self.assertTrue(protocol.is_vaulted)
            self.assertEqual(protocol.user, self.user)
    
    def test_import_objects_update_existing(self):
        """Test updating existing objects"""
        # Create existing object
        existing_protocol = ProtocolModel.objects.create(
            protocol_title='Original Title',
            protocol_description='Original Description',
            user=self.user,
            remote_id=1,
            remote_host=self.remote_host,
            is_vaulted=True
        )
        
        # Mock newer timestamp
        newer_time = timezone.now()
        existing_protocol.updated_at = newer_time - timezone.timedelta(hours=1)
        existing_protocol.save()
        
        remote_objects = [
            {
                'id': 1,
                'protocol_title': 'Updated Title',
                'protocol_description': 'Updated Description',
                'updated_at': newer_time.isoformat()
            }
        ]
        
        with SyncService(self.remote_host, self.user) as sync_service:
            result = sync_service.import_objects('protocol', remote_objects)
            
            self.assertTrue(result['success'])
            self.assertEqual(result['imported_count'], 0)
            self.assertEqual(result['updated_count'], 1)
            self.assertEqual(result['skipped_count'], 0)
            
            # Verify object was updated
            existing_protocol.refresh_from_db()
            self.assertEqual(existing_protocol.protocol_title, 'Updated Title')
    
    def test_import_objects_skip_older(self):
        """Test skipping objects that are not newer"""
        # Create existing object with newer timestamp
        existing_protocol = ProtocolModel.objects.create(
            protocol_title='Current Title',
            protocol_description='Current Description',
            user=self.user,
            remote_id=1,
            remote_host=self.remote_host,
            is_vaulted=True
        )
        
        older_time = timezone.now() - timezone.timedelta(hours=1)
        
        remote_objects = [
            {
                'id': 1,
                'protocol_title': 'Older Title',
                'protocol_description': 'Older Description',
                'updated_at': older_time.isoformat()
            }
        ]
        
        with SyncService(self.remote_host, self.user) as sync_service:
            result = sync_service.import_objects('protocol', remote_objects)
            
            self.assertTrue(result['success'])
            self.assertEqual(result['imported_count'], 0)
            self.assertEqual(result['updated_count'], 0)
            self.assertEqual(result['skipped_count'], 1)
            
            # Verify object was not updated
            existing_protocol.refresh_from_db()
            self.assertEqual(existing_protocol.protocol_title, 'Current Title')
    
    def test_get_sync_status(self):
        """Test getting sync status"""
        # Create some synced objects
        ProtocolModel.objects.create(
            protocol_title='Synced Protocol',
            user=self.user,
            remote_id=1,
            remote_host=self.remote_host,
            is_vaulted=True
        )
        
        Project.objects.create(
            project_title='Synced Project',
            owner=self.user,
            remote_id=1,
            remote_host=self.remote_host,
            is_vaulted=True
        )
        
        with SyncService(self.remote_host, self.user) as sync_service:
            result = sync_service.get_sync_status()
            
            self.assertTrue(result['success'])
            status = result['status']
            
            self.assertEqual(status['remote_host']['id'], self.remote_host.id)
            self.assertEqual(status['remote_host']['name'], self.remote_host.host_name)
            self.assertEqual(status['synced_objects']['protocol'], 1)
            self.assertEqual(status['synced_objects']['project'], 1)
            self.assertEqual(status['total_synced'], 2)
    
    @patch('cc.services.sync_service.SyncAuthenticator')
    def test_pull_all_data_success(self, mock_auth_class):
        """Test pulling all data successfully"""
        # Mock authenticator
        mock_session = Mock()
        mock_auth = Mock()
        mock_auth.session = mock_session
        mock_auth.authenticate.return_value = {'success': True, 'message': 'OK'}
        mock_auth_class.return_value = mock_auth
        
        # Mock responses for different models
        def mock_get(url, params=None):
            mock_response = Mock()
            mock_response.status_code = 200
            
            if 'protocol' in url:
                mock_response.json.return_value = {
                    'results': [
                        {
                            'id': 1,
                            'protocol_title': 'Test Protocol',
                            'updated_at': timezone.now().isoformat()
                        }
                    ]
                }
            elif 'project' in url:
                mock_response.json.return_value = {
                    'results': [
                        {
                            'id': 1,
                            'project_title': 'Test Project',
                            'updated_at': timezone.now().isoformat()
                        }
                    ]
                }
            else:
                mock_response.json.return_value = {'results': []}
            
            return mock_response
        
        mock_session.get.side_effect = mock_get
        
        with SyncService(self.remote_host, self.user) as sync_service:
            sync_service.authenticator = mock_auth
            
            result = sync_service.pull_all_data(models=['protocol', 'project'])
            
            self.assertTrue(result['success'])
            self.assertIn('protocol', result['models'])
            self.assertIn('project', result['models'])
            self.assertEqual(result['summary']['total_pulled'], 2)
    
    def test_should_update_object_newer_remote(self):
        """Test should_update_object with newer remote timestamp"""
        local_obj = Mock()
        local_obj.updated_at = timezone.now() - timezone.timedelta(hours=1)
        
        remote_data = {
            'updated_at': timezone.now().isoformat()
        }
        
        with SyncService(self.remote_host, self.user) as sync_service:
            should_update = sync_service._should_update_object(local_obj, remote_data)
            
            self.assertTrue(should_update)
    
    def test_should_update_object_older_remote(self):
        """Test should_update_object with older remote timestamp"""
        local_obj = Mock()
        local_obj.updated_at = timezone.now()
        
        remote_data = {
            'updated_at': (timezone.now() - timezone.timedelta(hours=1)).isoformat()
        }
        
        with SyncService(self.remote_host, self.user) as sync_service:
            should_update = sync_service._should_update_object(local_obj, remote_data)
            
            self.assertFalse(should_update)
    
    def test_prepare_local_data(self):
        """Test preparing remote data for local model"""
        remote_data = {
            'id': 1,
            'protocol_title': 'Test Protocol',
            'protocol_description': 'Test Description',
            'user': 999,  # Should be excluded
            'remote_id': 123,  # Should be excluded
            'created_at': '2024-01-01T00:00:00Z',  # Should be excluded
            'some_field': 'some_value'
        }
        
        with SyncService(self.remote_host, self.user) as sync_service:
            local_data = sync_service._prepare_local_data(remote_data, 'protocol')
            
            self.assertNotIn('id', local_data)
            self.assertNotIn('user', local_data)
            self.assertNotIn('remote_id', local_data)
            self.assertNotIn('created_at', local_data)
            
            self.assertIn('protocol_title', local_data)
            self.assertIn('protocol_description', local_data)
            self.assertIn('some_field', local_data)
            
            self.assertEqual(local_data['protocol_title'], 'Test Protocol')


class SyncAuthenticatorTestCase(TestCase):
    """Test cases for SyncAuthenticator"""
    
    def setUp(self):
        """Set up test data"""
        self.remote_host = RemoteHost.objects.create(
            host_name='test-remote.local',
            host_port=8000,
            host_protocol='http',
            host_description='Test remote host'
        )
        
        # Set up a test token
        self.remote_host.encrypt_token('test-token-12345')
        self.remote_host.save()
    
    def test_authenticator_initialization(self):
        """Test SyncAuthenticator initialization"""
        with SyncAuthenticator(self.remote_host) as auth:
            self.assertEqual(auth.remote_host, self.remote_host)
            self.assertEqual(auth.base_url, 'http://test-remote.local:8000')
            self.assertIsNotNone(auth.session)
    
    @patch('requests.Session.get')
    def test_test_connection_success(self, mock_get):
        """Test successful connection test"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_get.return_value = mock_response
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.test_connection()
            
            self.assertTrue(result['success'])
            self.assertEqual(result['status_code'], 200)
            self.assertEqual(result['response_time'], 0.5)
            self.assertEqual(result['host_name'], 'test-remote.local')
    
    @patch('requests.Session.get')
    def test_test_connection_timeout(self, mock_get):
        """Test connection timeout"""
        mock_get.side_effect = Timeout('Connection timed out')
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.test_connection()
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error'], 'timeout')
            self.assertIn('timed out', result['message'])
    
    @patch('requests.Session.get')
    def test_authenticate_success(self, mock_get):
        """Test successful authentication"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'username': 'testuser'}
        mock_response.content = b'{"username": "testuser"}'
        mock_get.return_value = mock_response
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.authenticate()
            
            self.assertTrue(result['success'])
            self.assertEqual(result['message'], 'Authentication successful')
            self.assertIn('user_info', result)
    
    @patch('requests.Session.get')
    def test_authenticate_invalid_token(self, mock_get):
        """Test authentication with invalid token"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.authenticate()
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error'], 'invalid_credentials')
            self.assertEqual(result['status_code'], 401)
    
    def test_authenticate_no_token(self):
        """Test authentication with no token"""
        self.remote_host.host_token = None
        self.remote_host.save()
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.authenticate()
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error'], 'no_token')
    
    @patch('requests.Session.get')
    def test_test_api_access_success(self, mock_get):
        """Test successful API access"""
        # Mock authentication response
        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {'username': 'testuser'}
        auth_response.content = b'{"username": "testuser"}'
        
        # Mock API endpoint response
        api_response = Mock()
        api_response.status_code = 200
        api_response.json.return_value = {'results': [1, 2, 3]}
        api_response.elapsed.total_seconds.return_value = 0.3
        
        mock_get.side_effect = [auth_response, api_response]
        
        with SyncAuthenticator(self.remote_host) as auth:
            result = auth.test_api_access('protocol')
            
            self.assertTrue(result['success'])
            self.assertEqual(result['endpoint'], 'protocol')
            self.assertEqual(result['count'], 3)
            self.assertEqual(result['response_time'], 0.3)