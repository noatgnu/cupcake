"""
Tests for SamplePool model - pooled sample functionality for SDRF compliance
"""
import json
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from cc.models import (
    SamplePool, InstrumentJob, Instrument, LabGroup, MetadataColumn, 
    MetadataTableTemplate, Project
)


class SamplePoolModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Test MS Instrument',
            instrument_description='Test mass spectrometer for pool testing'
        )
        self.lab_group = LabGroup.objects.create(
            name='Test Lab Group',
            description='Test lab group for pool testing'
        )
        self.project = Project.objects.create(
            project_name='Test Project',
            project_description='Test project for pool testing',
            owner=self.user
        )
        
        self.instrument_job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            project=self.project,
            job_type='analysis',
            sample_number=10  # Set to 10 samples
        )
    
    def test_sample_pool_creation(self):
        """Test basic sample pool creation"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Test Pool 1',
            pool_description='First test pool',
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[4, 5],
            created_by=self.user
        )
        
        self.assertEqual(pool.pool_name, 'Test Pool 1')
        self.assertEqual(pool.pool_description, 'First test pool')
        self.assertEqual(pool.pooled_only_samples, [1, 2, 3])
        self.assertEqual(pool.pooled_and_independent_samples, [4, 5])
        self.assertEqual(pool.created_by, self.user)
        self.assertFalse(pool.is_reference)  # Default should be False
        
    def test_sample_pool_unique_constraint(self):
        """Test unique constraint on instrument_job and pool_name"""
        # Create first pool
        SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Duplicate Pool',
            created_by=self.user
        )
        
        # Try to create second pool with same name
        with self.assertRaises(Exception):  # Should raise IntegrityError
            SamplePool.objects.create(
                instrument_job=self.instrument_job,
                pool_name='Duplicate Pool',
                created_by=self.user
            )
    
    def test_sample_pool_clean_validation(self):
        """Test validation logic in clean method"""
        # Test overlapping samples (should fail)
        pool = SamplePool(
            instrument_job=self.instrument_job,
            pool_name='Invalid Pool',
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[3, 4, 5],  # 3 appears in both
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            pool.clean()
        
        self.assertIn('pooled only', str(context.exception))
        self.assertIn('pooled and independent', str(context.exception))
    
    def test_sample_pool_sample_index_validation(self):
        """Test validation of sample indices against job sample number"""
        # Test invalid sample indices (outside valid range)
        pool = SamplePool(
            instrument_job=self.instrument_job,
            pool_name='Invalid Range Pool',
            pooled_only_samples=[0, 11, 15],  # 0 too low, 11 and 15 too high (max is 10)
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            pool.clean()
        
        error_message = str(context.exception)
        self.assertIn('0', error_message)
        self.assertIn('11', error_message)
        self.assertIn('15', error_message)
        self.assertIn('between 1 and 10', error_message)
    
    def test_all_pooled_samples_property(self):
        """Test all_pooled_samples property returns sorted unique samples"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Test Pool',
            pooled_only_samples=[3, 1, 5],
            pooled_and_independent_samples=[7, 2],
            created_by=self.user
        )
        
        all_samples = pool.all_pooled_samples
        self.assertEqual(all_samples, [1, 2, 3, 5, 7])  # Should be sorted
    
    def test_total_samples_count_property(self):
        """Test total_samples_count property"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Count Test Pool',
            pooled_only_samples=[1, 3, 5],
            pooled_and_independent_samples=[2, 4],
            created_by=self.user
        )
        
        self.assertEqual(pool.total_samples_count, 5)
    
    def test_get_sample_status_method(self):
        """Test get_sample_status method"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Status Test Pool',
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[3, 4],
            created_by=self.user
        )
        
        self.assertEqual(pool.get_sample_status(1), 'pooled_only')
        self.assertEqual(pool.get_sample_status(3), 'pooled_and_independent')
        self.assertEqual(pool.get_sample_status(5), 'not_in_pool')
    
    def test_add_sample_method(self):
        """Test add_sample method"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Add Sample Test Pool',
            pooled_only_samples=[1],
            created_by=self.user
        )
        
        # Add pooled_only sample
        pool.add_sample(2, 'pooled_only')
        self.assertIn(2, pool.pooled_only_samples)
        self.assertEqual(pool.pooled_only_samples, [1, 2])  # Should be sorted
        
        # Add pooled_and_independent sample
        pool.add_sample(3, 'pooled_and_independent')
        self.assertIn(3, pool.pooled_and_independent_samples)
        
        # Change existing sample status (should move from one list to another)
        pool.add_sample(1, 'pooled_and_independent')
        self.assertNotIn(1, pool.pooled_only_samples)
        self.assertIn(1, pool.pooled_and_independent_samples)
    
    def test_remove_sample_method(self):
        """Test remove_sample method"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Remove Sample Test Pool',
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[4, 5],
            created_by=self.user
        )
        
        # Remove from pooled_only
        pool.remove_sample(2)
        self.assertEqual(pool.pooled_only_samples, [1, 3])
        
        # Remove from pooled_and_independent
        pool.remove_sample(4)
        self.assertEqual(pool.pooled_and_independent_samples, [5])
        
        # Remove non-existent sample (should not raise error)
        pool.remove_sample(10)
        self.assertEqual(pool.pooled_only_samples, [1, 3])
        self.assertEqual(pool.pooled_and_independent_samples, [5])
    
    def test_template_sample_functionality(self):
        """Test template sample functionality"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Template Test Pool',
            template_sample=3,
            pooled_only_samples=[1, 2],
            created_by=self.user
        )
        
        self.assertEqual(pool.template_sample, 3)
    
    def test_reference_pool_functionality(self):
        """Test is_reference field functionality"""
        # Create reference pool
        ref_pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Reference Pool',
            is_reference=True,
            pooled_only_samples=[1, 2, 3],
            created_by=self.user
        )
        
        # Create regular pool
        regular_pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Regular Pool',
            is_reference=False,
            pooled_only_samples=[4, 5],
            created_by=self.user
        )
        
        self.assertTrue(ref_pool.is_reference)
        self.assertFalse(regular_pool.is_reference)
    
    def test_metadata_relationships(self):
        """Test metadata relationships similar to InstrumentJob"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Metadata Test Pool',
            pooled_only_samples=[1, 2],
            created_by=self.user
        )
        
        # Create metadata columns
        user_metadata = MetadataColumn.objects.create(
            name='Pool User Meta',
            value='user_value',
            type='text'
        )
        
        staff_metadata = MetadataColumn.objects.create(
            name='Pool Staff Meta',
            value='staff_value',
            type='text'
        )
        
        # Add metadata to pool
        pool.user_metadata.add(user_metadata)
        pool.staff_metadata.add(staff_metadata)
        
        # Verify relationships
        self.assertIn(user_metadata, pool.user_metadata.all())
        self.assertIn(staff_metadata, pool.staff_metadata.all())
        
        # Verify reverse relationships
        self.assertIn(pool, user_metadata.sample_pools.all())
        self.assertIn(pool, staff_metadata.assigned_sample_pools.all())


class SamplePoolSDRFTest(TestCase):
    """Test SDRF-specific functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Test MS',
            instrument_description='Test instrument'
        )
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab'
        )
        self.project = Project.objects.create(
            project_name='Test Project',
            owner=self.user
        )
        
        self.instrument_job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            project=self.project,
            job_type='analysis',
            sample_number=6
        )
    
    def test_sdrf_value_without_source_names(self):
        """Test SDRF value generation without Source name metadata"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='SDRF Test Pool',
            pooled_only_samples=[1, 3, 5],
            created_by=self.user
        )
        
        # Without Source name metadata, should use fallback format
        sdrf_value = pool.sdrf_value
        self.assertEqual(sdrf_value, 'SN=sample 1,sample 3,sample 5')
    
    def test_sdrf_value_with_source_names(self):
        """Test SDRF value generation with Source name metadata"""
        # Create Source name metadata column
        source_name_column = MetadataColumn.objects.create(
            name='Source name',
            value='DefaultSample',
            type='text',
            modifiers=json.dumps([
                {"samples": "1", "value": "Heart_Sample_001"},
                {"samples": "3", "value": "Liver_Sample_003"},
                {"samples": "5", "value": "Kidney_Sample_005"}
            ])
        )
        
        # Add to instrument job
        self.instrument_job.user_metadata.add(source_name_column)
        
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='SDRF Source Names Pool',
            pooled_only_samples=[1, 3, 5],
            created_by=self.user
        )
        
        sdrf_value = pool.sdrf_value
        self.assertEqual(sdrf_value, 'SN=Heart_Sample_001,Liver_Sample_003,Kidney_Sample_005')
    
    def test_sdrf_value_empty_pool(self):
        """Test SDRF value for empty pool"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Empty Pool',
            pooled_only_samples=[],
            pooled_and_independent_samples=[],
            created_by=self.user
        )
        
        sdrf_value = pool.sdrf_value
        self.assertEqual(sdrf_value, 'not pooled')
    
    def test_parse_sample_indices_from_modifier_string(self):
        """Test _parse_sample_indices_from_modifier_string method"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Parser Test Pool',
            created_by=self.user
        )
        
        # Test single numbers
        indices = pool._parse_sample_indices_from_modifier_string("1,3,5")
        self.assertEqual(sorted(indices), [1, 3, 5])
        
        # Test ranges
        indices = pool._parse_sample_indices_from_modifier_string("1-3,5")
        self.assertEqual(sorted(indices), [1, 2, 3, 5])
        
        # Test complex ranges
        indices = pool._parse_sample_indices_from_modifier_string("1-2,4-6")
        self.assertEqual(sorted(indices), [1, 2, 4, 5, 6])
        
        # Test empty string
        indices = pool._parse_sample_indices_from_modifier_string("")
        self.assertEqual(indices, [])
        
        # Test invalid formats (should handle gracefully)
        indices = pool._parse_sample_indices_from_modifier_string("invalid,1,bad-range")
        self.assertEqual(indices, [1])  # Should parse the valid ones
    
    def test_source_names_with_default_value(self):
        """Test source name extraction with default value"""
        # Create Source name metadata with default value
        source_name_column = MetadataColumn.objects.create(
            name='Source name',
            value='DefaultSample',
            type='text'
        )
        self.instrument_job.user_metadata.add(source_name_column)
        
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Default Value Pool',
            pooled_only_samples=[1, 2, 3],
            created_by=self.user
        )
        
        source_names = pool._get_source_names_for_samples()
        
        # All samples should have the default value
        for i in range(1, self.instrument_job.sample_number + 1):
            self.assertEqual(source_names[i], 'DefaultSample')


class SamplePoolIntegrationTest(TestCase):
    """Integration tests for SamplePool with other models"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.instrument = Instrument.objects.create(
            instrument_name='Integration Test MS',
            instrument_description='Test instrument for integration'
        )
        self.lab_group = LabGroup.objects.create(
            name='Integration Test Lab',
            description='Test lab for integration'
        )
        self.project = Project.objects.create(
            project_name='Integration Test Project',
            owner=self.user
        )
        
        self.instrument_job = InstrumentJob.objects.create(
            instrument=self.instrument,
            user=self.user,
            service_lab_group=self.lab_group,
            project=self.project,
            job_type='analysis',
            sample_number=12
        )
    
    def test_complete_pool_workflow(self):
        """Test complete workflow with pools and metadata"""
        # 1. Create metadata template
        template = MetadataTableTemplate.objects.create(
            name='Pool Test Template',
            user=self.user
        )
        
        # 2. Create metadata columns
        source_name_col = MetadataColumn.objects.create(
            name='Source name',
            value='Sample',
            type='text',
            modifiers=json.dumps([
                {"samples": "1-3", "value": "Group_A"},
                {"samples": "4-6", "value": "Group_B"},
                {"samples": "7-9", "value": "Group_C"}
            ])
        )
        
        concentration_col = MetadataColumn.objects.create(
            name='Concentration',
            value='1.0',
            type='number',
            modifiers=json.dumps([
                {"samples": "1,4,7", "value": "2.0"},
                {"samples": "2,5,8", "value": "1.5"}
            ])
        )
        
        # 3. Add metadata to job
        self.instrument_job.user_metadata.add(source_name_col, concentration_col)
        
        # 4. Create pools
        pool1 = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Pool_A',
            pool_description='Samples from Group A',
            pooled_only_samples=[1, 2, 3],
            is_reference=True,
            created_by=self.user
        )
        
        pool2 = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Pool_B',
            pool_description='Mixed samples',
            pooled_only_samples=[4],
            pooled_and_independent_samples=[5, 6],
            template_sample=4,
            created_by=self.user
        )
        
        # 5. Add metadata to pools
        pool_meta = MetadataColumn.objects.create(
            name='Pool Type',
            value='Reference',
            type='text'
        )
        pool1.user_metadata.add(pool_meta)
        
        # Test relationships
        self.assertEqual(pool1.instrument_job, self.instrument_job)
        self.assertEqual(pool2.instrument_job, self.instrument_job)
        
        # Test SDRF values
        pool1_sdrf = pool1.sdrf_value
        self.assertEqual(pool1_sdrf, 'SN=Group_A,Group_A,Group_A')
        
        pool2_sdrf = pool2.sdrf_value
        self.assertEqual(pool2_sdrf, 'SN=Group_B,Group_B,Group_B')
        
        # Test metadata inheritance
        self.assertIn(pool_meta, pool1.user_metadata.all())
        
        # Test sample status queries
        self.assertEqual(pool2.get_sample_status(4), 'pooled_only')
        self.assertEqual(pool2.get_sample_status(5), 'pooled_and_independent')
        self.assertEqual(pool2.get_sample_status(7), 'not_in_pool')
        
        # Test sample counting
        self.assertEqual(pool1.total_samples_count, 3)
        self.assertEqual(pool2.total_samples_count, 3)
        
        # Verify pools can be retrieved from job
        job_pools = self.instrument_job.sample_pools.all()
        self.assertIn(pool1, job_pools)
        self.assertIn(pool2, job_pools)
        self.assertEqual(job_pools.count(), 2)
    
    def test_pool_deletion_cascade(self):
        """Test that pools are deleted when job is deleted"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Deletion Test Pool',
            pooled_only_samples=[1, 2],
            created_by=self.user
        )
        
        pool_id = pool.id
        
        # Delete the job
        self.instrument_job.delete()
        
        # Pool should be deleted due to CASCADE
        with self.assertRaises(SamplePool.DoesNotExist):
            SamplePool.objects.get(id=pool_id)
    
    def test_pool_string_representation(self):
        """Test pool string representation"""
        pool = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='String Test Pool',
            created_by=self.user
        )
        
        expected_str = f"String Test Pool - Job {self.instrument_job.id}"
        self.assertEqual(str(pool), expected_str)
    
    def test_pool_ordering(self):
        """Test pool ordering (should be by -created_at)"""
        pool1 = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='First Pool',
            created_by=self.user
        )
        
        pool2 = SamplePool.objects.create(
            instrument_job=self.instrument_job,
            pool_name='Second Pool',
            created_by=self.user
        )
        
        pools = SamplePool.objects.filter(instrument_job=self.instrument_job)
        self.assertEqual(list(pools), [pool2, pool1])  # Most recent first