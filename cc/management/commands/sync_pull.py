"""
Management command for pulling data from remote CUPCAKE instances
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction

from cc.models import RemoteHost
from cc.services.sync_service import SyncService, SyncError
from cc.utils.sync_auth import SyncAuthError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Pull data from a remote CUPCAKE instance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'remote_host_id',
            type=int,
            help='ID of the RemoteHost to sync from'
        )
        
        parser.add_argument(
            'user_id',
            type=int,
            help='ID of the user who will own imported objects'
        )
        
        parser.add_argument(
            '--models',
            nargs='+',
            help='Specific models to sync (default: all supported models)',
            choices=['protocol', 'protocol_step', 'protocol_section', 'project', 
                    'annotation', 'annotation_folder', 'stored_reagent', 
                    'storage_object', 'tag', 'instrument', 'session']
        )
        
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of objects per model (for testing)',
            default=None
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without actually importing'
        )
        
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output'
        )
        
        parser.add_argument(
            '--test-auth',
            action='store_true',
            help='Test authentication only, don\'t sync data'
        )
    
    def handle(self, *args, **options):
        # Configure logging
        if options['verbose']:
            logging.basicConfig(level=logging.DEBUG)
        
        # Get remote host
        try:
            remote_host = RemoteHost.objects.get(id=options['remote_host_id'])
        except RemoteHost.DoesNotExist:
            raise CommandError(f"RemoteHost with ID {options['remote_host_id']} does not exist")
        
        # Get user
        try:
            user = User.objects.get(id=options['user_id'])
        except User.DoesNotExist:
            raise CommandError(f"User with ID {options['user_id']} does not exist")
        
        self.stdout.write(
            self.style.SUCCESS(f"Starting sync from {remote_host.host_name} for user {user.username}")
        )
        
        try:
            with SyncService(remote_host, user) as sync_service:
                # Test authentication first
                self.stdout.write("Testing authentication...")
                auth_result = sync_service.authenticate()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Authentication successful: {auth_result['message']}")
                )
                
                # If only testing auth, stop here
                if options['test_auth']:
                    self.stdout.write(self.style.SUCCESS("Authentication test completed successfully"))
                    return
                
                # Perform sync
                models_to_sync = options.get('models', None)
                limit_per_model = options.get('limit', None)
                
                if options['dry_run']:
                    self.stdout.write(self.style.WARNING("DRY RUN MODE - No data will be imported"))
                    # TODO: Implement dry run functionality
                    self.stdout.write("Dry run functionality will be implemented in a future update")
                    return
                
                self.stdout.write("Starting data synchronization...")
                
                # Perform the sync
                results = sync_service.pull_all_data(
                    models=models_to_sync,
                    limit_per_model=limit_per_model
                )
                
                # Display results
                self._display_results(results)
                
                if results['success']:
                    self.stdout.write(
                        self.style.SUCCESS(f"Sync completed successfully from {remote_host.host_name}")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR('Sync completed with errors. See details above.')
                    )
                    
        except SyncAuthError as e:
            raise CommandError(f"Authentication failed: {e}")
        except SyncError as e:
            raise CommandError(f"Sync failed: {e}")
        except Exception as e:
            raise CommandError(f"Unexpected error: {e}")
    
    def _display_results(self, results):
        """Display sync results in formatted output"""
        
        self.stdout.write("\n" + "="*60)
        self.stdout.write(f"SYNC RESULTS FROM {results['remote_host']}")
        self.stdout.write("="*60)
        
        # Summary
        summary = results['summary']
        self.stdout.write(f"📊 SUMMARY:")
        self.stdout.write(f"  • Objects Pulled: {summary['total_pulled']}")
        self.stdout.write(f"  • Objects Updated: {summary['total_updated']}")
        self.stdout.write(f"  • Objects Skipped: {summary['total_skipped']}")
        self.stdout.write(f"  • Errors: {summary['total_errors']}")
        
        # Model-by-model results
        self.stdout.write(f"\n📋 DETAILS BY MODEL:")
        for model_name, model_results in results['models'].items():
            if 'error' in model_results:
                self.stdout.write(
                    f"  ❌ {model_name}: {model_results['error']}"
                )
            elif 'import_result' in model_results:
                import_result = model_results['import_result']
                if 'message' in import_result:
                    self.stdout.write(f"  ⚪ {model_name}: {import_result['message']}")
                else:
                    self.stdout.write(
                        f"  ✅ {model_name}: "
                        f"{import_result.get('imported_count', 0)} new, "
                        f"{import_result.get('updated_count', 0)} updated, "
                        f"{import_result.get('skipped_count', 0)} skipped"
                    )
        
        # Errors
        if results['sync_stats']['errors']:
            self.stdout.write(f"\n❌ ERRORS:")
            for error in results['sync_stats']['errors']:
                self.stdout.write(f"  • {error}")
        
        # Recommendations
        self.stdout.write(f"\n💡 NEXT STEPS:")
        self.stdout.write(f"  • Check vaulted data with: include_vaulted=true in API calls")
        self.stdout.write(f"  • Use frontend vaulting toggles to view synced data")
        self.stdout.write(f"  • Monitor sync status via: /api/remote_hosts/{results.get('remote_host_id', 'ID')}/sync-status/")
        
        self.stdout.write("\n" + "="*60 + "\n")