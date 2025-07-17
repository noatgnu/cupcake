from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from cc.models import BackupLog, SiteSettings


class Command(BaseCommand):
    help = 'Display backup status and configuration information'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to look back for backup history (default: 30)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed backup information',
        )

    def handle(self, *args, **options):
        days_back = options['days']
        verbose = options['verbose']
        
        self.stdout.write(self.style.SUCCESS("=== BACKUP STATUS REPORT ==="))
        self.stdout.write("")
        
        # Show current configuration
        self.show_configuration()
        self.stdout.write("")
        
        # Show backup schedule status
        self.show_schedule_status()
        self.stdout.write("")
        
        # Show recent backup history
        self.show_backup_history(days_back, verbose)
        self.stdout.write("")
        
        # Show backup statistics
        self.show_backup_statistics(days_back)

    def show_configuration(self):
        """Display current backup configuration"""
        self.stdout.write(self.style.WARNING("📋 BACKUP CONFIGURATION"))
        self.stdout.write("-" * 40)
        
        try:
            settings = SiteSettings.get_or_create_default()
            backup_enabled = getattr(settings, 'enable_backup_module', True)
            backup_frequency = getattr(settings, 'backup_frequency_days', 7)
            
            self.stdout.write(f"Backup Module Enabled: {'✅ Yes' if backup_enabled else '❌ No'}")
            self.stdout.write(f"Backup Frequency: {backup_frequency} days")
            
            if backup_frequency == 0:
                self.stdout.write(self.style.WARNING("⚠️  Automatic backups are DISABLED"))
            elif backup_frequency == 1:
                self.stdout.write("📅 Backups run DAILY")
            elif backup_frequency == 7:
                self.stdout.write("📅 Backups run WEEKLY")
            elif backup_frequency == 30:
                self.stdout.write("📅 Backups run MONTHLY")
            else:
                self.stdout.write(f"📅 Backups run every {backup_frequency} days")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error reading configuration: {str(e)}"))

    def show_schedule_status(self):
        """Show when the next backup is due"""
        self.stdout.write(self.style.WARNING("⏰ BACKUP SCHEDULE STATUS"))
        self.stdout.write("-" * 40)
        
        try:
            settings = SiteSettings.get_or_create_default()
            backup_frequency = getattr(settings, 'backup_frequency_days', 7)
            
            if backup_frequency == 0:
                self.stdout.write("🚫 Automatic backups disabled")
                return
            
            # Get last successful backup
            last_backup = BackupLog.objects.filter(
                backup_type='database',
                status='completed'
            ).order_by('-completed_at').first()
            
            if not last_backup:
                self.stdout.write("⚠️  No previous backups found - backup is DUE")
                return
            
            days_since_last = (timezone.now() - last_backup.completed_at).days
            next_backup_date = last_backup.completed_at + timedelta(days=backup_frequency)
            days_until_next = (next_backup_date - timezone.now()).days
            
            self.stdout.write(f"Last Backup: {last_backup.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            self.stdout.write(f"Days Since Last: {days_since_last}")
            self.stdout.write(f"Next Backup Due: {next_backup_date.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if days_since_last >= backup_frequency:
                self.stdout.write(self.style.ERROR("🔴 BACKUP IS OVERDUE"))
            elif days_until_next <= 1:
                self.stdout.write(self.style.WARNING("🟡 BACKUP DUE SOON"))
            else:
                self.stdout.write(self.style.SUCCESS(f"🟢 Next backup in {days_until_next} days"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error checking schedule: {str(e)}"))

    def show_backup_history(self, days_back, verbose):
        """Show recent backup history"""
        self.stdout.write(self.style.WARNING(f"📊 BACKUP HISTORY (Last {days_back} days)"))
        self.stdout.write("-" * 40)
        
        start_date = timezone.now() - timedelta(days=days_back)
        recent_backups = BackupLog.objects.filter(
            created_at__gte=start_date
        ).order_by('-created_at')
        
        if not recent_backups:
            self.stdout.write("No backups found in the specified period")
            return
        
        for backup in recent_backups:
            status_icon = self.get_status_icon(backup.status)
            date_str = backup.created_at.strftime('%Y-%m-%d %H:%M')
            
            if verbose:
                size_info = f" ({backup.file_size_mb:.1f} MB)" if backup.file_size else ""
                duration = ""
                if backup.completed_at:
                    duration_seconds = (backup.completed_at - backup.created_at).total_seconds()
                    duration = f" [{duration_seconds:.1f}s]"
                
                self.stdout.write(
                    f"{status_icon} {backup.backup_type.upper()} - {date_str} - "
                    f"{backup.triggered_by}{size_info}{duration}"
                )
                
                if backup.status == 'failed' and backup.error_message:
                    self.stdout.write(f"    ❌ Error: {backup.error_message[:100]}...")
            else:
                self.stdout.write(
                    f"{status_icon} {backup.backup_type} ({date_str}) - {backup.triggered_by}"
                )

    def show_backup_statistics(self, days_back):
        """Show backup statistics"""
        self.stdout.write(self.style.WARNING(f"📈 BACKUP STATISTICS (Last {days_back} days)"))
        self.stdout.write("-" * 40)
        
        start_date = timezone.now() - timedelta(days=days_back)
        recent_backups = BackupLog.objects.filter(created_at__gte=start_date)
        
        total_backups = recent_backups.count()
        completed_backups = recent_backups.filter(status='completed').count()
        failed_backups = recent_backups.filter(status='failed').count()
        
        success_rate = (completed_backups / total_backups * 100) if total_backups > 0 else 0
        
        self.stdout.write(f"Total Backups: {total_backups}")
        self.stdout.write(f"Successful: {completed_backups}")
        self.stdout.write(f"Failed: {failed_backups}")
        self.stdout.write(f"Success Rate: {success_rate:.1f}%")
        
        # Show total backup size
        completed_with_size = recent_backups.filter(
            status='completed',
            file_size__isnull=False
        )
        
        if completed_with_size.exists():
            total_size_mb = sum(b.file_size_mb for b in completed_with_size)
            avg_size_mb = total_size_mb / completed_with_size.count()
            self.stdout.write(f"Total Backup Size: {total_size_mb:.1f} MB")
            self.stdout.write(f"Average Backup Size: {avg_size_mb:.1f} MB")
        
        # Show backup types
        db_backups = recent_backups.filter(backup_type='database').count()
        media_backups = recent_backups.filter(backup_type='media').count()
        
        if db_backups > 0 or media_backups > 0:
            self.stdout.write(f"Database Backups: {db_backups}")
            self.stdout.write(f"Media Backups: {media_backups}")

    def get_status_icon(self, status):
        """Get appropriate icon for backup status"""
        icons = {
            'completed': '✅',
            'failed': '❌',
            'in_progress': '⏳',
            'created': '🔄'
        }
        return icons.get(status, '❓')