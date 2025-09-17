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

# py-pglite Database Configuration
PGLITE_AVAILABLE = False
PGLITE_MANAGER = None

try:
    import socket

    from py_pglite import PGliteConfig, PGliteManager

    # Test if we can actually use py-pglite by trying to connect to the port
    # In CI/testing environments, py-pglite might be installed but not usable
    def test_pglite_connectivity():
        """Test if py-pglite is running on the expected port."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", 55432))
            sock.close()
            return result == 0
        except Exception:
            return False

    # Only use py-pglite if it's actually running or we're in a real Electron environment
    # Check for actual Electron environment vs CI testing
    in_real_electron = os.environ.get("ELECTRON_APP_DATA") is not None
    pglite_running = test_pglite_connectivity()

    if in_real_electron or pglite_running:
        # Configure py-pglite for persistent storage
        PGLITE_CONFIG = PGliteConfig(
            work_dir=PGLITE_DATA_DIR,  # Persistent storage in Electron app data
            use_tcp=True,
            tcp_host="127.0.0.1",
            tcp_port=55432,  # Use py-pglite default port to avoid conflicts
            extensions=[],  # Add ["pgvector"] or other extensions if needed
        )

        # Initialize py-pglite manager (will be started in AppConfig)
        PGLITE_MANAGER = PGliteManager(PGLITE_CONFIG)

        # Database configuration using py-pglite
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "cupcake_vanilla",
                "USER": "postgres",
                "PASSWORD": "postgres",
                "HOST": "127.0.0.1",
                "PORT": "55432",
                "OPTIONS": {
                    "sslmode": "disable",
                    "connect_timeout": 10,
                },
            }
        }

        PGLITE_AVAILABLE = True
        print(f"py-pglite configured with data directory: {PGLITE_DATA_DIR}")
    else:
        # Fall back to SQLite in testing/CI environments
        raise ImportError("py-pglite installed but not running, falling back to SQLite")

except ImportError as e:
    # Fallback to SQLite if py-pglite is not available
    print(f"py-pglite not available ({e}), falling back to SQLite")

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla_fallback.db"),
            "OPTIONS": {
                "timeout": 20,
                "check_same_thread": False,
            },
        }
    }

    PGLITE_AVAILABLE = False

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
    "DATABASE_BACKEND": "py-pglite" if PGLITE_AVAILABLE else "sqlite",
    "DATABASE_DIR": PGLITE_DATA_DIR if PGLITE_AVAILABLE else None,
    "DATABASE_FILE": None if PGLITE_AVAILABLE else DATABASES["default"]["NAME"],
    "LOG_FILE": os.path.join(ELECTRON_USER_DATA, "cupcake_vanilla.log"),
    "PGLITE_AVAILABLE": PGLITE_AVAILABLE,
    "PGLITE_PORT": 55432 if PGLITE_AVAILABLE else None,
    "PGLITE_DATA_DIR": PGLITE_DATA_DIR,
    "ENABLE_AUTO_MIGRATION": True,
    "ENABLE_COLLECTSTATIC": True,
    "SYNC_OPERATIONS_ONLY": False,
    "IS_ELECTRON_ENVIRONMENT": True,
}

# Environment detection flag
IS_ELECTRON_ENVIRONMENT = True


# py-pglite management functions
def start_pglite_database():
    """Start py-pglite database for Electron app"""
    if not PGLITE_AVAILABLE or not PGLITE_MANAGER:
        return False

    try:
        PGLITE_MANAGER.__enter__()
        print("py-pglite database started successfully")
        print(f"Data directory: {PGLITE_DATA_DIR}")
        print(f"TCP port: {PGLITE_CONFIG.tcp_port}")
        return True
    except Exception as e:
        print(f"Failed to start py-pglite database: {e}")
        return False


def stop_pglite_database():
    """Stop py-pglite database"""
    if not PGLITE_AVAILABLE or not PGLITE_MANAGER:
        return False

    try:
        PGLITE_MANAGER.__exit__(None, None, None)
        print("py-pglite database stopped successfully")
        return True
    except Exception as e:
        print(f"Failed to stop py-pglite database: {e}")
        return False


def get_database_info():
    """Get database connection information for debugging"""
    if PGLITE_AVAILABLE:
        return {
            "backend": "py-pglite",
            "persistent": True,
            "data_directory": PGLITE_DATA_DIR,
            "host": DATABASES["default"]["HOST"],
            "port": DATABASES["default"]["PORT"],
            "database": DATABASES["default"]["NAME"],
            "connection_string": f"postgresql://{DATABASES['default']['USER']}@{DATABASES['default']['HOST']}:{DATABASES['default']['PORT']}/{DATABASES['default']['NAME']}",
        }
    else:
        return {
            "backend": "sqlite",
            "persistent": True,
            "database_file": DATABASES["default"]["NAME"],
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
    print(f"Database Backend: {'py-pglite' if PGLITE_AVAILABLE else 'sqlite'}")
    if PGLITE_AVAILABLE:
        print(f"Database Data Directory: {PGLITE_DATA_DIR}")
        print("Database Port: 55432")
    else:
        print(f"SQLite Database: {DATABASES['default']['NAME']}")
    print(f"Static Files: {STATIC_ROOT}")
    print(f"Media Files: {MEDIA_ROOT}")
    print(f"Log File: {os.path.join(ELECTRON_USER_DATA, 'cupcake_vanilla.log')}")
    print("=" * 50)
