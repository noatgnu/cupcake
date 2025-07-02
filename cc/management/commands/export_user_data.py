"""
Django management command to export all user data to SQLite with media files
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from cc.utils.user_data_export_revised import export_user_data_revised
import os


class Command(BaseCommand):
    help = '''Export comprehensive user data to portable SQLite archive.
    
    This command exports ALL user-related data including:
    - Projects, protocols, sessions, and annotations
    - Lab group memberships and permissions  
    - Instrument access and usage records
    - Reagent inventory and transactions
    - Metadata, tags, and custom configurations
    - Message threads and document permissions
    - WebRTC sessions and collaboration data
    - Presets, templates, and vocabulary data
    - All associated media files and attachments
    
    The export creates a ZIP archive containing a SQLite database and media files
    that can be imported into another CUPCAKE LIMS instance for user migration.'''

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help='Username of the user whose data should be exported'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            help='Directory to save the export archive (default: current directory)',
            default='.'
        )
        parser.add_argument(
            '--filename',
            type=str,
            help='Custom filename for the export archive (default: auto-generated)',
            default=None
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Display detailed export progress and statistics'
        )
        parser.add_argument(
            '--include-shared',
            action='store_true',
            help='Include data shared with the user (default: only owned data)',
            default=False
        )

    def handle(self, *args, **options):
        username = options['username']
        output_dir = options['output_dir']
        custom_filename = options['filename']
        verbose = options['verbose']
        include_shared = options['include_shared']

        try:
            # Get the user
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist.')

        self.stdout.write(f'Starting comprehensive export for user: {username}')
        
        if verbose:
            self.stdout.write(f'User details:')
            self.stdout.write(f'  - ID: {user.id}')
            self.stdout.write(f'  - Email: {user.email}')
            self.stdout.write(f'  - Joined: {user.date_joined}')
            self.stdout.write(f'  - Active: {user.is_active}')
            self.stdout.write(f'Include shared data: {include_shared}')

        try:
            # Create export directory if needed
            if output_dir != '.':
                os.makedirs(output_dir, exist_ok=True)

            # Perform the comprehensive export
            if verbose:
                self.stdout.write('Initializing comprehensive export utility...')
            
            export_archive_path = export_user_data_revised(user)
            
            # Move to desired location with custom filename if specified
            if custom_filename or output_dir != '.':
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                final_filename = custom_filename or f'{username}_comprehensive_export_{timestamp}.zip'
                final_path = os.path.join(output_dir, final_filename)
                
                # Move the file
                import shutil
                shutil.move(export_archive_path, final_path)
                export_archive_path = final_path

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully exported comprehensive user data for "{username}"'
                )
            )
            self.stdout.write(f'Export location: {export_archive_path}')

            # Display detailed statistics
            file_size = os.path.getsize(export_archive_path)
            file_size_mb = file_size / (1024 * 1024)
            self.stdout.write(f'Archive size: {file_size_mb:.2f} MB')

            if verbose:
                self.stdout.write('\nExport includes:')
                self.stdout.write('  ✓ User profile and preferences')
                self.stdout.write('  ✓ Projects and protocols (with all steps, sections, ratings)')
                self.stdout.write('  ✓ Sessions and execution history')
                self.stdout.write('  ✓ Annotations and media files')
                self.stdout.write('  ✓ Lab group memberships and permissions')
                self.stdout.write('  ✓ Instrument access and usage records')
                self.stdout.write('  ✓ Reagent inventory and transactions')
                self.stdout.write('  ✓ Metadata and custom configurations')
                self.stdout.write('  ✓ Tags and organizational data')
                self.stdout.write('  ✓ Message threads and communications')
                self.stdout.write('  ✓ Document sharing permissions')
                self.stdout.write('  ✓ WebRTC collaboration sessions')
                self.stdout.write('  ✓ Presets and templates')
                self.stdout.write('  ✓ Vocabulary and reference data')
                self.stdout.write('  ✓ All media files and attachments')
                
                self.stdout.write(f'\nData format: SQLite database with media files')
                self.stdout.write(f'Export format version: 3.0 (revised comprehensive with accurate field mapping)')
                self.stdout.write(f'Compatible with: CUPCAKE LIMS v1.0+')

            # Provide usage instructions
            self.stdout.write(f'\nUsage instructions:')
            self.stdout.write(f'To import this data to another CUPCAKE instance, use:')
            self.stdout.write(f'  python manage.py import_user_data <target_username> {export_archive_path}')

        except Exception as e:
            import traceback
            if verbose:
                self.stdout.write(self.style.ERROR('Full error traceback:'))
                self.stdout.write(traceback.format_exc())
            raise CommandError(f'Comprehensive export failed: {str(e)}')