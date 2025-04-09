"""
Django settings for cupcake project.

Generated by 'django-admin startproject' using Django 5.0.3.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", 'django-insecure-29x1mu@2n0m#go9vq)17zzcrsr4@6n$s%(v9jfn+1))v^%ggao')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True
if os.environ.get("DEBUG", "True") == "False":
    DEBUG = False

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'corsheaders',
    'channels',
    'django_rq',
    'django_filters',
    'cc.apps.CcConfig',
    'rest_framework',
    'rest_framework.authtoken',
    'dbbackup',
    'drf_chunked_upload',
]

MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'cc.middlewares.XCupcakeInstanceIDMiddleware'
]

ROOT_URLCONF = 'cupcake.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'cupcake.wsgi.application'
ASGI_APPLICATION = 'cupcake.asgi.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

SQLITE_BACKUP_LOCATION = os.environ.get("SQLITE_DB_PATH", None)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'postgres'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5433'),
        'TEST': {
            'DEPENDENCIES': [],
        }
    },

}
if SQLITE_BACKUP_LOCATION:
    DATABASES['backup_db'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': SQLITE_BACKUP_LOCATION,
    }

# if test environment, use sqlite
if os.environ.get("ENV", "dev") == "test":
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Rest Framework settings

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20
}


CORS_EXPOSED_HEADERS = [
    "Set-Cookie"
]
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "withCredentials",
    "http_x_xsrf_token",
    "content-range",
    "content-disposition",
    "x-cupcake-instance-id",
    "http_x_cupcake_instance_id",
    'http-x-session-token',
    "http-x-csrftoken",
    'x-session-token',
]
CSRF_COOKIE_NAME = "csrfToken"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
CSRF_USE_SESSIONS = False
CSRF_COOKIE_HTTPONLY = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
CSRF_TRUSTED_ORIGINS = os.environ.get("CORS_ORIGIN_WHITELIST", "http://localhost:4200").split(",")
CORS_ORIGIN_WHITELIST = os.environ.get("CORS_ORIGIN_WHITELIST", "http://localhost:4200").split(",")
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT"
]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")

DBBACKUP_STORAGE = 'django.core.files.storage.FileSystemStorage'
DBBACKUP_STORAGE_OPTIONS = {
    "location": os.environ.get("BACKUP_DIR", "/app/backup")
}

DBBACKUP_CONNECTORS = {
    'default': {
        'dump_cmd': 'pg_dump --no-owner --no-acl --no-privileges',
        'restore_cmd': 'pg_restore --no-owner --no-acl --no-privileges --disable-triggers',
        'RESTORE_SUFFIX': '--if-exists'
    }
}


# Protocols.io Access Token
PROTOCOLS_IO_ACCESS_TOKEN = os.environ.get('PROTOCOLS_IO_ACCESS_TOKEN', 'access_token')


# Redis settings
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = os.environ.get("REDIS_PORT", "6380")
REDIS_DB = os.environ.get("REDIS_DB", "0")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "redis")
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,
        }
    }
}

# Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "symmetric_encryption_keys": [SECRET_KEY]
        },
    },
}

# Django-RQ settings
RQ_QUEUES = {
    'default': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    },
    'transcribe': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    },
    'export': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    },
    'llama': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    },
    'ocr': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    },
    'import-data': {
        'HOST': REDIS_HOST,
        'PORT': REDIS_PORT,
        'DB': REDIS_DB,
        'PASSWORD': REDIS_PASSWORD,
        'DEFAULT_TIMEOUT': 360,
    }
}



# Storage settings
STORAGES = {
    # ...
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
SENDFILE_BACKEND = 'django_sendfile.backends.simple'
SENDFILE_ROOT = MEDIA_ROOT

WHISPERCPP_PATH = os.environ.get("WHISPERCPP_PATH", "/app/whisper.cpp/build/bin/whisper-cli")
WHISPERCPP_DEFAULT_MODEL = os.environ.get("WHISPERCPP_DEFAULT_MODEL", "/app/whisper.cpp/models/ggml-medium.bin")
WHISPERCPP_THREAD_COUNT = os.environ.get("WHISPERCPP_THREAD_COUNT", "6")

# llama.cpp
LLAMA_BIN_PATH = os.environ.get("LLAMA_BIN_PATH", "/llama.cpp/main")
LLAMA_DEFAULT_MODEL = os.environ.get("LLAMA_DEFAULT_MODEL", "/llama.cpp/models/capybarahermes-2.5-mistral-7b.Q5_K_M.gguf")

# COTURN settings
COTURN_SERVER = os.environ.get("COTURN_SERVER", "localhost")
COTURN_PORT = os.environ.get("COTURN_PORT", "3478")
COTURN_SECRET = os.environ.get("COTURN_SECRET", "savr423qb5vikret953n7wps'a'4'6n34421")

# DRF Chunked Upload settings

DRF_CHUNKED_UPLOAD_ABSTRACT_MODEL = False
DRF_CHUNKED_UPLOAD_CHECKSUM = 'sha256'

# CUPCAKE SETTINGS

USE_LLM = os.environ.get("USE_LLM", "False") == "True"
USE_WHISPER = os.environ.get("USE_WHISPER", "False") == "True"
USE_COTURN = os.environ.get("USE_COTURN", "False") == "True"
USE_OCR = os.environ.get("USE_OCR", "False") == "True"

# Amazon SES SETTINGS

EMAIL_BACKEND = 'django_ses.SESBackend'
NOTIFICATION_EMAIL_FROM = os.environ.get("NOTIFICATION_EMAIL_FROM", "")
AWS_SES_ACCESS_KEY_ID = os.environ.get("AWS_SES_ACCESS_KEY_ID", "")
AWS_SES_SECRET_ACCESS_KEY = os.environ.get("AWS_SES_SECRET_ACCESS_KEY", "")
AWS_SES_REGION_NAME = os.environ.get('AWS_SES_REGION_NAME', "us-east-1")
AWS_SES_REGION_ENDPOINT = os.environ.get('AWS_SES_REGION_ENDPOINT', 'email.us-east-1.amazonaws.com')
if EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 465))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False') == 'True'
    EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False') == 'True'

# Frontend settings

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:4200")

# Instrument Booking Settings
ALLOW_OVERLAP_BOOKINGS = os.environ.get("ALLOW_OVERLAP_BOOKINGS", "True") == "True"
DEFAULT_SERVICE_LAB_GROUP = os.environ.get("DEFAULT_SERVICE_LAB_GROUP", "MS Facility")
