"""
Django settings for Cupcake Vanilla when embedded in an Electron application.

This configuration uses:
- py-pglite for persistent embedded PostgreSQL database
- No async task queues (all operations run synchronously)
- Local file storage within Electron app data directory
- Minimal dependencies for embedded environment

Requirements:
- pip install py-pglite[django]
"""

import os
import tempfile
from pathlib import Path

from .settings import *  # Import base settings  # noqa: F403, F401

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Electron app data directory
ELECTRON_APP_DATA = os.environ.get("ELECTRON_APP_DATA", tempfile.gettempdir())
ELECTRON_USER_DATA = os.path.join(ELECTRON_APP_DATA, "cupcake-vanilla")
os.makedirs(ELECTRON_USER_DATA, exist_ok=True)

# py-pglite database directory
PGLITE_DATA_DIR = os.path.join(ELECTRON_USER_DATA, "database")
os.makedirs(PGLITE_DATA_DIR, exist_ok=True)

# Debug mode - can be toggled for Electron
DEBUG = os.environ.get("ELECTRON_DEBUG", "False").lower() == "true"

# Security settings for embedded app
SECRET_KEY = os.environ.get(
    "ELECTRON_SECRET_KEY", "electron-embedded-key-change-in-production-" + str(hash(ELECTRON_USER_DATA))
)

# Allowed hosts for local Electron app
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "[::1]",
    "0.0.0.0",
]

# CORS settings for Electron frontend
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Database Configuration - py-pglite only
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",  # Use default postgres database for py-pglite
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "127.0.0.1",
        "PORT": "55432",
        "OPTIONS": {
            "sslmode": "disable",
            "connect_timeout": 30,
            "application_name": "cupcake_vanilla",
            "client_encoding": "UTF8",
        },
    }
}

DATABASE_BACKEND = "py-pglite"

# Cache configuration - Simple in-memory cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "cupcake-vanilla-cache",
        "OPTIONS": {
            "MAX_ENTRIES": 5000,
            "CULL_FREQUENCY": 3,
        },
    }
}

# RQ (Redis Queue) configuration for async tasks in Electron
# Use fakeredis for embedded environment to avoid Redis dependency
RQ_QUEUES = {
    "default": {
        "HOST": "localhost",
        "PORT": 6379,
        "DB": 0,
        "PASSWORD": "",
        "DEFAULT_TIMEOUT": 360,
        "CONNECTION_CLASS": "fakeredis.FakeRedis",
    },
    "high": {
        "HOST": "localhost",
        "PORT": 6379,
        "DB": 0,
        "PASSWORD": "",
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_CLASS": "fakeredis.FakeRedis",
    },
    "low": {
        "HOST": "localhost",
        "PORT": 6379,
        "DB": 0,
        "PASSWORD": "",
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_CLASS": "fakeredis.FakeRedis",
    },
}

# Static files configuration for Electron
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(ELECTRON_USER_DATA, "static")

# Media files for user uploads
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(ELECTRON_USER_DATA, "media")

# Ensure directories exist
os.makedirs(STATIC_ROOT, exist_ok=True)
os.makedirs(MEDIA_ROOT, exist_ok=True)

# Logging configuration for Electron
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla.log"),
            "formatter": "verbose",
        },
        "console": {
            "level": "DEBUG" if DEBUG else "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "ccv": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "py_pglite": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Disable external services for embedded environment
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# WebSocket configuration for Electron - Simple in-memory
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
        "CONFIG": {
            "capacity": 1000,
            "expiry": 60,
        },
    },
}

# Security adjustments for embedded environment
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = False
SECURE_BROWSER_XSS_FILTER = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Session configuration - Use database sessions
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 86400  # 1 day

# Minimal middleware for embedded environment
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# Performance optimizations for embedded environment
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Time zone for embedded app
USE_TZ = True
TIME_ZONE = "UTC"

# Internationalization
LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_L10N = True

# File upload settings for local use
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB

# Electron-specific settings
ELECTRON_SETTINGS = {
    "APP_DATA_DIR": ELECTRON_USER_DATA,
    "DATABASE_BACKEND": DATABASE_BACKEND,
    "LOG_FILE": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla.log"),
    "ENABLE_AUTO_MIGRATION": True,
    "ENABLE_COLLECTSTATIC": True,
    "SYNC_OPERATIONS_ONLY": False,
    "IS_ELECTRON_ENVIRONMENT": True,
}

# Environment detection flag
IS_ELECTRON_ENVIRONMENT = True


def get_database_info():
    """Get database connection information for debugging"""
    return {
        "backend": "py-pglite",
        "persistent": True,
        "host": DATABASES["default"]["HOST"],
        "port": DATABASES["default"]["PORT"],
        "database": DATABASES["default"]["NAME"],
        "connection_string": f"postgresql://{DATABASES['default']['USER']}@{DATABASES['default']['HOST']}:{DATABASES['default']['PORT']}/{DATABASES['default']['NAME']}",
    }


def check_database_status():
    """Check if database is accessible"""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


# Print startup information
if __name__ == "__main__":
    print("=" * 50)
    print("Cupcake Vanilla - Electron Configuration")
    print("=" * 50)
    print(f"App Data Directory: {ELECTRON_USER_DATA}")
    print(f"Database Backend: {DATABASE_BACKEND}")
    print(f"Database Host: {DATABASES['default']['HOST']}")
    print(f"Database Port: {DATABASES['default']['PORT']}")
    print(f"Database Name: {DATABASES['default']['NAME']}")
    print(f"Static Files: {STATIC_ROOT}")
    print(f"Media Files: {MEDIA_ROOT}")
    print(f"Log File: {os.path.join(ELECTRON_USER_DATA, 'cupcake_vanilla.log')}")
    print("=" * 50)
