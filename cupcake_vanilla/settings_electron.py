"""
Django settings for Cupcake Vanilla when embedded in an Electron application.

This configuration uses:
- SQLite for cross-platform embedded database
- fakeredis for async task queues without Redis server
- Local file storage within Electron app data directory
- Minimal dependencies for embedded environment
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

# Database directory for SQLite
DATABASE_DIR = os.path.join(ELECTRON_USER_DATA, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

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

# Database Configuration - SQLite for cross-platform compatibility
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla.db"),
    }
}

DATABASE_BACKEND = "sqlite3"

# Cache configuration - Use Redis for caching
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 50,
                "retry_on_timeout": True,
                "socket_keepalive": True,
                "socket_keepalive_options": {},
            },
        },
    }
}

from datetime import timedelta

# RQ (Redis Queue) configuration for async tasks in Electron
# Use portable Redis binary included with Electron

# Redis configuration for Electron - use standard Redis environment variables

RQ_QUEUES = {
    "default": {
        "HOST": os.environ.get("REDIS_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("REDIS_PORT", "6379")),
        "DB": int(os.environ.get("REDIS_DB_RQ", "3")),  # Use different DB from cache and channels
        "PASSWORD": os.environ.get("REDIS_PASSWORD", None),
        "DEFAULT_TIMEOUT": 3600,  # 1 hour timeout for tasks
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
    "high": {
        "HOST": os.environ.get("REDIS_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("REDIS_PORT", "6379")),
        "DB": int(os.environ.get("REDIS_DB_RQ", "3")),
        "PASSWORD": os.environ.get("REDIS_PASSWORD", None),
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
    "low": {
        "HOST": os.environ.get("REDIS_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("REDIS_PORT", "6379")),
        "DB": int(os.environ.get("REDIS_DB_RQ", "3")),
        "PASSWORD": os.environ.get("REDIS_PASSWORD", None),
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
}

# Static files configuration for Electron
STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("ELECTRON_STATIC_ROOT", os.path.join(ELECTRON_USER_DATA, "static"))

# Media files for user uploads - configurable for Electron
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("ELECTRON_MEDIA_ROOT", os.path.join(ELECTRON_USER_DATA, "media"))

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
    },
}

# Disable external services for embedded environment
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# WebSocket configuration for Electron - Use Redis for channel layers
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/2")],
            "capacity": 1000,
            "expiry": 60,
        },
    },
}


# Custom WebSocket origin validation for Electron
# Allow file:// origins for Electron apps
def electron_websocket_origin_validator(application):
    """Custom WebSocket origin validator that allows file:// origins for Electron."""

    def inner(scope, receive, send):
        # Allow all WebSocket connections for Electron environment
        if scope["type"] == "websocket":
            # Skip origin validation for Electron - all origins allowed
            pass
        return application(scope, receive, send)

    return inner


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

# JWT configuration for Electron - longer sessions for desktop app
# Allow customization via environment variables
ELECTRON_ACCESS_TOKEN_HOURS = int(os.environ.get("ELECTRON_ACCESS_TOKEN_HOURS", "24"))  # 24 hours default
ELECTRON_REFRESH_TOKEN_DAYS = int(os.environ.get("ELECTRON_REFRESH_TOKEN_DAYS", "30"))  # 30 days default

# Electron-specific settings
ELECTRON_SETTINGS = {
    "APP_DATA_DIR": ELECTRON_USER_DATA,
    "DATABASE_BACKEND": DATABASE_BACKEND,
    "DATABASE_FILE": DATABASES["default"]["NAME"],
    "STATIC_ROOT": STATIC_ROOT,
    "MEDIA_ROOT": MEDIA_ROOT,
    "LOG_FILE": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla.log"),
    "ENABLE_AUTO_MIGRATION": True,
    "ENABLE_COLLECTSTATIC": True,
    "SYNC_OPERATIONS_ONLY": False,
    "IS_ELECTRON_ENVIRONMENT": True,
    "ACCESS_TOKEN_HOURS": ELECTRON_ACCESS_TOKEN_HOURS,
    "REFRESH_TOKEN_DAYS": ELECTRON_REFRESH_TOKEN_DAYS,
    "WEBSOCKET_FILE_ORIGIN_ALLOWED": True,
    "ASGI_APPLICATION": "cupcake_vanilla.asgi_electron.application",
    "REDIS_HOST": os.environ.get("REDIS_HOST", "127.0.0.1"),
    "REDIS_PORT": int(os.environ.get("REDIS_PORT", "6379")),
    "REDIS_PASSWORD": os.environ.get("REDIS_PASSWORD", None),
    "REDIS_URL": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"),
}

# Environment detection flag
IS_ELECTRON_ENVIRONMENT = True

# Use Electron-specific ASGI application that allows file:// origins
ASGI_APPLICATION = "cupcake_vanilla.asgi_electron.application"


def get_database_info():
    """Get database connection information for debugging"""
    return {
        "backend": "sqlite3",
        "persistent": True,
        "database_file": DATABASES["default"]["NAME"],
        "connection_string": f"sqlite:///{DATABASES['default']['NAME']}",
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


def get_redis_info():
    """Get Redis connection information for debugging"""
    return {
        "host": os.environ.get("REDIS_HOST", "127.0.0.1"),
        "port": int(os.environ.get("REDIS_PORT", "6379")),
        "password_set": bool(os.environ.get("REDIS_PASSWORD")),
        "redis_url": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"),
    }


def check_redis_status():
    """Check if Redis is accessible"""
    try:
        import redis

        r = redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD", None),
            socket_connect_timeout=5,
        )
        r.ping()
        return True
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return False


# Override SIMPLE_JWT settings with longer expiry times for Electron
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=ELECTRON_ACCESS_TOKEN_HOURS),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=ELECTRON_REFRESH_TOKEN_DAYS),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(hours=ELECTRON_ACCESS_TOKEN_HOURS),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=ELECTRON_REFRESH_TOKEN_DAYS),
}

# Print startup information
if __name__ == "__main__":
    print("=" * 50)
    print("Cupcake Vanilla - Electron Configuration")
    print("=" * 50)
    print(f"App Data Directory: {ELECTRON_USER_DATA}")
    print(f"Database Backend: {DATABASE_BACKEND}")
    print(f"Database File: {DATABASES['default']['NAME']}")
    print(f"Redis Host: {os.environ.get('REDIS_HOST', '127.0.0.1')}")
    print(f"Redis Port: {os.environ.get('REDIS_PORT', '6379')}")
    print(f"Redis URL: {os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379')}")
    print(f"Redis Password: {'SET' if os.environ.get('REDIS_PASSWORD') else 'NOT SET'}")
    print(f"Static Files: {STATIC_ROOT}")
    print(f"Media Files: {MEDIA_ROOT}")
    print(f"Log File: {os.path.join(ELECTRON_USER_DATA, 'cupcake_vanilla.log')}")
    print(f"JWT Access Token: {ELECTRON_ACCESS_TOKEN_HOURS} hours")
    print(f"JWT Refresh Token: {ELECTRON_REFRESH_TOKEN_DAYS} days")
    print("WebSocket file:// origins: ALLOWED")
    print(f"ASGI Application: {ASGI_APPLICATION}")
    print("=" * 50)
