"""
Authentication utilities for distributed sync system
Handles secure communication between CUPCAKE instances
"""

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from django.conf import settings
from django.core import signing
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class SyncAuthError(Exception):
    """Base exception for sync authentication errors"""
    pass


class RemoteHostNotReachable(SyncAuthError):
    """Raised when remote host cannot be reached"""
    pass


class AuthenticationFailed(SyncAuthError):
    """Raised when authentication fails"""
    pass


class SyncAuthenticator:
    """Handle authentication with remote CUPCAKE instances"""
    
    def __init__(self, remote_host):
        """
        Initialize authenticator for a specific remote host
        
        Args:
            remote_host: RemoteHost model instance
        """
        self.remote_host = remote_host
        self.base_url = f"{remote_host.host_protocol}://{remote_host.host_name}:{remote_host.host_port}"
        self.session = requests.Session()
        
        # Set default timeout and SSL verification
        self.session.timeout = 30
        self.session.verify = False  # TODO: Implement proper SSL verification in production
        
        # Set user agent to identify as CUPCAKE sync client
        self.session.headers.update({
            'User-Agent': 'CUPCAKE-Sync-Client/1.0',
            'Content-Type': 'application/json'
        })
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test basic connectivity to remote host
        
        Returns:
            dict: Connection test results
        """
        try:
            logger.info(f"Testing connection to {self.remote_host.host_name}")
            
            # Try to reach the API root endpoint
            response = self.session.get(
                f"{self.base_url}/api/",
                timeout=10
            )
            
            result = {
                'success': True,
                'status_code': response.status_code,
                'response_time': response.elapsed.total_seconds(),
                'host_name': self.remote_host.host_name,
                'url': f"{self.base_url}/api/"
            }
            
            if response.status_code == 200:
                result['message'] = 'Connection successful'
                logger.info(f"Successfully connected to {self.remote_host.host_name}")
            else:
                result['success'] = False
                result['message'] = f'HTTP {response.status_code}'
                result['details'] = response.text[:200]
                logger.warning(f"Connection to {self.remote_host.host_name} returned HTTP {response.status_code}")
            
            return result
            
        except Timeout:
            error_msg = f"Connection to {self.remote_host.host_name} timed out"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'timeout',
                'message': error_msg,
                'host_name': self.remote_host.host_name
            }
            
        except ConnectionError as e:
            error_msg = f"Failed to connect to {self.remote_host.host_name}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'connection_error',
                'message': error_msg,
                'host_name': self.remote_host.host_name,
                'details': str(e)
            }
            
        except RequestException as e:
            error_msg = f"Request failed to {self.remote_host.host_name}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'request_error',
                'message': error_msg,
                'host_name': self.remote_host.host_name,
                'details': str(e)
            }
    
    def authenticate(self) -> Dict[str, Any]:
        """
        Attempt to authenticate with remote host using stored token
        
        Returns:
            dict: Authentication results
        """
        try:
            if not self.remote_host.host_token:
                return {
                    'success': False,
                    'error': 'no_token',
                    'message': 'No authentication token configured for this host'
                }
            
            # Decrypt the stored token
            try:
                token = self.remote_host.decrypt_token()
                if not token:
                    return {
                        'success': False,
                        'error': 'invalid_token',
                        'message': 'Failed to decrypt authentication token'
                    }
            except signing.BadSignature:
                return {
                    'success': False,
                    'error': 'corrupted_token',
                    'message': 'Authentication token is corrupted'
                }
            
            logger.info(f"Attempting authentication with {self.remote_host.host_name}")
            
            # Test authentication by making an authenticated request
            self.session.headers.update({
                'Authorization': f'Token {token}'
            })
            
            # Try to access a protected endpoint
            response = self.session.get(f"{self.base_url}/api/user/")
            
            if response.status_code == 200:
                logger.info(f"Successfully authenticated with {self.remote_host.host_name}")
                return {
                    'success': True,
                    'message': 'Authentication successful',
                    'host_name': self.remote_host.host_name,
                    'user_info': response.json() if response.content else None
                }
            elif response.status_code == 401:
                logger.warning(f"Authentication failed for {self.remote_host.host_name}: Invalid token")
                return {
                    'success': False,
                    'error': 'invalid_credentials',
                    'message': 'Authentication token is invalid or expired',
                    'status_code': 401
                }
            else:
                logger.warning(f"Authentication request failed for {self.remote_host.host_name}: HTTP {response.status_code}")
                return {
                    'success': False,
                    'error': 'auth_request_failed',
                    'message': f'Authentication request failed with HTTP {response.status_code}',
                    'status_code': response.status_code,
                    'details': response.text[:200]
                }
                
        except Exception as e:
            error_msg = f"Authentication error with {self.remote_host.host_name}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'authentication_error',
                'message': error_msg,
                'details': str(e)
            }
    
    def test_api_access(self, endpoint: str = 'protocol') -> Dict[str, Any]:
        """
        Test access to a specific API endpoint
        
        Args:
            endpoint: API endpoint to test (default: 'protocol')
            
        Returns:
            dict: API access test results
        """
        try:
            # First authenticate
            auth_result = self.authenticate()
            if not auth_result['success']:
                return {
                    'success': False,
                    'error': 'authentication_required',
                    'message': 'Cannot test API access without authentication',
                    'auth_error': auth_result
                }
            
            logger.info(f"Testing API access to {endpoint} on {self.remote_host.host_name}")
            
            # Test the specified endpoint
            response = self.session.get(f"{self.base_url}/api/{endpoint}/")
            
            if response.status_code == 200:
                data = response.json() if response.content else {}
                logger.info(f"Successfully accessed {endpoint} API on {self.remote_host.host_name}")
                return {
                    'success': True,
                    'message': f'Successfully accessed {endpoint} API',
                    'endpoint': endpoint,
                    'count': len(data.get('results', [])) if isinstance(data, dict) else 0,
                    'response_time': response.elapsed.total_seconds()
                }
            else:
                logger.warning(f"API access failed for {endpoint} on {self.remote_host.host_name}: HTTP {response.status_code}")
                return {
                    'success': False,
                    'error': 'api_access_failed',
                    'message': f'Failed to access {endpoint} API',
                    'endpoint': endpoint,
                    'status_code': response.status_code,
                    'details': response.text[:200]
                }
                
        except Exception as e:
            error_msg = f"API access test failed for {endpoint}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'api_test_error',
                'message': error_msg,
                'endpoint': endpoint,
                'details': str(e)
            }
    
    def get_remote_info(self) -> Dict[str, Any]:
        """
        Get basic information about the remote CUPCAKE instance
        
        Returns:
            dict: Remote instance information
        """
        try:
            # First authenticate
            auth_result = self.authenticate()
            if not auth_result['success']:
                return {
                    'success': False,
                    'error': 'authentication_required',
                    'message': 'Cannot get remote info without authentication',
                    'auth_error': auth_result
                }
            
            logger.info(f"Getting remote info from {self.remote_host.host_name}")
            
            # Try to get user info and basic stats
            info = {
                'host_name': self.remote_host.host_name,
                'host_url': self.base_url,
                'connection_time': None,
                'user_count': 0,
                'protocol_count': 0,
                'project_count': 0
            }
            
            # Get user count
            try:
                response = self.session.get(f"{self.base_url}/api/user/")
                if response.status_code == 200:
                    data = response.json()
                    info['user_count'] = data.get('count', len(data.get('results', [])))
            except:
                pass  # Not critical if this fails
            
            # Get protocol count
            try:
                response = self.session.get(f"{self.base_url}/api/protocol/")
                if response.status_code == 200:
                    data = response.json()
                    info['protocol_count'] = data.get('count', len(data.get('results', [])))
            except:
                pass  # Not critical if this fails
            
            # Get project count
            try:
                response = self.session.get(f"{self.base_url}/api/project/")
                if response.status_code == 200:
                    data = response.json()
                    info['project_count'] = data.get('count', len(data.get('results', [])))
            except:
                pass  # Not critical if this fails
            
            logger.info(f"Successfully retrieved remote info from {self.remote_host.host_name}")
            return {
                'success': True,
                'message': 'Remote info retrieved successfully',
                'info': info
            }
            
        except Exception as e:
            error_msg = f"Failed to get remote info: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': 'remote_info_error',
                'message': error_msg,
                'details': str(e)
            }
    
    def close(self):
        """Close the session"""
        if self.session:
            self.session.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


def test_remote_host_auth(remote_host) -> Dict[str, Any]:
    """
    Convenience function to test authentication with a remote host
    
    Args:
        remote_host: RemoteHost model instance
        
    Returns:
        dict: Comprehensive test results
    """
    with SyncAuthenticator(remote_host) as auth:
        results = {
            'host_name': remote_host.host_name,
            'host_url': f"{remote_host.host_protocol}://{remote_host.host_name}:{remote_host.host_port}",
            'tests': {}
        }
        
        # Test connection
        results['tests']['connection'] = auth.test_connection()
        
        # Test authentication (only if connection succeeded)
        if results['tests']['connection']['success']:
            results['tests']['authentication'] = auth.authenticate()
            
            # Test API access (only if authentication succeeded)
            if results['tests']['authentication']['success']:
                results['tests']['api_access'] = auth.test_api_access()
                results['tests']['remote_info'] = auth.get_remote_info()
        
        # Overall success
        results['success'] = all(
            test.get('success', False) 
            for test in results['tests'].values()
        )
        
        return results