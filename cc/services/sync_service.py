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
    
    # PHASE 3: BIDIRECTIONAL SYNC (PUSH FUNCTIONALITY)
    
    def push_model_data(self, model_name: str, local_objects: List[models.Model], 
                       conflict_strategy: str = 'timestamp') -> Dict[str, Any]:
        """
        Push local objects to remote host
        
        Args:
            model_name: Name of model to push ('protocol', 'project', etc.)
            local_objects: List of local model instances to push
            conflict_strategy: Strategy for handling conflicts ('timestamp', 'force_push', 'skip')
            
        Returns:
            dict: Results of push operation
        """
        if model_name not in self.SYNCABLE_MODELS:
            raise SyncError(f"Model '{model_name}' is not syncable")
            
        if not self.authenticator:
            raise SyncError("Must authenticate before pushing data")
        
        results = {
            'success': True,
            'model_name': model_name,
            'pushed_count': 0,
            'updated_count': 0,
            'skipped_count': 0,
            'conflicts': [],
            'errors': []
        }
        
        try:
            logger.info(f"Pushing {len(local_objects)} {model_name} objects to {self.remote_host.host_name}")
            
            for local_obj in local_objects:
                try:
                    push_result = self._push_single_object(local_obj, model_name, conflict_strategy)
                    
                    if push_result['action'] == 'created':
                        results['pushed_count'] += 1
                    elif push_result['action'] == 'updated':
                        results['updated_count'] += 1
                    elif push_result['action'] == 'skipped':
                        results['skipped_count'] += 1
                    elif push_result['action'] == 'conflict':
                        results['conflicts'].append(push_result)
                        results['skipped_count'] += 1
                        
                except Exception as e:
                    error_msg = f"Failed to push {model_name} object {local_obj.id}: {str(e)}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)
                    results['success'] = False
            
            logger.info(f"Push complete for {model_name}: {results['pushed_count']} created, "
                       f"{results['updated_count']} updated, {results['skipped_count']} skipped")
            
            return results
            
        except Exception as e:
            error_msg = f"Failed to push {model_name} data: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'model_name': model_name,
                'error': error_msg
            }
    
    def _push_single_object(self, local_obj: models.Model, model_name: str, 
                           conflict_strategy: str) -> Dict[str, Any]:
        """
        Push a single object to remote host
        
        Args:
            local_obj: Local model instance to push
            model_name: Name of model
            conflict_strategy: Strategy for handling conflicts
            
        Returns:
            dict: Result of push operation for this object
        """
        # Prepare data for remote API
        remote_data = self._prepare_remote_data(local_obj, model_name)
        
        # Check if object already exists on remote
        remote_obj = None
        if hasattr(local_obj, 'remote_id') and local_obj.remote_id:
            remote_obj = self._get_remote_object(model_name, local_obj.remote_id)
        
        # Handle conflict detection and resolution
        if remote_obj:
            conflict_result = self._handle_push_conflict(
                local_obj, remote_obj, model_name, conflict_strategy
            )
            if conflict_result['has_conflict']:
                return conflict_result
                
            # Update existing remote object
            return self._update_remote_object(local_obj, remote_obj, model_name, remote_data)
        else:
            # Create new remote object
            return self._create_remote_object(local_obj, model_name, remote_data)
    
    def _get_remote_object(self, model_name: str, remote_id: int) -> Optional[Dict]:
        """
        Get object from remote host by ID
        
        Args:
            model_name: Name of model
            remote_id: Remote object ID
            
        Returns:
            dict or None: Remote object data if found
        """
        try:
            endpoint = model_name if model_name != 'protocol' else 'protocol'
            response = self.authenticator.session.get(
                f"{self.authenticator.base_url}/api/{endpoint}/{remote_id}/"
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                raise SyncError(f"Failed to fetch remote object: HTTP {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Could not fetch remote object {remote_id}: {e}")
            return None
    
    def _handle_push_conflict(self, local_obj: models.Model, remote_obj: Dict, 
                             model_name: str, conflict_strategy: str) -> Dict[str, Any]:
        """
        Handle conflicts when pushing objects that exist on both sides
        
        Args:
            local_obj: Local model instance
            remote_obj: Remote object data
            model_name: Name of model
            conflict_strategy: Strategy for resolving conflicts
            
        Returns:
            dict: Conflict resolution result
        """
        conflict_info = {
            'has_conflict': False,
            'action': 'proceed',
            'local_id': local_obj.id,
            'remote_id': remote_obj['id'],
            'conflict_type': None,
            'resolution': conflict_strategy
        }
        
        # Check for timestamp conflicts
        if hasattr(local_obj, 'updated_at') and 'updated_at' in remote_obj:
            local_updated = local_obj.updated_at
            remote_updated_str = remote_obj['updated_at']
            
            try:
                remote_updated = datetime.fromisoformat(remote_updated_str.replace('Z', '+00:00'))
                if remote_updated.tzinfo is None:
                    remote_updated = remote_updated.replace(tzinfo=timezone.utc)
                if local_updated.tzinfo is None:
                    local_updated = local_updated.replace(tzinfo=timezone.utc)
                
                # Detect conflict: both objects modified since last sync
                if remote_updated > local_updated:
                    conflict_info.update({
                        'has_conflict': True,
                        'conflict_type': 'remote_newer',
                        'local_timestamp': local_updated.isoformat(),
                        'remote_timestamp': remote_updated.isoformat()
                    })
                    
                    # Apply conflict resolution strategy
                    if conflict_strategy == 'timestamp':
                        # Keep remote (newer) version - skip push
                        conflict_info.update({
                            'action': 'skipped',
                            'reason': 'Remote object is newer'
                        })
                    elif conflict_strategy == 'force_push':
                        # Force push local version despite conflict
                        conflict_info.update({
                            'action': 'force_update',
                            'reason': 'Force push strategy applied'
                        })
                    elif conflict_strategy == 'skip':
                        # Skip on any conflict
                        conflict_info.update({
                            'action': 'skipped',
                            'reason': 'Skip strategy applied'
                        })
                        
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to compare timestamps for conflict detection: {e}")
                # Proceed with caution on timestamp parse failure
                conflict_info['action'] = 'proceed'
        
        return conflict_info
    
    def _create_remote_object(self, local_obj: models.Model, model_name: str, 
                             remote_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new object on remote host
        
        Args:
            local_obj: Local model instance
            model_name: Name of model
            remote_data: Prepared data for remote API
            
        Returns:
            dict: Result of create operation
        """
        try:
            endpoint = model_name if model_name != 'protocol' else 'protocol'
            response = self.authenticator.session.post(
                f"{self.authenticator.base_url}/api/{endpoint}/",
                json=remote_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code in [200, 201]:
                remote_obj_data = response.json()
                
                # Update local object with remote ID
                if 'id' in remote_obj_data:
                    local_obj.remote_id = remote_obj_data['id']
                    local_obj.remote_host = self.remote_host
                    local_obj.save()
                
                return {
                    'action': 'created',
                    'local_id': local_obj.id,
                    'remote_id': remote_obj_data.get('id'),
                    'success': True
                }
            else:
                return {
                    'action': 'error',
                    'local_id': local_obj.id,
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'success': False
                }
                
        except Exception as e:
            return {
                'action': 'error',
                'local_id': local_obj.id,
                'error': str(e),
                'success': False
            }
    
    def _update_remote_object(self, local_obj: models.Model, remote_obj: Dict, 
                             model_name: str, remote_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing object on remote host
        
        Args:
            local_obj: Local model instance
            remote_obj: Remote object data
            model_name: Name of model
            remote_data: Prepared data for remote API
            
        Returns:
            dict: Result of update operation
        """
        try:
            endpoint = model_name if model_name != 'protocol' else 'protocol'
            remote_id = remote_obj['id']
            
            response = self.authenticator.session.put(
                f"{self.authenticator.base_url}/api/{endpoint}/{remote_id}/",
                json=remote_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code in [200, 201]:
                return {
                    'action': 'updated',
                    'local_id': local_obj.id,
                    'remote_id': remote_id,
                    'success': True
                }
            else:
                return {
                    'action': 'error',
                    'local_id': local_obj.id,
                    'remote_id': remote_id,
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'success': False
                }
                
        except Exception as e:
            return {
                'action': 'error',
                'local_id': local_obj.id,
                'remote_id': remote_obj.get('id'),
                'error': str(e),
                'success': False
            }
    
    def _prepare_remote_data(self, local_obj: models.Model, model_name: str) -> Dict[str, Any]:
        """
        Prepare local object data for remote API
        
        Args:
            local_obj: Local model instance
            model_name: Name of model
            
        Returns:
            dict: Data formatted for remote API
        """
        # Get all model fields except those that shouldn't be synced
        excluded_fields = {
            'id', 'remote_id', 'remote_host', 'is_vaulted',
            'created_at', 'updated_at'  # Let remote handle these
        }
        
        remote_data = {}
        
        # Get all field values from the model
        for field in local_obj._meta.fields:
            field_name = field.name
            if field_name not in excluded_fields:
                field_value = getattr(local_obj, field_name)
                
                # Handle foreign key relationships
                if hasattr(field, 'related_model') and field_value is not None:
                    # For now, just use the ID - TODO: handle relationship sync
                    if hasattr(field_value, 'id'):
                        remote_data[field_name] = field_value.id
                else:
                    # Handle datetime serialization
                    if hasattr(field_value, 'isoformat'):
                        remote_data[field_name] = field_value.isoformat()
                    else:
                        remote_data[field_name] = field_value
        
        # Add model-specific transformations
        remote_data = self._apply_model_transformations(remote_data, model_name, 'push')
        
        return remote_data
    
    def _apply_model_transformations(self, data: Dict[str, Any], model_name: str, 
                                   direction: str) -> Dict[str, Any]:
        """
        Apply model-specific data transformations for sync
        
        Args:
            data: Object data to transform
            model_name: Name of model
            direction: 'push' or 'pull'
            
        Returns:
            dict: Transformed data
        """
        # TODO: Add model-specific transformations as needed
        # Examples:
        # - Convert file paths for media fields
        # - Handle protocol-specific fields
        # - Transform user references
        
        return data
    
    def push_local_changes(self, models: Optional[List[str]] = None, 
                          modified_since: Optional[datetime] = None,
                          conflict_strategy: str = 'timestamp',
                          limit_per_model: Optional[int] = None) -> Dict[str, Any]:
        """
        Push local changes to remote host
        
        Args:
            models: List of model names to push (default: all syncable models)
            modified_since: Only push objects modified since this date
            conflict_strategy: Strategy for handling conflicts
            limit_per_model: Limit objects per model (for testing)
            
        Returns:
            dict: Overall push results
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
                'total_pushed': 0,
                'total_updated': 0,
                'total_skipped': 0,
                'total_conflicts': 0,
                'total_errors': 0
            }
        }
        
        try:
            for model_name in models:
                try:
                    logger.info(f"Pushing {model_name} to {self.remote_host.host_name}")
                    
                    # Get local objects to push
                    local_objects = self._get_local_objects_to_push(
                        model_name, modified_since, limit_per_model
                    )
                    
                    if local_objects:
                        # Push to remote
                        push_result = self.push_model_data(
                            model_name, local_objects, conflict_strategy
                        )
                        results['models'][model_name] = push_result
                        
                        # Update summary
                        results['summary']['total_pushed'] += push_result['pushed_count']
                        results['summary']['total_updated'] += push_result['updated_count']
                        results['summary']['total_skipped'] += push_result['skipped_count']
                        results['summary']['total_conflicts'] += len(push_result['conflicts'])
                        results['summary']['total_errors'] += len(push_result['errors'])
                        
                        if not push_result['success']:
                            results['success'] = False
                    else:
                        results['models'][model_name] = {
                            'message': 'No local objects to push'
                        }
                        
                except Exception as e:
                    error_msg = f"Failed to push {model_name}: {str(e)}"
                    logger.error(error_msg)
                    results['models'][model_name] = {'error': error_msg}
                    results['summary']['total_errors'] += 1
                    results['success'] = False
                    
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            
        logger.info(f"Push complete: {results['summary']}")
        
        return results
    
    def _get_local_objects_to_push(self, model_name: str, modified_since: Optional[datetime] = None,
                                  limit: Optional[int] = None) -> List[models.Model]:
        """
        Get local objects that should be pushed to remote
        
        Args:
            model_name: Name of model
            modified_since: Only include objects modified since this date
            limit: Maximum number of objects to return
            
        Returns:
            list: Local model instances to push
        """
        model_class = self.SYNCABLE_MODELS[model_name]
        
        # Build query for local objects
        queryset = model_class.objects.filter(
            # Only push objects owned by the current user or accessible to them
            **self._get_ownership_filter(model_class)
        ).exclude(
            # Don't push vaulted objects (they came from remote)
            is_vaulted=True
        )
        
        # Filter by modification date if specified
        if modified_since and hasattr(model_class, 'updated_at'):
            queryset = queryset.filter(updated_at__gte=modified_since)
            
        # Apply limit if specified
        if limit:
            queryset = queryset[:limit]
            
        return list(queryset)
    
    def _get_ownership_filter(self, model_class) -> Dict[str, Any]:
        """
        Get ownership filter for a model class
        
        Args:
            model_class: Model class to filter
            
        Returns:
            dict: Filter parameters for ownership
        """
        # Check common ownership patterns
        if hasattr(model_class, 'user'):
            return {'user': self.importing_user}
        elif hasattr(model_class, 'owner'):
            return {'owner': self.importing_user}
        else:
            # For models without clear ownership, return all (be careful!)
            return {}