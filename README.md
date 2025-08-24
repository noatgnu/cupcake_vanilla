# CUPCAKE Metadata

CUPCAKE (Comprehensive User-friendly Platform for Collaborative and Knowledge-based Experimental data management) is a Django package for managing scientific metadata, user collaboration, and SDRF-compliant data processing.


## Start

### 1. Add to Django Project

Add both apps to your Django project's INSTALLED_APPS:

```python
# settings.py
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'rest_framework',
    'django_filters',
    'simple_history',
    'corsheaders',

    # CUPCAKE apps
    'ccc',  # CUPCAKE Core - User & Lab Management
    'ccv',  # CUPCAKE Vanilla - Metadata Management

    # Your apps
    'your_app',
]

# Configure REST Framework
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
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 20,
}

# Database configuration (PostgreSQL recommended)
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
```

### 2. Configure URLs

Add CUPCAKE URLs to your project:

```python
# urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('ccc.urls')),  # User management APIs
    path('api/v1/', include('ccv.urls')),  # Metadata management APIs
    path('api/v1/', include('ccc.auth_urls')),  # Authentication endpoints
]
```

### 3. Run Migrations

```
python manage.py migrate ccc
python manage.py migrate ccv
```

### 4. Load Initial Data

Load essential ontologies and schemas:

```
# Load scientific ontologies
python manage.py load_ontologies --no-limit

# Load species data
python manage.py load_species

# Load tissue information
python manage.py load_tissue

# Load the rest of the ontologies please look under ccv/management/commands/

# Load SDRF schemas
python manage.py sync_schemas

# Load default column
python manage.py load_column_templates
```
