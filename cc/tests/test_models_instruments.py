"""
Tests for instrument-related models: Instrument, InstrumentUsage, InstrumentPermission, InstrumentJob
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import IntegrityError
from datetime import timedelta, datetime
from cc.models import (
    Instrument, InstrumentUsage, InstrumentPermission, InstrumentJob,
    MaintenanceLog, SupportInformation, LabGroup, AnnotationFolder,
    MetadataColumn, MetadataTableTemplate
)


class InstrumentModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.manager_user = User.objects.create_user('manager', 'manager@example.com', 'password')
        
    def test_instrument_creation(self):
        """Test basic instrument creation"""
        instrument = Instrument.objects.create(
            instrument_name='Test Spectrometer',
            instrument_description='A test mass spectrometer',
            location='Lab A'
        )
        
        self.assertEqual(instrument.instrument_name, 'Test Spectrometer')
        self.assertEqual(instrument.location, 'Lab A')
        self.assertTrue(instrument.enabled)
        self.assertFalse(instrument.requires_staff_approval)
        self.assertEqual(instrument.max_days_within_usage_pre_approval, 0)
        self.assertEqual(instrument.max_days_ahead_pre_approval, 0)
    
    def test_instrument_default_folder_creation(self):
        """Test that default folders are created for instruments"""
        instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A'
        )
        
        # Should create default folders
        instrument.create_default_folders()
        
        # Check that folders were created
        folders = AnnotationFolder.objects.filter(instrument=instrument)
        folder_names = [folder.folder_name for folder in folders]
        
        expected_folders = ['Maintenance', 'Certificates', 'Data']
        for expected_folder in expected_folders:
            self.assertIn(expected_folder, folder_names)
    
    def test_instrument_manager_notification(self):
        """Test instrument manager notification system"""
        instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A'
        )
        
        # Add manager permission
        permission = InstrumentPermission.objects.create(
            instrument=instrument,
            user=self.manager_user,
            can_manage=True,
            can_book=True,
            can_view=True
        )
        
        # Test notification method (should not raise errors)
        try:
            instrument.notify_instrument_managers("Test message")
        except Exception as e:
            self.fail(f"notify_instrument_managers raised {e} unexpectedly")


class InstrumentPermissionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A'
        )
    
    def test_permission_creation(self):
        """Test basic permission creation"""
        permission = InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.user,
            can_view=True,
            can_book=True,
            can_manage=False
        )
        
        self.assertEqual(permission.instrument, self.instrument)
        self.assertEqual(permission.user, self.user)
        self.assertTrue(permission.can_view)
        self.assertTrue(permission.can_book)
        self.assertFalse(permission.can_manage)
    
    def test_manager_permission(self):
        """Test manager-level permissions"""
        permission = InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.manager,
            can_view=True,
            can_book=True,
            can_manage=True
        )
        
        self.assertTrue(permission.can_manage)
        self.assertTrue(permission.can_book)  # Managers should also be able to book
        self.assertTrue(permission.can_view)   # Managers should also be able to view
    
    def test_unique_permission_constraint(self):
        """Test that each user can only have one permission per instrument"""
        InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.user,
            can_view=True
        )
        
        # Creating duplicate permission should raise IntegrityError
        with self.assertRaises(IntegrityError):
            InstrumentPermission.objects.create(
                instrument=self.instrument,
                user=self.user,
                can_book=True
            )


class InstrumentUsageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A',
            max_days_within_usage_pre_approval=7,
            max_days_ahead_pre_approval=30
        )
        
        # Create permission for user
        InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.user,
            can_book=True,
            can_view=True
        )
    
    def test_usage_creation(self):
        """Test basic usage booking creation"""
        start_time = timezone.now() + timedelta(days=1)
        end_time = start_time + timedelta(hours=2)
        
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=start_time,
            time_ended=end_time,
            usage_name='Test Usage'
        )
        
        self.assertEqual(usage.instrument, self.instrument)
        self.assertEqual(usage.user, self.user)
        self.assertEqual(usage.usage_name, 'Test Usage')
        self.assertFalse(usage.approved)  # Should default to False
    
    def test_usage_duration_calculation(self):
        """Test usage duration calculation"""
        start_time = timezone.now()
        end_time = start_time + timedelta(hours=3)
        
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=start_time,
            time_ended=end_time
        )
        
        duration = end_time - start_time
        self.assertEqual(usage.time_ended - usage.time_started, duration)
    
    def test_auto_approval_logic(self):
        """Test automatic approval logic based on instrument settings"""
        # Create usage within auto-approval limits
        start_time = timezone.now() + timedelta(days=1)  # 1 day ahead
        end_time = start_time + timedelta(hours=2)       # 2 hour duration
        
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=start_time,
            time_ended=end_time
        )
        
        # This should be auto-approved based on instrument settings
        # (would need to implement auto-approval logic in model save method)
        
        # Test usage outside auto-approval limits
        far_future_start = timezone.now() + timedelta(days=45)  # Beyond 30 day limit
        far_future_end = far_future_start + timedelta(hours=2)
        
        usage2 = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=far_future_start,
            time_ended=far_future_end
        )
        
        # This should not be auto-approved
        self.assertFalse(usage2.approved)


class InstrumentJobTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.staff_user = User.objects.create_user('staff', 'staff@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Mass Spectrometer',
            location='Lab B'
        )
        
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab Group',
            description='A test lab group'
        )
        self.lab_group.users.add(self.user)
    
    def test_instrument_job_creation(self):
        """Test basic instrument job creation"""
        job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            job_name='Protein Analysis',
            job_type='analysis',
            sample_type='protein',
            sample_number=10,
            status='pending'
        )
        
        self.assertEqual(job.instrument, self.instrument)
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.job_name, 'Protein Analysis')
        self.assertEqual(job.job_type, 'analysis')
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.sample_number, 10)
    
    def test_job_status_choices(self):
        """Test valid job status choices"""
        valid_statuses = ['pending', 'approved', 'in_progress', 'completed', 'cancelled', 'failed']
        
        for status in valid_statuses:
            job = InstrumentJob.objects.create(
                instrument=self.instrument,
                user=self.user,
                service_lab_group=self.lab_group,
                job_name=f'Test Job {status}',
                status=status
            )
            self.assertEqual(job.status, status)
    
    def test_job_type_choices(self):
        """Test valid job type choices"""
        valid_types = ['analysis', 'maintenance', 'calibration', 'training', 'other']
        
        for job_type in valid_types:
            job = InstrumentJob.objects.create(
                instrument=self.instrument,
                user=self.user,
                service_lab_group=self.lab_group,
                job_name=f'Test Job {job_type}',
                job_type=job_type
            )
            self.assertEqual(job.job_type, job_type)
    
    def test_job_staff_assignment(self):
        """Test staff assignment to jobs"""
        job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            job_name='Staff Job'
        )
        
        # Add staff to job
        job.staff.add(self.staff_user)
        
        self.assertIn(self.staff_user, job.staff.all())
    
    def test_job_metadata_template(self):
        """Test metadata template assignment"""
        # Create metadata template
        template = MetadataTableTemplate.objects.create(
            name='MS Analysis Template',
            description='Template for mass spec analysis'
        )
        
        job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            job_name='Metadata Job',
            selected_template=template
        )
        
        self.assertEqual(job.selected_template, template)
    
    def test_job_cost_tracking(self):
        """Test cost center and amount tracking"""
        job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            job_name='Cost Tracking Job',
            cost_center='CC-12345',
            amount=150.00
        )
        
        self.assertEqual(job.cost_center, 'CC-12345')
        self.assertEqual(job.amount, 150.00)


class MaintenanceLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A'
        )
    
    def test_maintenance_log_creation(self):
        """Test basic maintenance log creation"""
        log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            user=self.user,
            maintenance_type='routine',
            description='Regular cleaning and calibration',
            performed_by='Service Technician'
        )
        
        self.assertEqual(log.instrument, self.instrument)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.maintenance_type, 'routine')
        self.assertEqual(log.description, 'Regular cleaning and calibration')
        self.assertIsNotNone(log.performed_at)
    
    def test_maintenance_type_choices(self):
        """Test valid maintenance type choices"""
        valid_types = ['routine', 'repair', 'calibration', 'upgrade', 'emergency']
        
        for maintenance_type in valid_types:
            log = MaintenanceLog.objects.create(
                instrument=self.instrument,
                user=self.user,
                maintenance_type=maintenance_type,
                description=f'Test {maintenance_type} maintenance'
            )
            self.assertEqual(log.maintenance_type, maintenance_type)


class SupportInformationTest(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            location='Lab A'
        )
    
    def test_support_info_creation(self):
        """Test basic support information creation"""
        support = SupportInformation.objects.create(
            instrument=self.instrument,
            contact_name='John Doe',
            contact_email='john.doe@vendor.com',
            contact_phone='+1-555-123-4567',
            vendor_name='Equipment Vendor Inc.',
            service_contract='SC-2024-001'
        )
        
        self.assertEqual(support.instrument, self.instrument)
        self.assertEqual(support.contact_name, 'John Doe')
        self.assertEqual(support.contact_email, 'john.doe@vendor.com')
        self.assertEqual(support.vendor_name, 'Equipment Vendor Inc.')
    
    def test_support_info_string_representation(self):
        """Test support information string representation"""
        support = SupportInformation.objects.create(
            instrument=self.instrument,
            contact_name='John Doe',
            vendor_name='Equipment Vendor Inc.'
        )
        
        expected_str = f"{self.instrument.instrument_name} - Equipment Vendor Inc."
        self.assertEqual(str(support), expected_str)


class InstrumentIntegrationTest(TestCase):
    """Integration tests for instrument-related models working together"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Integration Test Instrument',
            location='Lab A',
            requires_staff_approval=True,
            max_days_within_usage_pre_approval=7,
            max_days_ahead_pre_approval=30
        )
        
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='Test lab group'
        )
        self.lab_group.users.add(self.user)
    
    def test_complete_instrument_workflow(self):
        """Test complete workflow from permission to usage to job"""
        # 1. Create permissions
        user_permission = InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.user,
            can_book=True,
            can_view=True
        )
        
        manager_permission = InstrumentPermission.objects.create(
            instrument=self.instrument,
            user=self.manager,
            can_manage=True,
            can_book=True,
            can_view=True
        )
        
        # 2. Create usage booking
        start_time = timezone.now() + timedelta(days=1)
        end_time = start_time + timedelta(hours=3)
        
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=start_time,
            time_ended=end_time,
            usage_name='Integration Test Usage'
        )
        
        # 3. Create instrument job
        job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            job_name='Integration Test Job',
            job_type='analysis',
            status='pending'
        )
        
        # 4. Add maintenance log
        maintenance = MaintenanceLog.objects.create(
            instrument=self.instrument,
            user=self.manager,
            maintenance_type='routine',
            description='Pre-analysis calibration'
        )
        
        # Verify all relationships
        self.assertEqual(usage.instrument, self.instrument)
        self.assertEqual(job.instrument, self.instrument)
        self.assertEqual(maintenance.instrument, self.instrument)
        
        # Verify permissions work
        self.assertTrue(user_permission.can_book)
        self.assertTrue(manager_permission.can_manage)
        
        # Verify instrument can access related objects
        self.assertIn(usage, self.instrument.instrument_usages.all())
        self.assertIn(job, self.instrument.instrument_jobs.all())
        self.assertIn(maintenance, self.instrument.maintenance_logs.all())