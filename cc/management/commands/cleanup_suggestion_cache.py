"""
Django management command to clean up expired SDRF suggestion cache.

Usage:
    python manage.py cleanup_suggestion_cache [--days-old 30]
"""

from django.core.management.base import BaseCommand
from cc.models import ProtocolStepSuggestionCache


class Command(BaseCommand):
    help = 'Clean up expired SDRF suggestion cache entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days-old',
            type=int,
            default=30,
            help='Delete cache entries older than this many days (default: 30)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days_old = options['days_old']
        dry_run = options['dry_run']
        
        # Get count of entries to be deleted
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=days_old)
        old_entries = ProtocolStepSuggestionCache.objects.filter(created_at__lt=cutoff_date)
        count = old_entries.count()
        
        if count == 0:
            self.stdout.write(f"No cache entries older than {days_old} days found.")
            return
        
        if dry_run:
            self.stdout.write(f"Would delete {count} cache entries older than {days_old} days.")
            # Show some examples
            for entry in old_entries[:5]:
                self.stdout.write(f"  - Step {entry.step_id} ({entry.analyzer_type}) - {entry.created_at}")
            if count > 5:
                self.stdout.write(f"  ... and {count - 5} more entries")
        else:
            # Actually delete the entries
            ProtocolStepSuggestionCache.cleanup_expired_cache(days_old)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully deleted {count} cache entries older than {days_old} days.")
            )