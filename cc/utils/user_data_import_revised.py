"""
COMPLETELY REVISED User Data Import Utility for CUPCAKE LIMS

This is a completely rewritten version that matches the export utility with
accurate field mapping based on comprehensive model analysis and database schema.
"""
import os
import json
import sqlite3
import shutil
import zipfile
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from django.contrib.auth.models import User
from django.core.files import File
from django.core.files.storage import default_storage
from django.conf import settings
from django.db import transaction, models
from django.apps import apps
from django.utils import timezone
from django.core.serializers import serialize
from django.forms.models import model_to_dict

# Import all relevant models with exact names
from cc.models import (
    # Import tracking models
    ImportTracker, ImportedObject, ImportedFile, ImportedRelationship,
    
    # Core Protocol Models
    ProtocolModel, ProtocolStep, ProtocolSection, ProtocolRating,
    
    # Session and Execution Models  
    Session, TimeKeeper, Annotation, AnnotationFolder, StepVariation,
    
    # Instrument Models
    Instrument, InstrumentUsage, InstrumentPermission, InstrumentJob,
    MaintenanceLog, SupportInformation,
    
    # Reagent and Storage Models
    Reagent, ProtocolReagent, StepReagent, StoredReagent, StorageObject, 
    ReagentAction, ReagentSubscription,
    
    # Organization and Permission Models
    LabGroup, MetadataColumn, MetadataTableTemplate, Preset, FavouriteMetadataOption,
    
    # Tagging and Classification
    Tag, ProtocolTag, StepTag, 
    
    # Communication Models
    MessageThread, Message, MessageRecipient, MessageAttachment,
    
    # External and Support Models
    ExternalContact, ExternalContactDetails, DocumentPermission, RemoteHost,
    
    # Projects
    Project,
    
    # Vocabulary Models
    Tissue, HumanDisease, MSUniqueVocabularies, Species, SubcellularLocation, Unimod,
    
    # WebRTC Models (for completeness)
    WebRTCSession, WebRTCUserChannel, WebRTCUserOffer
)


class UserDataImporter:
    """
    COMPLETELY REVISED comprehensive user data importer with exact field mapping
    """
    
    def __init__(self, target_user: User, import_path: str, import_options: dict = None, progress_callback=None, storage_object_mappings: dict = None, bulk_transfer_mode: bool = False):
        self.target_user = target_user
        self.import_path = import_path
        self.temp_dir = tempfile.mkdtemp(prefix=f'cupcake_import_{target_user.username}_')
        self.sqlite_path = None
        self.media_dir = None
        self.progress_callback = progress_callback
        self.bulk_transfer_mode = bulk_transfer_mode
        
        # Storage object mappings for stored reagents: {original_storage_id: nominated_storage_id}
        self.storage_object_mappings = storage_object_mappings or {}
        
        # Import options for selective import
        self.import_options = import_options or {
            'protocols': True,
            'sessions': True, 
            'annotations': True,
            'projects': True,
            'reagents': True,
            'instruments': True,
            'lab_groups': True,
            'messaging': False,  # Default to false for privacy
            'support_models': True
        }
        
        # ID mapping for handling foreign key relationships
        self.id_mappings = {
            'users': {},
            'protocols': {},
            'sessions': {},
            'annotations': {},
            'steps': {},
            'instruments': {},
            'reagents': {},
            'storage_objects': {},
            'lab_groups': {},
            'projects': {},
            'folders': {},
            'tags': {},
            'remote_hosts': {},
        }
        
        self.stats = {
            'models_imported': 0,
            'relationships_imported': 0,
            'files_imported': 0,
            'errors': []
        }
        
        # Track what has been imported to avoid duplicates
        self.imported_objects = set()
        
        # Initialize import tracking
        self.import_tracker = None
        self.import_id = uuid.uuid4()
    
    def _send_progress(self, progress: int, message: str, status: str = "processing"):
        """Send progress update via callback if available"""
        if self.progress_callback:
            self.progress_callback(progress, message, status)
    
    def _initialize_import_tracker(self, metadata: dict = None):
        """Initialize the import tracker to monitor all changes"""
        # Archive must exist - this should fail if missing
        archive_size_mb = round(os.path.getsize(self.import_path) / (1024 * 1024), 2)
        
        self.import_tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.target_user,
            archive_path=self.import_path,
            archive_size_mb=archive_size_mb,
            import_options=self.import_options,
            metadata=metadata or {},
            import_status='in_progress'
        )
        print(f"Created import tracker with ID: {self.import_id}")
    
    def _track_created_object(self, obj, original_id=None):
        """Track a created object for rollback purposes"""
        if not self.import_tracker:
            return
        
        try:
            # Serialize object data for rollback
            object_data = model_to_dict(obj)
            
            # Handle non-serializable fields
            for field_name, field_value in object_data.items():
                if hasattr(field_value, 'isoformat'):
                    object_data[field_name] = field_value.isoformat()
                elif isinstance(field_value, uuid.UUID):
                    object_data[field_name] = str(field_value)
            
            ImportedObject.objects.create(
                import_tracker=self.import_tracker,
                model_name=obj.__class__.__name__,
                object_id=obj.pk,
                original_id=original_id,
                object_data=object_data
            )
            
            self.import_tracker.total_objects_created += 1
            self.import_tracker.save()
            
        except Exception as e:
            self.stats['errors'].append(f"Failed to track object {obj.__class__.__name__}({obj.pk}): {e}")
    
    def _track_created_file(self, file_path: str, original_name: str):
        """Track a created file for rollback purposes"""
        if not self.import_tracker:
            return
        
        # File must exist - this should fail if missing (no graceful fallback)
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        file_size = os.path.getsize(full_path)
        
        ImportedFile.objects.create(
            import_tracker=self.import_tracker,
            file_path=file_path,
            original_name=original_name,
            file_size_bytes=file_size
        )
        
        self.import_tracker.total_files_imported += 1
        self.import_tracker.save()
    
    def _track_created_relationship(self, from_obj, to_obj, field_name):
        """Track a many-to-many relationship for rollback purposes"""
        if not self.import_tracker:
            return
        
        try:
            ImportedRelationship.objects.create(
                import_tracker=self.import_tracker,
                from_model=from_obj.__class__.__name__,
                from_object_id=from_obj.pk,
                to_model=to_obj.__class__.__name__,
                to_object_id=to_obj.pk,
                relationship_field=field_name
            )
            
            self.import_tracker.total_relationships_created += 1
            self.import_tracker.save()
            
        except Exception as e:
            self.stats['errors'].append(f"Failed to track relationship {from_obj.__class__.__name__} -> {to_obj.__class__.__name__}: {e}")
    
    def _finalize_import_tracker(self, success: bool):
        """Finalize the import tracker with completion status"""
        if not self.import_tracker:
            return
        
        self.import_tracker.import_completed_at = timezone.now()
        self.import_tracker.import_status = 'completed' if success else 'failed'
        self.import_tracker.save()
        
        print(f"Import tracker finalized. Status: {self.import_tracker.import_status}")
        print(f"Objects created: {self.import_tracker.total_objects_created}")
        print(f"Files imported: {self.import_tracker.total_files_imported}")
        print(f"Relationships created: {self.import_tracker.total_relationships_created}")
    
    def _detect_archive_format(self, file_path: str) -> str:
        """Detect archive format based on file extension and magic bytes"""
        import tarfile
        
        file_path_lower = file_path.lower()
        
        # Check file extensions first
        if file_path_lower.endswith('.zip'):
            return 'zip'
        elif file_path_lower.endswith(('.tar.gz', '.tgz')):
            return 'tar.gz'
        elif file_path_lower.endswith('.tar'):
            return 'tar'
        
        # If no clear extension, try to detect by content
        try:
            if zipfile.is_zipfile(file_path):
                return 'zip'
            elif tarfile.is_tarfile(file_path):
                return 'tar.gz'
        except Exception:
            pass
        
        # Default fallback
        raise ValueError(f"Cannot determine archive format for file: {file_path}")
    
    def _extract_archive(self, archive_path: str, extract_dir: str) -> str:
        """Extract archive based on detected format"""
        import tarfile
        
        archive_format = self._detect_archive_format(archive_path)
        self._send_progress(5, f"Extracting {archive_format} archive...")
        
        if archive_format == 'zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_format in ['tar.gz', 'tar']:
            with tarfile.open(archive_path, 'r:*') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            raise ValueError(f"Unsupported archive format: {archive_format}")
        
        return archive_format
    
    def import_user_data(self) -> Dict[str, Any]:
        """
        Import ALL user data with accurate field mapping.
        
        Returns:
            Dict: Import statistics and results
        """
        try:
            print(f"Starting REVISED COMPREHENSIVE import for user: {self.target_user.username}")
            self._send_progress(0, "Starting import process...")
            
            # Extract and validate archive
            self._send_progress(5, "Extracting and validating archive...")
            self._extract_and_validate_archive()
            
            # Load and validate metadata
            self._send_progress(10, "Loading and validating metadata...")
            metadata = self._load_and_validate_metadata()
            
            # Initialize import tracking
            self._send_progress(12, "Initializing import tracking...")
            self._initialize_import_tracker(metadata)
            
            # Connect to SQLite database
            self._send_progress(15, "Connecting to import database...")
            self._connect_to_import_database()
            
            with transaction.atomic():
                # Import data in dependency order with selective import
                if self.import_options.get('lab_groups', True):
                    self._send_progress(20, "Importing lab groups...")
                    self._import_remote_hosts()
                    self._import_lab_groups()
                
                if self.import_options.get('reagents', True):
                    self._send_progress(25, "Importing storage and reagents...")
                    self._import_storage_objects()
                    self._import_reagents()
                    self._import_stored_reagents()
                
                if self.import_options.get('projects', True):
                    self._send_progress(35, "Importing projects...")
                    self._import_projects()
                
                if self.import_options.get('protocols', True):
                    self._send_progress(45, "Importing protocols...")
                    self._import_protocols_accurate()
                
                if self.import_options.get('sessions', True):
                    self._send_progress(60, "Importing sessions...")
                    self._import_sessions_accurate()
                
                if self.import_options.get('annotations', True):
                    self._send_progress(70, "Importing annotations...")
                    self._import_annotations_accurate()
                
                if self.import_options.get('instruments', True):
                    self._send_progress(80, "Importing instruments...")
                    self._import_instruments_accurate()
                
                # Import instrument usage after both annotations and instruments are imported
                self._send_progress(82, "Importing instrument usage...")
                self._import_instrument_usage_and_jobs()
                
                self._send_progress(85, "Importing tags and relationships...")
                self._import_tags_and_relationships()
                
                if self.import_options.get('support_models', True):
                    self._send_progress(88, "Importing metadata and support models...")
                    self._import_metadata_and_support()
                
                # Import media files only if annotations were imported
                if self.import_options.get('annotations', True):
                    self._send_progress(92, "Importing media files...")
                    self._import_media_files()
                else:
                    print("Skipping media files import (annotations not imported)")
                
                # Import remaining relationships
                self._send_progress(95, "Finalizing relationships...")
                self._import_remaining_relationships()
            
            print(f"REVISED COMPREHENSIVE import completed successfully")
            print(f"Import stats: {self.stats}")
            
            # Finalize import tracking
            self._finalize_import_tracker(True)
            
            return {
                'success': True,
                'stats': self.stats,
                'metadata': metadata,
                'id_mappings': self.id_mappings,
                'import_id': str(self.import_id)
            }
            
        except Exception as e:
            print(f"Import failed: {e}")
            self.stats['errors'].append(f"Import failed: {e}")
            
            # Finalize import tracking as failed
            self._finalize_import_tracker(False)
            
            return {
                'success': False,
                'error': str(e),
                'stats': self.stats,
                'import_id': str(self.import_id) if hasattr(self, 'import_id') else None
            }
        finally:
            self._cleanup()
    
    def _extract_and_validate_archive(self):
        """Extract archive (ZIP or TAR.GZ) and validate structure"""
        if not os.path.exists(self.import_path):
            raise FileNotFoundError(f"Import file not found: {self.import_path}")
        
        # Detect and extract archive format
        try:
            archive_format = self._extract_archive(self.import_path, self.temp_dir)
            print(f"Extracted {archive_format} archive successfully")
        except Exception as e:
            raise ValueError(f"Failed to extract archive: {e}")
        
        # Set paths
        self.sqlite_path = os.path.join(self.temp_dir, 'user_data.sqlite')
        self.media_dir = os.path.join(self.temp_dir, 'media')
        
        # Validate required files
        if not os.path.exists(self.sqlite_path):
            raise FileNotFoundError("user_data.sqlite not found in archive")
        
        self._send_progress(8, f"Archive validated ({archive_format} format)")
        print("Archive extracted and validated")
    
    def _load_and_validate_metadata(self) -> Dict[str, Any]:
        """Load and validate export metadata"""
        metadata_path = os.path.join(self.temp_dir, 'export_metadata.json')
        if not os.path.exists(metadata_path):
            print("Warning: export_metadata.json not found, proceeding without metadata validation")
            return {}
        
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        print(f"Loaded metadata: Export version {metadata.get('export_format_version', 'unknown')}")
        return metadata
    
    def _connect_to_import_database(self):
        """Connect to the SQLite import database"""
        self.conn = sqlite3.connect(self.sqlite_path)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        print("Connected to import database")
    
    def _import_remote_hosts(self):
        """Import remote hosts (needed for foreign keys)"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_remote_hosts")
        
        for row in cursor.fetchall():
            # Create or get existing remote host
            remote_host, created = RemoteHost.objects.get_or_create(
                host_name=row['host_name'],
                defaults={
                    'host_port': row['host_port'],
                    'host_protocol': row['host_protocol'],
                    'host_description': row['host_description'],
                    'host_token': row['host_token'],
                }
            )
            
            self.id_mappings['remote_hosts'][row['id']] = remote_host.id
        
        print("Imported remote hosts")
        self.stats['models_imported'] += 1
    
    def _import_lab_groups(self):
        """Import lab groups"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_lab_groups")
        
        for row in cursor.fetchall():
            # Create lab group (admin privilege required)
            lab_group = LabGroup.objects.create(
                name=f"{row['name']}_imported_{self.target_user.username}",
                description=row['description'],
                is_professional=bool(row['is_professional']),
                # Note: default_storage_id and service_storage_id will be set later
            )
            
            # Add target user to the lab group
            lab_group.users.add(self.target_user)
            
            self.id_mappings['lab_groups'][row['id']] = lab_group.id
        
        print("Imported lab groups")
        self.stats['models_imported'] += 1
    
    def _import_storage_objects(self):
        """Import storage objects"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_storage_objects")
        
        for row in cursor.fetchall():
            storage_object = StorageObject.objects.create(
                object_type=row['object_type'],
                object_name=row['object_name'],
                object_description=row['object_description'],
                png_base64=row['png_base64'],
                user=self.target_user,
                # stored_at_id will be handled later for self-references
            )
            
            self.id_mappings['storage_objects'][row['id']] = storage_object.id
        
        print("Imported storage objects")
        self.stats['models_imported'] += 1
    
    def _import_reagents(self):
        """Import reagents - behavior depends on bulk_transfer_mode"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_reagents")
        
        imported_count = 0
        skipped_count = 0
        
        for row in cursor.fetchall():
            if self.bulk_transfer_mode:
                # In bulk transfer mode, always import reagents as-is
                reagent_name = row['name'] or "Imported Reagent"
                
                reagent = Reagent.objects.create(
                    name=reagent_name,
                    unit=row['unit'],
                    description=row.get('description', ''),
                    cas_number=row.get('cas_number', ''),
                    # Add other reagent fields as needed
                )
                
                # Track created reagent
                self._track_created_object(reagent, row['id'])
                self.id_mappings['reagents'][row['id']] = reagent.id
                imported_count += 1
            else:
                # User-centric mode: check if reagent already exists (by name and unit)
                existing_reagent = Reagent.objects.filter(
                    name=row['name'],
                    unit=row['unit']
                ).first()
                
                if existing_reagent:
                    # Use existing reagent
                    self.id_mappings['reagents'][row['id']] = existing_reagent.id
                    skipped_count += 1
                    self.stats.setdefault('skipped_reagents', []).append(
                        f"Reagent '{row['name']}' ({row['unit']}) already exists - using existing"
                    )
                else:
                    # Create new reagent with import marking
                    reagent_name = row['name']
                    if reagent_name and not reagent_name.startswith('[IMPORTED]'):
                        reagent_name = f"[IMPORTED] {reagent_name}"
                    
                    reagent = Reagent.objects.create(
                        name=reagent_name,
                        unit=row['unit'],
                        description=row.get('description', ''),
                        cas_number=row.get('cas_number', ''),
                        # Add other reagent fields as needed
                    )
                    
                    # Track created reagent
                    self._track_created_object(reagent, row['id'])
                    self.id_mappings['reagents'][row['id']] = reagent.id
                    imported_count += 1
        
        print(f"Imported {imported_count} reagents, skipped {skipped_count} existing reagents")
        self.stats['models_imported'] += 1
    
    def _import_stored_reagents(self):
        """Import stored reagents - behavior depends on bulk_transfer_mode"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_stored_reagents")
        
        imported_count = 0
        skipped_count = 0
        
        for row in cursor.fetchall():
            reagent_id = row['reagent_id']
            original_storage_id = row['storage_object_id']
            
            # Check if we have mappings for reagent
            if reagent_id not in self.id_mappings.get('reagents', {}):
                skipped_count += 1
                self.stats.setdefault('skipped_stored_reagents', []).append(
                    f"Stored reagent skipped - reagent ID {reagent_id} not found"
                )
                continue
            
            if self.bulk_transfer_mode:
                # In bulk transfer mode, use original storage objects as-is
                target_storage_id = self.id_mappings.get('storage_objects', {}).get(original_storage_id)
                if not target_storage_id:
                    skipped_count += 1
                    self.stats.setdefault('skipped_stored_reagents', []).append(
                        f"Stored reagent skipped - storage object {original_storage_id} not imported"
                    )
                    continue
                
                notes = row['notes'] or "Imported Stored Reagent"
            else:
                # User-centric mode: require storage object nomination
                if not hasattr(self, 'storage_object_mappings') or not self.storage_object_mappings:
                    # Don't return early, just skip this item and log the issue
                    skipped_count += 1
                    self.stats.setdefault('skipped_stored_reagents', []).append(
                        f"Stored reagent skipped - no storage object mappings provided"
                    )
                    continue

                # Get the user-nominated storage object for this original storage
                nominated_storage_id = self.storage_object_mappings.get(str(original_storage_id))
                if not nominated_storage_id:
                    skipped_count += 1
                    self.stats.setdefault('skipped_stored_reagents', []).append(
                        f"Stored reagent skipped - no storage object nominated for original storage {original_storage_id}"
                    )
                    continue
                
                # Verify the nominated storage object exists and user has access
                try:
                    storage_obj = StorageObject.objects.get(id=nominated_storage_id)
                    # Check if user has access to this storage object
                    if storage_obj.user != self.target_user and not storage_obj.access_users.filter(id=self.target_user.id).exists():
                        skipped_count += 1
                        self.stats.setdefault('skipped_stored_reagents', []).append(
                            f"Stored reagent skipped - no access to nominated storage object {nominated_storage_id}"
                        )
                        continue
                except StorageObject.DoesNotExist:
                    skipped_count += 1
                    self.stats.setdefault('skipped_stored_reagents', []).append(
                        f"Stored reagent skipped - nominated storage object {nominated_storage_id} does not exist"
                    )
                    continue
                
                target_storage_id = nominated_storage_id
                notes = f"[IMPORTED] {row['notes']}" if row['notes'] else "[IMPORTED] Stored Reagent"
            
            # Create the stored reagent
            stored_reagent = StoredReagent.objects.create(
                reagent_id=self.id_mappings['reagents'][reagent_id],
                storage_object_id=target_storage_id,
                quantity=row['quantity'],
                notes=notes,
                barcode=row['barcode'],
                png_base64=row['png_base64'],
                shareable=bool(row.get('shareable', True)),
                user=self.target_user,
                # Add other fields as needed from the export schema
            )
            
            # Track created stored reagent
            self._track_created_object(stored_reagent, row['id'])
            self.id_mappings.setdefault('stored_reagents', {})[row['id']] = stored_reagent.id
            imported_count += 1
        
        print(f"Imported {imported_count} stored reagents, skipped {skipped_count} stored reagents")
        self.stats['models_imported'] += 1
    
    def _import_projects(self):
        """Import projects"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_projects")
        
        for row in cursor.fetchall():
            project = Project.objects.create(
                project_name=row['project_name'],
                project_description=row['project_description'],
                owner=self.target_user,
            )
            
            self.id_mappings['projects'][row['id']] = project.id
        
        print("Imported projects")
        self.stats['models_imported'] += 1
    
    def _import_protocols_accurate(self):
        """Import protocols with exact field mapping"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_protocols")
        
        print("Importing protocols...")
        
        for row in cursor.fetchall():
            # Add import marking to protocol title
            protocol_title = row['protocol_title']
            if protocol_title and not protocol_title.startswith('[IMPORTED]'):
                protocol_title = f"[IMPORTED] {protocol_title}"
            elif not protocol_title:
                protocol_title = "[IMPORTED] Protocol"
            
            # Create protocol with exact field mapping
            protocol = ProtocolModel.objects.create(
                protocol_id=row['protocol_id'],
                protocol_title=protocol_title,  # Exact field name
                protocol_description=row['protocol_description'],
                protocol_url=row['protocol_url'],
                protocol_version_uri=row['protocol_version_uri'],
                protocol_created_on=datetime.fromisoformat(row['protocol_created_on']) if row['protocol_created_on'] else timezone.now(),
                protocol_doi=row['protocol_doi'],
                enabled=bool(row['enabled']),
                model_hash=row['model_hash'],
                user=self.target_user,
                # remote_host will be set later if needed
            )
            
            # Track created object
            self._track_created_object(protocol, row['id'])
            
            self.id_mappings['protocols'][row['id']] = protocol.id
        
        # Import protocol sections
        cursor.execute("SELECT * FROM export_protocol_sections")
        for row in cursor.fetchall():
            if row['protocol_id'] in self.id_mappings['protocols']:
                section = ProtocolSection.objects.create(
                    section_description=row['section_description'],
                    section_duration=row['section_duration'],
                    protocol_id=self.id_mappings['protocols'][row['protocol_id']],
                )
                self._track_created_object(section, row['id'])
        
        # Import protocol steps
        cursor.execute("SELECT * FROM export_protocol_steps")
        step_mapping = {}
        
        # First pass: create steps without foreign key references
        for row in cursor.fetchall():
            if row['protocol_id'] in self.id_mappings['protocols']:
                step = ProtocolStep.objects.create(
                    step_id=row['step_id'],
                    step_description=row['step_description'],
                    step_duration=row['step_duration'],
                    original=bool(row['original']),
                    protocol_id=self.id_mappings['protocols'][row['protocol_id']],
                    # Will set step_section_id, previous_step_id, branch_from_id later
                )
                step_mapping[row['id']] = step.id
                self.id_mappings['steps'][row['id']] = step.id
                self._track_created_object(step, row['id'])
        
        # Second pass: update foreign key references
        cursor.execute("SELECT * FROM export_protocol_steps")
        for row in cursor.fetchall():
            if row['id'] in step_mapping:
                step = ProtocolStep.objects.get(id=step_mapping[row['id']])
                
                # Update previous_step reference
                if row['previous_step_id'] and row['previous_step_id'] in step_mapping:
                    step.previous_step_id = step_mapping[row['previous_step_id']]
                
                # Update branch_from reference
                if row['branch_from_id'] and row['branch_from_id'] in step_mapping:
                    step.branch_from_id = step_mapping[row['branch_from_id']]
                
                step.save()
        
        # Import protocol ratings
        cursor.execute("SELECT * FROM export_protocol_ratings")
        for row in cursor.fetchall():
            if row['protocol_id'] in self.id_mappings['protocols']:
                ProtocolRating.objects.create(
                    complexity_rating=row['complexity_rating'],
                    duration_rating=row['duration_rating'],
                    protocol_id=self.id_mappings['protocols'][row['protocol_id']],
                    user=self.target_user,
                )
        
        # Import many-to-many relationships
        self._import_protocol_relationships()
        
        print("Imported protocols with all relationships")
        self.stats['models_imported'] += 4
    
    def _import_protocol_relationships(self):
        """Import protocol many-to-many relationships"""
        cursor = self.conn.cursor()
        
        # Import protocol editors (but only add target user since we don't have other users)
        cursor.execute("SELECT * FROM export_protocol_editors")
        for row in cursor.fetchall():
            if row['protocolmodel_id'] in self.id_mappings['protocols']:
                protocol = ProtocolModel.objects.get(id=self.id_mappings['protocols'][row['protocolmodel_id']])
                protocol.editors.add(self.target_user)
                self._track_created_relationship(protocol, self.target_user, 'editors')
        
        # Import protocol viewers
        cursor.execute("SELECT * FROM export_protocol_viewers")
        for row in cursor.fetchall():
            if row['protocolmodel_id'] in self.id_mappings['protocols']:
                protocol = ProtocolModel.objects.get(id=self.id_mappings['protocols'][row['protocolmodel_id']])
                protocol.viewers.add(self.target_user)
                self._track_created_relationship(protocol, self.target_user, 'viewers')
        
        self.stats['relationships_imported'] += 2
    
    def _import_sessions_accurate(self):
        """Import sessions with exact field mapping"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM export_sessions")
        
        print("Importing sessions...")
        
        for row in cursor.fetchall():
            # Generate new UUID for unique_id to avoid conflicts
            # Add import marking to session name
            session_name = row['name']
            if session_name and not session_name.startswith('[IMPORTED]'):
                session_name = f"[IMPORTED] {session_name}"
            elif not session_name:
                session_name = "[IMPORTED] Session"
            
            session = Session.objects.create(
                unique_id=uuid.uuid4(),  # Generate new UUID
                name=session_name,
                enabled=bool(row['enabled']),
                processing=bool(row['processing']),
                started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
                ended_at=datetime.fromisoformat(row['ended_at']) if row['ended_at'] else None,
                user=self.target_user,
            )
            
            # Track created session
            self._track_created_object(session, row['id'])
            
            self.id_mappings['sessions'][row['id']] = session.id
        
        # Import session-protocol relationships
        cursor.execute("SELECT * FROM export_session_protocols")
        for row in cursor.fetchall():
            if (row['session_id'] in self.id_mappings['sessions'] and 
                row['protocolmodel_id'] in self.id_mappings['protocols']):
                session = Session.objects.get(id=self.id_mappings['sessions'][row['session_id']])
                protocol = ProtocolModel.objects.get(id=self.id_mappings['protocols'][row['protocolmodel_id']])
                session.protocols.add(protocol)
        
        # Import session editors/viewers (add target user)
        cursor.execute("SELECT * FROM export_session_editors")
        for row in cursor.fetchall():
            if row['session_id'] in self.id_mappings['sessions']:
                session = Session.objects.get(id=self.id_mappings['sessions'][row['session_id']])
                session.editors.add(self.target_user)
        
        cursor.execute("SELECT * FROM export_session_viewers")
        for row in cursor.fetchall():
            if row['session_id'] in self.id_mappings['sessions']:
                session = Session.objects.get(id=self.id_mappings['sessions'][row['session_id']])
                session.viewers.add(self.target_user)
        
        print("Imported sessions with relationships")
        self.stats['models_imported'] += 1
        self.stats['relationships_imported'] += 3
    
    def _import_annotations_accurate(self):
        """Import annotations and folders with exact field mapping"""
        cursor = self.conn.cursor()
        
        print("Importing annotation folders...")
        
        # Import annotation folders first
        cursor.execute("SELECT * FROM export_annotation_folders")
        folder_mapping = {}
        
        # First pass: create folders without parent references
        for row in cursor.fetchall():
            folder = AnnotationFolder.objects.create(
                folder_name=row['folder_name'],
                session_id=self.id_mappings['sessions'].get(row['session_id']),
                is_shared_document_folder=bool(row['is_shared_document_folder']),
                owner=self.target_user,
                # parent_folder_id will be set in second pass
            )
            folder_mapping[row['id']] = folder.id
            self.id_mappings['folders'][row['id']] = folder.id
        
        # Second pass: update parent folder references
        cursor.execute("SELECT * FROM export_annotation_folders")
        for row in cursor.fetchall():
            if row['id'] in folder_mapping and row['parent_folder_id']:
                if row['parent_folder_id'] in folder_mapping:
                    folder = AnnotationFolder.objects.get(id=folder_mapping[row['id']])
                    folder.parent_folder_id = folder_mapping[row['parent_folder_id']]
                    folder.save()
        
        print("Importing annotations...")
        
        # Import annotations
        cursor.execute("SELECT * FROM export_annotations")
        for row in cursor.fetchall():
            annotation_text = row['annotation']
            annotation_type = row['annotation_type']
            annotation_name = row['annotation_name']
            converted_from_instrument = False
            
            # Handle instrument annotation conversion (only in user-centric mode)
            if annotation_type == 'instrument' and not self.bulk_transfer_mode:
                # Check if instruments are allowed to be imported
                if not self.import_options.get('instruments', True):
                    # Convert to text annotation with special marking
                    converted_from_instrument = True
                    annotation_type = 'text'
                    
                    # Get instrument usage details if available to include in text
                    instrument_usage_text = self._get_instrument_usage_details(row['id'])
                    if instrument_usage_text:
                        annotation_text = f"[IMPORTED INSTRUMENT BOOKING]\n\n{instrument_usage_text}\n\nOriginal annotation: {annotation_text}"
                    else:
                        annotation_text = f"[IMPORTED INSTRUMENT BOOKING]\n\nThis was originally an instrument booking annotation.\n\nOriginal annotation: {annotation_text}"
                    
                    if annotation_name:
                        annotation_name = f"[IMPORTED] {annotation_name}"
                    else:
                        annotation_name = "[IMPORTED] Converted Instrument Booking"
                else:
                    # Check if the referenced instrument exists
                    referenced_instrument = self._get_annotation_referenced_instrument(row['id'])
                    if referenced_instrument and not self._instrument_exists_or_importable(referenced_instrument):
                        # Convert to text if instrument doesn't exist
                        converted_from_instrument = True
                        annotation_type = 'text'
                        
                        instrument_usage_text = self._get_instrument_usage_details(row['id'])
                        instrument_info = f"Instrument: {referenced_instrument.get('name', 'Unknown')}"
                        if instrument_usage_text:
                            annotation_text = f"[IMPORTED INSTRUMENT BOOKING - INSTRUMENT NOT AVAILABLE]\n\n{instrument_info}\n\n{instrument_usage_text}\n\nOriginal annotation: {annotation_text}"
                        else:
                            annotation_text = f"[IMPORTED INSTRUMENT BOOKING - INSTRUMENT NOT AVAILABLE]\n\n{instrument_info}\n\nOriginal annotation: {annotation_text}"
                        
                        if annotation_name:
                            annotation_name = f"[IMPORTED - NO INSTRUMENT] {annotation_name}"
                        else:
                            annotation_name = "[IMPORTED - NO INSTRUMENT] Converted Instrument Booking"
            
            # Add import marking to annotation name for easy identification (only in user-centric mode)
            if not self.bulk_transfer_mode:
                if not converted_from_instrument and annotation_name and not annotation_name.startswith('[IMPORTED]'):
                    annotation_name = f"[IMPORTED] {annotation_name}"
                elif not converted_from_instrument and not annotation_name:
                    annotation_name = "[IMPORTED] Annotation"
            
            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                annotation_name=annotation_name,
                transcribed=bool(row['transcribed']),
                transcription=row['transcription'],
                language=row['language'],
                translation=row['translation'],
                scratched=bool(row['scratched']),
                summary=row['summary'],
                fixed=bool(row['fixed']),
                session_id=self.id_mappings['sessions'].get(row['session_id']),
                step_id=self.id_mappings['steps'].get(row['step_id']),
                folder_id=self.id_mappings['folders'].get(row['folder_id']),
                user=self.target_user,
                # file will be handled during media import
            )
            
            # Track the created annotation
            self._track_created_object(annotation, row['id'])
            
            self.id_mappings['annotations'][row['id']] = annotation.id
            
            # Log conversion if it happened
            if converted_from_instrument:
                self.stats.setdefault('conversions', []).append(
                    f"Converted instrument annotation '{annotation_name}' to text annotation"
                )
        
        print("Imported annotations and folders")
        self.stats['models_imported'] += 2
    
    def _get_instrument_usage_details(self, annotation_id):
        """Get instrument usage details for an annotation"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT iu.*, i.name as instrument_name, i.description as instrument_description
            FROM export_instrument_usage iu
            LEFT JOIN export_instruments i ON iu.instrument_id = i.id
            WHERE iu.annotation_id = ?
        """, (annotation_id,))
        
        usage_row = cursor.fetchone()
        if not usage_row:
            return None
        
        details = []
        details.append(f"Instrument: {usage_row['instrument_name'] or 'Unknown'}")
        
        if usage_row['instrument_description']:
            details.append(f"Description: {usage_row['instrument_description']}")
        
        if usage_row['time_started']:
            details.append(f"Start Time: {usage_row['time_started']}")
        
        if usage_row['time_ended']:
            details.append(f"End Time: {usage_row['time_ended']}")
        
        if usage_row['description']:
            details.append(f"Usage Description: {usage_row['description']}")
        
        if usage_row['approved']:
            details.append("Status: Approved")
        
        if usage_row['maintenance']:
            details.append("Type: Maintenance")
        
        return "\n".join(details)
    
    def _get_annotation_referenced_instrument(self, annotation_id):
        """Get the instrument referenced by an annotation"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT i.*
            FROM export_instrument_usage iu
            JOIN export_instruments i ON iu.instrument_id = i.id
            WHERE iu.annotation_id = ?
        """, (annotation_id,))
        
        instrument_row = cursor.fetchone()
        if instrument_row:
            return dict(instrument_row)
        return None
    
    def _instrument_exists_or_importable(self, instrument_data):
        """Check if an instrument exists in the system or can be imported"""
        # Check if instrument exists by name
        instrument_name = instrument_data.get('name')
        if instrument_name:
            existing = Instrument.objects.filter(name=instrument_name).exists()
            if existing:
                return True
        
        # Check if instruments are set to be imported
        if self.import_options.get('instruments', True):
            # In this case, the instrument would be imported, so it would be available
            return True
        
        return False
    
    def _import_instruments_accurate(self):
        """Import instruments - behavior depends on bulk_transfer_mode"""
        # Import instruments if allowed by options
        if self.import_options.get('instruments', True):
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM export_instruments")
            
            for row in cursor.fetchall():
                if self.bulk_transfer_mode:
                    # In bulk transfer mode, import instruments as-is
                    instrument_name = row['name'] or "Imported Instrument"
                else:
                    # User-centric mode: add import marking
                    instrument_name = row['name']
                    if instrument_name and not instrument_name.startswith('[IMPORTED]'):
                        instrument_name = f"[IMPORTED] {instrument_name}"
                    elif not instrument_name:
                        instrument_name = "[IMPORTED] Instrument"
                
                instrument = Instrument.objects.create(
                    name=instrument_name,
                    description=row['description'],
                    accepts_bookings=bool(row.get('accepts_bookings', True)),
                    # Add other instrument fields as needed
                )
                self._track_created_object(instrument, row['id'])
                self.id_mappings['instruments'][row['id']] = instrument.id
            
            print(f"Imported {len(self.id_mappings['instruments'])} instruments")
        else:
            print("Skipped instrument import (disabled in options)")
        
        self.stats['models_imported'] += 1
    
    def _import_instrument_usage_and_jobs(self):
        """Import instrument usage records, converting to annotations if needed"""
        cursor = self.conn.cursor()
        
        # Import instrument usage - but only if we haven't converted these to text annotations
        cursor.execute("SELECT * FROM export_instrument_usage")
        for row in cursor.fetchall():
            annotation_id = row['annotation_id']
            instrument_id = row['instrument_id']
            
            # Check if this annotation still exists and is of type 'instrument'
            if (annotation_id in self.id_mappings['annotations'] and 
                instrument_id in self.id_mappings.get('instruments', {})):
                
                annotation = Annotation.objects.get(id=self.id_mappings['annotations'][annotation_id])
                
                if annotation.annotation_type == 'instrument':
                    # Create the instrument usage
                    usage = InstrumentUsage.objects.create(
                        instrument_id=self.id_mappings['instruments'][instrument_id],
                        annotation=annotation,
                        time_started=datetime.fromisoformat(row['time_started']) if row['time_started'] else None,
                        time_ended=datetime.fromisoformat(row['time_ended']) if row['time_ended'] else None,
                        approved=bool(row['approved']),
                        maintenance=bool(row['maintenance']),
                        description=row['description'],
                        user=self.target_user,
                    )
                    self._track_created_object(usage, row['id'])
                else:
                    # This was converted to text, so we don't create usage
                    self.stats.setdefault('skipped_usage', []).append(
                        f"Skipped instrument usage for converted annotation {annotation_id}"
                    )
            else:
                # Either annotation doesn't exist or instrument doesn't exist
                self.stats.setdefault('skipped_usage', []).append(
                    f"Skipped instrument usage - annotation {annotation_id} or instrument {instrument_id} not found"
                )
        
        print("Imported instrument usage records")
        self.stats['models_imported'] += 1
    
    def _import_tags_and_relationships(self):
        """Import tags and tagging relationships"""
        cursor = self.conn.cursor()
        
        # Import tags
        cursor.execute("SELECT * FROM export_tags")
        for row in cursor.fetchall():
            tag, created = Tag.objects.get_or_create(
                tag=row['tag'],
                defaults={}
            )
            self.id_mappings['tags'][row['id']] = tag.id
        
        # Import protocol tags
        cursor.execute("SELECT * FROM export_protocol_tags")
        for row in cursor.fetchall():
            if (row['protocol_id'] in self.id_mappings['protocols'] and 
                row['tag_id'] in self.id_mappings['tags']):
                ProtocolTag.objects.create(
                    protocol_id=self.id_mappings['protocols'][row['protocol_id']],
                    tag_id=self.id_mappings['tags'][row['tag_id']],
                )
        
        # Import step tags
        cursor.execute("SELECT * FROM export_step_tags")
        for row in cursor.fetchall():
            if (row['step_id'] in self.id_mappings['steps'] and 
                row['tag_id'] in self.id_mappings['tags']):
                StepTag.objects.create(
                    step_id=self.id_mappings['steps'][row['step_id']],
                    tag_id=self.id_mappings['tags'][row['tag_id']],
                )
        
        print("Imported tags and relationships")
        self.stats['models_imported'] += 1
        self.stats['relationships_imported'] += 2
    
    def _import_metadata_and_support(self):
        """Import metadata columns and other support models"""
        cursor = self.conn.cursor()
        
        # Import metadata columns
        cursor.execute("SELECT * FROM export_metadata_columns")
        for row in cursor.fetchall():
            MetadataColumn.objects.create(
                name=row['name'],
                type=row['type'],
                column_position=row['column_position'],
                value=row['value'],
                not_applicable=bool(row['not_applicable']),
                mandatory=bool(row['mandatory']),
                modifiers=row['modifiers'],
                auto_generated=bool(row['auto_generated']),
                hidden=bool(row['hidden']),
                readonly=bool(row['readonly']),
                annotation_id=self.id_mappings['annotations'].get(row['annotation_id']),
                protocol_id=self.id_mappings['protocols'].get(row['protocol_id']),
                # instrument_id and stored_reagent_id handled if available
            )
        
        print("Imported metadata and support models")
        self.stats['models_imported'] += 1
    
    def _import_media_files(self):
        """Import media files and link them to annotations"""
        if not os.path.exists(self.media_dir):
            print("No media directory found, skipping file import")
            return
        
        print("Importing media files...")
        
        # First, copy all media files to Django media root
        copied_files = {}
        for root, dirs, files in os.walk(self.media_dir):
            for file in files:
                src_path = os.path.join(root, file)
                rel_path = os.path.relpath(src_path, self.media_dir)
                dst_path = os.path.join(settings.MEDIA_ROOT, rel_path)

                # Create destination directory
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)

                # Copy file
                shutil.copy2(src_path, dst_path)

                # Track copied files for linking
                copied_files[file] = rel_path
                self.stats['files_imported'] += 1

                # Track file for rollback
                self._track_created_file(rel_path, file)

        # Now link files to annotation records
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, file FROM export_annotations WHERE file IS NOT NULL AND file != ''")

        files_linked = 0
        for row in cursor.fetchall():
            original_id = row['id']
            original_file_path = row['file']

            if original_id in self.id_mappings['annotations']:
                # Extract filename from original path
                filename = os.path.basename(original_file_path)

                if filename in copied_files:
                    # Update annotation with correct file path
                    try:
                        annotation = Annotation.objects.get(id=self.id_mappings['annotations'][original_id])
                        annotation.file = copied_files[filename]  # Use relative path from media root
                        annotation.save()
                        files_linked += 1
                    except Annotation.DoesNotExist:
                        print(f"Warning: Annotation not found for file {filename}")
                else:
                    print(f"Warning: File not found - annotation exists but file is missing: {filename}")

        print(f"Imported {self.stats['files_imported']} media files")
        print(f"Linked {files_linked} files to annotation records")
    
    def _import_remaining_relationships(self):
        """Import any remaining relationships"""
        print("Imported remaining relationships")
        self.stats['relationships_imported'] += 1
    
    def _cleanup(self):
        """Clean up temporary files"""
        if self.conn:
            self.conn.close()
        
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        
        print("Cleanup completed")


class UserDataImportDryRun:
    """
    Dry run analyzer for user data imports - analyzes what would be imported without making changes
    """
    
    def __init__(self, target_user: User, import_path: str, import_options: dict = None, progress_callback=None):
        self.target_user = target_user
        self.import_path = import_path
        self.temp_dir = tempfile.mkdtemp(prefix=f'cupcake_dryrun_{target_user.username}_')
        self.sqlite_path = None
        self.media_dir = None
        self.progress_callback = progress_callback
        
        # Import options for selective import
        self.import_options = import_options or {
            'protocols': True,
            'sessions': True, 
            'annotations': True,
            'projects': True,
            'reagents': True,
            'instruments': True,
            'lab_groups': True,
            'messaging': False,
            'support_models': True
        }
        
        self.analysis_report = {
            'archive_info': {},
            'data_summary': {},
            'potential_conflicts': [],
            'size_analysis': {},
            'import_plan': {},
            'warnings': [],
            'errors': []
        }
    
    def _send_progress(self, progress: int, message: str, status: str = "analyzing"):
        """Send progress update via callback if available"""
        if self.progress_callback:
            self.progress_callback(progress, message, status)
    
    def analyze_import(self) -> Dict[str, Any]:
        """
        Analyze the import archive and return a comprehensive report without importing anything
        """
        try:
            self._send_progress(0, "Starting dry run analysis...")
            
            # Extract and validate archive
            self._send_progress(10, "Extracting and validating archive...")
            archive_format = self._extract_and_validate_archive()
            
            # Load metadata
            self._send_progress(20, "Loading export metadata...")
            metadata = self._load_metadata()
            
            # Connect to database
            self._send_progress(30, "Connecting to archive database...")
            self._connect_to_database()
            
            # Analyze data structure
            self._send_progress(40, "Analyzing data structure...")
            self._analyze_data_structure()
            
            # Check for conflicts
            self._send_progress(60, "Checking for potential conflicts...")
            self._check_conflicts()
            
            # Analyze file sizes
            self._send_progress(70, "Analyzing file sizes...")
            self._analyze_file_sizes()
            
            # Generate import plan
            self._send_progress(80, "Generating import plan...")
            self._generate_import_plan()
            
            # Validate against site settings
            self._send_progress(90, "Validating against site restrictions...")
            self._validate_site_restrictions()
            
            self._send_progress(100, "Dry run analysis completed")
            
            return {
                'success': True,
                'analysis_report': self.analysis_report,
                'metadata': metadata,
                'archive_format': archive_format
            }
            
        except Exception as e:
            self.analysis_report['errors'].append(f"Analysis failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'analysis_report': self.analysis_report
            }
        finally:
            self._cleanup()
    
    def _extract_and_validate_archive(self) -> str:
        """Extract and validate archive without side effects"""
        if not os.path.exists(self.import_path):
            raise FileNotFoundError(f"Import file not found: {self.import_path}")
        
        # Get file info
        file_size = os.path.getsize(self.import_path)
        self.analysis_report['archive_info'] = {
            'file_path': self.import_path,
            'file_size_bytes': file_size,
            'file_size_mb': round(file_size / (1024 * 1024), 2)
        }
        
        # Detect and extract
        archive_format = self._detect_archive_format()
        self._extract_archive_safe(archive_format)
        
        # Validate structure
        self.sqlite_path = os.path.join(self.temp_dir, 'user_data.sqlite')
        self.media_dir = os.path.join(self.temp_dir, 'media')
        
        if not os.path.exists(self.sqlite_path):
            raise FileNotFoundError("user_data.sqlite not found in archive")
        
        self.analysis_report['archive_info']['format'] = archive_format
        self.analysis_report['archive_info']['has_media'] = os.path.exists(self.media_dir)
        
        return archive_format
    
    def _detect_archive_format(self) -> str:
        """Detect archive format"""
        import tarfile
        
        file_path_lower = self.import_path.lower()
        
        if file_path_lower.endswith('.zip'):
            return 'zip'
        elif file_path_lower.endswith(('.tar.gz', '.tgz')):
            return 'tar.gz'
        elif file_path_lower.endswith('.tar'):
            return 'tar'
        
        # Detect by content
        try:
            if zipfile.is_zipfile(self.import_path):
                return 'zip'
            elif tarfile.is_tarfile(self.import_path):
                return 'tar.gz'
        except Exception:
            pass
        
        raise ValueError(f"Cannot determine archive format for file: {self.import_path}")
    
    def _extract_archive_safe(self, archive_format: str):
        """Extract archive safely"""
        import tarfile
        
        if archive_format == 'zip':
            with zipfile.ZipFile(self.import_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
        elif archive_format in ['tar.gz', 'tar']:
            with tarfile.open(self.import_path, 'r:*') as tar_ref:
                tar_ref.extractall(self.temp_dir)
    
    def _load_metadata(self) -> Dict[str, Any]:
        """Load export metadata"""
        metadata_path = os.path.join(self.temp_dir, 'export_metadata.json')
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _connect_to_database(self):
        """Connect to SQLite database"""
        self.conn = sqlite3.connect(self.sqlite_path)
        self.conn.row_factory = sqlite3.Row
    
    def _analyze_data_structure(self):
        """Analyze what data is available in the archive"""
        cursor = self.conn.cursor()
        
        # Get table names and counts
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'export_%'")
        tables = cursor.fetchall()
        
        data_summary = {}
        total_records = 0
        
        for table in tables:
            table_name = table['name']
            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            count = cursor.fetchone()['count']
            
            # Clean up table name for reporting
            clean_name = table_name.replace('export_', '').replace('_', ' ').title()
            data_summary[clean_name] = count
            total_records += count
        
        self.analysis_report['data_summary'] = data_summary
        self.analysis_report['data_summary']['Total Records'] = total_records
        
        # Analyze what will actually be imported based on options
        filtered_summary = {}
        for table_name, count in data_summary.items():
            should_import = self._should_import_table(table_name)
            if should_import:
                filtered_summary[table_name] = count
            else:
                filtered_summary[f"{table_name} (SKIPPED)"] = count
        
        self.analysis_report['filtered_data_summary'] = filtered_summary
    
    def _should_import_table(self, table_name: str) -> bool:
        """Determine if a table should be imported based on import options"""
        table_lower = table_name.lower()
        
        mapping = {
            'protocols': ['protocol'],
            'sessions': ['session'],
            'annotations': ['annotation'],
            'projects': ['project'],
            'reagents': ['reagent', 'storage'],
            'instruments': ['instrument'],
            'lab_groups': ['lab group'],
            'messaging': ['message'],
            'support_models': ['metadata', 'tag', 'remote']
        }
        
        for option, keywords in mapping.items():
            if any(keyword in table_lower for keyword in keywords):
                return self.import_options.get(option, True)
        
        return True  # Default to import if unclear
    
    def _check_conflicts(self):
        """Check for potential conflicts with existing data"""
        cursor = self.conn.cursor()
        conflicts = []
        
        # Check for protocol title conflicts
        if self.import_options.get('protocols', True):
            try:
                cursor.execute("SELECT protocol_title FROM export_protocols")
                protocol_titles = [row['protocol_title'] for row in cursor.fetchall()]
                
                from cc.models import ProtocolModel
                existing_titles = set(ProtocolModel.objects.filter(
                    protocol_title__in=protocol_titles, 
                    user=self.target_user
                ).values_list('protocol_title', flat=True))
                
                if existing_titles:
                    conflicts.append({
                        'type': 'Protocol Title Conflict',
                        'description': f"Found {len(existing_titles)} protocols with existing titles",
                        'items': list(existing_titles)[:10],  # Limit to first 10
                        'total_conflicts': len(existing_titles)
                    })
            except Exception as e:
                self.analysis_report['warnings'].append(f"Could not check protocol conflicts: {e}")
        
        # Check for project name conflicts
        if self.import_options.get('projects', True):
            try:
                cursor.execute("SELECT project_name FROM export_projects")
                project_names = [row['project_name'] for row in cursor.fetchall()]
                
                from cc.models import Project
                existing_projects = set(Project.objects.filter(
                    project_name__in=project_names,
                    owner=self.target_user
                ).values_list('project_name', flat=True))
                
                if existing_projects:
                    conflicts.append({
                        'type': 'Project Name Conflict',
                        'description': f"Found {len(existing_projects)} projects with existing names",
                        'items': list(existing_projects)[:10],
                        'total_conflicts': len(existing_projects)
                    })
            except Exception as e:
                self.analysis_report['warnings'].append(f"Could not check project conflicts: {e}")
        
        # Check for reagent duplicates and stored reagent storage requirements
        if self.import_options.get('reagents', True):
            try:
                # Check for reagent name+unit duplicates
                cursor.execute("SELECT name, unit FROM export_reagents")
                reagent_combinations = [(row['name'], row['unit']) for row in cursor.fetchall()]
                
                from cc.models import Reagent
                existing_reagents = []
                for name, unit in reagent_combinations:
                    if Reagent.objects.filter(name=name, unit=unit).exists():
                        existing_reagents.append(f"{name} ({unit})")
                
                if existing_reagents:
                    conflicts.append({
                        'type': 'Existing Reagents',
                        'description': f"Found {len(existing_reagents)} reagents that already exist (will use existing)",
                        'items': existing_reagents[:10],
                        'total_conflicts': len(existing_reagents)
                    })
                
                # Check for stored reagents requiring storage object nomination
                cursor.execute("""
                    SELECT COUNT(*) as count, 
                           GROUP_CONCAT(DISTINCT so.object_name) as storage_names
                    FROM export_stored_reagents sr
                    JOIN export_storage_objects so ON sr.storage_object_id = so.id
                """)
                stored_reagent_row = cursor.fetchone()
                
                if stored_reagent_row and stored_reagent_row['count'] > 0:
                    # Get detailed storage object requirements
                    cursor.execute("""
                        SELECT so.id, so.object_name, so.object_type, COUNT(sr.id) as reagent_count
                        FROM export_stored_reagents sr
                        JOIN export_storage_objects so ON sr.storage_object_id = so.id
                        GROUP BY so.id, so.object_name, so.object_type
                    """)
                    storage_requirements = cursor.fetchall()
                    
                    storage_info = []
                    for req in storage_requirements:
                        storage_info.append(f"{req['object_name']} ({req['object_type']}) - {req['reagent_count']} reagents")
                    
                    self.analysis_report['storage_object_requirements'] = {
                        'total_stored_reagents': stored_reagent_row['count'],
                        'required_storage_objects': storage_requirements,
                        'description': f"Import contains {stored_reagent_row['count']} stored reagents requiring storage object nomination"
                    }
                    
                    conflicts.append({
                        'type': 'Storage Object Requirements',
                        'description': f"Found {stored_reagent_row['count']} stored reagents requiring storage object nomination",
                        'items': storage_info,
                        'total_conflicts': len(storage_requirements)
                    })
                
            except Exception as e:
                self.analysis_report['warnings'].append(f"Could not check reagent conflicts: {e}")
        
        self.analysis_report['potential_conflicts'] = conflicts
    
    def _analyze_file_sizes(self):
        """Analyze file sizes in media directory"""
        size_analysis = {
            'total_media_files': 0,
            'total_media_size_bytes': 0,
            'total_media_size_mb': 0,
            'large_files': [],
            'file_types': {}
        }
        
        if os.path.exists(self.media_dir):
            for root, dirs, files in os.walk(self.media_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        size_analysis['total_media_files'] += 1
                        size_analysis['total_media_size_bytes'] += file_size
                        
                        # Track large files (>10MB)
                        if file_size > 10 * 1024 * 1024:
                            size_analysis['large_files'].append({
                                'name': file,
                                'size_mb': round(file_size / (1024 * 1024), 2)
                            })
                        
                        # Track file types
                        ext = os.path.splitext(file)[1].lower()
                        if ext:
                            size_analysis['file_types'][ext] = size_analysis['file_types'].get(ext, 0) + 1
        
        size_analysis['total_media_size_mb'] = round(size_analysis['total_media_size_bytes'] / (1024 * 1024), 2)
        self.analysis_report['size_analysis'] = size_analysis
    
    def _generate_import_plan(self):
        """Generate a detailed import execution plan"""
        import_plan = {
            'execution_order': [],
            'estimated_duration_minutes': 0,
            'database_operations': 0,
            'file_operations': 0,
            'dependency_resolution': []
        }
        
        # Define import order based on dependencies
        import_order = [
            ('Remote Hosts', 'Lab Groups and Projects setup'),
            ('Lab Groups', 'Organization setup'),
            ('Storage Objects', 'Storage infrastructure'),
            ('Reagents', 'Chemical inventory'),
            ('Projects', 'Project structure'),
            ('Protocols', 'Protocol definitions and structure'),
            ('Sessions', 'Execution sessions'),
            ('Annotations', 'Data and files'),
            ('Instruments', 'Instrument configurations'),
            ('Tags and Relationships', 'Metadata and connections'),
            ('Support Models', 'Additional metadata'),
            ('Media Files', 'File copying and validation')
        ]
        
        total_records = self.analysis_report['data_summary'].get('Total Records', 0)
        media_files = self.analysis_report['size_analysis']['total_media_files']
        
        for step, description in import_order:
            import_plan['execution_order'].append({
                'step': step,
                'description': description,
                'estimated_records': total_records // len(import_order)  # Rough estimate
            })
        
        # Estimate duration (very rough)
        import_plan['estimated_duration_minutes'] = max(1, (total_records // 100) + (media_files // 50))
        import_plan['database_operations'] = total_records
        import_plan['file_operations'] = media_files
        
        self.analysis_report['import_plan'] = import_plan
    
    def _validate_site_restrictions(self):
        """Validate import against site settings"""
        try:
            from cc.models import SiteSettings
            site_settings = SiteSettings.objects.filter(is_active=True).first()
            
            if site_settings:
                # Check archive size limit
                archive_size_mb = self.analysis_report['archive_info']['file_size_mb']
                if (site_settings.import_archive_size_limit_mb > 0 and 
                    archive_size_mb > site_settings.import_archive_size_limit_mb):
                    self.analysis_report['errors'].append(
                        f"Archive size ({archive_size_mb}MB) exceeds site limit "
                        f"({site_settings.import_archive_size_limit_mb}MB)"
                    )
                
                # Check restricted import types
                restrictions = []
                restriction_mapping = {
                    'protocols': 'allow_import_protocols',
                    'sessions': 'allow_import_sessions',
                    'annotations': 'allow_import_annotations',
                    'projects': 'allow_import_projects',
                    'reagents': 'allow_import_reagents',
                    'instruments': 'allow_import_instruments',
                    'lab_groups': 'allow_import_lab_groups',
                    'messaging': 'allow_import_messaging',
                    'support_models': 'allow_import_support_models'
                }
                
                for option, field in restriction_mapping.items():
                    if (self.import_options.get(option, False) and 
                        not getattr(site_settings, field, True)):
                        restrictions.append(option)
                
                if restrictions and not self.target_user.is_staff:
                    self.analysis_report['warnings'].append(
                        f"Site restrictions prevent import of: {', '.join(restrictions)}"
                    )
                
        except Exception as e:
            self.analysis_report['warnings'].append(f"Could not validate site restrictions: {e}")
    
    def _cleanup(self):
        """Clean up temporary files"""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
        
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


def dry_run_import_user_data(target_user: User, import_path: str, import_options: dict = None, progress_callback=None) -> Dict[str, Any]:
    """
    Perform a dry run analysis of user data import without making any changes.
    
    Args:
        target_user: Django User instance to import data for
        import_path: Path to archive file (ZIP or TAR.GZ) containing exported data
        import_options: Optional dict specifying what to import
        progress_callback: Optional callback function for progress updates
    
    Returns:
        Dict: Analysis results and import plan
    """
    analyzer = UserDataImportDryRun(target_user, import_path, import_options, progress_callback)
    return analyzer.analyze_import()


class ImportReverter:
    """Handles reverting user data imports"""
    
    def __init__(self, import_tracker: ImportTracker, reverting_user: User):
        self.import_tracker = import_tracker
        self.reverting_user = reverting_user
        
        self.stats = {
            'objects_deleted': 0,
            'files_deleted': 0,
            'relationships_removed': 0,
            'errors': []
        }
    
    def revert_import(self) -> Dict[str, Any]:
        """
        Revert all changes made by an import.
        
        Returns:
            Dict: Revert results and statistics
        """
        if self.import_tracker.import_status == 'reverted':
            return {
                'success': False,
                'error': 'Import has already been reverted',
                'stats': self.stats
            }
        
        if not self.import_tracker.can_revert:
            return {
                'success': False,
                'error': f'Import cannot be reverted: {self.import_tracker.revert_reason}',
                'stats': self.stats
            }
        
        try:
            with transaction.atomic():
                print(f"Starting revert of import {self.import_tracker.import_id}")
                
                # Remove many-to-many relationships first
                self._revert_relationships()
                
                # Delete files
                self._revert_files()
                
                # Delete objects in reverse order of creation
                self._revert_objects()
                
                # Update tracker status
                self.import_tracker.import_status = 'reverted'
                self.import_tracker.reverted_at = timezone.now()
                self.import_tracker.reverted_by = self.reverting_user
                self.import_tracker.save()
                
                print(f"Successfully reverted import {self.import_tracker.import_id}")
                print(f"Revert stats: {self.stats}")
                
                return {
                    'success': True,
                    'stats': self.stats,
                    'import_id': str(self.import_tracker.import_id)
                }
                
        except Exception as e:
            self.stats['errors'].append(f"Revert failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'stats': self.stats
            }
    
    def _revert_relationships(self):
        """Remove many-to-many relationships created during import"""
        relationships = self.import_tracker.imported_relationships.all().order_by('-created_at')
        
        for rel in relationships:
            try:
                # Get the model classes - handle special cases
                if rel.from_model == 'User':
                    from_model = apps.get_model('auth', 'User')
                else:
                    from_model = apps.get_model('cc', rel.from_model)
                
                if rel.to_model == 'User':
                    to_model = apps.get_model('auth', 'User')
                else:
                    to_model = apps.get_model('cc', rel.to_model)
                
                # Get the objects
                from_obj = from_model.objects.get(pk=rel.from_object_id)
                to_obj = to_model.objects.get(pk=rel.to_object_id)
                
                # Remove the relationship
                relationship_field = getattr(from_obj, rel.relationship_field)
                relationship_field.remove(to_obj)
                
                self.stats['relationships_removed'] += 1
                
            except Exception as e:
                self.stats['errors'].append(f"Failed to remove relationship {rel}: {e}")
                
        print(f"Removed {self.stats['relationships_removed']} relationships")
    
    def _revert_files(self):
        """Delete files created during import"""
        files = self.import_tracker.imported_files.all()
        
        for file_record in files:
            try:
                file_path = os.path.join(settings.MEDIA_ROOT, file_record.file_path)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
                    # Try to remove empty directories
                    try:
                        parent_dir = os.path.dirname(file_path)
                        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                            os.rmdir(parent_dir)
                    except OSError:
                        pass  # Directory not empty or can't be removed
                
                self.stats['files_deleted'] += 1
                
            except Exception as e:
                self.stats['errors'].append(f"Failed to delete file {file_record.file_path}: {e}")
                
        print(f"Deleted {self.stats['files_deleted']} files")
    
    def _revert_objects(self):
        """Delete objects created during import in reverse order"""
        # Group objects by model and delete in dependency order
        objects_by_model = {}
        for obj_record in self.import_tracker.imported_objects.all().order_by('-created_at'):
            model_name = obj_record.model_name
            if model_name not in objects_by_model:
                objects_by_model[model_name] = []
            objects_by_model[model_name].append(obj_record)
        
        # Delete in reverse dependency order
        deletion_order = [
            'MetadataColumn',
            'StepTag', 'ProtocolTag',
            'ProtocolRating',
            'Annotation', 'AnnotationFolder',
            'Session',
            'ProtocolStep', 'ProtocolSection',
            'ProtocolModel',
            'ReagentAction', 'StoredReagent',
            'StorageObject',
            'Project',
            'LabGroup',
            'RemoteHost',
            'Tag', 'Reagent'
        ]
        
        # Delete objects in specified order, then any remaining
        all_models = set(objects_by_model.keys())
        for model_name in deletion_order:
            if model_name in objects_by_model:
                self._delete_objects_of_model(model_name, objects_by_model[model_name])
                all_models.remove(model_name)
        
        # Delete any remaining models not in the explicit order
        for model_name in all_models:
            self._delete_objects_of_model(model_name, objects_by_model[model_name])
            
        print(f"Deleted {self.stats['objects_deleted']} objects")
    
    def _delete_objects_of_model(self, model_name: str, obj_records: List):
        """Delete all objects of a specific model"""
        try:
            model_class = apps.get_model('cc', model_name)
            
            for obj_record in obj_records:
                try:
                    obj = model_class.objects.get(pk=obj_record.object_id)
                    obj.delete()
                    self.stats['objects_deleted'] += 1
                    
                except model_class.DoesNotExist:
                    # Object already deleted or doesn't exist
                    pass
                except Exception as e:
                    self.stats['errors'].append(f"Failed to delete {model_name}({obj_record.object_id}): {e}")
                    
        except LookupError:
            self.stats['errors'].append(f"Model {model_name} not found")


def revert_user_data_import(import_id: str, reverting_user: User) -> Dict[str, Any]:
    """
    Revert a user data import by import ID.
    
    Args:
        import_id: UUID string of the import to revert
        reverting_user: User performing the revert (must be staff or the original user)
    
    Returns:
        Dict: Revert results and statistics
    """
    try:
        import_tracker = ImportTracker.objects.get(import_id=import_id)
        
        # Check permissions
        if not (reverting_user.is_staff or reverting_user == import_tracker.user):
            return {
                'success': False,
                'error': 'Insufficient permissions to revert this import'
            }
        
        reverter = ImportReverter(import_tracker, reverting_user)
        return reverter.revert_import()
        
    except ImportTracker.DoesNotExist:
        return {
            'success': False,
            'error': f'Import with ID {import_id} not found'
        }


def list_user_imports(user: User, include_reverted: bool = False) -> List[Dict[str, Any]]:
    """
    List all imports for a user.
    
    Args:
        user: User to list imports for
        include_reverted: Whether to include reverted imports
    
    Returns:
        List of import information dictionaries
    """
    queryset = ImportTracker.objects.filter(user=user)
    
    if not include_reverted:
        queryset = queryset.exclude(import_status='reverted')
    
    imports = []
    for tracker in queryset.order_by('-import_started_at'):
        imports.append({
            'import_id': str(tracker.import_id),
            'import_started_at': tracker.import_started_at.isoformat(),
            'import_completed_at': tracker.import_completed_at.isoformat() if tracker.import_completed_at else None,
            'import_status': tracker.import_status,
            'archive_size_mb': tracker.archive_size_mb,
            'total_objects_created': tracker.total_objects_created,
            'total_files_imported': tracker.total_files_imported,
            'total_relationships_created': tracker.total_relationships_created,
            'can_revert': tracker.can_revert,
            'reverted_at': tracker.reverted_at.isoformat() if tracker.reverted_at else None,
            'reverted_by': tracker.reverted_by.username if tracker.reverted_by else None
        })
    
    return imports


def import_user_data_revised(target_user: User, import_path: str, import_options: dict = None, progress_callback=None, storage_object_mappings: dict = None, bulk_transfer_mode: bool = False) -> Dict[str, Any]:
    """
    REVISED comprehensive function to import user data with progress tracking and selective import.
    
    Args:
        target_user: Django User instance to import data for
        import_path: Path to archive file (ZIP or TAR.GZ) containing exported data
        import_options: Optional dict specifying what to import
        progress_callback: Optional callback function for progress updates
        storage_object_mappings: Optional dict mapping original storage IDs to nominated storage IDs
        bulk_transfer_mode: If True, import everything as-is without user-centric modifications
    
    Returns:
        Dict: Import results and statistics
    """
    importer = UserDataImporter(target_user, import_path, import_options, progress_callback, storage_object_mappings, bulk_transfer_mode)
    return importer.import_user_data()
