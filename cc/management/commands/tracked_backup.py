import os
import subprocess
import socket
from django.core.management.base import BaseCommand
from django.utils import timezone
from cc.models import BackupLog


class Command(BaseCommand):
    help = 'Run database and media backups with logging to BackupLog model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--database-only',
            action='store_true',
            help='Run only database backup',
        )
        parser.add_argument(
            '--media-only',
            action='store_true',
            help='Run only media backup',
        )
        parser.add_argument(
            '--triggered-by',
            type=str,
            default='manual',
            help='What triggered this backup (cron, manual, api, etc.)',
        )

    def handle(self, *args, **options):
        database_only = options['database_only']
        media_only = options['media_only']
        triggered_by = options['triggered_by']
        
        # Get container ID if running in Docker
        container_id = self.get_container_id()
        
        if not database_only and not media_only:
            # Run both backups
            self.run_database_backup(triggered_by, container_id)
            self.run_media_backup(triggered_by, container_id)
        elif database_only:
            self.run_database_backup(triggered_by, container_id)
        elif media_only:
            self.run_media_backup(triggered_by, container_id)

    def get_container_id(self):
        """Get Docker container ID if running in container"""
        try:
            # Try to get container ID from hostname (Docker default)
            return socket.gethostname()[:12]  # Docker container IDs are 64 chars, hostname is first 12
        except:
            return None

    def get_file_size(self, file_path):
        """Get file size in bytes"""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return None

    def run_database_backup(self, triggered_by, container_id):
        """Run database backup with logging"""
        backup_log = BackupLog.objects.create(
            backup_type='database',
            triggered_by=triggered_by,
            container_id=container_id
        )
        
        try:
            self.stdout.write(f"Starting database backup (Log ID: {backup_log.id})...")
            
            # Run the dbbackup command
            result = subprocess.run(
                ['python', '/app/manage.py', 'dbbackup'],
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode == 0:
                # Try to find the backup file path from the output
                backup_file_path = self.extract_backup_path(result.stdout, 'database')
                file_size = self.get_file_size(backup_file_path) if backup_file_path else None
                
                backup_log.mark_completed(
                    file_path=backup_file_path,
                    file_size=file_size,
                    success_message=f"Database backup completed successfully. Output: {result.stdout[:500]}"
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Database backup completed successfully (Log ID: {backup_log.id})")
                )
                if file_size:
                    self.stdout.write(f"Backup file size: {backup_log.file_size_mb} MB")
            else:
                error_msg = f"Database backup failed. Return code: {result.returncode}. Stderr: {result.stderr}"
                backup_log.mark_failed(error_msg)
                self.stdout.write(
                    self.style.ERROR(f"Database backup failed (Log ID: {backup_log.id}): {error_msg}")
                )
                
        except subprocess.TimeoutExpired:
            error_msg = "Database backup timed out (exceeded 1 hour)"
            backup_log.mark_failed(error_msg)
            self.stdout.write(self.style.ERROR(f"Database backup timed out (Log ID: {backup_log.id})"))
            
        except Exception as e:
            error_msg = f"Database backup failed with exception: {str(e)}"
            backup_log.mark_failed(error_msg)
            self.stdout.write(self.style.ERROR(f"Database backup failed (Log ID: {backup_log.id}): {error_msg}"))

    def run_media_backup(self, triggered_by, container_id):
        """Run media backup with logging"""
        backup_log = BackupLog.objects.create(
            backup_type='media',
            triggered_by=triggered_by,
            container_id=container_id
        )
        
        try:
            self.stdout.write(f"Starting media backup (Log ID: {backup_log.id})...")
            
            # Run the mediabackup command
            result = subprocess.run(
                ['python', '/app/manage.py', 'mediabackup'],
                capture_output=True,
                text=True,
                timeout=7200  # 2 hour timeout for media files
            )
            
            if result.returncode == 0:
                # Try to find the backup file path from the output
                backup_file_path = self.extract_backup_path(result.stdout, 'media')
                file_size = self.get_file_size(backup_file_path) if backup_file_path else None
                
                backup_log.mark_completed(
                    file_path=backup_file_path,
                    file_size=file_size,
                    success_message=f"Media backup completed successfully. Output: {result.stdout[:500]}"
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Media backup completed successfully (Log ID: {backup_log.id})")
                )
                if file_size:
                    self.stdout.write(f"Backup file size: {backup_log.file_size_mb} MB")
            else:
                error_msg = f"Media backup failed. Return code: {result.returncode}. Stderr: {result.stderr}"
                backup_log.mark_failed(error_msg)
                self.stdout.write(
                    self.style.ERROR(f"Media backup failed (Log ID: {backup_log.id}): {error_msg}")
                )
                
        except subprocess.TimeoutExpired:
            error_msg = "Media backup timed out (exceeded 2 hours)"
            backup_log.mark_failed(error_msg)
            self.stdout.write(self.style.ERROR(f"Media backup timed out (Log ID: {backup_log.id})"))
            
        except Exception as e:
            error_msg = f"Media backup failed with exception: {str(e)}"
            backup_log.mark_failed(error_msg)
            self.stdout.write(self.style.ERROR(f"Media backup failed (Log ID: {backup_log.id}): {error_msg}"))

    def extract_backup_path(self, output, backup_type):
        """Extract backup file path from command output"""
        # This is a basic implementation - you may need to adjust based on 
        # the actual output format of your backup commands
        lines = output.split('\n')
        for line in lines:
            if 'backup' in line.lower() and ('created' in line.lower() or 'saved' in line.lower()):
                # Try to extract file path - this is very basic and may need refinement
                if '/app/backup/' in line:
                    parts = line.split('/app/backup/')
                    if len(parts) > 1:
                        # Extract the filename part
                        filename = parts[1].split()[0].strip()
                        return f"/app/backup/{filename}"
        return None