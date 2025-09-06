"""
URL configuration for cupcake_vanilla project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

urlpatterns = [
    path("admin/", admin.site.urls),
    # API v1 endpoints from both apps
    path("api/v1/", include("ccc.urls")),  # CCC: ViewSets + auth endpoints
    path("api/v1/", include("ccc.auth_urls")),
    path("api/v1/", include("ccv.urls")),  # CCV: ViewSets + chunked upload
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # Non-API auth endpoints from CCC (not behind api/v1)
    # Auth endpoints like auth/login/, auth/orcid/
    # DRF browsable API
    path("api-auth/", include("rest_framework.urls")),
    # RQ admin interface (only in development)
    path("admin/rq/", include("django_rq.urls")),
]

# Conditionally add CUPCAKE app URLs based on configuration
if getattr(settings, "ENABLE_CUPCAKE_MACARON", True):
    urlpatterns += [
        path("api/v1/", include("ccm.urls")),  # CCM: Instrument & inventory endpoints
    ]

# Add CCMC (Communication) endpoints
if getattr(settings, "ENABLE_CUPCAKE_MINT_CHOCOLATE", False):
    urlpatterns += [
        path("api/v1/", include("ccmc.urls")),  # CCMC: Communication & messaging endpoints
    ]

# Add CCSC (Billing) endpoints
if getattr(settings, "ENABLE_CUPCAKE_SALTED_CARAMEL", True):
    urlpatterns += [
        path("api/v1/", include("ccsc.urls")),  # CCSC: Billing & financial management endpoints
    ]

# Add CCRV (Project & Protocol) endpoints
if getattr(settings, "ENABLE_CUPCAKE_RED_VELVET", True):
    urlpatterns += [
        path("api/v1/", include("ccrv.urls")),  # CCRV: Project & protocol management endpoints
    ]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
