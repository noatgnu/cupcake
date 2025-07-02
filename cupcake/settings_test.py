"""
Django settings for CUPCAKE LIMS testing environment
Inherits from main settings but optimized for testing
"""

from .settings import *
import os

# Override settings for testing
DEBUG = True
TESTING = True

# Database configuration for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_NAME', 'cupcake_test'),
        'USER': os.environ.get('POSTGRES_USER', 'test_user'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'test_password'),
        'HOST': os.environ.get('POSTGRES_HOST', 'test-db'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'TEST': {
            'NAME': 'test_cupcake_test',
        },
    }
}

# Redis configuration for testing
REDIS_HOST = os.environ.get('REDIS_HOST', 'test-redis')
REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', 'test_redis_password')

# RQ configuration for testing
RQ_QUEUES = {
    'default': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 0,
        'DEFAULT_TIMEOUT': 360,
    },
    'transcribe': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 1,
        'DEFAULT_TIMEOUT': 3600,
    },
    'llama': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 2,
        'DEFAULT_TIMEOUT': 3600,
    },
    'export': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 3,
        'DEFAULT_TIMEOUT': 3600,
    },
    'import-data': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 4,
        'DEFAULT_TIMEOUT': 3600,
    },
    'ocr': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 5,
        'DEFAULT_TIMEOUT': 1800,
    },
    'maintenance': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'PASSWORD': REDIS_PASSWORD,
        'DB': 6,
        'DEFAULT_TIMEOUT': 1800,
    }
}

# Test secret key
SECRET_KEY = os.environ.get('SECRET_KEY', 'test-secret-key-for-testing-only-not-secure')

# Media and static files for testing
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', '/app/test_media')
STATIC_ROOT = os.environ.get('STATIC_ROOT', '/app/test_static')

# Disable external services during testing
USE_COTURN = os.environ.get('USE_COTURN', 'False').lower() == 'true'
USE_LLM = os.environ.get('USE_LLM', 'False').lower() == 'true'
USE_WHISPER = os.environ.get('USE_WHISPER', 'False').lower() == 'true'
USE_OCR = os.environ.get('USE_OCR', 'False').lower() == 'true'

# Disable Slack notifications during testing
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# Email backend for testing
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable caching during tests
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Password validation (simplified for testing)
AUTH_PASSWORD_VALIDATORS = []

# Logging configuration for testing
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'cc': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}

# Test-specific file upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE

# Faster password hashing for tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Test runner configuration
TEST_RUNNER = 'django.test.runner.DiscoverRunner'

# Allowed hosts for testing
ALLOWED_HOSTS = ['localhost', 'test-app', '127.0.0.1', 'testserver']

# CORS settings for testing
CORS_ORIGIN_WHITELIST = [
    'http://localhost',
    'http://test-app',
    'http://127.0.0.1',
]

# Disable migrations during tests (optional - speeds up tests)
class DisableMigrations:
    def __contains__(self, item):
        return True
    
    def __getitem__(self, item):
        return None

# Uncomment to disable migrations (faster tests but may miss migration issues)
# MIGRATION_MODULES = DisableMigrations()

# Test file paths
TEST_FIXTURE_DIR = '/app/test_fixtures'
TEST_MEDIA_DIR = '/app/test_media'
TEST_COVERAGE_DIR = '/app/test_coverage'