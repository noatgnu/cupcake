"""
Performance tests for CUPCAKE LIMS using Locust
Tests API endpoints under load to identify performance bottlenecks
"""
import json
import random
from locust import HttpUser, task, between, events
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CupcakeAPIUser(HttpUser):
    """Simulated CUPCAKE LIMS user for performance testing"""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Initialize user session and authenticate"""
        self.admin_token = None
        self.user_token = None
        self.project_ids = []
        self.session_ids = []
        self.protocol_ids = []
        
        # Authenticate as admin
        response = self.client.post("/api/token-auth/", data={
            "username": "testadmin",
            "password": "testpassword123"
        })
        
        if response.status_code == 200:
            self.admin_token = response.json()["token"]
            self.headers = {"Authorization": f"Token {self.admin_token}"}
            logger.info("Admin authentication successful")
        else:
            logger.error(f"Admin authentication failed: {response.status_code}")
    
    def on_stop(self):
        """Cleanup resources when user stops"""
        # Clean up created projects
        for project_id in self.project_ids:
            self.client.delete(f"/api/project/{project_id}/", headers=self.headers)
        
        # Clean up created sessions  
        for session_id in self.session_ids:
            self.client.delete(f"/api/session/{session_id}/", headers=self.headers)
    
    @task(10)
    def list_projects(self):
        """List all projects - most common operation"""
        response = self.client.get("/api/project/", headers=self.headers)
        if response.status_code == 200:
            projects = response.json().get("results", [])
            # Store some project IDs for other operations
            if projects and len(self.project_ids) < 5:
                self.project_ids.extend([p["id"] for p in projects[:3]])
    
    @task(8)
    def list_sessions(self):
        """List protocol sessions"""
        response = self.client.get("/api/session/", headers=self.headers)
        if response.status_code == 200:
            sessions = response.json().get("results", [])
            if sessions and len(self.session_ids) < 5:
                self.session_ids.extend([s["id"] for s in sessions[:3]])
    
    @task(6)
    def list_protocols(self):
        """List protocols"""
        response = self.client.get("/api/protocol/", headers=self.headers)
        if response.status_code == 200:
            protocols = response.json().get("results", [])
            if protocols and len(self.protocol_ids) < 5:
                self.protocol_ids.extend([p["id"] for p in protocols[:3]])
    
    @task(5)
    def get_project_detail(self):
        """Get detailed project information"""
        if self.project_ids:
            project_id = random.choice(self.project_ids)
            self.client.get(f"/api/project/{project_id}/", headers=self.headers)
    
    @task(5)
    def get_session_detail(self):
        """Get detailed session information"""
        if self.session_ids:
            session_id = random.choice(self.session_ids)
            self.client.get(f"/api/session/{session_id}/", headers=self.headers)
    
    @task(4)
    def get_protocol_detail(self):
        """Get detailed protocol information"""
        if self.protocol_ids:
            protocol_id = random.choice(self.protocol_ids)
            self.client.get(f"/api/protocol/{protocol_id}/", headers=self.headers)
    
    @task(3)
    def create_project(self):
        """Create new project"""
        project_data = {
            "project_name": f"Performance Test Project {random.randint(1000, 9999)}",
            "project_description": "Created during performance testing"
        }
        
        response = self.client.post(
            "/api/project/",
            json=project_data,
            headers=self.headers
        )
        
        if response.status_code == 201:
            project_id = response.json()["id"]
            self.project_ids.append(project_id)
    
    @task(3)
    def create_session(self):
        """Create new session"""
        response = self.client.post("/api/session/", headers=self.headers)
        
        if response.status_code == 201:
            session_id = response.json()["id"]
            self.session_ids.append(session_id)
    
    @task(2)
    def update_project(self):
        """Update existing project"""
        if self.project_ids:
            project_id = random.choice(self.project_ids)
            update_data = {
                "project_description": f"Updated during performance test at {random.randint(1000, 9999)}"
            }
            
            self.client.patch(
                f"/api/project/{project_id}/",
                json=update_data,
                headers=self.headers
            )
    
    @task(2)
    def search_projects(self):
        """Search projects by name"""
        search_terms = ["test", "alpha", "beta", "protocol", "experiment"]
        search_term = random.choice(search_terms)
        
        self.client.get(
            f"/api/project/?search={search_term}",
            headers=self.headers
        )
    
    @task(2)
    def list_lab_groups(self):
        """List laboratory groups"""
        self.client.get("/api/lab_groups/", headers=self.headers)
    
    @task(2)
    def list_annotations(self):
        """List annotations"""
        self.client.get("/api/annotation/", headers=self.headers)
    
    @task(1)
    def get_site_settings(self):
        """Get site settings"""
        self.client.get("/api/site_settings/", headers=self.headers)
    
    @task(1)
    def get_public_site_settings(self):
        """Get public site settings (no auth required)"""
        self.client.get("/api/site_settings/public/")
    
    @task(1)
    def list_users(self):
        """List users (admin only)"""
        self.client.get("/api/user/", headers=self.headers)
    
    @task(1)
    def get_user_protocols(self):
        """Get user's protocols"""
        self.client.get("/api/protocol/get_user_protocols/", headers=self.headers)
    
    @task(1)
    def paginated_requests(self):
        """Test pagination performance"""
        # Test different page sizes
        page_sizes = [10, 25, 50, 100]
        page_size = random.choice(page_sizes)
        
        self.client.get(
            f"/api/project/?limit={page_size}&offset=0",
            headers=self.headers
        )
    
    @task(1)
    def filtered_requests(self):
        """Test filtering performance"""
        # Test date-based filtering
        self.client.get(
            "/api/project/?created_at__gte=2024-01-01",
            headers=self.headers
        )
    
    @task(1)
    def ordered_requests(self):
        """Test ordering performance"""
        ordering_fields = ["project_name", "-created_at", "updated_at"]
        ordering = random.choice(ordering_fields)
        
        self.client.get(
            f"/api/project/?ordering={ordering}",
            headers=self.headers
        )


class HighVolumeUser(HttpUser):
    """High-volume user for stress testing"""
    
    wait_time = between(0.1, 0.5)  # Very short wait time
    weight = 1  # Lower weight - fewer instances
    
    def on_start(self):
        """Quick authentication"""
        response = self.client.post("/api/token-auth/", data={
            "username": "testadmin",
            "password": "testpassword123"
        })
        
        if response.status_code == 200:
            self.admin_token = response.json()["token"]
            self.headers = {"Authorization": f"Token {self.admin_token}"}
    
    @task(20)
    def rapid_project_list(self):
        """Rapid project listing for stress testing"""
        self.client.get("/api/project/?limit=10", headers=self.headers)
    
    @task(10)
    def rapid_session_list(self):
        """Rapid session listing"""
        self.client.get("/api/session/?limit=10", headers=self.headers)
    
    @task(5)
    def rapid_public_settings(self):
        """Rapid public settings access"""
        self.client.get("/api/sitesettings/public/")


# Event handlers for performance monitoring
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    """Log slow requests"""
    if response_time > 2000:  # Log requests taking more than 2 seconds
        logger.warning(f"Slow request: {request_type} {name} took {response_time}ms")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts"""
    logger.info("Starting CUPCAKE LIMS performance test")
    logger.info(f"Target host: {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops"""
    logger.info("CUPCAKE LIMS performance test completed")
    
    # Log summary statistics
    stats = environment.stats
    logger.info(f"Total requests: {stats.total.num_requests}")
    logger.info(f"Total failures: {stats.total.num_failures}")
    logger.info(f"Average response time: {stats.total.avg_response_time}ms")
    logger.info(f"Max response time: {stats.total.max_response_time}ms")


# Custom task sets for specific scenarios
class DatabaseIntensiveUser(HttpUser):
    """User performing database-intensive operations"""
    
    wait_time = between(2, 5)
    weight = 1  # Lower weight
    
    def on_start(self):
        response = self.client.post("/api/token-auth/", data={
            "username": "testadmin",
            "password": "testpassword123"
        })
        
        if response.status_code == 200:
            self.admin_token = response.json()["token"]
            self.headers = {"Authorization": f"Token {self.admin_token}"}
    
    @task(5)
    def complex_search(self):
        """Complex search operations"""
        self.client.get(
            "/api/protocol/?search=test&ordering=-created_at&limit=50",
            headers=self.headers
        )
    
    @task(3)
    def large_pagination(self):
        """Large pagination requests"""
        self.client.get(
            "/api/annotation/?limit=100&offset=0",
            headers=self.headers
        )
    
    @task(2)
    def multiple_filters(self):
        """Multiple filter combinations"""
        self.client.get(
            "/api/session/?created_at__gte=2024-01-01&ordering=created_at&limit=25",
            headers=self.headers
        )


if __name__ == "__main__":
    # Run with: locust -f locustfile.py --host=http://test-app:8000
    pass