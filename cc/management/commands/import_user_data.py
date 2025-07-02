"""
Django management command to import user data from SQLite export archive
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from cc.utils.user_data_import_revised import import_user_data_revised, UserDataImportDryRun
from cc.utils.archive_schema_migrator import ArchiveSchemaMigrator, migrate_archive_if_needed
import os
import json
import tempfile
import shutil


class Command(BaseCommand):
    help = 'Import user data from SQLite export archive. Always performs dry run analysis first with confirmation prompt unless --dry-run-only is specified.'

    def add_arguments(self, parser):
        parser.add_argument(
            'target_username',
            type=str,
            help='Username of the target user to import data for'
        )
        parser.add_argument(
            'archive_path',
            type=str,
            help='Path to the export archive ZIP file'
        )
        parser.add_argument(
            '--merge-strategy',
            type=str,
            choices=['skip_existing', 'update_existing', 'fail_on_conflict'],
            default='skip_existing',
            help='Strategy for handling existing data (default: skip_existing)'
        )
        parser.add_argument(
            '--create-user',
            action='store_true',
            help='Create the target user if it does not exist'
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Email for the new user (required with --create-user)'
        )
        parser.add_argument(
            '--dry-run-only',
            action='store_true',
            help='Perform only dry run analysis without prompting for import'
        )
        parser.add_argument(
            '--no-interactive',
            action='store_true',
            help='Skip confirmation prompt and proceed directly with import after dry run'
        )
        parser.add_argument(
            '--import-options',
            type=str,
            help='JSON string with import options (e.g., \'{"protocols": true, "sessions": false}\')'
        )
        parser.add_argument(
            '--auto-migrate',
            action='store_true',
            help='Automatically migrate archive schema if needed'
        )
        parser.add_argument(
            '--skip-migration-check',
            action='store_true',
            help='Skip schema version compatibility check'
        )

    def handle(self, *args, **options):
        target_username = options['target_username']
        archive_path = options['archive_path']
        merge_strategy = options['merge_strategy']
        create_user = options['create_user']
        email = options['email']
        dry_run_only = options['dry_run_only']
        no_interactive = options['no_interactive']
        auto_migrate = options['auto_migrate']
        skip_migration_check = options['skip_migration_check']
        import_options_str = options.get('import_options')
        
        # Parse import options if provided
        import_options = None
        if import_options_str:
            try:
                import_options = json.loads(import_options_str)
            except json.JSONDecodeError:
                raise CommandError('Invalid JSON format for --import-options')

        # Validate archive path
        if not os.path.exists(archive_path):
            raise CommandError(f'Archive file does not exist: {archive_path}')
        
        # STEP 0: Check and migrate schema if needed (unless skipped)
        final_archive_path = archive_path
        migration_performed = False
        
        if not skip_migration_check:
            self.stdout.write(self.style.WARNING('STEP 0: CHECKING SCHEMA COMPATIBILITY'))
            
            try:
                # Check if migration is needed
                migrator = ArchiveSchemaMigrator(archive_path)
                
                # Quick version check (without full extraction)
                temp_dir = tempfile.mkdtemp(prefix='cupcake_version_check_')
                try:
                    # Extract just enough to check version
                    if archive_path.endswith('.zip'):
                        import zipfile
                        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                            zip_ref.extractall(temp_dir)
                    else:
                        import tarfile
                        with tarfile.open(archive_path, 'r:gz') as tar_ref:
                            tar_ref.extractall(temp_dir)
                    
                    # Find SQLite database
                    migrator.temp_dir = temp_dir
                    migrator.sqlite_path = migrator._find_sqlite_db()
                    
                    if migrator.sqlite_path:
                        current_version, _ = migrator.detect_schema_version()
                        target_version = "1.7.0"  # Current version
                        
                        self.stdout.write(f'Archive schema version: {current_version}')
                        self.stdout.write(f'Current system version: {target_version}')
                        
                        if current_version != target_version and current_version != "unknown":
                            if auto_migrate:
                                self.stdout.write(
                                    self.style.WARNING(f'⚠️  Schema migration needed: {current_version} → {target_version}')
                                )
                                self.stdout.write('Performing automatic migration...')
                                
                                # Create migrated archive
                                base, ext = os.path.splitext(archive_path)
                                if ext == '.gz':
                                    base, ext2 = os.path.splitext(base)
                                    ext = ext2 + ext
                                
                                migrated_path = f"{base}_migrated{ext}"
                                
                                migration_result = migrate_archive_if_needed(
                                    archive_path, target_version, migrated_path
                                )
                                
                                if migration_result['success']:
                                    final_archive_path = migrated_path
                                    migration_performed = True
                                    self.stdout.write(
                                        self.style.SUCCESS(f'✅ Schema migrated successfully to: {migrated_path}')
                                    )
                                else:
                                    raise CommandError(f'Schema migration failed: {migration_result.get("error", "Unknown error")}')
                            
                            else:
                                self.stdout.write(
                                    self.style.ERROR(f'❌ Schema incompatibility detected!')
                                )
                                self.stdout.write(f'Archive version: {current_version}')
                                self.stdout.write(f'Required version: {target_version}')
                                self.stdout.write('\nOptions:')
                                self.stdout.write('1. Add --auto-migrate to automatically migrate the archive')
                                self.stdout.write('2. Use: python manage.py migrate_archive "archive_path" to create a migrated version')
                                self.stdout.write('3. Add --skip-migration-check to skip this check (not recommended)')
                                raise CommandError('Schema migration required - use --auto-migrate or migrate_archive command')
                        
                        elif current_version == "unknown":
                            self.stdout.write(
                                self.style.WARNING('⚠️  Cannot determine archive schema version')
                            )
                            if not auto_migrate:
                                self.stdout.write('Proceeding anyway (use --skip-migration-check to skip this warning)')
                        
                        else:
                            self.stdout.write(
                                self.style.SUCCESS('✅ Schema version compatible')
                            )
                    
                finally:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                        
            except Exception as e:
                if auto_migrate:
                    raise CommandError(f'Schema migration failed: {str(e)}')
                else:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️  Schema check failed: {str(e)}')
                    )
                    self.stdout.write('Proceeding anyway (use --skip-migration-check to skip this check)')
        
        else:
            self.stdout.write(self.style.WARNING('Skipping schema compatibility check'))

        # Get or create target user (create temporary user for dry run analysis)
        try:
            target_user = User.objects.get(username=target_username)
            self.stdout.write(f'Target user found: {target_username}')
            user_exists = True
        except User.DoesNotExist:
            if create_user:
                if not email:
                    raise CommandError('Email is required when creating a new user')
                user_exists = False
                # For dry run, create a temporary user object (won't be saved)
                target_user = User(username=target_username, email=email)
            else:
                raise CommandError(
                    f'User "{target_username}" does not exist. Use --create-user to create it.'
                )

        # STEP 1: Always perform dry run analysis first
        self.stdout.write(self.style.WARNING('STEP 1: PERFORMING DRY RUN ANALYSIS'))
        self.stdout.write(f'Archive: {final_archive_path}')
        if migration_performed:
            self.stdout.write(f'Original archive: {archive_path}')
        if import_options:
            self.stdout.write(f'Import options: {import_options}')
        
        try:
            # Perform dry run analysis using the potentially migrated archive
            dry_runner = UserDataImportDryRun(target_user, final_archive_path, import_options)
            analysis_result = dry_runner.analyze_import()
            
            self.stdout.write(
                self.style.SUCCESS('Dry run analysis completed successfully!')
            )
            
            # Display analysis report
            self._display_dry_run_report(analysis_result)
            
            # Check if there are errors that would prevent import
            errors = analysis_result.get('errors', [])
            if errors:
                self.stdout.write(
                    self.style.ERROR('\n❌ Cannot proceed with import due to errors detected in dry run.')
                )
                return
            
            # If dry-run-only flag is set, stop here
            if dry_run_only:
                self.stdout.write(
                    self.style.SUCCESS('\n✅ Dry run analysis complete. Use the command without --dry-run-only to proceed with import.')
                )
                return
            
            # STEP 2: Ask for confirmation (unless no-interactive is set)
            proceed_with_import = False
            
            if no_interactive:
                proceed_with_import = True
                self.stdout.write(
                    self.style.WARNING('\n--no-interactive flag set, proceeding with import...')
                )
            else:
                # Interactive confirmation
                self.stdout.write('\n' + '='*60)
                self.stdout.write('CONFIRMATION REQUIRED')
                self.stdout.write('='*60)
                
                # Show summary of what will be imported
                filtered_summary = analysis_result.get('filtered_data_summary', {})
                conflicts = analysis_result.get('potential_conflicts', [])
                
                if filtered_summary:
                    self.stdout.write('The following data will be imported:')
                    for key, value in filtered_summary.items():
                        if value > 0:
                            self.stdout.write(f'  • {value} {key}')
                
                if conflicts and any(c['total_conflicts'] > 0 for c in conflicts):
                    self.stdout.write(self.style.WARNING('\n⚠️  Conflicts detected - existing data may be affected.'))
                
                self.stdout.write(f'\nTarget user: {target_username}')
                self.stdout.write(f'Merge strategy: {merge_strategy}')
                
                # Get user confirmation
                while True:
                    try:
                        response = input('\nDo you want to proceed with the import? [y/N]: ').strip().lower()
                        if response in ['y', 'yes']:
                            proceed_with_import = True
                            break
                        elif response in ['n', 'no', '']:
                            proceed_with_import = False
                            break
                        else:
                            self.stdout.write('Please enter y/yes or n/no')
                    except KeyboardInterrupt:
                        self.stdout.write('\nImport cancelled by user.')
                        return
            
            if not proceed_with_import:
                self.stdout.write(self.style.WARNING('\nImport cancelled by user.'))
                return
            
            # STEP 3: Create user if needed (now that we're actually importing)
            if not user_exists:
                self.stdout.write(f'\nCreating new user: {target_username}')
                target_user = User.objects.create_user(
                    username=target_username,
                    email=email,
                    password=User.objects.make_random_password()
                )
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Created new user: {target_username}')
                )
            
            # STEP 4: Perform the actual import with transaction rollback
            self.stdout.write('\n' + '='*60)
            self.stdout.write('STEP 2: PERFORMING IMPORT')
            self.stdout.write('='*60)
            self.stdout.write(f'Starting import for user: {target_username}')
            self.stdout.write(f'Merge strategy: {merge_strategy}')
            
            # Wrap the entire import in a transaction for rollback capability
            try:
                with transaction.atomic():
                    # Create a savepoint before import
                    savepoint = transaction.savepoint()
                    
                    try:
                        result = import_user_data_revised(target_user, final_archive_path)
                        
                        if result['success']:
                            # Commit the savepoint
                            transaction.savepoint_commit(savepoint)
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'\n✅ Successfully imported data for "{target_username}"'
                                )
                            )
                            
                            # Display statistics
                            stats = result['stats']
                            self.stdout.write('\nImport Statistics:')
                            for key, value in stats.items():
                                if key != 'errors':
                                    self.stdout.write(f'  {key}: {value}')
                            
                            if stats['errors']:
                                self.stdout.write(f'\nWarnings/Non-critical errors: {len(stats["errors"])}')
                                for error in stats['errors'][:5]:  # Show first 5 errors
                                    self.stdout.write(f'  - {error}')
                                
                                if len(stats['errors']) > 5:
                                    self.stdout.write(f'  ... and {len(stats["errors"]) - 5} more warnings')
                            
                            self.stdout.write(f'\nSource user: {result.get("source_user", "unknown")}')
                            
                        else:
                            # Rollback on failure
                            transaction.savepoint_rollback(savepoint)
                            
                            error_msg = result.get("error", "unknown error")
                            self.stdout.write(
                                self.style.ERROR(f'\n❌ Import failed: {error_msg}')
                            )
                            self.stdout.write(
                                self.style.WARNING('🔄 All changes have been rolled back.')
                            )
                            
                            # Show errors
                            if result.get('stats', {}).get('errors'):
                                self.stdout.write('\nErrors:')
                                for error in result['stats']['errors'][:10]:
                                    self.stdout.write(f'  - {error}')
                            
                            raise CommandError('Import failed - all changes have been rolled back')
                    
                    except Exception as import_error:
                        # Rollback on any exception during import
                        transaction.savepoint_rollback(savepoint)
                        self.stdout.write(
                            self.style.ERROR(f'\n❌ Import failed with exception: {str(import_error)}')
                        )
                        self.stdout.write(
                            self.style.WARNING('🔄 All changes have been rolled back.')
                        )
                        raise CommandError(f'Import failed - all changes have been rolled back: {str(import_error)}')
            
            except Exception as transaction_error:
                self.stdout.write(
                    self.style.ERROR(f'\n❌ Transaction failed: {str(transaction_error)}')
                )
                raise CommandError(f'Import transaction failed: {str(transaction_error)}')

        except Exception as e:
            if dry_run_only:
                raise CommandError(f'Dry run analysis failed: {str(e)}')
            else:
                raise CommandError(f'Import process failed: {str(e)}')
        
        finally:
            # Cleanup migrated archive if it was created
            if migration_performed and final_archive_path != archive_path:
                try:
                    if os.path.exists(final_archive_path):
                        os.remove(final_archive_path)
                        self.stdout.write(f'Cleaned up temporary migrated archive: {final_archive_path}')
                except Exception as cleanup_error:
                    self.stdout.write(
                        self.style.WARNING(f'Warning: Could not clean up migrated archive: {cleanup_error}')
                    )

    def _display_dry_run_report(self, analysis_result):
        """Display the dry run analysis report in a user-friendly format"""
        
        # Archive Information
        archive_info = analysis_result.get('archive_info', {})
        self.stdout.write('\n' + '='*60)
        self.stdout.write('ARCHIVE INFORMATION')
        self.stdout.write('='*60)
        self.stdout.write(f'File: {archive_info.get("file_path", "unknown")}')
        self.stdout.write(f'Size: {archive_info.get("file_size_mb", 0):.2f} MB')
        self.stdout.write(f'Format: {archive_info.get("format", "unknown")}')
        self.stdout.write(f'Contains Media: {"Yes" if archive_info.get("has_media", False) else "No"}')
        
        # Data Summary
        data_summary = analysis_result.get('data_summary', {})
        filtered_summary = analysis_result.get('filtered_data_summary', {})
        
        self.stdout.write('\n' + '='*60)
        self.stdout.write('DATA SUMMARY')
        self.stdout.write('='*60)
        self.stdout.write('Total records in archive:')
        for key, value in data_summary.items():
            self.stdout.write(f'  {key}: {value}')
        
        if filtered_summary:
            self.stdout.write('\nRecords that would be imported (after filtering):')
            for key, value in filtered_summary.items():
                self.stdout.write(f'  {key}: {value}')
        
        # Potential Conflicts
        conflicts = analysis_result.get('potential_conflicts', [])
        if conflicts:
            self.stdout.write('\n' + '='*60)
            self.stdout.write('POTENTIAL CONFLICTS')
            self.stdout.write('='*60)
            for conflict in conflicts:
                self.stdout.write(f'{conflict["type"]}: {conflict["total_conflicts"]} conflicts')
                self.stdout.write(f'  Description: {conflict["description"]}')
                if conflict['items']:
                    items_to_show = conflict['items'][:5]  # Show first 5
                    for item in items_to_show:
                        self.stdout.write(f'    - {item}')
                    if len(conflict['items']) > 5:
                        self.stdout.write(f'    ... and {len(conflict["items"]) - 5} more')
                self.stdout.write('')
        
        # Size Analysis
        size_analysis = analysis_result.get('size_analysis', {})
        if size_analysis:
            self.stdout.write('\n' + '='*60)
            self.stdout.write('SIZE ANALYSIS')
            self.stdout.write('='*60)
            self.stdout.write(f'Total media files: {size_analysis.get("total_media_files", 0)}')
            self.stdout.write(f'Total media size: {size_analysis.get("total_media_size_mb", 0):.2f} MB')
            
            large_files = size_analysis.get('large_files', [])
            if large_files:
                self.stdout.write('\nLarge files (>10MB):')
                for file_info in large_files[:10]:  # Show first 10
                    self.stdout.write(f'  {file_info["name"]}: {file_info["size_mb"]:.2f} MB')
        
        # Import Plan
        import_plan = analysis_result.get('import_plan', {})
        if import_plan:
            self.stdout.write('\n' + '='*60)
            self.stdout.write('IMPORT PLAN')
            self.stdout.write('='*60)
            
            execution_order = import_plan.get('execution_order', [])
            if execution_order:
                self.stdout.write('Execution order:')
                for i, step in enumerate(execution_order, 1):
                    self.stdout.write(f'  {i}. {step["step"]}: {step["estimated_records"]} records')
                    self.stdout.write(f'     {step["description"]}')
            
            self.stdout.write(f'\nEstimated duration: {import_plan.get("estimated_duration_minutes", 0)} minutes')
            self.stdout.write(f'Database operations: {import_plan.get("database_operations", 0)}')
            self.stdout.write(f'File operations: {import_plan.get("file_operations", 0)}')
        
        # Warnings
        warnings = analysis_result.get('warnings', [])
        if warnings:
            self.stdout.write('\n' + '='*60)
            self.stdout.write(self.style.WARNING('WARNINGS'))
            self.stdout.write('='*60)
            for warning in warnings:
                self.stdout.write(self.style.WARNING(f'  ⚠ {warning}'))
        
        # Errors
        errors = analysis_result.get('errors', [])
        if errors:
            self.stdout.write('\n' + '='*60)
            self.stdout.write(self.style.ERROR('ERRORS'))
            self.stdout.write('='*60)
            for error in errors:
                self.stdout.write(self.style.ERROR(f'  ✗ {error}'))
        
        # Summary recommendation
        self.stdout.write('\n' + '='*60)
        self.stdout.write('ANALYSIS SUMMARY')
        self.stdout.write('='*60)
        
        if errors:
            self.stdout.write(self.style.ERROR('❌ Import NOT possible due to critical errors. Please fix the issues above.'))
            self.stdout.write('   The import process will not proceed if these errors exist.')
        elif conflicts and any(c['total_conflicts'] > 0 for c in conflicts):
            self.stdout.write(self.style.WARNING('⚠️  Import ready but conflicts detected. Review conflicts carefully.'))
            self.stdout.write('   Conflicts will be handled according to the merge strategy.')
        elif warnings:
            self.stdout.write(self.style.WARNING('⚠️  Import ready with minor warnings. Review warnings above.'))
            self.stdout.write('   These warnings are informational and won\'t prevent import.')
        else:
            self.stdout.write(self.style.SUCCESS('✅ Import ready! No issues detected.'))
            self.stdout.write('   The archive appears to be clean and ready for import.')
