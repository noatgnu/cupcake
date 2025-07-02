# CUPCAKE LIMS Test Suite

Comprehensive testing environment for CUPCAKE LIMS that mirrors production infrastructure while being optimized for testing.

## Overview

This test suite provides:

- **Unit Tests**: Individual component testing using Django's test framework
- **Integration Tests**: Full API and workflow testing
- **Performance Tests**: Load testing with Locust
- **Coverage Reporting**: Code coverage analysis
- **Static Analysis**: Code quality and security analysis

## Quick Start

### Using the Test Runner (Recommended)

```bash
# Run all tests
python tests/run_tests.py

# Run specific test types
python tests/run_tests.py --test-type unit
python tests/run_tests.py --test-type integration
python tests/run_tests.py --test-type performance

# Run comprehensive suite with performance and static analysis
python tests/run_tests.py --include-performance --include-static
```

### Using Docker Compose Directly

```bash
cd tests/

# Build test environment
docker-compose -f docker-compose.test.yml build

# Run unit tests
docker-compose -f docker-compose.test.yml run --rm test-runner

# Run integration tests  
docker-compose -f docker-compose.test.yml up -d test-app test-worker
docker-compose -f docker-compose.test.yml run --rm integration-test

# Run performance tests
docker-compose -f docker-compose.test.yml up -d test-app
docker-compose -f docker-compose.test.yml up performance-test

# Cleanup
docker-compose -f docker-compose.test.yml down -v
```

## Test Environment Architecture

### Services

1. **test-db** (PostgreSQL 14)
   - Isolated test database
   - Health checks for readiness
   - Test fixtures pre-loaded

2. **test-redis** (Redis 7)
   - Background task queue
   - Session storage
   - Caching layer

3. **test-app** (Django Application)
   - Main CUPCAKE LIMS application
   - Test-specific settings
   - Health check endpoint

4. **test-worker** (RQ Worker)
   - Background task processing
   - Minimal configuration for testing

5. **test-runner** (Comprehensive Test Runner)
   - Django unit tests
   - Coverage reporting
   - Static analysis tools

6. **integration-test** (API Testing)
   - Full API endpoint testing
   - Authentication testing
   - Workflow validation

7. **performance-test** (Load Testing)
   - Locust-based performance testing
   - Concurrent user simulation
   - Performance metrics

### Key Features

- **Isolated Environment**: Completely separate from development/production
- **Health Checks**: Ensures services are ready before testing
- **Parallel Testing**: Leverages Django's parallel test runner
- **Coverage Reports**: HTML and XML coverage reports
- **Performance Metrics**: Detailed performance analysis
- **Easy Cleanup**: Automatic environment cleanup

## Test Categories

### 1. Unit Tests (`cc/tests/`)

Located in the main Django app, these test individual models, views, and utilities:

- **Model Tests**: Database model validation and business logic
- **View Tests**: API endpoint functionality
- **Utility Tests**: Helper functions and utilities
- **Permission Tests**: Access control and security

```bash
# Run all unit tests
python tests/run_tests.py --test-type unit

# Run specific test files
docker-compose -f tests/docker-compose.test.yml run --rm test-runner \
  python manage.py test cc.tests.test_models_core
```

### 2. Integration Tests (`tests/integration/`)

End-to-end testing of complete workflows:

- **API Endpoints**: Full REST API testing
- **Background Tasks**: RQ task processing
- **Authentication**: Token-based auth flows
- **Data Workflows**: Complete CRUD operations

```bash
# Run integration tests
python tests/run_tests.py --test-type integration
```

### 3. Performance Tests (`tests/performance/`)

Load testing and performance analysis:

- **Concurrent Users**: Simulated user load
- **API Performance**: Response time analysis
- **Database Load**: Query performance under load
- **Memory Usage**: Resource utilization

```bash
# Run performance tests
python tests/run_tests.py --test-type performance --performance-users 20 --performance-duration 10m

# Interactive performance testing
docker-compose -f tests/docker-compose.test.yml up performance-test
# Access web interface at http://localhost:8089
```

## Configuration

### Test Settings

Test-specific Django settings in `cupcake/settings_test.py`:

- **Database**: PostgreSQL test database
- **Redis**: Test Redis instance
- **External Services**: Disabled (LLM, OCR, etc.)
- **Media Files**: Test media directory
- **Logging**: Optimized for testing

### Environment Variables

Key environment variables for testing:

```bash
DJANGO_SETTINGS_MODULE=cupcake.settings_test
POSTGRES_NAME=cupcake_test
POSTGRES_USER=test_user
POSTGRES_PASSWORD=test_password
POSTGRES_HOST=test-db
REDIS_HOST=test-redis
REDIS_PASSWORD=test_redis_password
SECRET_KEY=test-secret-key-for-testing-only-not-secure
```

### Test Fixtures

Initial test data in `tests/fixtures/initial_data.json`:

- **Users**: Admin and test users
- **Projects**: Sample projects
- **Lab Groups**: Test laboratory groups
- **Site Settings**: Test configuration

## Coverage Reports

Coverage analysis tracks code execution during tests:

```bash
# Generate coverage report
python tests/run_tests.py --test-type coverage

# View HTML report
docker-compose -f tests/docker-compose.test.yml run --rm test-runner \
  coverage html
```

Coverage reports are generated in:
- **HTML**: `test_coverage/htmlcov/index.html`
- **XML**: `test_coverage/coverage.xml`

### Coverage Configuration

Coverage settings in `tests/.coveragerc`:

- **Source**: All application code
- **Omit**: Migrations, tests, virtual environments
- **Thresholds**: Minimum coverage requirements
- **Output**: HTML and XML formats

## Static Analysis

Code quality and security analysis:

```bash
# Run static analysis
python tests/run_tests.py --test-type static
```

Tools included:
- **Flake8**: Style and syntax checking
- **Bandit**: Security vulnerability scanning
- **Safety**: Dependency security analysis

## Performance Testing

### Locust Configuration

Performance tests simulate realistic user behavior:

- **User Classes**: Different user types (normal, high-volume, database-intensive)
- **Task Weights**: Realistic distribution of operations
- **Wait Times**: Human-like delays between actions
- **Monitoring**: Response time and error tracking

### Performance Metrics

Key metrics tracked:
- **Response Times**: Average, median, 95th percentile
- **Requests/Second**: Throughput under load
- **Error Rates**: Failed request percentage
- **Resource Usage**: CPU, memory, database connections

### Example Performance Test

```bash
# Custom performance test
docker-compose -f tests/docker-compose.test.yml run --rm performance-test \
  locust -f /app/performance_tests/locustfile.py \
  --host=http://test-app:8000 \
  --headless \
  --users 50 \
  --spawn-rate 5 \
  --run-time 15m
```

## Continuous Integration

### GitHub Actions Integration

Example workflow file:

```yaml
name: CUPCAKE LIMS Test Suite
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Test Suite
        run: |
          cd tests
          python run_tests.py --include-static
```

### Test Automation

Automated testing features:
- **Parallel Execution**: Multiple test processes
- **Fail Fast**: Stop on first failure (optional)
- **Retry Logic**: Retry flaky tests
- **Artifact Collection**: Test reports and logs

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check database health
   docker-compose -f tests/docker-compose.test.yml exec test-db \
     pg_isready -U test_user -d cupcake_test
   ```

2. **Redis Connection Issues**
   ```bash
   # Test Redis connectivity
   docker-compose -f tests/docker-compose.test.yml exec test-redis \
     redis-cli -a test_redis_password ping
   ```

3. **Service Startup Delays**
   ```bash
   # Check service logs
   docker-compose -f tests/docker-compose.test.yml logs test-app
   ```

4. **Port Conflicts**
   - Ensure ports 5434, 6381, 8002, 8089 are available
   - Modify port mappings in docker-compose.test.yml if needed

### Debug Mode

Run tests with additional debugging:

```bash
# Verbose test output
python tests/run_tests.py --test-type unit --verbose

# Keep containers running for debugging
docker-compose -f tests/docker-compose.test.yml up -d
# Debug using: docker exec -it cupcake-test-app bash
```

### Performance Debugging

Monitor system resources during tests:

```bash
# Monitor container resources
docker stats

# Check database queries
docker-compose -f tests/docker-compose.test.yml exec test-db \
  psql -U test_user -d cupcake_test -c "SELECT * FROM pg_stat_activity;"
```

## Best Practices

### Writing Tests

1. **Isolation**: Each test should be independent
2. **Setup/Teardown**: Use proper test fixtures
3. **Naming**: Descriptive test method names
4. **Documentation**: Comment complex test logic
5. **Performance**: Avoid unnecessary database queries

### Test Data

1. **Fixtures**: Use JSON fixtures for consistent test data
2. **Factories**: Use Factory Boy for dynamic test data
3. **Cleanup**: Ensure proper test data cleanup
4. **Realistic Data**: Use realistic test scenarios

### Performance Testing

1. **Gradual Load**: Ramp up users gradually
2. **Realistic Scenarios**: Simulate actual user behavior
3. **Monitoring**: Watch for memory leaks and resource issues
4. **Baselines**: Establish performance baselines

## Development Workflow

### Adding New Tests

1. **Unit Tests**: Add to appropriate `cc/tests/test_*.py` file
2. **Integration Tests**: Add to `tests/integration/`
3. **Performance Tests**: Update `tests/performance/locustfile.py`
4. **Run Tests**: Verify new tests pass
5. **Coverage**: Ensure adequate test coverage

### Test-Driven Development

1. Write failing test first
2. Implement minimal code to pass
3. Refactor while keeping tests green
4. Add integration tests for workflows
5. Verify performance impact

This comprehensive test suite ensures CUPCAKE LIMS maintains high quality, performance, and reliability across all development stages.