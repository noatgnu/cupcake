"""
Django management command to revert user data imports
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from cc.utils.user_data_import_revised import revert_user_data_import, list_user_imports
from cc.models import ImportTracker


class Command(BaseCommand):
    help = 'Revert a user data import by import ID'

    def add_arguments(self, parser):
        parser.add_argument(
            'import_id',
            type=str,
            nargs='?',
            help='UUID of the import to revert'
        )
        parser.add_argument(
            '--reverting-user',
            type=str,
            help='Username of the user performing the revert (defaults to the import owner)'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all imports instead of reverting'
        )
        parser.add_argument(
            '--list-user',
            type=str,
            help='Username to list imports for (used with --list)'
        )
        parser.add_argument(
            '--include-reverted',
            action='store_true',
            help='Include reverted imports in the list (used with --list)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reverted without actually reverting'
        )

    def handle(self, *args, **options):
        if options['list']:
            return self._handle_list(options)
        else:
            return self._handle_revert(options)

    def _handle_list(self, options):
        """Handle listing imports"""
        list_user_str = options.get('list_user')
        include_reverted = options.get('include_reverted', False)
        
        if list_user_str:
            try:
                list_user = User.objects.get(username=list_user_str)
            except User.DoesNotExist:
                raise CommandError(f'User "{list_user_str}" does not exist')
        else:
            # List all imports
            self.stdout.write('Listing all imports in the system...')
            trackers = ImportTracker.objects.all()
            if not include_reverted:
                trackers = trackers.exclude(import_status='reverted')
            
            self._display_imports_table(trackers)
            return

        # List imports for specific user
        imports = list_user_imports(list_user, include_reverted)
        
        if not imports:
            self.stdout.write(f'No imports found for user "{list_user.username}"')
            return
        
        self.stdout.write(f'Imports for user "{list_user.username}":')
        self.stdout.write('='*80)
        
        for imp in imports:
            self.stdout.write(f'Import ID: {imp["import_id"]}')
            self.stdout.write(f'  Status: {imp["import_status"]}')
            self.stdout.write(f'  Started: {imp["import_started_at"]}')
            if imp["import_completed_at"]:
                self.stdout.write(f'  Completed: {imp["import_completed_at"]}')
            self.stdout.write(f'  Archive Size: {imp["archive_size_mb"]} MB')
            self.stdout.write(f'  Objects Created: {imp["total_objects_created"]}')
            self.stdout.write(f'  Files Imported: {imp["total_files_imported"]}')
            self.stdout.write(f'  Relationships: {imp["total_relationships_created"]}')
            self.stdout.write(f'  Can Revert: {imp["can_revert"]}')
            if imp["reverted_at"]:
                self.stdout.write(f'  Reverted: {imp["reverted_at"]} by {imp["reverted_by"]}')
            self.stdout.write('')

    def _display_imports_table(self, trackers):
        """Display imports in a table format"""
        self.stdout.write('Import Tracking Summary:')
        self.stdout.write('='*120)
        self.stdout.write(f'{"Import ID":<36} {"User":<15} {"Status":<10} {"Objects":<8} {"Files":<6} {"Size (MB)":<10} {"Started":<20}')
        self.stdout.write('-'*120)
        
        for tracker in trackers.order_by('-import_started_at'):
            self.stdout.write(
                f'{str(tracker.import_id):<36} '
                f'{tracker.user.username:<15} '
                f'{tracker.import_status:<10} '
                f'{tracker.total_objects_created:<8} '
                f'{tracker.total_files_imported:<6} '
                f'{tracker.archive_size_mb or 0:<10.1f} '
                f'{tracker.import_started_at.strftime("%Y-%m-%d %H:%M"):<20}'
            )

    def _handle_revert(self, options):
        """Handle reverting an import"""
        import_id = options['import_id']
        if not import_id:
            raise CommandError('import_id is required when not using --list')
            
        reverting_user_str = options.get('reverting_user')
        dry_run = options.get('dry_run', False)
        
        # Get the import tracker
        try:
            import_tracker = ImportTracker.objects.get(import_id=import_id)
        except ImportTracker.DoesNotExist:
            raise CommandError(f'Import with ID {import_id} not found')
        
        # Determine reverting user
        if reverting_user_str:
            try:
                reverting_user = User.objects.get(username=reverting_user_str)
            except User.DoesNotExist:
                raise CommandError(f'User "{reverting_user_str}" does not exist')
        else:
            reverting_user = import_tracker.user
        
        # Check permissions
        if not (reverting_user.is_staff or reverting_user == import_tracker.user):
            raise CommandError('Insufficient permissions to revert this import')
        
        # Display import information
        self.stdout.write('Import Information:')
        self.stdout.write('='*60)
        self.stdout.write(f'Import ID: {import_tracker.import_id}')
        self.stdout.write(f'User: {import_tracker.user.username}')
        self.stdout.write(f'Status: {import_tracker.import_status}')
        self.stdout.write(f'Started: {import_tracker.import_started_at}')
        if import_tracker.import_completed_at:
            self.stdout.write(f'Completed: {import_tracker.import_completed_at}')
        self.stdout.write(f'Archive: {import_tracker.archive_path}')
        self.stdout.write(f'Archive Size: {import_tracker.archive_size_mb} MB')
        self.stdout.write(f'Objects Created: {import_tracker.total_objects_created}')
        self.stdout.write(f'Files Imported: {import_tracker.total_files_imported}')
        self.stdout.write(f'Relationships: {import_tracker.total_relationships_created}')
        self.stdout.write(f'Can Revert: {import_tracker.can_revert}')
        
        # Check if already reverted
        if import_tracker.import_status == 'reverted':
            self.stdout.write(self.style.ERROR('❌ This import has already been reverted'))
            if import_tracker.reverted_at:
                self.stdout.write(f'Reverted at: {import_tracker.reverted_at}')
            if import_tracker.reverted_by:
                self.stdout.write(f'Reverted by: {import_tracker.reverted_by.username}')
            return
        
        # Check if can revert
        if not import_tracker.can_revert:
            reason = import_tracker.revert_reason or "Unknown reason"
            self.stdout.write(self.style.ERROR(f'❌ Cannot revert this import: {reason}'))
            return
        
        if dry_run:
            self.stdout.write('\n' + '='*60)
            self.stdout.write('DRY RUN - What would be reverted:')
            self.stdout.write('='*60)
            
            # Show what would be deleted
            objects = import_tracker.imported_objects.all()
            files = import_tracker.imported_files.all()
            relationships = import_tracker.imported_relationships.all()
            
            self.stdout.write(f'Objects to delete: {objects.count()}')
            for obj in objects.order_by('model_name', 'object_id')[:10]:
                self.stdout.write(f'  - {obj.model_name}(id={obj.object_id})')
            if objects.count() > 10:
                self.stdout.write(f'  ... and {objects.count() - 10} more objects')
            
            self.stdout.write(f'\nFiles to delete: {files.count()}')
            for file_obj in files[:5]:
                self.stdout.write(f'  - {file_obj.file_path}')
            if files.count() > 5:
                self.stdout.write(f'  ... and {files.count() - 5} more files')
            
            self.stdout.write(f'\nRelationships to remove: {relationships.count()}')
            for rel in relationships[:5]:
                self.stdout.write(f'  - {rel.from_model}({rel.from_object_id}) -> {rel.to_model}({rel.to_object_id})')
            if relationships.count() > 5:
                self.stdout.write(f'  ... and {relationships.count() - 5} more relationships')
            
            self.stdout.write('\nDry run completed. Use the command without --dry-run to perform the actual revert.')
            return
        
        # Confirm revert
        self.stdout.write('\n' + '='*60)
        self.stdout.write('REVERT CONFIRMATION')
        self.stdout.write('='*60)
        self.stdout.write(self.style.WARNING('⚠️  This will permanently delete all data created during this import!'))
        self.stdout.write(f'Objects to delete: {import_tracker.total_objects_created}')
        self.stdout.write(f'Files to delete: {import_tracker.total_files_imported}')
        self.stdout.write(f'Relationships to remove: {import_tracker.total_relationships_created}')
        
        # Get user confirmation
        while True:
            try:
                response = input('\nAre you sure you want to revert this import? [y/N]: ').strip().lower()
                if response in ['y', 'yes']:
                    break
                elif response in ['n', 'no', '']:
                    self.stdout.write('Revert cancelled.')
                    return
                else:
                    self.stdout.write('Please enter y/yes or n/no')
            except KeyboardInterrupt:
                self.stdout.write('\nRevert cancelled by user.')
                return
        
        # Perform the revert
        self.stdout.write('\n' + '='*60)
        self.stdout.write('REVERTING IMPORT')
        self.stdout.write('='*60)
        
        result = revert_user_data_import(import_id, reverting_user)
        
        if result['success']:
            self.stdout.write(self.style.SUCCESS('✅ Import reverted successfully!'))
            self.stdout.write('\nRevert Statistics:')
            stats = result['stats']
            self.stdout.write(f'  Objects deleted: {stats["objects_deleted"]}')
            self.stdout.write(f'  Files deleted: {stats["files_deleted"]}')
            self.stdout.write(f'  Relationships removed: {stats["relationships_removed"]}')
            
            if stats['errors']:
                self.stdout.write(f'\nWarnings/Errors: {len(stats["errors"])}')
                for error in stats['errors'][:5]:
                    self.stdout.write(f'  - {error}')
                if len(stats['errors']) > 5:
                    self.stdout.write(f'  ... and {len(stats["errors"]) - 5} more errors')
        else:
            self.stdout.write(self.style.ERROR(f'❌ Revert failed: {result["error"]}'))
            if 'stats' in result and result['stats']['errors']:
                self.stdout.write('\nErrors:')
                for error in result['stats']['errors']:
                    self.stdout.write(f'  - {error}')