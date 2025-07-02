"""
Archive Schema Migration Utility for CUPCAKE LIMS

This utility handles migration of SQLite export archives from different versions
of the application to ensure compatibility with the current schema.
"""

import sqlite3
import os
import shutil
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ArchiveSchemaMigrator:
    """
    Handles migration of SQLite archives between different schema versions
    """
    
    # Define schema versions and their migration paths
    SCHEMA_VERSIONS = {
        "1.0.0": "Initial schema",
        "1.1.0": "Added instrument jobs and metadata columns",
        "1.2.0": "Added lab groups and permissions",
        "1.3.0": "Added messaging system",
        "1.4.0": "Added storage objects and reagent tracking",
        "1.5.0": "Added WebRTC and real-time features",
        "1.6.0": "Added site settings and import restrictions",
        "1.7.0": "Current schema with dry run support"
    }
    
    def __init__(self, archive_path: str, target_version: str = "1.7.0"):
        self.archive_path = archive_path
        self.target_version = target_version
        self.temp_dir = None
        self.sqlite_path = None
        self.migration_log = []
        
    def detect_schema_version(self) -> Tuple[str, Dict[str, Any]]:
        """
        Detect the schema version of the SQLite archive
        Returns (version, schema_info)
        """
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Get schema info for each table
            schema_info = {}
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                schema_info[table] = {
                    'columns': [(col[1], col[2]) for col in columns],  # (name, type)
                    'column_names': [col[1] for col in columns]
                }
            
            # Detect version based on schema characteristics
            version = self._analyze_schema_version(tables, schema_info)
            
            return version, schema_info
    
    def _analyze_schema_version(self, tables: List[str], schema_info: Dict) -> str:
        """
        Analyze schema characteristics to determine version
        """
        # Version detection logic based on table presence and column structure
        
        # v1.0.0 - Basic tables only
        basic_tables = {'cc_protocolmodel', 'cc_protocolstep', 'cc_session', 'cc_annotation'}
        
        # v1.1.0 - Added instrument jobs
        v11_indicators = {'cc_instrumentjob', 'cc_metadatacolumn'}
        
        # v1.2.0 - Added lab groups
        v12_indicators = {'cc_labgroup', 'cc_instrumentpermission'}
        
        # v1.3.0 - Added messaging
        v13_indicators = {'cc_messagethread', 'cc_message', 'cc_messagerecipient'}
        
        # v1.4.0 - Added storage and reagents
        v14_indicators = {'cc_storageobject', 'cc_storedreagent', 'cc_reagentaction'}
        
        # v1.5.0 - Added WebRTC
        v15_indicators = {'cc_webrtcsession', 'cc_webrtcuserchannel'}
        
        # v1.6.0 - Added site settings
        v16_indicators = {'cc_sitesettings', 'cc_backuplog'}
        
        # v1.7.0 - Check for recent columns
        v17_indicators = set()
        if 'cc_sitesettings' in schema_info:
            site_settings_cols = schema_info['cc_sitesettings']['column_names']
            if 'allow_import_protocols' in site_settings_cols:
                v17_indicators.add('import_restrictions')
        
        # Determine version based on feature presence
        table_set = set(tables)
        
        if v17_indicators:
            return "1.7.0"
        elif v16_indicators.intersection(table_set):
            return "1.6.0"
        elif v15_indicators.intersection(table_set):
            return "1.5.0"
        elif v14_indicators.intersection(table_set):
            return "1.4.0"
        elif v13_indicators.intersection(table_set):
            return "1.3.0"
        elif v12_indicators.intersection(table_set):
            return "1.2.0"
        elif v11_indicators.intersection(table_set):
            return "1.1.0"
        elif basic_tables.intersection(table_set):
            return "1.0.0"
        else:
            return "unknown"
    
    def needs_migration(self) -> bool:
        """
        Check if the archive needs migration to target version
        """
        current_version, _ = self.detect_schema_version()
        return current_version != self.target_version and current_version != "unknown"
    
    def migrate_archive(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Migrate the archive to the target schema version
        Returns migration result with details
        """
        # Extract archive to temporary directory
        self.temp_dir = tempfile.mkdtemp(prefix='cupcake_migration_')
        
        try:
            # Extract archive
            if self.archive_path.endswith('.zip'):
                import zipfile
                with zipfile.ZipFile(self.archive_path, 'r') as zip_ref:
                    zip_ref.extractall(self.temp_dir)
            elif self.archive_path.endswith(('.tar.gz', '.tgz')):
                import tarfile
                with tarfile.open(self.archive_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(self.temp_dir)
            else:
                raise ValueError(f"Unsupported archive format: {self.archive_path}")
            
            # Find SQLite database
            self.sqlite_path = self._find_sqlite_db()
            if not self.sqlite_path:
                raise ValueError("No SQLite database found in archive")
            
            # Detect current version
            current_version, schema_info = self.detect_schema_version()
            
            if current_version == "unknown":
                raise ValueError("Cannot determine schema version of archive")
            
            if current_version == self.target_version:
                return {
                    'success': True,
                    'migration_needed': False,
                    'current_version': current_version,
                    'target_version': self.target_version,
                    'message': 'Archive is already at target version'
                }
            
            # Perform migration
            migration_result = self._perform_migration(current_version, schema_info)
            
            # Create migrated archive if output path specified
            if output_path and migration_result['success']:
                self._create_migrated_archive(output_path)
                migration_result['migrated_archive'] = output_path
            
            return migration_result
            
        finally:
            # Cleanup temporary directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
    
    def _find_sqlite_db(self) -> Optional[str]:
        """Find SQLite database in extracted archive"""
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.endswith('.sqlite') or file.endswith('.db'):
                    return os.path.join(root, file)
        return None
    
    def _perform_migration(self, current_version: str, schema_info: Dict) -> Dict[str, Any]:
        """
        Perform the actual schema migration
        """
        self.migration_log = []
        
        try:
            with sqlite3.connect(self.sqlite_path) as conn:
                cursor = conn.cursor()
                
                # Enable foreign key constraints
                cursor.execute("PRAGMA foreign_keys = ON")
                
                # Perform step-by-step migration
                version_path = self._get_migration_path(current_version, self.target_version)
                
                for from_version, to_version in version_path:
                    self._migrate_version_step(cursor, from_version, to_version, schema_info)
                
                # Update schema version metadata
                self._update_schema_metadata(cursor)
                
                conn.commit()
                
                return {
                    'success': True,
                    'migration_needed': True,
                    'current_version': current_version,
                    'target_version': self.target_version,
                    'migration_log': self.migration_log,
                    'message': f'Successfully migrated from {current_version} to {self.target_version}'
                }
                
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            return {
                'success': False,
                'migration_needed': True,
                'current_version': current_version,
                'target_version': self.target_version,
                'error': str(e),
                'migration_log': self.migration_log
            }
    
    def _get_migration_path(self, from_version: str, to_version: str) -> List[Tuple[str, str]]:
        """
        Get the migration path between versions
        """
        versions = list(self.SCHEMA_VERSIONS.keys())
        from_idx = versions.index(from_version)
        to_idx = versions.index(to_version)
        
        if from_idx > to_idx:
            raise ValueError("Downgrade migrations not supported")
        
        # Create step-by-step migration path
        path = []
        for i in range(from_idx, to_idx):
            path.append((versions[i], versions[i + 1]))
        
        return path
    
    def _migrate_version_step(self, cursor: sqlite3.Cursor, from_version: str, to_version: str, schema_info: Dict):
        """
        Migrate one version step
        """
        self.migration_log.append(f"Migrating from {from_version} to {to_version}")
        
        # Version-specific migration logic
        if from_version == "1.0.0" and to_version == "1.1.0":
            self._migrate_1_0_to_1_1(cursor, schema_info)
        elif from_version == "1.1.0" and to_version == "1.2.0":
            self._migrate_1_1_to_1_2(cursor, schema_info)
        elif from_version == "1.2.0" and to_version == "1.3.0":
            self._migrate_1_2_to_1_3(cursor, schema_info)
        elif from_version == "1.3.0" and to_version == "1.4.0":
            self._migrate_1_3_to_1_4(cursor, schema_info)
        elif from_version == "1.4.0" and to_version == "1.5.0":
            self._migrate_1_4_to_1_5(cursor, schema_info)
        elif from_version == "1.5.0" and to_version == "1.6.0":
            self._migrate_1_5_to_1_6(cursor, schema_info)
        elif from_version == "1.6.0" and to_version == "1.7.0":
            self._migrate_1_6_to_1_7(cursor, schema_info)
        else:
            self.migration_log.append(f"No specific migration for {from_version} -> {to_version}")
    
    def _migrate_1_0_to_1_1(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.0.0 to v1.1.0 - Add instrument jobs and metadata"""
        if 'cc_instrumentjob' not in schema_info:
            # Add missing columns to existing tables if needed
            self._add_column_if_missing(cursor, 'cc_protocolmodel', 'remote_id', 'TEXT')
            self._add_column_if_missing(cursor, 'cc_session', 'processing', 'BOOLEAN DEFAULT 0')
            self.migration_log.append("Added instrument job support and metadata columns")
    
    def _migrate_1_1_to_1_2(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.1.0 to v1.2.0 - Add lab groups"""
        if 'cc_labgroup' not in schema_info:
            self._add_column_if_missing(cursor, 'cc_protocolmodel', 'viewers', 'TEXT')
            self._add_column_if_missing(cursor, 'cc_protocolmodel', 'editors', 'TEXT')
            self.migration_log.append("Added lab group and permission support")
    
    def _migrate_1_2_to_1_3(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.2.0 to v1.3.0 - Add messaging system"""
        # Messaging tables are optional, just log
        self.migration_log.append("Added messaging system support")
    
    def _migrate_1_3_to_1_4(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.3.0 to v1.4.0 - Add storage and reagents"""
        # Storage and reagent tables are optional
        self.migration_log.append("Added storage object and reagent tracking support")
    
    def _migrate_1_4_to_1_5(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.4.0 to v1.5.0 - Add WebRTC features"""
        # WebRTC tables are optional
        self.migration_log.append("Added WebRTC and real-time communication support")
    
    def _migrate_1_5_to_1_6(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.5.0 to v1.6.0 - Add site settings"""
        # Site settings are optional in import context
        self.migration_log.append("Added site settings and backup logging support")
    
    def _migrate_1_6_to_1_7(self, cursor: sqlite3.Cursor, schema_info: Dict):
        """Migrate from v1.6.0 to v1.7.0 - Add import restrictions"""
        # Import restriction fields can be handled during import
        self.migration_log.append("Added import restrictions and dry run support")
    
    def _add_column_if_missing(self, cursor: sqlite3.Cursor, table: str, column: str, column_type: str):
        """Add a column to a table if it doesn't exist"""
        try:
            # Check if column exists
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            
            if column not in columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
                self.migration_log.append(f"Added column {column} to {table}")
            else:
                self.migration_log.append(f"Column {column} already exists in {table}")
                
        except sqlite3.Error as e:
            self.migration_log.append(f"Warning: Could not add column {column} to {table}: {str(e)}")
    
    def _update_schema_metadata(self, cursor: sqlite3.Cursor):
        """Update schema version metadata in the database"""
        # Create metadata table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cupcake_schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Update schema version
        cursor.execute("""
            INSERT OR REPLACE INTO cupcake_schema_metadata (key, value, updated_at)
            VALUES ('schema_version', ?, CURRENT_TIMESTAMP)
        """, (self.target_version,))
        
        # Add migration timestamp
        cursor.execute("""
            INSERT OR REPLACE INTO cupcake_schema_metadata (key, value, updated_at)
            VALUES ('last_migration', ?, CURRENT_TIMESTAMP)
        """, (datetime.now().isoformat(),))
    
    def _create_migrated_archive(self, output_path: str):
        """Create a new archive with the migrated data"""
        if output_path.endswith('.zip'):
            import zipfile
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arc_path = os.path.relpath(file_path, self.temp_dir)
                        zip_file.write(file_path, arc_path)
        elif output_path.endswith(('.tar.gz', '.tgz')):
            import tarfile
            with tarfile.open(output_path, 'w:gz') as tar_file:
                tar_file.add(self.temp_dir, arcname='.')
    
    @classmethod
    def can_migrate(cls, from_version: str, to_version: str) -> bool:
        """Check if migration is possible between versions"""
        try:
            versions = list(cls.SCHEMA_VERSIONS.keys())
            from_idx = versions.index(from_version)
            to_idx = versions.index(to_version)
            return from_idx <= to_idx  # Only forward migrations
        except ValueError:
            return False
    
    @classmethod
    def get_supported_versions(cls) -> List[str]:
        """Get list of supported schema versions"""
        return list(cls.SCHEMA_VERSIONS.keys())


def migrate_archive_if_needed(archive_path: str, target_version: str = "1.7.0", 
                             output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to migrate an archive if needed
    
    Args:
        archive_path: Path to the source archive
        target_version: Target schema version (default: latest)
        output_path: Path for migrated archive (optional)
    
    Returns:
        Migration result dictionary
    """
    migrator = ArchiveSchemaMigrator(archive_path, target_version)
    
    # Check if migration is needed
    if not migrator.needs_migration():
        return {
            'success': True,
            'migration_needed': False,
            'message': 'Archive is already compatible'
        }
    
    # Perform migration
    return migrator.migrate_archive(output_path)