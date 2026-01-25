"""
Authentication-only URLs for CUPCAKE Core (CCC).
These URLs are not behind the api/v1/ prefix.
"""

from django.urls import path

from .authentication import CustomTokenObtainPairView, login_view, logout_view, user_profile_view
from .view_modules.auth_views import (
    auth_status,
    exchange_auth_code,
    orcid_callback,
    orcid_login_initiate,
    orcid_token_exchange,
)

urlpatterns = [
    path("auth/login/", login_view, name="auth-login"),
    path("auth/logout/", logout_view, name="auth-logout"),
    path("auth/profile/", user_profile_view, name="auth-profile"),
    path(
        "auth/token/",
        CustomTokenObtainPairView.as_view(),
        name="auth-token-obtain-pair",
    ),
    path("auth/orcid/login/", orcid_login_initiate, name="orcid-login"),
    path("auth/orcid/callback/", orcid_callback, name="orcid-callback"),
    path("auth/orcid/token/", orcid_token_exchange, name="orcid-token"),
    path("auth/exchange-code/", exchange_auth_code, name="auth-exchange-code"),
    path("auth/status/", auth_status, name="auth-status"),
]
