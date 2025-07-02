"""
Django management command to migrate SQLite export archives between schema versions
"""
from django.core.management.base import BaseCommand, CommandError
from cc.utils.archive_schema_migrator import ArchiveSchemaMigrator, migrate_archive_if_needed
import os


class Command(BaseCommand):
    help = 'Migrate SQLite export archive to compatible schema version'

    def add_arguments(self, parser):
        parser.add_argument(
            'archive_path',
            type=str,
            help='Path to the export archive (ZIP or TAR.GZ)'
        )
        parser.add_argument(
            '--output',
            type=str,
            help='Path for the migrated archive (default: adds _migrated to original name)'
        )
        parser.add_argument(
            '--target-version',
            type=str,
            default='1.7.0',
            help='Target schema version (default: 1.7.0 - latest)'
        )
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Only check if migration is needed without performing it'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force migration even if versions appear compatible'
        )

    def handle(self, *args, **options):
        archive_path = options['archive_path']
        output_path = options.get('output')
        target_version = options['target_version']
        check_only = options['check_only']
        force = options['force']

        # Validate archive path
        if not os.path.exists(archive_path):
            raise CommandError(f'Archive file does not exist: {archive_path}')

        # Validate archive format
        if not (archive_path.endswith('.zip') or archive_path.endswith(('.tar.gz', '.tgz'))):
            raise CommandError('Archive must be ZIP or TAR.GZ format')

        # Generate output path if not provided
        if not output_path and not check_only:
            base, ext = os.path.splitext(archive_path)
            if ext == '.gz':
                base, ext2 = os.path.splitext(base)
                ext = ext2 + ext
            output_path = f"{base}_migrated{ext}"

        self.stdout.write(f'Analyzing archive: {archive_path}')
        self.stdout.write(f'Target version: {target_version}')

        try:
            # Create migrator instance
            migrator = ArchiveSchemaMigrator(archive_path, target_version)
            
            # Extract archive temporarily to analyze
            import tempfile
            migrator.temp_dir = tempfile.mkdtemp(prefix='cupcake_analysis_')
            
            try:
                # Extract archive for analysis
                if archive_path.endswith('.zip'):
                    import zipfile
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extractall(migrator.temp_dir)
                else:
                    import tarfile
                    with tarfile.open(archive_path, 'r:gz') as tar_ref:
                        tar_ref.extractall(migrator.temp_dir)
                
                # Find SQLite database
                migrator.sqlite_path = migrator._find_sqlite_db()
                if not migrator.sqlite_path:
                    raise CommandError("No SQLite database found in archive")
                
                # Detect current version
                current_version, schema_info = migrator.detect_schema_version()
                
                self.stdout.write('\n' + '='*60)
                self.stdout.write('SCHEMA ANALYSIS')
                self.stdout.write('='*60)
                self.stdout.write(f'Current schema version: {current_version}')
                self.stdout.write(f'Target schema version: {target_version}')
                
                if current_version == "unknown":
                    self.stdout.write(
                        self.style.ERROR('❌ Cannot determine schema version of archive')
                    )
                    self.stdout.write('This archive may be from an unsupported version or corrupted.')
                    return
                
                # Show schema details
                self._display_schema_info(schema_info)
                
                # Check if migration is needed
                migration_needed = (current_version != target_version) or force
                
                if not migration_needed:
                    self.stdout.write(
                        self.style.SUCCESS('✅ Archive is already at target version - no migration needed')
                    )
                    return
                
                # Check if migration is possible
                if not ArchiveSchemaMigrator.can_migrate(current_version, target_version):
                    raise CommandError(
                        f'Migration from {current_version} to {target_version} is not supported'
                    )
                
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Migration needed: {current_version} → {target_version}')
                )
                
                if check_only:
                    self.stdout.write('\n--check-only flag set, stopping here.')
                    self.stdout.write(f'To migrate, run: python manage.py migrate_archive "{archive_path}" --output "{output_path}"')
                    return
                
                # Perform migration
                self.stdout.write('\n' + '='*60)
                self.stdout.write('PERFORMING MIGRATION')
                self.stdout.write('='*60)
                self.stdout.write(f'Output archive: {output_path}')
                
                result = migrator.migrate_archive(output_path)
                
                if result['success']:
                    self.stdout.write(
                        self.style.SUCCESS('✅ Migration completed successfully!')
                    )
                    
                    # Display migration log
                    if result.get('migration_log'):
                        self.stdout.write('\nMigration steps performed:')
                        for log_entry in result['migration_log']:
                            self.stdout.write(f'  • {log_entry}')
                    
                    # Verify output file
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path) / (1024 * 1024)
                        self.stdout.write(f'\nMigrated archive created: {output_path} ({file_size:.2f} MB)')
                        self.stdout.write('You can now use this migrated archive for import.')
                    
                else:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Migration failed: {result.get("error", "Unknown error")}')
                    )
                    
                    if result.get('migration_log'):
                        self.stdout.write('\nMigration log:')
                        for log_entry in result['migration_log']:
                            self.stdout.write(f'  • {log_entry}')
                    
                    raise CommandError('Migration failed')
            
            finally:
                # Cleanup temporary directory
                if migrator.temp_dir and os.path.exists(migrator.temp_dir):
                    import shutil
                    shutil.rmtree(migrator.temp_dir)

        except Exception as e:
            raise CommandError(f'Migration process failed: {str(e)}')

    def _display_schema_info(self, schema_info):
        """Display schema information in a readable format"""
        self.stdout.write('\nDatabase structure:')
        
        # Group tables by category
        table_categories = {
            'Core Protocol': [t for t in schema_info.keys() if 'protocol' in t.lower()],
            'Sessions & Execution': [t for t in schema_info.keys() if any(x in t.lower() for x in ['session', 'annotation', 'timekeeper'])],
            'Instruments': [t for t in schema_info.keys() if 'instrument' in t.lower()],
            'Reagents & Storage': [t for t in schema_info.keys() if any(x in t.lower() for x in ['reagent', 'storage'])],
            'Lab Management': [t for t in schema_info.keys() if any(x in t.lower() for x in ['labgroup', 'user', 'permission'])],
            'Communication': [t for t in schema_info.keys() if any(x in t.lower() for x in ['message', 'webrtc'])],
            'System': [t for t in schema_info.keys() if any(x in t.lower() for x in ['site', 'backup', 'metadata'])],
            'Other': []
        }
        
        # Assign uncategorized tables
        categorized = set()
        for category_tables in table_categories.values():
            categorized.update(category_tables)
        
        table_categories['Other'] = [t for t in schema_info.keys() if t not in categorized]
        
        # Display by category
        for category, tables in table_categories.items():
            if tables:
                self.stdout.write(f'\n  {category} Tables:')
                for table in sorted(tables):
                    column_count = len(schema_info[table]['columns'])
                    self.stdout.write(f'    • {table} ({column_count} columns)')
        
        total_tables = len(schema_info)
        self.stdout.write(f'\nTotal tables: {total_tables}')
        
        # Show supported versions
        self.stdout.write(f'\nSupported schema versions: {", ".join(ArchiveSchemaMigrator.get_supported_versions())}')