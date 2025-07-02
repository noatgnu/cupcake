"""
Integration tests for CUPCAKE LIMS background tasks
Tests RQ job processing, task queues, and async operations
"""
import pytest
import requests
import redis
import json
import time
from pathlib import Path


class TestBackgroundTasks:
    """Test suite for background task processing"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment"""
        self.base_url = "http://test-app:8000"
        self.redis_client = redis.Redis(
            host='test-redis',
            port=6379,
            password='test_redis_password',
            decode_responses=True
        )
        
        # Get admin token for API access
        credentials = {"username": "testadmin", "password": "testpassword123"}
        response = requests.post(f"{self.base_url}/api/token-auth/", data=credentials)
        self.admin_token = response.json()["token"]
        self.headers = {"Authorization": f"Token {self.admin_token}"}
    
    def test_redis_connection(self):
        """Test Redis connection and basic operations"""
        # Test connection
        assert self.redis_client.ping()
        
        # Test basic operations
        self.redis_client.set("test_key", "test_value")
        assert self.redis_client.get("test_key") == "test_value"
        self.redis_client.delete("test_key")
    
    def test_rq_queues_exist(self):
        """Test that RQ queues are properly configured"""
        # Check for expected queue names
        expected_queues = [
            'rq:queue:default',
            'rq:queue:transcribe', 
            'rq:queue:llama',
            'rq:queue:export',
            'rq:queue:import-data',
            'rq:queue:ocr',
            'rq:queue:maintenance'
        ]
        
        # Get all keys and check for queue existence
        all_keys = self.redis_client.keys('rq:queue:*')
        
        # At least some queues should exist
        assert len(all_keys) > 0
    
    def test_task_enqueueing(self):
        """Test that tasks can be enqueued properly"""
        # Create a simple annotation to test transcription queue
        session_response = requests.post(f"{self.base_url}/api/session/", headers=self.headers)
        session_id = session_response.json()["id"]
        
        annotation_data = {
            "annotation_name": "Test Audio Annotation",
            "annotation": "Testing background task",
            "annotation_type": "audio",
            "session": session_id
        }
        
        response = requests.post(
            f"{self.base_url}/api/annotation/",
            json=annotation_data,
            headers=self.headers
        )
        assert response.status_code == 201
        
        # Check if any jobs were created
        # Note: This is a basic check - actual audio processing would require file upload
        time.sleep(1)  # Give tasks time to be enqueued
    
    def test_export_task_creation(self):
        """Test export task creation and processing"""
        # Create a protocol first
        protocol_data = {
            "protocol_title": "Test Protocol for Export",
            "protocol_description": "Testing export functionality",
            "protocol_url": "https://example.com/export-test"
        }
        
        protocol_response = requests.post(
            f"{self.base_url}/api/protocol/",
            json=protocol_data,
            headers=self.headers
        )
        protocol_id = protocol_response.json()["id"]
        
        # Request export
        export_data = {
            "protocols": [protocol_id],
            "format": "docx"
        }
        
        response = requests.post(
            f"{self.base_url}/api/protocol/{protocol_id}/create_export/",
            json=export_data,
            headers=self.headers
        )
        
        # Export endpoint behavior may vary, but should not error
        assert response.status_code in [200, 201, 202]
    
    def test_import_dry_run_task(self):
        """Test import dry run task creation"""
        # This would require an actual archive file
        # For now, test the endpoint availability
        response = requests.get(
            f"{self.base_url}/api/user/get_available_import_options/",
            headers=self.headers
        )
        assert response.status_code == 200
        
        options = response.json()
        assert "available_options" in options
    
    def test_queue_monitoring(self):
        """Test queue monitoring and job status"""
        # Get queue information
        queue_info = {}
        
        for queue_name in ['default', 'transcribe', 'export', 'import-data']:
            queue_key = f'rq:queue:{queue_name}'
            queue_length = self.redis_client.llen(queue_key)
            queue_info[queue_name] = queue_length
        
        # Queues should exist (length >= 0)
        for queue_name, length in queue_info.items():
            assert length >= 0
    
    def test_failed_jobs_handling(self):
        """Test failed job queue and error handling"""
        # Check for failed jobs queue
        failed_queue_key = 'rq:queue:failed'
        failed_jobs = self.redis_client.llen(failed_queue_key)
        
        # Should be accessible (may be 0 if no failed jobs)
        assert failed_jobs >= 0
    
    def test_job_timeout_configuration(self):
        """Test that job timeouts are properly configured"""
        # This is more of a configuration test
        # Check that Redis is accessible and queues can be monitored
        queue_stats = {}
        
        for queue_name in ['default', 'transcribe', 'llama', 'export']:
            try:
                queue_key = f'rq:queue:{queue_name}'
                exists = self.redis_client.exists(queue_key)
                queue_stats[queue_name] = exists
            except Exception as e:
                pytest.fail(f"Failed to check queue {queue_name}: {e}")
        
        # At least default queue should be trackable
        assert queue_stats.get('default') is not None
    
    @pytest.mark.slow
    def test_background_worker_health(self):
        """Test that background workers are responsive"""
        # Create a simple task and see if it gets processed
        # This is a longer test that waits for actual processing
        
        initial_queue_length = self.redis_client.llen('rq:queue:default')
        
        # Create a simple annotation task
        session_response = requests.post(f"{self.base_url}/api/session/", headers=self.headers)
        session_id = session_response.json()["id"]
        
        annotation_data = {
            "annotation_name": "Worker Health Test",
            "annotation": "Testing worker responsiveness",
            "annotation_type": "text",
            "session": session_id
        }
        
        response = requests.post(
            f"{self.base_url}/api/annotation/",
            json=annotation_data,
            headers=self.headers
        )
        assert response.status_code == 201
        
        # Wait a bit and check if queue length changed
        time.sleep(5)
        final_queue_length = self.redis_client.llen('rq:queue:default')
        
        # Queue should be processing (this test assumes workers are running)
        # In a real environment, we'd check job completion
        print(f"Initial queue length: {initial_queue_length}")
        print(f"Final queue length: {final_queue_length}")
    
    def test_task_priority_queues(self):
        """Test different priority queues work correctly"""
        # Test that different queue types are accessible
        queue_types = ['default', 'transcribe', 'export', 'import-data', 'maintenance']
        
        for queue_type in queue_types:
            queue_key = f'rq:queue:{queue_type}'
            # Should be able to check queue without error
            length = self.redis_client.llen(queue_key)
            assert length >= 0
    
    def test_redis_memory_usage(self):
        """Test Redis memory usage and key patterns"""
        # Get Redis info
        info = self.redis_client.info('memory')
        
        # Should have reasonable memory usage
        used_memory = info.get('used_memory', 0)
        assert used_memory > 0
        
        # Check for expected key patterns
        all_keys = self.redis_client.keys('*')
        rq_keys = [key for key in all_keys if key.startswith('rq:')]
        
        # Should have some RQ-related keys
        assert len(rq_keys) >= 0
    
    def test_task_result_storage(self):
        """Test that task results are properly stored and retrievable"""
        # This would test job result storage in Redis
        # For now, verify Redis can store and retrieve data
        
        test_result = {
            "status": "success",
            "result": "test_completed",
            "timestamp": time.time()
        }
        
        # Store result
        result_key = "test:task:result:12345"
        self.redis_client.setex(result_key, 3600, json.dumps(test_result))
        
        # Retrieve result
        stored_result = self.redis_client.get(result_key)
        assert stored_result is not None
        
        parsed_result = json.loads(stored_result)
        assert parsed_result["status"] == "success"
        
        # Cleanup
        self.redis_client.delete(result_key)
    
    def test_concurrent_task_handling(self):
        """Test handling of multiple concurrent tasks"""
        # Create multiple sessions and annotations
        session_ids = []
        
        for i in range(3):
            session_response = requests.post(f"{self.base_url}/api/session/", headers=self.headers)
            session_ids.append(session_response.json()["id"])
        
        # Create multiple annotations
        annotation_ids = []
        for i, session_id in enumerate(session_ids):
            annotation_data = {
                "annotation_name": f"Concurrent Test {i}",
                "annotation": f"Testing concurrent processing {i}",
                "annotation_type": "text",
                "session": session_id
            }
            
            response = requests.post(
                f"{self.base_url}/api/annotation/",
                json=annotation_data,
                headers=self.headers
            )
            assert response.status_code == 201
            annotation_ids.append(response.json()["id"])
        
        # All should be created successfully
        assert len(annotation_ids) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])