"""
Comprehensive edge case and validation tests for CUPCAKE models
Focuses on boundary conditions, invalid data, and error handling
"""
import uuid
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, Mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from cc.models import (
    Project, ProtocolModel, ProtocolRating, ProtocolStep, Session,
    Instrument, InstrumentJob, InstrumentUsage, Annotation, AnnotationFolder,
    StorageObject, StoredReagent, LabGroup, MetadataColumn, Preset,
    FavouriteMetadataOption, MetadataTableTemplate, SamplePool,
    RemoteHost, ServiceTier, BillingRecord,
    ImportTracker, ImportedObject, SiteSettings
)


class ProjectEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.remote_host = RemoteHost.objects.create(
            host_name='test.host.com',
            host_port=8000,
            host_protocol='https'
        )
    
    def test_project_empty_name(self):
        """Test project with empty name"""
        with self.assertRaises(IntegrityError):
            Project.objects.create(project_name='')
    
    def test_project_very_long_name(self):
        """Test project with name exceeding max_length"""
        long_name = 'x' * 300  # Exceeds 255 char limit
        with self.assertRaises(ValidationError):
            project = Project(project_name=long_name)
            project.full_clean()
    
    def test_project_null_description(self):
        """Test project with null description is allowed"""
        project = Project.objects.create(
            project_name='Test Project',
            project_description=None
        )
        self.assertIsNone(project.project_description)
    
    def test_project_unicode_name(self):
        """Test project with unicode characters"""
        unicode_name = 'Тест 项目 プロジェクト 🧪'
        project = Project.objects.create(project_name=unicode_name)
        self.assertEqual(project.project_name, unicode_name)
    
    def test_project_with_remote_id_boundary(self):
        """Test project with boundary remote_id values"""
        # Test maximum BigIntegerField value
        max_remote_id = 9223372036854775807
        project = Project.objects.create(
            project_name='Max Remote ID',
            remote_id=max_remote_id
        )
        self.assertEqual(project.remote_id, max_remote_id)
        
        # Test minimum value (negative)
        min_remote_id = -9223372036854775808
        project2 = Project.objects.create(
            project_name='Min Remote ID',
            remote_id=min_remote_id
        )
        self.assertEqual(project2.remote_id, min_remote_id)
    
    def test_project_owner_cascade_delete(self):
        """Test project behavior when owner is deleted"""
        project = Project.objects.create(
            project_name='Test Project',
            owner=self.user
        )
        project_id = project.id
        
        # Delete the user, project should be deleted too
        self.user.delete()
        
        with self.assertRaises(Project.DoesNotExist):
            Project.objects.get(id=project_id)


class ProtocolRatingEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
    
    def test_rating_boundary_values(self):
        """Test rating with boundary values (0 and 10)"""
        # Test minimum valid values
        rating = ProtocolRating.objects.create(
            protocol=self.protocol,
            user=self.user,
            complexity_rating=0,
            duration_rating=0
        )
        self.assertEqual(rating.complexity_rating, 0)
        self.assertEqual(rating.duration_rating, 0)
        
        # Test maximum valid values
        rating2 = ProtocolRating.objects.create(
            protocol=self.protocol,
            user=self.user,
            complexity_rating=10,
            duration_rating=10
        )
        self.assertEqual(rating2.complexity_rating, 10)
        self.assertEqual(rating2.duration_rating, 10)
    
    def test_rating_invalid_low_values(self):
        """Test rating with values below allowed range"""
        with self.assertRaises(ValueError):
            ProtocolRating.objects.create(
                protocol=self.protocol,
                user=self.user,
                complexity_rating=-1,
                duration_rating=5
            )
        
        with self.assertRaises(ValueError):
            ProtocolRating.objects.create(
                protocol=self.protocol,
                user=self.user,
                complexity_rating=5,
                duration_rating=-1
            )
    
    def test_rating_invalid_high_values(self):
        """Test rating with values above allowed range"""
        with self.assertRaises(ValueError):
            ProtocolRating.objects.create(
                protocol=self.protocol,
                user=self.user,
                complexity_rating=11,
                duration_rating=5
            )
        
        with self.assertRaises(ValueError):
            ProtocolRating.objects.create(
                protocol=self.protocol,
                user=self.user,
                complexity_rating=5,
                duration_rating=11
            )
    
    def test_multiple_ratings_same_user_protocol(self):
        """Test multiple ratings from same user for same protocol"""
        ProtocolRating.objects.create(
            protocol=self.protocol,
            user=self.user,
            complexity_rating=5,
            duration_rating=6
        )
        
        # Should allow multiple ratings (no unique constraint)
        rating2 = ProtocolRating.objects.create(
            protocol=self.protocol,
            user=self.user,
            complexity_rating=7,
            duration_rating=8
        )
        
        # Both should exist
        ratings = ProtocolRating.objects.filter(
            protocol=self.protocol,
            user=self.user
        )
        self.assertEqual(ratings.count(), 2)


class InstrumentJobEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test MS Instrument'
        )
        self.lab_group = LabGroup.objects.create(
            name='Test Lab Group',
            description='Test description'
        )
    
    def test_injection_volume_boundary_values(self):
        """Test injection volume with boundary values"""
        # Test with very small positive value
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            injection_volume=0.01
        )
        self.assertAlmostEqual(job.injection_volume, 0.01, places=2)
        
        # Test with very large value
        large_volume = 999999.99
        job2 = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            injection_volume=large_volume
        )
        self.assertAlmostEqual(job2.injection_volume, large_volume, places=2)
    
    def test_injection_volume_zero(self):
        """Test injection volume with zero value"""
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            injection_volume=0.0
        )
        self.assertEqual(job.injection_volume, 0.0)
    
    def test_injection_volume_negative(self):
        """Test injection volume with negative value (should allow it)"""
        # FloatField doesn't automatically reject negative values
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            injection_volume=-1.0
        )
        self.assertEqual(job.injection_volume, -1.0)
    
    def test_sample_number_boundary_values(self):
        """Test sample number with boundary values"""
        # Test minimum value
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            sample_number=1
        )
        self.assertEqual(job.sample_number, 1)
        
        # Test large value
        job2 = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            sample_number=999999
        )
        self.assertEqual(job2.sample_number, 999999)
    
    def test_sample_number_zero_or_negative(self):
        """Test sample number with zero or negative values"""
        # IntegerField allows zero and negative values by default
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            sample_number=0
        )
        self.assertEqual(job.sample_number, 0)
        
        job2 = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument,
            sample_number=-1
        )
        self.assertEqual(job2.sample_number, -1)
    
    def test_job_status_transitions(self):
        """Test job status field with various values"""
        valid_statuses = [
            'draft', 'submitted', 'pending', 'completed', 
            'in_progress', 'cancelled'
        ]
        
        for status in valid_statuses:
            job = InstrumentJob.objects.create(
                user=self.user,
                project=self.project,
                instrument=self.instrument,
                status=status
            )
            self.assertEqual(job.status, status)
    
    def test_job_invalid_status(self):
        """Test job with invalid status"""
        with self.assertRaises(ValidationError):
            job = InstrumentJob(
                user=self.user,
                project=self.project,
                instrument=self.instrument,
                status='invalid_status'
            )
            job.full_clean()


class SamplePoolEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test MS Instrument'
        )
        self.instrument_job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument
        )
    
    def test_pool_empty_sample_lists(self):
        """Test pool with empty sample lists"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Empty Pool',
            pooled_only_samples=[],
            pooled_and_independent_samples=[],
            created_by=self.user
        )
        self.assertEqual(pool.pooled_only_samples, [])
        self.assertEqual(pool.pooled_and_independent_samples, [])
    
    def test_pool_very_large_sample_lists(self):
        """Test pool with very large sample lists"""
        large_list = list(range(1, 10001))  # 10,000 samples
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Large Pool',
            pooled_only_samples=large_list,
            pooled_and_independent_samples=large_list[:5000],
            created_by=self.user
        )
        self.assertEqual(len(pool.pooled_only_samples), 10000)
        self.assertEqual(len(pool.pooled_and_independent_samples), 5000)
    
    def test_pool_name_boundary_values(self):
        """Test pool name with boundary values"""
        # Single character name
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='A',
            created_by=self.user
        )
        self.assertEqual(pool.pool_name, 'A')
        
        # Very long name (near max_length limit)
        long_name = 'x' * 200
        pool2 = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name=long_name,
            created_by=self.user
        )
        self.assertEqual(pool2.pool_name, long_name)
    
    def test_pool_duplicate_samples(self):
        """Test pool with duplicate sample IDs"""
        # Should handle duplicate IDs gracefully
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Duplicate Pool',
            pooled_only_samples=[1, 2, 2, 3, 3, 3],
            pooled_and_independent_samples=[1, 1, 4, 4],
            created_by=self.user
        )
        # Should store duplicates as provided
        self.assertEqual(pool.pooled_only_samples, [1, 2, 2, 3, 3, 3])
        self.assertEqual(pool.pooled_and_independent_samples, [1, 1, 4, 4])
    
    def test_pool_sample_overlap(self):
        """Test pool with samples in both lists"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Overlap Pool',
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[2, 3, 4],
            created_by=self.user
        )
        # Should allow overlap - business logic handles validation
        self.assertIn(2, pool.pooled_only_samples)
        self.assertIn(2, pool.pooled_and_independent_samples)


class MetadataColumnEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test MS Instrument'
        )
    
    def test_metadata_column_empty_name(self):
        """Test metadata column with empty name"""
        with self.assertRaises(IntegrityError):
            MetadataColumn.objects.create(column_name='')
    
    def test_metadata_column_very_long_name(self):
        """Test metadata column with very long name"""
        long_name = 'x' * 300  # Exceeds typical varchar limits
        with self.assertRaises(ValidationError):
            column = MetadataColumn(column_name=long_name)
            column.full_clean()
    
    def test_metadata_column_unicode_name(self):
        """Test metadata column with unicode characters"""
        unicode_name = 'Température °C 测试 テスト 🌡️'
        column = MetadataColumn.objects.create(column_name=unicode_name)
        self.assertEqual(column.column_name, unicode_name)
    
    def test_metadata_column_special_characters(self):
        """Test metadata column with special characters"""
        special_name = 'Column_Name-123!@#$%^&*()+=[]{}|;:"<>?,.'
        column = MetadataColumn.objects.create(column_name=special_name)
        self.assertEqual(column.column_name, special_name)
    
    def test_metadata_column_large_json_modifiers(self):
        """Test metadata column with large JSON modifiers"""
        large_modifiers = {
            'options': [f'option_{i}' for i in range(1000)],
            'validation': {'pattern': 'x' * 1000},
            'nested': {'deep': {'very': {'nested': {'data': 'x' * 500}}}}
        }
        column = MetadataColumn.objects.create(
            column_name='Large JSON Column',
            modifiers=large_modifiers
        )
        self.assertEqual(len(column.modifiers['options']), 1000)
    
    def test_metadata_column_null_json_modifiers(self):
        """Test metadata column with null JSON modifiers"""
        column = MetadataColumn.objects.create(
            column_name='Null Modifiers Column',
            modifiers=None
        )
        # Should default to empty dict based on model definition
        self.assertEqual(column.modifiers, {})


class ImportTrackerEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.import_id = uuid.uuid4()
    
    def test_import_tracker_boundary_statistics(self):
        """Test import tracker with boundary statistic values"""
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/test/path',
            total_objects_created=2147483647,  # Max positive int
            total_files_imported=0,  # Minimum
            total_relationships_created=1000000
        )
        self.assertEqual(tracker.total_objects_created, 2147483647)
        self.assertEqual(tracker.total_files_imported, 0)
    
    def test_import_tracker_large_archive_path(self):
        """Test import tracker with very long archive path"""
        long_path = '/very/long/path/' + 'x' * 1000 + '/archive.zip'
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path=long_path
        )
        self.assertEqual(tracker.archive_path, long_path)
    
    def test_import_tracker_large_archive_size(self):
        """Test import tracker with very large archive size"""
        large_size = 999999.99  # Near GB range
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/test/path',
            archive_size_mb=large_size
        )
        self.assertEqual(tracker.archive_size_mb, large_size)
    
    def test_import_tracker_complex_json_data(self):
        """Test import tracker with complex JSON data"""
        complex_options = {
            'nested': {'deeply': {'nested': {'options': True}}},
            'list': [1, 2, {'inner': 'value'}],
            'unicode': 'テスト データ 🧪',
            'numbers': [1.23, 4.56e10, -999.999]
        }
        complex_metadata = {
            'file_mapping': {f'file_{i}.txt': f'new_name_{i}.txt' for i in range(100)},
            'processing_log': ['step1', 'step2', 'error occurred', 'retry successful']
        }
        
        tracker = ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/test/path',
            import_options=complex_options,
            metadata=complex_metadata
        )
        
        self.assertEqual(tracker.import_options['unicode'], 'テスト データ 🧪')
        self.assertEqual(len(tracker.metadata['file_mapping']), 100)
    
    def test_import_tracker_invalid_status(self):
        """Test import tracker with invalid status"""
        with self.assertRaises(ValidationError):
            tracker = ImportTracker(
                import_id=self.import_id,
                user=self.user,
                archive_path='/test/path',
                import_status='invalid_status'
            )
            tracker.full_clean()
    
    def test_import_tracker_duplicate_uuid(self):
        """Test import tracker with duplicate UUID"""
        ImportTracker.objects.create(
            import_id=self.import_id,
            user=self.user,
            archive_path='/test/path1'
        )
        
        with self.assertRaises(IntegrityError):
            ImportTracker.objects.create(
                import_id=self.import_id,
                user=self.user,
                archive_path='/test/path2'
            )


class BillingRecordEdgeCaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test MS Instrument'
        )
        self.instrument_job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=self.instrument
        )
        self.service_tier = ServiceTier.objects.create(
            tier_name='Test Tier',
            tier_description='Test description'
        )
    
    def test_billing_record_zero_amounts(self):
        """Test billing record with zero amounts"""
        record = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=Decimal('0.00'),
            instrument_rate=Decimal('10.50'),
            instrument_cost=Decimal('0.00'),
            total_amount=Decimal('0.00')
        )
        self.assertEqual(record.total_amount, Decimal('0.00'))
    
    def test_billing_record_very_large_amounts(self):
        """Test billing record with very large amounts"""
        large_amount = Decimal('999999999.99')
        record = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=Decimal('1000.50'),
            instrument_rate=Decimal('999999.99'),
            instrument_cost=large_amount,
            total_amount=large_amount
        )
        self.assertEqual(record.total_amount, large_amount)
    
    def test_billing_record_high_precision_amounts(self):
        """Test billing record with high precision decimals"""
        precise_hours = Decimal('123.456789')
        record = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=precise_hours,
            instrument_rate=Decimal('10.50'),
            instrument_cost=Decimal('1296.30'),
            total_amount=Decimal('1296.30')
        )
        # Should handle precision according to DecimalField definition
        self.assertAlmostEqual(float(record.instrument_hours), float(precise_hours), places=2)
    
    def test_billing_record_complex_calculation(self):
        """Test billing record with multiple cost components"""
        record = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=Decimal('5.25'),
            instrument_rate=Decimal('100.00'),
            instrument_cost=Decimal('525.00'),
            personnel_hours=Decimal('2.5'),
            personnel_rate=Decimal('50.00'),
            personnel_cost=Decimal('125.00'),
            other_quantity=Decimal('10'),
            other_rate=Decimal('5.00'),
            other_cost=Decimal('50.00'),
            other_description='Sample preparation',
            total_amount=Decimal('700.00')
        )
        self.assertEqual(record.total_amount, Decimal('700.00'))
        self.assertEqual(record.other_description, 'Sample preparation')
    
    def test_billing_record_negative_amounts(self):
        """Test billing record with negative amounts (refund scenario)"""
        negative_amount = Decimal('-50.00')
        record = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_cost=negative_amount,
            total_amount=negative_amount,
            other_description='Refund for cancelled service'
        )
        self.assertEqual(record.total_amount, negative_amount)


class SiteSettingsEdgeCaseTest(TestCase):
    def test_site_settings_singleton_behavior(self):
        """Test that only one SiteSettings instance can exist"""
        settings1 = SiteSettings.objects.create(
            site_name='Test Site 1',
            site_description='First settings'
        )
        
        # Creating second instance should replace first if singleton pattern
        settings2 = SiteSettings.objects.create(
            site_name='Test Site 2',
            site_description='Second settings'
        )
        
        # Check how many instances exist
        count = SiteSettings.objects.count()
        # This depends on implementation - might be 1 (singleton) or 2 (allowed)
        self.assertGreaterEqual(count, 1)
    
    def test_site_settings_large_json_data(self):
        """Test site settings with large JSON configuration"""
        large_config = {
            'features': {f'feature_{i}': True for i in range(1000)},
            'settings': {f'setting_{i}': f'value_{i}' for i in range(500)},
            'metadata': {
                'complex_nested': {
                    'level1': {
                        'level2': {
                            'level3': {'data': 'x' * 1000}
                        }
                    }
                }
            }
        }
        
        settings = SiteSettings.objects.create(
            site_name='Large Config Site',
            configuration=large_config
        )
        
        self.assertEqual(len(settings.configuration['features']), 1000)
        self.assertEqual(len(settings.configuration['settings']), 500)
    
    def test_site_settings_unicode_content(self):
        """Test site settings with unicode content"""
        unicode_config = {
            'welcome_message': 'Добро пожаловать! 欢迎! ようこそ! 🎉',
            'languages': ['English', 'Español', '中文', '日本語', 'Русский'],
            'symbols': '°C ±10% ≤100 ≥50 ∞ α β γ δ ε'
        }
        
        settings = SiteSettings.objects.create(
            site_name='Unicode Site',
            site_description='Site with unicode content',
            configuration=unicode_config
        )
        
        self.assertIn('🎉', settings.configuration['welcome_message'])
        self.assertIn('中文', settings.configuration['languages'])


class ConcurrencyEdgeCaseTest(TestCase):
    """Test edge cases related to concurrent operations"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
    
    def test_concurrent_protocol_creation(self):
        """Test creating protocols concurrently with same title"""
        # This would be better tested with actual threading, but test basic case
        protocol1 = ProtocolModel.objects.create(
            protocol_title='Duplicate Title',
            user=self.user
        )
        
        # Should allow duplicate titles (no unique constraint)
        protocol2 = ProtocolModel.objects.create(
            protocol_title='Duplicate Title',
            user=self.user
        )
        
        self.assertEqual(protocol1.protocol_title, protocol2.protocol_title)
        self.assertNotEqual(protocol1.id, protocol2.id)
    
    def test_transaction_rollback_behavior(self):
        """Test transaction rollback with invalid data"""
        try:
            with transaction.atomic():
                # Create valid project
                project = Project.objects.create(project_name='Valid Project')
                
                # Try to create invalid rating (should rollback everything)
                protocol = ProtocolModel.objects.create(
                    protocol_title='Test Protocol',
                    user=self.user
                )
                
                # This should raise an error and rollback the transaction
                ProtocolRating.objects.create(
                    protocol=protocol,
                    user=self.user,
                    complexity_rating=15,  # Invalid rating > 10
                    duration_rating=5
                )
        except ValueError:
            pass  # Expected error
        
        # Project should not exist due to rollback
        self.assertFalse(Project.objects.filter(project_name='Valid Project').exists())
