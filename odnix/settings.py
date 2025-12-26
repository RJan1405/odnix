"""
Django settings for odnix project.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-change-this-key-in-production-123456789'

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# FIXED: Site domain for clean invite links
SITE_DOMAIN = 'http://127.0.0.1:8000'

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'chat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'odnix.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'odnix.wsgi.application'

# ASGI application for channels
ASGI_APPLICATION = 'odnix.asgi.application'

# Channel layers configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            # Use REDIS_URL env var if provided, else localhost
            "hosts": [
                os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
            ]
        }
    }
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# FIXED: Media files configuration with profile pics support
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Ensure media directories exist
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(MEDIA_ROOT / 'profile_pics', exist_ok=True)
os.makedirs(MEDIA_ROOT / 'chat_media', exist_ok=True)

# FIXED: File upload settings - PREVENTS CORRUPTION
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_PERMISSIONS = 0o644

# Allowed file types for uploads
ALLOWED_MEDIA_TYPES = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    'video': ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
    'document': ['.pdf', '.doc', '.docx', '.txt']
}

# Maximum file sizes (in bytes)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'chat.CustomUser'

# Login URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# FIXED: Email settings for verification using provided credentials
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'mail.vulnix.org'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'intern@vulnix.org'
EMAIL_HOST_PASSWORD = 'Anag@9987716115'
DEFAULT_FROM_EMAIL = 'intern@vulnix.org'

# For development/testing - uncomment to see emails in console
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Session settings
SESSION_COOKIE_AGE = 86400  # 1 day
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Security settings for media files
SECURE_CROSS_ORIGIN_OPENER_POLICY = None
X_FRAME_OPTIONS = 'DENY'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'django_errors.log',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
        },
    },
    # Ensure everything goes to console so you can see call/WS logs in the runserver terminal
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'chat': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

# --- Reels Compression Settings ---
# Tunable knobs for server-side reel compression. You can override via env vars
# or directly edit here per environment.
REELS_MAX_WIDTH = int(os.getenv('REELS_MAX_WIDTH', 480))           # px
REELS_MAX_DURATION = int(os.getenv('REELS_MAX_DURATION', 120))      # seconds
# frames per second (cap)
REELS_MAX_FPS = int(os.getenv('REELS_MAX_FPS', 30))
# 18-32 (lower=better quality)
REELS_CRF = int(os.getenv('REELS_CRF', 28))
# ultrafast..veryslow
REELS_PRESET = os.getenv('REELS_PRESET', 'veryfast')
REELS_AUDIO_BITRATE = os.getenv(
    'REELS_AUDIO_BITRATE', '96k')      # e.g. '96k', '128k'
REELS_SMART_FALLBACK = os.getenv(
    'REELS_SMART_FALLBACK', '1') in ('1', 'true', 'True')
REELS_FORCE_MP4 = os.getenv('REELS_FORCE_MP4', '1') in ('1', 'true', 'True')
