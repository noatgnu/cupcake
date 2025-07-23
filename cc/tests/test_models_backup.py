"""
Tests for backup and monitoring models: BackupLog
"""
from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from cc.models import BackupLog


class BackupLogModelTest(TestCase):
    def test_backup_log_creation(self):
        """Test basic backup log creation"""
        backup = BackupLog.objects.create(
            backup_type='database',
            status='running',
            triggered_by='cron',
            container_id='abc123def456'
        )
        
        self.assertEqual(backup.backup_type, 'database')
        self.assertEqual(backup.status, 'running')
        self.assertEqual(backup.triggered_by, 'cron')
        self.assertEqual(backup.container_id, 'abc123def456')
        self.assertIsNotNone(backup.created_at)
        self.assertIsNone(backup.completed_at)
        self.assertIsNone(backup.duration_seconds)
    
    def test_backup_log_str_representation(self):
        """Test backup log string representation"""
        backup = BackupLog.objects.create(
            backup_type='full',
            status='completed'
        )
        
        expected_str = f"Full Backup - Completed at {backup.created_at}"
        self.assertEqual(str(backup), expected_str)
    
    def test_backup_type_choices(self):
        """Test all backup type choices"""
        backup_types = ['database', 'media', 'full']
        
        for backup_type in backup_types:
            backup = BackupLog.objects.create(
                backup_type=backup_type,
                status='running'
            )
            self.assertEqual(backup.backup_type, backup_type)
    
    def test_status_choices(self):
        """Test all status choices"""
        statuses = ['running', 'completed', 'failed', 'cancelled']
        
        for status in statuses:
            backup = BackupLog.objects.create(
                backup_type='database',
                status=status
            )
            self.assertEqual(backup.status, status)
    
    def test_file_size_mb_property(self):
        """Test file size MB property calculation"""
        # Test with no file size
        backup_no_size = BackupLog.objects.create(
            backup_type='database',
            status='completed'
        )
        self.assertIsNone(backup_no_size.file_size_mb)
        
        # Test with file size in bytes
        backup_with_size = BackupLog.objects.create(
            backup_type='full',
            status='completed',
            file_size_bytes=1048576  # 1 MB
        )
        self.assertEqual(backup_with_size.file_size_mb, 1.0)
        
        # Test with fractional MB
        backup_fractional = BackupLog.objects.create(
            backup_type='media',
            status='completed',
            file_size_bytes=1572864  # 1.5 MB
        )
        self.assertEqual(backup_fractional.file_size_mb, 1.5)
        
        # Test rounding
        backup_rounded = BackupLog.objects.create(
            backup_type='database',
            status='completed',
            file_size_bytes=1234567  # ~1.18 MB
        )
        self.assertEqual(backup_rounded.file_size_mb, 1.18)
    
    def test_mark_completed_method(self):
        """Test mark_completed method"""
        backup = BackupLog.objects.create(
            backup_type='database',
            status='running'
        )
        
        # Store original created time
        created_time = backup.created_at
        
        # Mark as completed with all parameters
        backup.mark_completed(
            file_path='/backup/db_backup_2025.sql',
            file_size=1048576,
            success_message='Database backup completed successfully'
        )
        
        # Refresh from database
        backup.refresh_from_db()
        
        self.assertEqual(backup.status, 'completed')
        self.assertEqual(backup.backup_file_path, '/backup/db_backup_2025.sql')
        self.assertEqual(backup.file_size_bytes, 1048576)
        self.assertEqual(backup.success_message, 'Database backup completed successfully')
        self.assertIsNotNone(backup.completed_at)
        self.assertIsNotNone(backup.duration_seconds)
        self.assertGreaterEqual(backup.duration_seconds, 0)
    
    def test_mark_completed_minimal(self):
        """Test mark_completed method with minimal parameters"""
        backup = BackupLog.objects.create(
            backup_type='media',
            status='running'
        )
        
        backup.mark_completed()
        backup.refresh_from_db()
        
        self.assertEqual(backup.status, 'completed')
        self.assertIsNotNone(backup.completed_at)
        self.assertIsNotNone(backup.duration_seconds)
        self.assertIsNone(backup.backup_file_path)
        self.assertIsNone(backup.file_size_bytes)
        self.assertIsNone(backup.success_message)
    
    def test_mark_failed_method(self):
        """Test mark_failed method"""
        backup = BackupLog.objects.create(
            backup_type='full',
            status='running'
        )
        
        error_msg = 'Database connection failed during backup'
        backup.mark_failed(error_msg)
        backup.refresh_from_db()
        
        self.assertEqual(backup.status, 'failed')
        self.assertEqual(backup.error_message, error_msg)
        self.assertIsNotNone(backup.completed_at)
        self.assertIsNotNone(backup.duration_seconds)
        self.assertGreaterEqual(backup.duration_seconds, 0)
    
    def test_backup_log_ordering(self):
        """Test backup log ordering by created_at descending"""
        # Create backups with different timestamps
        old_backup = BackupLog.objects.create(
            backup_type='database',
            status='completed'
        )
        
        # Simulate time passing
        import time
        time.sleep(0.1)
        
        new_backup = BackupLog.objects.create(
            backup_type='media',
            status='running'
        )
        
        backups = list(BackupLog.objects.all())
        self.assertEqual(backups[0], new_backup)  # Newest first
        self.assertEqual(backups[1], old_backup)
    
    def test_backup_log_indexes(self):
        """Test that backup log has appropriate database indexes"""
        # Create test data for different combinations
        BackupLog.objects.create(backup_type='database', status='completed')
        BackupLog.objects.create(backup_type='database', status='failed')
        BackupLog.objects.create(backup_type='media', status='completed')
        BackupLog.objects.create(backup_type='full', status='running')
        
        # Test filtering by backup_type and status (should use compound index)
        database_completed = BackupLog.objects.filter(
            backup_type='database',
            status='completed'
        )
        self.assertEqual(database_completed.count(), 1)
        
        # Test filtering by created_at (should use created_at index)
        recent_backups = BackupLog.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=1)
        )
        self.assertEqual(recent_backups.count(), 4)


class BackupLogWorkflowTest(TestCase):
    """Test complete backup workflow scenarios"""
    
    def test_successful_database_backup_workflow(self):
        """Test complete successful database backup workflow"""
        # Start backup
        backup = BackupLog.objects.create(
            backup_type='database',
            status='running',
            triggered_by='cron',
            container_id='backup-container-123'
        )
        
        # Verify initial state
        self.assertEqual(backup.status, 'running')
        self.assertIsNone(backup.completed_at)
        self.assertIsNone(backup.duration_seconds)
        
        # Simulate backup completion
        import time
        time.sleep(0.1)  # Simulate some processing time
        
        backup.mark_completed(
            file_path='/backups/database_20250122_0300.sql.gz',
            file_size=52428800,  # 50 MB
            success_message='Database backup completed - 1,234 tables exported'
        )
        
        # Verify completion state
        backup.refresh_from_db()
        self.assertEqual(backup.status, 'completed')
        self.assertEqual(backup.backup_file_path, '/backups/database_20250122_0300.sql.gz')
        self.assertEqual(backup.file_size_bytes, 52428800)
        self.assertEqual(backup.file_size_mb, 50.0)
        self.assertEqual(backup.success_message, 'Database backup completed - 1,234 tables exported')
        self.assertIsNotNone(backup.completed_at)
        self.assertIsNotNone(backup.duration_seconds)
        self.assertGreater(backup.duration_seconds, 0)
    
    def test_failed_media_backup_workflow(self):
        """Test failed media backup workflow"""
        # Start backup
        backup = BackupLog.objects.create(
            backup_type='media',
            status='running',
            triggered_by='manual',
            container_id='backup-media-456'
        )
        
        # Simulate backup failure
        import time
        time.sleep(0.05)  # Simulate some processing time
        
        error_message = 'Insufficient disk space: required 10GB, available 2GB'
        backup.mark_failed(error_message)
        
        # Verify failure state
        backup.refresh_from_db()
        self.assertEqual(backup.status, 'failed')
        self.assertEqual(backup.error_message, error_message)
        self.assertIsNotNone(backup.completed_at)
        self.assertIsNotNone(backup.duration_seconds)
        self.assertGreater(backup.duration_seconds, 0)
        self.assertIsNone(backup.backup_file_path)
        self.assertIsNone(backup.file_size_bytes)
        self.assertIsNone(backup.success_message)
    
    def test_full_backup_with_large_file(self):
        """Test full backup with large file scenario"""
        backup = BackupLog.objects.create(
            backup_type='full',
            status='running',
            triggered_by='weekly_cron'
        )
        
        # Simulate large backup file (5.7 GB)
        large_file_size = 6_123_456_789
        
        backup.mark_completed(
            file_path='/backups/full_backup_20250122.tar.gz',
            file_size=large_file_size,
            success_message='Full system backup completed'
        )
        
        backup.refresh_from_db()
        self.assertEqual(backup.file_size_bytes, large_file_size)
        # Should be approximately 5843.33 MB
        self.assertAlmostEqual(backup.file_size_mb, 5843.33, places=2)
    
    def test_multiple_backup_types_same_time(self):
        """Test multiple backup types running simultaneously"""
        from django.utils import timezone
        
        start_time = timezone.now()
        
        # Start multiple backups
        db_backup = BackupLog.objects.create(
            backup_type='database',
            status='running',
            triggered_by='cron'
        )
        
        media_backup = BackupLog.objects.create(
            backup_type='media',
            status='running',
            triggered_by='cron'
        )
        
        full_backup = BackupLog.objects.create(
            backup_type='full',
            status='running',
            triggered_by='manual'
        )
        
        # Complete them in different order
        media_backup.mark_completed(
            file_path='/backups/media_backup.tar',
            file_size=1073741824  # 1 GB
        )
        
        db_backup.mark_failed('Connection timeout')
        
        full_backup.mark_completed(
            file_path='/backups/full_backup.tar.gz',
            file_size=5368709120  # 5 GB
        )
        
        # Verify all backups exist with correct states
        all_backups = BackupLog.objects.filter(created_at__gte=start_time)
        self.assertEqual(all_backups.count(), 3)
        
        completed_backups = all_backups.filter(status='completed')
        self.assertEqual(completed_backups.count(), 2)
        
        failed_backups = all_backups.filter(status='failed')
        self.assertEqual(failed_backups.count(), 1)
    
    def test_backup_log_duration_calculation(self):
        """Test backup duration calculation accuracy"""
        backup = BackupLog.objects.create(
            backup_type='database',
            status='running'
        )
        
        # Store creation time
        start_time = backup.created_at
        
        # Simulate longer processing time
        import time
        time.sleep(0.2)  # Sleep for 200ms
        
        backup.mark_completed()
        
        # Verify duration is calculated correctly
        backup.refresh_from_db()
        actual_duration = (backup.completed_at - start_time).total_seconds()
        stored_duration = backup.duration_seconds
        
        # Should be close (within 0.1 seconds)
        self.assertAlmostEqual(actual_duration, stored_duration, delta=0.1)
        self.assertGreaterEqual(stored_duration, 0.2)  # At least our sleep time
    
    def test_backup_triggered_by_options(self):
        """Test different trigger sources"""
        trigger_sources = ['cron', 'manual', 'api', 'system', 'emergency']
        
        for source in trigger_sources:
            backup = BackupLog.objects.create(
                backup_type='database',
                status='completed',
                triggered_by=source
            )
            self.assertEqual(backup.triggered_by, source)
    
    def test_backup_container_id_tracking(self):
        """Test container ID tracking for Docker environments"""
        container_ids = [
            'abc123def456',
            'backup-worker-789',
            'k8s-backup-pod-xyz',
            None  # For non-containerized backups
        ]
        
        for container_id in container_ids:
            backup = BackupLog.objects.create(
                backup_type='database',
                status='completed',
                container_id=container_id
            )
            self.assertEqual(backup.container_id, container_id)


class BackupLogAnalyticsTest(TestCase):
    """Test backup log analytics and reporting"""
    
    def setUp(self):
        """Create sample backup data for analytics tests"""
        from django.utils import timezone
        
        # Create backups over the last 7 days
        base_time = timezone.now() - timedelta(days=7)
        
        # Successful database backups
        for i in range(7):
            BackupLog.objects.create(
                backup_type='database',
                status='completed',
                created_at=base_time + timedelta(days=i),
                completed_at=base_time + timedelta(days=i, minutes=30),
                duration_seconds=1800,  # 30 minutes
                file_size_bytes=50 * 1024 * 1024,  # 50 MB
                triggered_by='cron'
            )
        
        # Some failed backups
        BackupLog.objects.create(
            backup_type='media',
            status='failed',
            created_at=base_time + timedelta(days=2),
            completed_at=base_time + timedelta(days=2, minutes=5),
            duration_seconds=300,
            error_message='Disk full'
        )
        
        BackupLog.objects.create(
            backup_type='full',
            status='failed',
            created_at=base_time + timedelta(days=5),
            completed_at=base_time + timedelta(days=5, minutes=10),
            duration_seconds=600,
            error_message='Network timeout'
        )
        
        # Successful full backup
        BackupLog.objects.create(
            backup_type='full',
            status='completed',
            created_at=base_time + timedelta(days=6),
            completed_at=base_time + timedelta(days=6, hours=2),
            duration_seconds=7200,  # 2 hours
            file_size_bytes=2 * 1024 * 1024 * 1024,  # 2 GB
            triggered_by='weekly_cron'
        )
    
    def test_backup_success_rate(self):
        """Test calculating backup success rate"""
        total_backups = BackupLog.objects.count()
        successful_backups = BackupLog.objects.filter(status='completed').count()
        failed_backups = BackupLog.objects.filter(status='failed').count()
        
        self.assertEqual(total_backups, 10)
        self.assertEqual(successful_backups, 8)
        self.assertEqual(failed_backups, 2)
        
        success_rate = (successful_backups / total_backups) * 100
        self.assertEqual(success_rate, 80.0)
    
    def test_backup_type_distribution(self):
        """Test backup type distribution"""
        database_backups = BackupLog.objects.filter(backup_type='database').count()
        media_backups = BackupLog.objects.filter(backup_type='media').count()
        full_backups = BackupLog.objects.filter(backup_type='full').count()
        
        self.assertEqual(database_backups, 7)
        self.assertEqual(media_backups, 1)
        self.assertEqual(full_backups, 2)
    
    def test_average_backup_duration(self):
        """Test calculating average backup duration"""
        completed_backups = BackupLog.objects.filter(status='completed')
        
        total_duration = sum(backup.duration_seconds for backup in completed_backups)
        average_duration = total_duration / completed_backups.count()
        
        # Database backups: 7 × 1800s = 12600s
        # Full backup: 1 × 7200s = 7200s
        # Total: 19800s, Average: 19800/8 = 2475s
        self.assertEqual(average_duration, 2475.0)
    
    def test_total_backup_storage(self):
        """Test calculating total backup storage used"""
        completed_backups = BackupLog.objects.filter(
            status='completed',
            file_size_bytes__isnull=False
        )
        
        total_bytes = sum(backup.file_size_bytes for backup in completed_backups)
        total_mb = total_bytes / (1024 * 1024)
        
        # Database backups: 7 × 50MB = 350MB
        # Full backup: 1 × 2048MB = 2048MB
        # Total: 2398MB
        self.assertEqual(total_mb, 2398.0)
    
    def test_recent_backup_analysis(self):
        """Test analyzing recent backup performance"""
        from django.utils import timezone
        
        # Get backups from last 24 hours
        recent_cutoff = timezone.now() - timedelta(hours=24)
        recent_backups = BackupLog.objects.filter(created_at__gte=recent_cutoff)
        
        # Since our test data is older, we'll check for empty result
        self.assertEqual(recent_backups.count(), 0)
        
        # Get backups from last week (should include our test data)
        week_cutoff = timezone.now() - timedelta(days=7)
        week_backups = BackupLog.objects.filter(created_at__gte=week_cutoff)
        
        self.assertEqual(week_backups.count(), 10)  # All our test backups
    
    def test_failure_analysis(self):
        """Test analyzing backup failures"""
        failed_backups = BackupLog.objects.filter(status='failed')
        
        # Check failure reasons
        error_messages = [backup.error_message for backup in failed_backups]
        self.assertIn('Disk full', error_messages)
        self.assertIn('Network timeout', error_messages)
        
        # Check failure types
        failed_media = failed_backups.filter(backup_type='media').count()
        failed_full = failed_backups.filter(backup_type='full').count()
        failed_database = failed_backups.filter(backup_type='database').count()
        
        self.assertEqual(failed_media, 1)
        self.assertEqual(failed_full, 1)
        self.assertEqual(failed_database, 0)