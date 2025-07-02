#!/usr/bin/env python
"""
CUPCAKE LIMS Test Runner
Comprehensive test execution script for the dev container environment
"""

import os
import sys
import subprocess
import argparse
import time
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CupcakeTestRunner:
    """Comprehensive test runner for CUPCAKE LIMS"""
    
    def __init__(self, project_root=None):
        if project_root is None:
            # Auto-detect project root based on script location
            script_dir = Path(__file__).parent  # tests/
            self.project_root = script_dir.parent  # cupcake/
        else:
            self.project_root = Path(project_root)
        
        self.test_dir = self.project_root / "tests"
        self.compose_file = self.test_dir / "docker-compose.test.yml"
        
        # Log detected paths
        logger.info(f"Project root: {self.project_root}")
        logger.info(f"Test directory: {self.test_dir}")
        logger.info(f"Compose file: {self.compose_file}")
        
        # Verify paths exist
        if not self.project_root.exists():
            raise FileNotFoundError(f"Project root does not exist: {self.project_root}")
        if not self.test_dir.exists():
            raise FileNotFoundError(f"Test directory does not exist: {self.test_dir}")
        if not self.compose_file.exists():
            raise FileNotFoundError(f"Docker compose file does not exist: {self.compose_file}")
        
    def run_command(self, command, cwd=None, check=True):
        """Run a shell command with logging"""
        cwd = cwd or self.project_root
        logger.info(f"Running: {command}")
        
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                cwd=cwd, 
                capture_output=True, 
                text=True,
                check=check
            )
            
            if result.stdout:
                logger.info(f"STDOUT: {result.stdout}")
            if result.stderr and result.returncode != 0:
                logger.error(f"STDERR: {result.stderr}")
                
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e}")
            if e.stdout:
                logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                logger.error(f"STDERR: {e.stderr}")
            raise
    
    def setup_test_environment(self):
        """Set up the test environment"""
        logger.info("Setting up test environment...")
        
        # Clean up any existing test environment first
        logger.info("Cleaning up any existing test containers...")
        self.cleanup_test_environment()
        
        # Build test containers
        self.run_command(
            f"docker-compose -f {self.compose_file} build",
            cwd=self.test_dir
        )
        
        # Start core services (db, redis)
        self.run_command(
            f"docker-compose -f {self.compose_file} up -d test-db test-redis",
            cwd=self.test_dir
        )
        
        # Wait for services to be healthy
        logger.info("Waiting for services to be ready...")
        time.sleep(10)
        
        # Check service health
        self.check_service_health()
    
    def check_service_health(self):
        """Check that core services are healthy"""
        logger.info("Checking service health...")
        
        # Check database
        result = self.run_command(
            f"docker-compose -f {self.compose_file} exec -T test-db pg_isready -U test_user -d cupcake_test",
            cwd=self.test_dir,
            check=False
        )
        
        if result.returncode != 0:
            raise RuntimeError("Database is not ready")
        
        # Check Redis
        result = self.run_command(
            f"docker-compose -f {self.compose_file} exec -T test-redis redis-cli -a test_redis_password ping",
            cwd=self.test_dir,
            check=False
        )
        
        if result.returncode != 0:
            raise RuntimeError("Redis is not ready")
        
        logger.info("All services are healthy")
    
    def run_unit_tests(self):
        """Run Django unit tests"""
        logger.info("Running unit tests...")
        
        # Start test runner service
        result = self.run_command(
            f"docker-compose -f {self.compose_file} run --rm test-runner "
            f"python manage.py test cc.tests --keepdb --parallel auto --verbosity=2",
            cwd=self.test_dir
        )
        
        return result.returncode == 0
    
    def run_integration_tests(self):
        """Run integration tests"""
        logger.info("Running integration tests...")
        
        # Start application services
        self.run_command(
            f"docker-compose -f {self.compose_file} up -d test-app test-worker",
            cwd=self.test_dir
        )
        
        # Wait for app to be ready
        logger.info("Waiting for application to start...")
        time.sleep(20)
        
        # Run integration tests
        result = self.run_command(
            f"docker-compose -f {self.compose_file} run --rm integration-test",
            cwd=self.test_dir
        )
        
        return result.returncode == 0
    
    def run_performance_tests(self, duration="5m", users=10):
        """Run performance tests with Locust"""
        logger.info(f"Running performance tests for {duration} with {users} users...")
        
        # Ensure app services are running
        self.run_command(
            f"docker-compose -f {self.compose_file} up -d test-app test-worker",
            cwd=self.test_dir
        )
        
        # Wait for services
        time.sleep(15)
        
        # Run Locust headless
        result = self.run_command(
            f"docker-compose -f {self.compose_file} run --rm performance-test "
            f"locust -f /app/performance_tests/locustfile.py "
            f"--host=http://test-app:8000 --headless "
            f"--users {users} --spawn-rate 1 --run-time {duration}",
            cwd=self.test_dir
        )
        
        return result.returncode == 0
    
    def run_coverage_report(self):
        """Generate coverage report"""
        logger.info("Generating coverage report...")
        
        result = self.run_command(
            f"docker-compose -f {self.compose_file} run --rm test-runner "
            f"sh -c 'coverage run --rcfile=/app/.coveragerc manage.py test cc.tests --keepdb && "
            f"coverage report && coverage html'",
            cwd=self.test_dir
        )
        
        return result.returncode == 0
    
    def run_static_analysis(self):
        """Run static analysis tools"""
        logger.info("Running static analysis...")
        
        commands = [
            # Flake8 for style checking
            "flake8 cc/ --max-line-length=120 --exclude=migrations,__pycache__",
            # Bandit for security analysis  
            "bandit -r cc/ -x cc/tests/,cc/migrations/",
            # Safety for dependency security
            "safety check --json",
        ]
        
        all_passed = True
        for cmd in commands:
            try:
                self.run_command(
                    f"docker-compose -f {self.compose_file} run --rm test-runner {cmd}",
                    cwd=self.test_dir
                )
            except subprocess.CalledProcessError:
                all_passed = False
                logger.warning(f"Static analysis command failed: {cmd}")
        
        return all_passed
    
    def cleanup_test_environment(self):
        """Clean up test environment"""
        logger.info("Cleaning up test environment...")
        
        # Stop and remove all containers, networks, and volumes
        self.run_command(
            f"docker-compose -f {self.compose_file} down -v --remove-orphans",
            cwd=self.test_dir,
            check=False
        )
        
        # Additional cleanup to remove any lingering test networks
        self.run_command(
            "docker network prune -f",
            check=False
        )
    
    def run_all_tests(self, include_performance=False, include_static=False):
        """Run the complete test suite"""
        logger.info("Starting comprehensive test suite...")
        
        results = {
            'setup': False,
            'unit': False,
            'integration': False,
            'performance': False,
            'coverage': False,
            'static': False
        }
        
        try:
            # Setup
            self.setup_test_environment()
            results['setup'] = True
            
            # Unit tests
            results['unit'] = self.run_unit_tests()
            
            # Integration tests
            results['integration'] = self.run_integration_tests()
            
            # Performance tests (optional)
            if include_performance:
                results['performance'] = self.run_performance_tests()
            
            # Coverage report
            results['coverage'] = self.run_coverage_report()
            
            # Static analysis (optional)
            if include_static:
                results['static'] = self.run_static_analysis()
            
        except Exception as e:
            logger.error(f"Test suite failed with error: {e}")
            results['error'] = str(e)
        
        finally:
            # Always cleanup
            self.cleanup_test_environment()
        
        # Report results
        self.report_results(results)
        
        return all(results.values())
    
    def report_results(self, results):
        """Report test results"""
        logger.info("\n" + "="*60)
        logger.info("TEST RESULTS SUMMARY")
        logger.info("="*60)
        
        for test_type, passed in results.items():
            if test_type == 'error':
                continue
            status = "✅ PASSED" if passed else "❌ FAILED"
            logger.info(f"{test_type.upper():<15}: {status}")
        
        if 'error' in results:
            logger.error(f"ERROR: {results['error']}")
        
        total_tests = len([k for k in results.keys() if k != 'error'])
        passed_tests = sum(1 for k, v in results.items() if k != 'error' and v)
        
        logger.info("="*60)
        logger.info(f"OVERALL: {passed_tests}/{total_tests} test suites passed")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED!")
        else:
            logger.warning("⚠️  Some tests failed - check logs above")


def main():
    parser = argparse.ArgumentParser(description="CUPCAKE LIMS Test Runner")
    parser.add_argument("--test-type", choices=[
        'all', 'unit', 'integration', 'performance', 'coverage', 'static'
    ], default='all', help="Type of tests to run")
    parser.add_argument("--include-performance", action='store_true',
                       help="Include performance tests in 'all' run")
    parser.add_argument("--include-static", action='store_true',
                       help="Include static analysis in 'all' run")
    parser.add_argument("--performance-duration", default="5m",
                       help="Duration for performance tests")
    parser.add_argument("--performance-users", type=int, default=10,
                       help="Number of users for performance tests")
    parser.add_argument("--project-root", default=None,
                       help="Project root directory (auto-detected if not provided)")
    
    args = parser.parse_args()
    
    runner = CupcakeTestRunner(args.project_root)
    
    try:
        if args.test_type == 'all':
            success = runner.run_all_tests(
                include_performance=args.include_performance,
                include_static=args.include_static
            )
        elif args.test_type == 'unit':
            runner.setup_test_environment()
            success = runner.run_unit_tests()
            runner.cleanup_test_environment()
        elif args.test_type == 'integration':
            runner.setup_test_environment()
            success = runner.run_integration_tests()
            runner.cleanup_test_environment()
        elif args.test_type == 'performance':
            runner.setup_test_environment()
            success = runner.run_performance_tests(
                duration=args.performance_duration,
                users=args.performance_users
            )
            runner.cleanup_test_environment()
        elif args.test_type == 'coverage':
            runner.setup_test_environment()
            success = runner.run_coverage_report()
            runner.cleanup_test_environment()
        elif args.test_type == 'static':
            success = runner.run_static_analysis()
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.info("Test run interrupted by user")
        runner.cleanup_test_environment()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test run failed: {e}")
        runner.cleanup_test_environment()
        sys.exit(1)


if __name__ == "__main__":
    main()