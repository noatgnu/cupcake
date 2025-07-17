import os
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.management import call_command
from cc.models import BackupLog, SiteSettings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class Command(BaseCommand):
    help = 'Check backup frequency settings and run automatic backups if needed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force backup regardless of frequency settings',
        )
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Only check if backup is due, do not run backup',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID who triggered the backup (for WebSocket notifications)',
        )
        parser.add_argument(
            '--backup-id',
            type=str,
            help='Backup ID for progress tracking',
        )

    def handle(self, *args, **options):
        force = options['force']
        check_only = options['check_only']
        user_id = options.get('user_id')
        backup_id = options.get('backup_id')
        
        # Initialize channel layer for WebSocket notifications
        channel_layer = get_channel_layer() if user_id else None
        
        # Get current site settings
        try:
            settings = SiteSettings.get_or_create_default()
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to get site settings: {str(e)}")
            )
            return

        # Check if backup module is enabled
        if not getattr(settings, 'enable_backup_module', True):
            self.stdout.write(
                self.style.WARNING("Backup module is disabled in site settings. Skipping backup.")
            )
            return

        # Get backup frequency
        backup_frequency_days = getattr(settings, 'backup_frequency_days', 7)
        
        # If frequency is 0, automatic backups are disabled
        if backup_frequency_days == 0 and not force:
            self.stdout.write(
                self.style.WARNING("Automatic backups are disabled (frequency = 0 days). Use --force to run anyway.")
            )
            return

        # Check if backup is due
        is_due, days_since_last, next_backup_date = self.is_backup_due(backup_frequency_days)
        
        # Report status
        self.stdout.write(f"Backup frequency: {backup_frequency_days} days")
        self.stdout.write(f"Days since last backup: {days_since_last}")
        self.stdout.write(f"Next scheduled backup: {next_backup_date}")
        self.stdout.write(f"Backup due: {'Yes' if is_due else 'No'}")
        
        if check_only:
            if is_due or force:
                self.stdout.write(self.style.SUCCESS("Backup is due and would be executed."))
            else:
                self.stdout.write(self.style.WARNING("Backup is not due yet."))
            return

        # Run backup if due or forced
        if is_due or force:
            reason = "forced by --force flag" if force else f"due (frequency: {backup_frequency_days} days)"
            self.stdout.write(
                self.style.SUCCESS(f"Running automatic backup ({reason})...")
            )
            
            # Send initial WebSocket notification
            self.send_websocket_notification(
                channel_layer, user_id, backup_id, 0, "starting",
                f"Starting automatic backup ({reason})"
            )
            
            try:
                # Send progress notification
                self.send_websocket_notification(
                    channel_layer, user_id, backup_id, 10, "in_progress",
                    "Initializing backup process..."
                )
                
                # Call the tracked_backup command
                triggered_by = 'manual' if user_id else 'automatic'
                call_command('tracked_backup', triggered_by=triggered_by)
                
                # Send completion notification
                self.send_websocket_notification(
                    channel_layer, user_id, backup_id, 100, "completed",
                    "Automatic backup completed successfully"
                )
                
                self.stdout.write(
                    self.style.SUCCESS("Automatic backup completed successfully.")
                )
            except Exception as e:
                # Send error notification
                self.send_websocket_notification(
                    channel_layer, user_id, backup_id, -1, "failed",
                    f"Automatic backup failed: {str(e)}"
                )
                
                self.stdout.write(
                    self.style.ERROR(f"Automatic backup failed: {str(e)}")
                )
        else:
            self.stdout.write(
                self.style.WARNING(f"Backup not due yet. Next backup in {backup_frequency_days - days_since_last} days.")
            )

    def is_backup_due(self, frequency_days):
        """
        Check if a backup is due based on the frequency setting
        
        Returns:
            tuple: (is_due: bool, days_since_last: int, next_backup_date: datetime)
        """
        # Get the last successful backup
        last_backup = BackupLog.objects.filter(
            backup_type='database',
            status='completed'
        ).order_by('-completed_at').first()
        
        if not last_backup:
            # No previous backups, backup is due
            return True, float('inf'), timezone.now()
        
        # Calculate days since last backup
        days_since_last = (timezone.now() - last_backup.completed_at).days
        
        # Calculate next backup date
        next_backup_date = last_backup.completed_at + timedelta(days=frequency_days)
        
        # Check if backup is due
        is_due = days_since_last >= frequency_days
        
        return is_due, days_since_last, next_backup_date

    def send_websocket_notification(self, channel_layer, user_id, backup_id, progress, status, message):
        """Send WebSocket notification for backup progress"""
        if not channel_layer or not user_id:
            return
        
        try:
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                {
                    "type": "backup_progress",
                    "message": {
                        "backup_id": backup_id,
                        "progress": progress,
                        "status": status,
                        "message": message,
                        "timestamp": timezone.now().isoformat()
                    }
                }
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to send WebSocket notification: {str(e)}"))

    def get_backup_status_summary(self):
        """Get a summary of recent backup status"""
        recent_backups = BackupLog.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=30)
        ).order_by('-created_at')[:10]
        
        if not recent_backups:
            return "No recent backups found"
        
        summary = []
        for backup in recent_backups:
            status_icon = "✓" if backup.status == 'completed' else "✗" if backup.status == 'failed' else "⏳"
            date_str = backup.created_at.strftime('%Y-%m-%d %H:%M')
            summary.append(f"{status_icon} {backup.backup_type} ({date_str}) - {backup.triggered_by}")
        
        return "\n".join(summary)