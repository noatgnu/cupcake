"""
Core synchronization service for distributed CUPCAKE instances
Handles pulling and pushing data between remote hosts
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple
from django.db import transaction, models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone

from cc.models import (
    RemoteHost, ProtocolModel, ProtocolStep, ProtocolSection, 
    Project, Annotation, AnnotationFolder, StoredReagent, 
    StorageObject, Tag, Instrument, Session
)
from cc.utils.sync_auth import SyncAuthenticator, SyncAuthError

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Base exception for sync operations"""
    pass


class SyncConflict(SyncError):
    """Raised when sync conflicts are detected"""
    pass


class SyncService:
    """Main service for handling distributed synchronization"""
    
    # Models that support sync - must have remote_id and remote_host fields
    SYNCABLE_MODELS = {
        'protocol': ProtocolModel,
        'protocol_step': ProtocolStep,
        'protocol_section': ProtocolSection,
        'project': Project,
        'annotation': Annotation,
        'annotation_folder': AnnotationFolder,
        'stored_reagent': StoredReagent,
        'storage_object': StorageObject,
        'tag': Tag,
        'instrument': Instrument,
        'session': Session,
    }
    
    def __init__(self, remote_host: RemoteHost, importing_user: User):
        """
        Initialize sync service for specific remote host and user
        
        Args:
            remote_host: RemoteHost instance to sync with
            importing_user: User who will own imported objects
        """
        self.remote_host = remote_host
        self.importing_user = importing_user
        self.authenticator = None
        self.sync_stats = {
            'pulled_objects': 0,
            'updated_objects': 0,
            'skipped_objects': 0,
            'errors': []
        }
        
    def __enter__(self):
        """Context manager entry - initialize authenticator"""
        self.authenticator = SyncAuthenticator(self.remote_host)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup"""
        if self.authenticator:
            self.authenticator.close()
            
    def authenticate(self) -> Dict[str, Any]:
        """Authenticate with remote host"""
        if not self.authenticator:
            raise SyncError("SyncService must be used as context manager")
            
        auth_result = self.authenticator.authenticate()
        if not auth_result['success']:
            raise SyncAuthError(f"Authentication failed: {auth_result['message']}")
            
        return auth_result
    
    def pull_model_data(self, model_name: str, filters: Optional[Dict] = None, 
                       limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Pull data for a specific model from remote host
        
        Args:
            model_name: Name of model to sync ('protocol', 'project', etc.)
            filters: Optional filters to apply to remote query
            limit: Optional limit on number of objects to pull
            
        Returns:
            dict: Results of pull operation
        """
        if model_name not in self.SYNCABLE_MODELS:
            raise SyncError(f"Model '{model_name}' is not syncable")
            
        if not self.authenticator:
            raise SyncError("Must authenticate before pulling data")
            
        try:
            logger.info(f"Pulling {model_name} data from {self.remote_host.host_name}")
            
            # Build query parameters
            params = {}
            if filters:
                params.update(filters)
            if limit:
                params['limit'] = limit
                
            # Add timestamp filter to only get newer objects
            # TODO: Implement last_sync tracking in Phase 3
            
            # Make request to remote API
            endpoint = model_name if model_name != 'protocol' else 'protocol'
            response = self.authenticator.session.get(
                f"{self.authenticator.base_url}/api/{endpoint}/",
                params=params
            )
            
            if response.status_code != 200:
                raise SyncError(f"Failed to fetch {model_name} data: HTTP {response.status_code}")
                
            data = response.json()
            remote_objects = data.get('results', data if isinstance(data, list) else [])
            
            logger.info(f"Retrieved {len(remote_objects)} {model_name} objects from remote")
            
            return {
                'success': True,
                'model_name': model_name,
                'count': len(remote_objects),
                'objects': remote_objects
            }
            
        except Exception as e:
            error_msg = f"Failed to pull {model_name} data: {str(e)}"
            logger.error(error_msg)
            self.sync_stats['errors'].append(error_msg)
            raise SyncError(error_msg)
    
    def import_objects(self, model_name: str, remote_objects: List[Dict]) -> Dict[str, Any]:
        """
        Import objects from remote host into local database
        
        Args:
            model_name: Name of model being imported
            remote_objects: List of object data from remote host
            
        Returns:
            dict: Import results
        """
        if model_name not in self.SYNCABLE_MODELS:
            raise SyncError(f"Model '{model_name}' is not syncable")
            
        model_class = self.SYNCABLE_MODELS[model_name]
        imported_count = 0
        updated_count = 0
        skipped_count = 0
        
        try:
            with transaction.atomic():
                for obj_data in remote_objects:
                    try:
                        remote_id = obj_data.get('id')
                        if not remote_id:
                            logger.warning(f"Skipping {model_name} object without ID")
                            skipped_count += 1
                            continue
                        
                        # Check if we already have this object
                        existing_obj = model_class.objects.filter(
                            remote_id=remote_id,
                            remote_host=self.remote_host
                        ).first()
                        
                        if existing_obj:
                            # Update existing object if remote is newer
                            if self._should_update_object(existing_obj, obj_data):
                                self._update_local_object(existing_obj, obj_data, model_name)
                                updated_count += 1
                                logger.debug(f"Updated {model_name} {remote_id}")
                            else:
                                skipped_count += 1
                                logger.debug(f"Skipped {model_name} {remote_id} (not newer)")
                        else:
                            # Create new object
                            new_obj = self._create_local_object(obj_data, model_name, model_class)
                            imported_count += 1
                            logger.debug(f"Imported {model_name} {remote_id}")
                            
                    except Exception as e:
                        error_msg = f"Failed to import {model_name} object {obj_data.get('id', 'unknown')}: {str(e)}"
                        logger.error(error_msg)
                        self.sync_stats['errors'].append(error_msg)
                        skipped_count += 1
                        continue
                
                logger.info(f"Import complete for {model_name}: {imported_count} new, {updated_count} updated, {skipped_count} skipped")
                
                # Update sync stats
                self.sync_stats['pulled_objects'] += imported_count
                self.sync_stats['updated_objects'] += updated_count
                self.sync_stats['skipped_objects'] += skipped_count
                
                return {
                    'success': True,
                    'model_name': model_name,
                    'imported_count': imported_count,
                    'updated_count': updated_count,
                    'skipped_count': skipped_count,
                    'total_processed': len(remote_objects)
                }
                
        except Exception as e:
            error_msg = f"Transaction failed during {model_name} import: {str(e)}"
            logger.error(error_msg)
            self.sync_stats['errors'].append(error_msg)
            raise SyncError(error_msg)
    
    def _should_update_object(self, local_obj: models.Model, remote_data: Dict) -> bool:
        """
        Determine if local object should be updated with remote data
        
        Args:
            local_obj: Local model instance
            remote_data: Remote object data
            
        Returns:
            bool: True if local object should be updated
        """
        # TODO: Implement proper conflict detection in Phase 3
        # For now, always update if remote has a newer updated_at timestamp
        
        if not hasattr(local_obj, 'updated_at'):
            return True  # Update if we can't compare timestamps
            
        remote_updated_str = remote_data.get('updated_at')
        if not remote_updated_str:
            return False  # Don't update if remote doesn't have timestamp
            
        try:
            # Parse remote timestamp
            remote_updated = datetime.fromisoformat(remote_updated_str.replace('Z', '+00:00'))
            if remote_updated.tzinfo is None:
                remote_updated = remote_updated.replace(tzinfo=timezone.utc)
                
            local_updated = local_obj.updated_at
            if local_updated.tzinfo is None:
                local_updated = local_updated.replace(tzinfo=timezone.utc)
                
            return remote_updated > local_updated
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to compare timestamps: {e}")
            return True  # Update on timestamp parse failure
    
    def _create_local_object(self, remote_data: Dict, model_name: str, model_class) -> models.Model:
        """
        Create new local object from remote data
        
        Args:
            remote_data: Remote object data
            model_name: Name of model
            model_class: Model class
            
        Returns:
            Created model instance
        """
        # Prepare data for local creation
        local_data = self._prepare_local_data(remote_data, model_name)
        
        # Create the object
        obj = model_class.objects.create(**local_data)
        
        # Set sync-specific fields
        obj.remote_id = remote_data['id']
        obj.remote_host = self.remote_host
        obj.is_vaulted = True  # Mark synced objects as vaulted
        
        # Set ownership for user-owned models
        if hasattr(obj, 'user') and hasattr(obj, 'user_id'):
            obj.user = self.importing_user
        elif hasattr(obj, 'owner') and hasattr(obj, 'owner_id'):
            obj.owner = self.importing_user
            
        obj.save()
        
        return obj
    
    def _update_local_object(self, local_obj: models.Model, remote_data: Dict, model_name: str):
        """
        Update existing local object with remote data
        
        Args:
            local_obj: Local model instance to update
            remote_data: Remote object data
            model_name: Name of model
        """
        # Prepare data for local update
        local_data = self._prepare_local_data(remote_data, model_name)
        
        # Update fields
        for field, value in local_data.items():
            if hasattr(local_obj, field):
                setattr(local_obj, field, value)
        
        # Update remote tracking
        local_obj.remote_id = remote_data['id']
        local_obj.remote_host = self.remote_host
        
        local_obj.save()
    
    def _prepare_local_data(self, remote_data: Dict, model_name: str) -> Dict[str, Any]:
        """
        Prepare remote data for local model creation/update
        
        Args:
            remote_data: Raw remote object data
            model_name: Name of model
            
        Returns:
            dict: Cleaned data ready for local model
        """
        # Remove fields that shouldn't be copied
        excluded_fields = {
            'id', 'remote_id', 'remote_host', 'user', 'owner', 
            'created_at', 'updated_at'  # Let Django handle these
        }
        
        local_data = {}
        for key, value in remote_data.items():
            if key not in excluded_fields and value is not None:
                # TODO: Add model-specific field transformations here
                local_data[key] = value
        
        return local_data
    
    def pull_all_data(self, models: Optional[List[str]] = None, 
                     limit_per_model: Optional[int] = None) -> Dict[str, Any]:
        """
        Pull data for multiple models from remote host
        
        Args:
            models: List of model names to sync (default: all syncable models)
            limit_per_model: Limit objects per model (for testing)
            
        Returns:
            dict: Overall sync results
        """
        if not models:
            models = list(self.SYNCABLE_MODELS.keys())
            
        # Authenticate first
        self.authenticate()
        
        results = {
            'success': True,
            'remote_host': self.remote_host.host_name,
            'models': {},
            'summary': {
                'total_pulled': 0,
                'total_updated': 0,
                'total_skipped': 0,
                'total_errors': 0
            }
        }
        
        try:
            for model_name in models:
                try:
                    logger.info(f"Syncing {model_name} from {self.remote_host.host_name}")
                    
                    # Pull data from remote
                    pull_result = self.pull_model_data(model_name, limit=limit_per_model)
                    
                    if pull_result['count'] > 0:
                        # Import into local database
                        import_result = self.import_objects(model_name, pull_result['objects'])
                        results['models'][model_name] = {
                            'pull_result': pull_result,
                            'import_result': import_result
                        }
                        
                        # Update summary
                        results['summary']['total_pulled'] += import_result['imported_count']
                        results['summary']['total_updated'] += import_result['updated_count']
                        results['summary']['total_skipped'] += import_result['skipped_count']
                    else:
                        results['models'][model_name] = {
                            'pull_result': pull_result,
                            'import_result': {'message': 'No objects to import'}
                        }
                        
                except Exception as e:
                    error_msg = f"Failed to sync {model_name}: {str(e)}"
                    logger.error(error_msg)
                    results['models'][model_name] = {'error': error_msg}
                    results['summary']['total_errors'] += 1
                    results['success'] = False
                    
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            
        # Add sync stats
        results['sync_stats'] = self.sync_stats
        results['summary']['total_errors'] += len(self.sync_stats['errors'])
        
        logger.info(f"Sync complete: {results['summary']}")
        
        return results
    
    def get_sync_status(self) -> Dict[str, Any]:
        """
        Get current sync status for this remote host
        
        Returns:
            dict: Sync status information
        """
        try:
            # Count objects by model that were synced from this host
            status = {
                'remote_host': {
                    'id': self.remote_host.id,
                    'name': self.remote_host.host_name,
                    'url': f"{self.remote_host.host_protocol}://{self.remote_host.host_name}:{self.remote_host.host_port}"
                },
                'last_sync': None,  # TODO: Implement sync tracking
                'synced_objects': {},
                'total_synced': 0
            }
            
            total_count = 0
            for model_name, model_class in self.SYNCABLE_MODELS.items():
                count = model_class.objects.filter(
                    remote_host=self.remote_host,
                    is_vaulted=True
                ).count()
                
                status['synced_objects'][model_name] = count
                total_count += count
            
            status['total_synced'] = total_count
            
            return {
                'success': True,
                'status': status
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }