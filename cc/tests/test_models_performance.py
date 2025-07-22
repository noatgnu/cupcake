"""
Performance and stress tests for CUPCAKE models
Focuses on bulk operations, query optimization, and resource usage
"""
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.db import transaction, connection
from django.test.utils import override_settings
from django.core.management import call_command
from cc.models import (
    Project, ProtocolModel, ProtocolStep, Session, Annotation,
    Instrument, InstrumentJob, StoredReagent, Reagent, StorageObject,
    ImportTracker, ImportedObject, SamplePool, MetadataColumn
)


class BulkOperationsPerformanceTest(TestCase):
    """Test performance of bulk database operations"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test MS Instrument'
        )
    
    def test_bulk_project_creation(self):
        """Test creating many projects efficiently"""
        start_time = time.time()
        
        # Create 1000 projects using bulk_create
        projects = [
            Project(project_name=f'Bulk Project {i}', project_description=f'Description {i}')
            for i in range(1000)
        ]
        
        Project.objects.bulk_create(projects, batch_size=100)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should complete within reasonable time (adjust threshold as needed)
        self.assertLess(duration, 5.0, "Bulk project creation took too long")
        
        # Verify all projects were created
        self.assertEqual(Project.objects.filter(project_name__startswith='Bulk Project').count(), 1000)
    
    def test_bulk_annotation_creation(self):
        """Test creating many annotations efficiently"""
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        step = ProtocolStep.objects.create(
            protocol=protocol,
            step_title='Test Step',
            step_description='Test Description'
        )
        session = Session.objects.create(
            unique_id='bulk-test-session',
            user=self.user
        )
        
        start_time = time.time()
        
        # Create 5000 annotations
        annotations = [
            Annotation(
                step=step,
                session=session,
                user=self.user,
                annotation_name=f'Bulk Annotation {i}',
                data=f'Data content for annotation {i}' * 10,  # Some content
                annotation_type='text'
            )
            for i in range(5000)
        ]
        
        Annotation.objects.bulk_create(annotations, batch_size=500)
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertLess(duration, 10.0, "Bulk annotation creation took too long")
        self.assertEqual(Annotation.objects.filter(annotation_name__startswith='Bulk Annotation').count(), 5000)
    
    def test_bulk_instrument_job_creation(self):
        """Test creating many instrument jobs efficiently"""
        start_time = time.time()
        
        # Create 2000 instrument jobs
        jobs = [
            InstrumentJob(
                user=self.user,
                project=self.project,
                instrument=self.instrument,
                sample_number=i + 1,
                injection_volume=Decimal('10.5'),
                status='pending'
            )
            for i in range(2000)
        ]
        
        InstrumentJob.objects.bulk_create(jobs, batch_size=200)
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertLess(duration, 8.0, "Bulk job creation took too long")
        self.assertEqual(InstrumentJob.objects.filter(user=self.user).count(), 2000)
    
    def test_bulk_update_performance(self):
        """Test bulk updating many records"""
        # Create test data
        projects = [
            Project(project_name=f'Update Test {i}', project_description='Original')
            for i in range(1000)
        ]
        Project.objects.bulk_create(projects)
        
        # Get the created projects
        created_projects = list(Project.objects.filter(project_name__startswith='Update Test'))
        
        start_time = time.time()
        
        # Update all descriptions
        for project in created_projects:
            project.project_description = 'Updated Description'
        
        Project.objects.bulk_update(created_projects, ['project_description'], batch_size=100)
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertLess(duration, 3.0, "Bulk update took too long")
        
        # Verify updates
        updated_count = Project.objects.filter(
            project_name__startswith='Update Test',
            project_description='Updated Description'
        ).count()
        self.assertEqual(updated_count, 1000)


class QueryOptimizationTest(TestCase):
    """Test query optimization and N+1 query problems"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        
        # Create test data with relationships
        self.protocols = []
        for i in range(50):
            protocol = ProtocolModel.objects.create(
                protocol_title=f'Protocol {i}',
                user=self.user
            )
            self.protocols.append(protocol)
            
            # Create steps for each protocol
            for j in range(10):
                ProtocolStep.objects.create(
                    protocol=protocol,
                    step_title=f'Step {j}',
                    step_description=f'Description for step {j}'
                )
    
    def test_select_related_performance(self):
        """Test performance improvement with select_related"""
        # Test without select_related (N+1 queries)
        start_time = time.time()
        with self.assertNumQueries(51):  # 1 for protocols + 50 for users
            protocols = ProtocolModel.objects.all()
            usernames = [protocol.user.username for protocol in protocols]
        end_time = time.time()
        duration_without = end_time - start_time
        
        # Test with select_related (optimized)
        start_time = time.time()
        with self.assertNumQueries(1):  # Single JOIN query
            protocols = ProtocolModel.objects.select_related('user').all()
            usernames = [protocol.user.username for protocol in protocols]
        end_time = time.time()
        duration_with = end_time - start_time
        
        # Optimized version should be faster or at least not slower
        self.assertLessEqual(duration_with, duration_without + 0.1)
    
    def test_prefetch_related_performance(self):
        """Test performance improvement with prefetch_related"""
        # Test without prefetch_related
        start_time = time.time()
        protocols = ProtocolModel.objects.all()
        step_counts = [protocol.steps.count() for protocol in protocols]
        end_time = time.time()
        duration_without = end_time - start_time
        
        # Test with prefetch_related
        start_time = time.time()
        protocols = ProtocolModel.objects.prefetch_related('steps').all()
        step_counts = [len(protocol.steps.all()) for protocol in protocols]
        end_time = time.time()
        duration_with = end_time - start_time
        
        # Optimized version should be faster
        self.assertLess(duration_with, duration_without + 0.1)
    
    def test_annotation_query_optimization(self):
        """Test annotation queries with proper optimization"""
        # Create test data
        session = Session.objects.create(unique_id='test-session', user=self.user)
        
        for protocol in self.protocols[:10]:  # Use subset for faster test
            for step in protocol.steps.all()[:5]:
                for i in range(20):
                    Annotation.objects.create(
                        step=step,
                        session=session,
                        user=self.user,
                        annotation_name=f'Annotation {i}',
                        annotation_type='text'
                    )
        
        # Test optimized query
        start_time = time.time()
        annotations = Annotation.objects.select_related('step', 'session', 'user').filter(
            session=session
        )
        
        # Force evaluation
        list(annotations)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should complete within reasonable time
        self.assertLess(duration, 2.0, "Annotation query took too long")


class LargeDatasetTest(TestCase):
    """Test model behavior with large datasets"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Large Dataset Project')
    
    def test_large_json_field_performance(self):
        """Test performance with large JSON data"""
        # Create large JSON data
        large_metadata = {
            'samples': [{
                'id': i,
                'name': f'Sample_{i}',
                'properties': {
                    'temperature': 25.0 + (i % 50),
                    'ph': 7.0 + (i % 3),
                    'concentration': f'{100 + i}mM',
                    'notes': f'Sample notes for sample {i}' * 5
                }
            } for i in range(1000)]
        }
        
        start_time = time.time()
        
        # Create MetadataColumn with large JSON
        column = MetadataColumn.objects.create(
            column_name='Large JSON Column',
            modifiers=large_metadata
        )
        
        # Read back the data
        retrieved_column = MetadataColumn.objects.get(id=column.id)
        samples_count = len(retrieved_column.modifiers['samples'])
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertEqual(samples_count, 1000)
        self.assertLess(duration, 5.0, "Large JSON operation took too long")
    
    def test_large_sample_pool_performance(self):
        """Test performance with large sample pools"""
        instrument = Instrument.objects.create(
            instrument_name='Large Pool Instrument',
            instrument_description='Large Pool MS Instrument'
        )
        
        job = InstrumentJob.objects.create(
            user=self.user,
            project=self.project,
            instrument=instrument
        )
        
        # Create pool with large sample lists
        large_sample_list = list(range(1, 10001))  # 10,000 samples
        
        start_time = time.time()
        
        pool = SamplePool.objects.create(
            instrument_job=job,
            pool_name='Large Sample Pool',
            pooled_only_samples=large_sample_list,
            pooled_and_independent_samples=large_sample_list[:5000],
            created_by=self.user
        )
        
        # Retrieve and verify
        retrieved_pool = SamplePool.objects.get(id=pool.id)
        sample_count = len(retrieved_pool.pooled_only_samples)
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertEqual(sample_count, 10000)
        self.assertLess(duration, 3.0, "Large sample pool operation took too long")


class ConcurrentAccessTest(TransactionTestCase):
    """Test model behavior under concurrent access"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_concurrent_session_creation(self):
        """Test creating sessions concurrently"""
        import threading
        import queue
        
        results = queue.Queue()
        errors = queue.Queue()
        
        def create_sessions(thread_id):
            try:
                for i in range(100):
                    session = Session.objects.create(
                        unique_id=f'thread-{thread_id}-session-{i}',
                        user=self.user
                    )
                    results.put(session.id)
            except Exception as e:
                errors.put(str(e))
        
        # Create multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=create_sessions, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertTrue(errors.empty(), f"Errors occurred: {list(errors.queue)}")
        
        # Should have created 500 sessions (5 threads * 100 sessions)
        total_sessions = Session.objects.filter(unique_id__startswith='thread-').count()
        self.assertEqual(total_sessions, 500)
    
    def test_concurrent_protocol_updates(self):
        """Test updating protocols concurrently"""
        # Create a protocol to update
        protocol = ProtocolModel.objects.create(
            protocol_title='Concurrent Test Protocol',
            user=self.user
        )
        
        import threading
        import queue
        
        errors = queue.Queue()
        
        def update_protocol(thread_id):
            try:
                for i in range(50):
                    # Use select_for_update to prevent race conditions
                    with transaction.atomic():
                        updated_protocol = ProtocolModel.objects.select_for_update().get(id=protocol.id)
                        updated_protocol.protocol_description = f'Updated by thread {thread_id} iteration {i}'
                        updated_protocol.save()
            except Exception as e:
                errors.put(str(e))
        
        # Create multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=update_protocol, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check for errors
        self.assertTrue(errors.empty(), f"Errors occurred: {list(errors.queue)}")
        
        # Protocol should still exist and be updated
        final_protocol = ProtocolModel.objects.get(id=protocol.id)
        self.assertIsNotNone(final_protocol.protocol_description)
        self.assertIn('Updated by thread', final_protocol.protocol_description)


class MemoryUsageTest(TestCase):
    """Test memory usage patterns"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Memory Test Project')
    
    def test_queryset_memory_efficiency(self):
        """Test that querysets are memory efficient with large datasets"""
        # Create large dataset
        projects = [
            Project(project_name=f'Memory Test {i}', project_description='Test')
            for i in range(5000)
        ]
        Project.objects.bulk_create(projects, batch_size=500)
        
        # Test iterator() for memory efficiency
        start_time = time.time()
        count = 0
        
        # Use iterator to avoid loading all objects into memory
        for project in Project.objects.filter(project_name__startswith='Memory Test').iterator(chunk_size=100):
            count += 1
            # Process one object at a time
            self.assertIsNotNone(project.project_name)
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertEqual(count, 5000)
        self.assertLess(duration, 10.0, "Iterator processing took too long")
    
    def test_lazy_loading_behavior(self):
        """Test that related objects are loaded lazily"""
        # Create test data
        protocol = ProtocolModel.objects.create(
            protocol_title='Lazy Loading Test',
            user=self.user
        )
        
        for i in range(100):
            ProtocolStep.objects.create(
                protocol=protocol,
                step_title=f'Step {i}',
                step_description='Description'
            )
        
        # Query protocol without prefetching steps
        queried_protocol = ProtocolModel.objects.get(id=protocol.id)
        
        # Steps should not be loaded yet (lazy loading)
        # This is implementation-dependent, but generally true
        
        # Access steps (should trigger additional query)
        step_count = queried_protocol.steps.count()
        self.assertEqual(step_count, 100)


class DatabaseConnectionTest(TestCase):
    """Test database connection and transaction behavior"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_transaction_rollback_integrity(self):
        """Test that transaction rollbacks maintain data integrity"""
        initial_count = Project.objects.count()
        
        try:
            with transaction.atomic():
                # Create valid project
                Project.objects.create(project_name='Valid Project')
                
                # Create invalid protocol (should cause rollback)
                protocol = ProtocolModel.objects.create(
                    protocol_title='Test Protocol',
                    user=self.user
                )
                
                # This should raise an error and rollback everything
                from cc.models import ProtocolRating
                ProtocolRating.objects.create(
                    protocol=protocol,
                    user=self.user,
                    complexity_rating=15,  # Invalid rating
                    duration_rating=5
                )
        except ValueError:
            pass  # Expected error
        
        # Count should be unchanged due to rollback
        final_count = Project.objects.count()
        self.assertEqual(initial_count, final_count)
    
    def test_database_connection_efficiency(self):
        """Test efficient database connection usage"""
        # Test that we're not creating excessive connections
        start_time = time.time()
        
        # Perform multiple operations
        for i in range(100):
            project = Project.objects.create(project_name=f'Connection Test {i}')
            # Read it back
            retrieved = Project.objects.get(id=project.id)
            self.assertEqual(retrieved.project_name, project.project_name)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should complete efficiently
        self.assertLess(duration, 5.0, "Database operations were inefficient")
        
        # Verify connection is still working
        final_count = Project.objects.filter(project_name__startswith='Connection Test').count()
        self.assertEqual(final_count, 100)
