"""
Management command for pushing local data to remote CUPCAKE instances
"""

import sys
from datetime import datetime, timezone
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from cc.models import RemoteHost
from cc.services.sync_service import SyncService, SyncError
from cc.utils.sync_auth import SyncAuthError


class Command(BaseCommand):
    help = 'Push local data to a remote CUPCAKE instance'
    
    def add_arguments(self, parser):
        # Required arguments
        parser.add_argument(
            'remote_host_id',
            type=int,
            help='ID of the RemoteHost to push data to'
        )
        parser.add_argument(
            'user_id',
            type=int,
            help='ID of the user whose data should be pushed'
        )
        
        # Optional arguments
        parser.add_argument(
            '--models',
            nargs='+',
            help='Specific models to push (e.g., protocol project stored_reagent)',
            default=None
        )
        parser.add_argument(
            '--modified-since',
            help='Only push objects modified since this datetime (ISO format: YYYY-MM-DDTHH:MM:SS[Z])',
            default=None
        )
        parser.add_argument(
            '--conflict-strategy',
            choices=['timestamp', 'force_push', 'skip'],
            default='timestamp',
            help='Strategy for handling conflicts (default: timestamp)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of objects per model (for testing)',
            default=None
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output'
        )
        parser.add_argument(
            '--test-auth',
            action='store_true',
            help='Only test authentication, do not push data'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be pushed without actually pushing (future feature)'
        )
    
    def handle(self, *args, **options):
        # Validate arguments
        try:
            remote_host = RemoteHost.objects.get(id=options['remote_host_id'])
        except RemoteHost.DoesNotExist:
            raise CommandError(f"RemoteHost with ID {options['remote_host_id']} not found")
        
        try:
            user = User.objects.get(id=options['user_id'])
        except User.DoesNotExist:
            raise CommandError(f"User with ID {options['user_id']} not found")
        
        # Parse modified_since if provided
        modified_since = None
        if options['modified_since']:
            try:
                modified_since = datetime.fromisoformat(
                    options['modified_since'].replace('Z', '+00:00')
                )
            except (ValueError, TypeError):
                raise CommandError(
                    'Invalid modified_since format. Use ISO format: YYYY-MM-DDTHH:MM:SS[Z]'
                )
        
        # Validate models if specified
        if options['models']:
            from cc.services.sync_service import SyncService
            valid_models = set(SyncService.SYNCABLE_MODELS.keys())
            invalid_models = set(options['models']) - valid_models
            if invalid_models:
                raise CommandError(
                    f"Invalid model(s): {', '.join(invalid_models)}. "
                    f"Valid models: {', '.join(sorted(valid_models))}"
                )
        
        # Show configuration
        if options['verbose']:
            self.stdout.write("=== CUPCAKE Sync Push Configuration ===")
            self.stdout.write(f"Remote Host: {remote_host.host_name} (ID: {remote_host.id})")
            self.stdout.write(f"Remote URL: {remote_host.host_protocol}://{remote_host.host_name}:{remote_host.host_port}")
            self.stdout.write(f"User: {user.username} (ID: {user.id})")
            self.stdout.write(f"Models: {options['models'] or 'all'}")
            self.stdout.write(f"Modified since: {options['modified_since'] or 'any time'}")
            self.stdout.write(f"Conflict strategy: {options['conflict_strategy']}")
            self.stdout.write(f"Limit per model: {options['limit'] or 'no limit'}")
            if options['test_auth']:
                self.stdout.write("Mode: Authentication test only")
            elif options['dry_run']:
                self.stdout.write("Mode: Dry run (not implemented yet)")
            else:
                self.stdout.write("Mode: Full push")
            self.stdout.write("")
        
        # Perform sync operation
        try:
            with SyncService(remote_host, user) as sync_service:
                if options['test_auth']:
                    # Test authentication only
                    if options['verbose']:
                        self.stdout.write("Testing authentication...")
                    
                    auth_result = sync_service.authenticate()
                    if auth_result['success']:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ Authentication successful with {remote_host.host_name}"
                            )
                        )
                        if options['verbose']:
                            self.stdout.write(f"  Message: {auth_result['message']}")
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"✗ Authentication failed with {remote_host.host_name}"
                            )
                        )
                        if options['verbose']:
                            self.stdout.write(f"  Message: {auth_result['message']}")
                        sys.exit(1)
                
                elif options['dry_run']:
                    # Dry run mode (not implemented yet)
                    self.stdout.write(
                        self.style.WARNING("Dry run mode not implemented yet")
                    )
                    sys.exit(1)
                
                else:
                    # Full push
                    if options['verbose']:
                        self.stdout.write("Starting push operation...")
                    
                    results = sync_service.push_local_changes(
                        models=options['models'],
                        modified_since=modified_since,
                        conflict_strategy=options['conflict_strategy'],
                        limit_per_model=options['limit']
                    )
                    
                    # Display results
                    self._display_results(results, options['verbose'])
                    
                    # Set exit code based on success
                    if not results['success']:
                        sys.exit(1)
        
        except SyncAuthError as e:
            self.stdout.write(
                self.style.ERROR(f"Authentication error: {e}")
            )
            sys.exit(1)
        
        except SyncError as e:
            self.stdout.write(
                self.style.ERROR(f"Sync error: {e}")
            )
            sys.exit(1)
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Unexpected error: {e}")
            )
            if options['verbose']:
                import traceback
                self.stdout.write(traceback.format_exc())
            sys.exit(1)
    
    def _display_results(self, results, verbose=False):
        """Display push results in a formatted way"""
        
        if results['success']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Push completed successfully to {results['remote_host']}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠ Push completed with errors to {results['remote_host']}"
                )
            )
        
        # Summary
        summary = results['summary']
        self.stdout.write(f"\n=== Push Summary ===")
        self.stdout.write(f"Created: {summary['total_pushed']}")
        self.stdout.write(f"Updated: {summary['total_updated']}")
        self.stdout.write(f"Skipped: {summary['total_skipped']}")
        self.stdout.write(f"Conflicts: {summary['total_conflicts']}")
        self.stdout.write(f"Errors: {summary['total_errors']}")
        
        # Model-by-model results
        if verbose and 'models' in results:
            self.stdout.write(f"\n=== Model Results ===")
            for model_name, model_result in results['models'].items():
                if 'error' in model_result:
                    self.stdout.write(
                        f"  {model_name}: " + 
                        self.style.ERROR(f"ERROR - {model_result['error']}")
                    )
                elif 'message' in model_result:
                    self.stdout.write(f"  {model_name}: {model_result['message']}")
                else:
                    pushed = model_result.get('pushed_count', 0)
                    updated = model_result.get('updated_count', 0)
                    skipped = model_result.get('skipped_count', 0)
                    conflicts = len(model_result.get('conflicts', []))
                    errors = len(model_result.get('errors', []))
                    
                    status_parts = []
                    if pushed > 0:
                        status_parts.append(f"{pushed} created")
                    if updated > 0:
                        status_parts.append(f"{updated} updated")
                    if skipped > 0:
                        status_parts.append(f"{skipped} skipped")
                    if conflicts > 0:
                        status_parts.append(self.style.WARNING(f"{conflicts} conflicts"))
                    if errors > 0:
                        status_parts.append(self.style.ERROR(f"{errors} errors"))
                    
                    if not status_parts:
                        status_parts.append("no changes")
                    
                    self.stdout.write(f"  {model_name}: {', '.join(status_parts)}")
        
        # Conflicts detail
        if verbose and 'models' in results:
            all_conflicts = []
            for model_name, model_result in results['models'].items():
                if 'conflicts' in model_result:
                    for conflict in model_result['conflicts']:
                        conflict['model'] = model_name
                        all_conflicts.append(conflict)
            
            if all_conflicts:
                self.stdout.write(f"\n=== Conflicts Detail ===")
                for conflict in all_conflicts:
                    self.stdout.write(
                        f"  {conflict['model']} (local:{conflict['local_id']} -> "
                        f"remote:{conflict['remote_id']}): {conflict.get('reason', 'conflict detected')}"
                    )
        
        # Errors detail
        if verbose and 'models' in results:
            all_errors = []
            for model_name, model_result in results['models'].items():
                if 'errors' in model_result:
                    for error in model_result['errors']:
                        all_errors.append(f"{model_name}: {error}")
            
            if all_errors:
                self.stdout.write(f"\n=== Errors Detail ===")
                for error in all_errors:
                    self.stdout.write(f"  {self.style.ERROR(error)}")