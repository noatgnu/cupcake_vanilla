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
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
