"""
Django settings for Cupcake Vanilla when embedded in a Wails application.

This configuration uses:
- SQLite for cross-platform embedded database
- Redis for async task queues and channel layers
- Local file storage within Wails app data directory
- Minimal dependencies for embedded environment
"""

import os
import tempfile
from pathlib import Path

from .settings import *  # noqa: F403, F401
from .settings import (
    REDIS_DB_RQ,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_URL_BASE,
    REDIS_URL_CACHE,
    REDIS_URL_CHANNELS,
)

BASE_DIR = Path(__file__).resolve().parent.parent

WAILS_APP_DATA = os.environ.get("WAILS_APP_DATA", tempfile.gettempdir())
WAILS_USER_DATA = os.path.join(WAILS_APP_DATA, "cupcake-vanilla")
os.makedirs(WAILS_USER_DATA, exist_ok=True)

DATABASE_DIR = os.path.join(WAILS_USER_DATA, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

DEBUG = os.environ.get("WAILS_DEBUG", "False").lower() == "true"

SECRET_KEY = os.environ.get("WAILS_SECRET_KEY", "wails-embedded-key-change-in-production-" + str(hash(WAILS_USER_DATA)))

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "[::1]",
    "0.0.0.0",
    "wails.localhost",
]

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(WAILS_USER_DATA, "cupcake_vanilla.db"),
    }
}

DATABASE_BACKEND = "sqlite3"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL_CACHE,
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

RQ_QUEUES = {
    "default": {
        "HOST": REDIS_HOST,
        "PORT": int(REDIS_PORT),
        "DB": REDIS_DB_RQ,
        "PASSWORD": REDIS_PASSWORD or None,
        "DEFAULT_TIMEOUT": 3600,
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
    "high": {
        "HOST": REDIS_HOST,
        "PORT": int(REDIS_PORT),
        "DB": REDIS_DB_RQ,
        "PASSWORD": REDIS_PASSWORD or None,
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
    "low": {
        "HOST": REDIS_HOST,
        "PORT": int(REDIS_PORT),
        "DB": REDIS_DB_RQ,
        "PASSWORD": REDIS_PASSWORD or None,
        "DEFAULT_TIMEOUT": 500,
        "CONNECTION_KWARGS": {
            "health_check_interval": 30,
        },
    },
}

STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("WAILS_STATIC_ROOT", os.path.join(WAILS_USER_DATA, "static"))

MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("WAILS_MEDIA_ROOT", os.path.join(WAILS_USER_DATA, "media"))

os.makedirs(STATIC_ROOT, exist_ok=True)
os.makedirs(MEDIA_ROOT, exist_ok=True)

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
            "filename": os.path.join(WAILS_USER_DATA, "cupcake_vanilla.log"),
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

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL_CHANNELS],
            "capacity": 1000,
            "expiry": 60,
        },
    },
}


def wails_websocket_origin_validator(application):
    """Custom WebSocket origin validator that allows wails:// and localhost origins."""

    def inner(scope, receive, send):
        if scope["type"] == "websocket":
            pass
        return application(scope, receive, send)

    return inner


SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = False
SECURE_BROWSER_XSS_FILTER = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 86400

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"

LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_L10N = True

FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024

WAILS_ACCESS_TOKEN_HOURS = int(os.environ.get("WAILS_ACCESS_TOKEN_HOURS", "24"))
WAILS_REFRESH_TOKEN_DAYS = int(os.environ.get("WAILS_REFRESH_TOKEN_DAYS", "30"))

WAILS_SETTINGS = {
    "APP_DATA_DIR": WAILS_USER_DATA,
    "DATABASE_BACKEND": DATABASE_BACKEND,
    "DATABASE_FILE": DATABASES["default"]["NAME"],
    "STATIC_ROOT": STATIC_ROOT,
    "MEDIA_ROOT": MEDIA_ROOT,
    "LOG_FILE": os.path.join(WAILS_USER_DATA, "cupcake_vanilla.log"),
    "ENABLE_AUTO_MIGRATION": True,
    "ENABLE_COLLECTSTATIC": True,
    "SYNC_OPERATIONS_ONLY": False,
    "IS_WAILS_ENVIRONMENT": True,
    "ACCESS_TOKEN_HOURS": WAILS_ACCESS_TOKEN_HOURS,
    "REFRESH_TOKEN_DAYS": WAILS_REFRESH_TOKEN_DAYS,
    "WEBSOCKET_WAILS_ORIGIN_ALLOWED": True,
    "ASGI_APPLICATION": "cupcake_vanilla.asgi_wails.application",
    "REDIS_HOST": REDIS_HOST,
    "REDIS_PORT": int(REDIS_PORT),
    "REDIS_PASSWORD": REDIS_PASSWORD or None,
    "REDIS_URL": REDIS_URL_BASE,
}

IS_WAILS_ENVIRONMENT = True

ASGI_APPLICATION = "cupcake_vanilla.asgi_wails.application"


def get_database_info():
    """Get database connection information for debugging."""
    return {
        "backend": "sqlite3",
        "persistent": True,
        "database_file": DATABASES["default"]["NAME"],
        "connection_string": f"sqlite:///{DATABASES['default']['NAME']}",
    }


def check_database_status():
    """Check if database is accessible."""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


def get_redis_info():
    """Get Redis connection information for debugging."""
    return {
        "host": REDIS_HOST,
        "port": int(REDIS_PORT),
        "password_set": bool(REDIS_PASSWORD),
        "redis_url": REDIS_URL_BASE,
    }


def check_redis_status():
    """Check if Redis is accessible."""
    try:
        import redis

        r = redis.Redis(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            password=REDIS_PASSWORD or None,
            socket_connect_timeout=5,
        )
        r.ping()
        return True
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return False


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=WAILS_ACCESS_TOKEN_HOURS),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=WAILS_REFRESH_TOKEN_DAYS),
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
    "SLIDING_TOKEN_LIFETIME": timedelta(hours=WAILS_ACCESS_TOKEN_HOURS),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=WAILS_REFRESH_TOKEN_DAYS),
}

if __name__ == "__main__":
    print("=" * 50)
    print("Cupcake Vanilla - Wails Configuration")
    print("=" * 50)
    print(f"App Data Directory: {WAILS_USER_DATA}")
    print(f"Database Backend: {DATABASE_BACKEND}")
    print(f"Database File: {DATABASES['default']['NAME']}")
    print(f"Redis Host: {REDIS_HOST}")
    print(f"Redis Port: {REDIS_PORT}")
    print(f"Redis URL: {REDIS_URL_BASE}")
    print(f"Redis Password: {'SET' if REDIS_PASSWORD else 'NOT SET'}")
    print(f"Static Files: {STATIC_ROOT}")
    print(f"Media Files: {MEDIA_ROOT}")
    print(f"Log File: {os.path.join(WAILS_USER_DATA, 'cupcake_vanilla.log')}")
    print(f"JWT Access Token: {WAILS_ACCESS_TOKEN_HOURS} hours")
    print(f"JWT Refresh Token: {WAILS_REFRESH_TOKEN_DAYS} days")
    print("WebSocket wails:// origins: ALLOWED")
    print(f"ASGI Application: {ASGI_APPLICATION}")
    print("=" * 50)
