# CUPCAKE Core - Installation Guide

This guide provides detailed installation instructions for CUPCAKE Metadata in different scenarios.

## Quick Installation

### 1. Install Package

```bash
pip install cupcake-metadata
```

### 2. Add to Django Settings

```python
# settings.py
INSTALLED_APPS = [
    # Django defaults
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Required third-party apps
    'rest_framework',
    'django_filters',
    'simple_history',
    'corsheaders',  # Optional: for frontend integration

    # CUPCAKE apps
    'ccc',  # CUPCAKE Core - User & Lab Management
    'ccv',  # CUPCAKE Vanilla - Metadata Management

    # Your apps
    'your_app',
]

# Database (PostgreSQL recommended)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'your_database',
        'USER': 'your_user',
        'PASSWORD': 'your_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
```

### 3. Configure URLs

```python
# urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('ccc.urls')),  # User management
    path('api/v1/', include('ccv.urls')),  # Metadata management
    path('auth/', include('ccc.auth_urls')),  # Authentication
]
```

### 4. Run Migrations

```bash
python manage.py migrate
```

### 5. Load Initial Data

```bash
python manage.py load_ontologies
python manage.py load_species
python manage.py sync_schemas
```

## Development Installation

### 1. Clone and Install in Development Mode

```bash
git clone https://github.com/your-org/cupcake-metadata.git
cd cupcake-metadata
pip install -e ".[dev]"
```

### 2. Set Up Development Environment

```bash
# Install pre-commit hooks
pre-commit install

# Set up environment variables
cp .env.example .env
# Edit .env with your settings
```

### 3. Run Tests

```bash
pytest
pytest --cov=ccc --cov=ccv --cov-report=html
```

## Production Deployment

### 1. Install with Production Dependencies

```bash
pip install cupcake-metadata[production]
```

### 2. Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/cupcake_prod

# Security
SECRET_KEY=your-very-long-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Email
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=your-email-password

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# ORCID (optional)
ORCID_CLIENT_ID=your-orcid-client-id
ORCID_CLIENT_SECRET=your-orcid-secret

# Frontend URL
FRONTEND_URL=https://yourdomain.com
```

### 3. Production Settings

```python
# settings_production.py
from .settings import *

DEBUG = False
ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com']

# Security settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Static files
STATIC_ROOT = '/path/to/staticfiles'
MEDIA_ROOT = '/path/to/media'

# Database connection pooling
DATABASES['default']['CONN_MAX_AGE'] = 60

# Caching
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/var/log/cupcake/cupcake.log',
        },
    },
    'loggers': {
        'ccc': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'ccv': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
```

### 4. Web Server Configuration

#### Nginx Configuration

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/private.key;

    location /static/ {
        alias /path/to/staticfiles/;
        expires 30d;
    }

    location /media/ {
        alias /path/to/media/;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Gunicorn Configuration

```python
# gunicorn_config.py
bind = "127.0.0.1:8000"
workers = 4
worker_class = "sync"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = True
```

```bash
gunicorn -c gunicorn_config.py your_project.wsgi:application
```

## Docker Installation

### 1. Using Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://cupcake:password@db:5432/cupcake
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - media_volume:/app/media
      - static_volume:/app/staticfiles

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: cupcake
      POSTGRES_USER: cupcake
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
  media_volume:
  static_volume:
```

### 2. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "your_project.wsgi:application"]
```

## Requirements

### System Requirements

- **Python**: 3.11 or higher
- **Database**: PostgreSQL 12+ (recommended) or SQLite 3.25+ (development)
- **Redis**: 6.0+ (optional, for caching and sessions)
- **Memory**: Minimum 1GB RAM (2GB+ recommended for production)
- **Storage**: Varies based on uploaded files and database size

### Python Dependencies

Core dependencies are automatically installed with the package:

- Django 5.2+
- Django REST Framework 3.14+
- django-simple-history 3.4+
- django-filter 23.5+
- psycopg2-binary (PostgreSQL)
- openpyxl (Excel processing)
- pandas (Data manipulation)
- pronto (Ontology processing)
- sdrf-pipelines (SDRF validation)

## Configuration

### Essential Settings

```python
# Minimum required settings
CUPCAKE_SETTINGS = {
    'SITE_NAME': 'Your Research Platform',
    'ADMIN_EMAIL': 'admin@yoursite.com',
    'ENABLE_USER_REGISTRATION': True,
    'ENABLE_ORCID_LOGIN': False,
    'MAX_UPLOAD_SIZE': 100 * 1024 * 1024,  # 100MB
    'DEFAULT_FROM_EMAIL': 'noreply@yoursite.com',
}
```

### Optional Features

```python
# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Email backend for production
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# File upload settings
CHUNKED_UPLOAD_PATH = 'chunked_uploads/'
CHUNKED_UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100MB

# CORS settings (if using with frontend)
CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",  # Angular dev server
    "https://yoursite.com",
]
```

## Troubleshooting

### Common Issues

#### 1. Database Connection Issues

```bash
# Check PostgreSQL connection
python manage.py dbshell

# If connection fails, verify:
# - Database exists
# - User has correct permissions
# - Host/port are correct
# - Password is correct
```

#### 2. Migration Issues

```bash
# If migrations fail, try:
python manage.py migrate --fake-initial

# Or reset migrations (development only):
python manage.py migrate ccc zero
python manage.py migrate ccv zero
python manage.py migrate
```

#### 3. Static Files Issues

```bash
# Collect static files
python manage.py collectstatic --clear

# Check STATIC_ROOT setting
python manage.py findstatic admin/css/base.css
```

#### 4. Permission Issues

```bash
# Create superuser
python manage.py createsuperuser

# Check site configuration
python manage.py shell
>>> from ccc.models import SiteConfig
>>> config = SiteConfig.objects.first()
>>> print(config.allow_user_registration if config else "No config found")
```

#### 5. ORCID Integration Issues

1. Verify ORCID credentials are correct
2. Check redirect URIs in ORCID developer console
3. Ensure HTTPS is enabled for production

### Getting Help

- **Documentation**: Check the comprehensive README.md
- **Issues**: Report bugs on GitHub Issues
- **Discussions**: Join GitHub Discussions for questions
- **Email**: Contact support@cupcake-metadata.org

### Performance Tips

1. **Use PostgreSQL** instead of SQLite for production
2. **Enable Redis caching** for better performance
3. **Configure proper indexes** on frequently queried fields
4. **Use CDN** for static files in production
5. **Monitor database queries** and optimize as needed
