"""
Authentication views for ORCID OAuth2 integration.
"""

import json
import logging
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from rest_framework_simplejwt.tokens import RefreshToken

from ..auth_backends import ORCIDOAuth2Helper

ORCID_CODE_CACHE_PREFIX = "orcid_auth_code_"
ORCID_CODE_EXPIRY = 60

logger = logging.getLogger(__name__)


@require_GET
def orcid_login_initiate(request):
    """
    Initiate ORCID OAuth2 authentication flow.

    Returns authorization URL that the frontend should redirect to.
    """
    try:
        authorization_url, state = ORCIDOAuth2Helper.get_authorization_url(request)

        remember_me = request.GET.get("remember_me", "false").lower() == "true"

        request.session["orcid_state"] = state
        request.session["orcid_remember_me"] = remember_me

        return JsonResponse({"authorization_url": authorization_url, "state": state})

    except ValueError as e:
        logger.error(f"ORCID configuration error: {e}")
        return JsonResponse({"error": "ORCID authentication not properly configured"}, status=500)
    except Exception as e:
        logger.error(f"Error initiating ORCID login: {e}")
        return JsonResponse({"error": "Failed to initiate ORCID authentication"}, status=500)


@require_GET
def orcid_callback(request):
    """
    Handle ORCID OAuth2 callback.

    Exchange authorization code for access token and authenticate user.
    Redirects back to frontend with tokens in query parameters.
    """
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")
    remember_me = request.session.get("orcid_remember_me", False)

    frontend_url = "/#/login"

    if error:
        logger.warning(f"ORCID authentication error: {error}")
        params = urlencode({"error": f"ORCID authentication failed: {error}"})
        return HttpResponseRedirect(f"{frontend_url}?{params}")

    if not code or not state:
        params = urlencode({"error": "Missing required parameters"})
        return HttpResponseRedirect(f"{frontend_url}?{params}")

    stored_state = request.session.get("orcid_state")
    if not stored_state or stored_state != state:
        logger.warning("ORCID state mismatch - possible CSRF attack")
        params = urlencode({"error": "Invalid state parameter"})
        return HttpResponseRedirect(f"{frontend_url}?{params}")

    try:
        token_data = ORCIDOAuth2Helper.exchange_code_for_token(request, code, state)
        if not token_data:
            params = urlencode({"error": "Failed to exchange code for token"})
            return HttpResponseRedirect(f"{frontend_url}?{params}")

        orcid_id = token_data.get("orcid")
        access_token = token_data.get("access_token")
        orcid_name = token_data.get("name", "")

        if not orcid_id or not access_token:
            params = urlencode({"error": "Invalid token response from ORCID"})
            return HttpResponseRedirect(f"{frontend_url}?{params}")

        user = authenticate(
            request,
            orcid_token=access_token,
            orcid_id=orcid_id,
            orcid_name=orcid_name,
            verify_token=False,
        )

        if not user:
            params = urlencode({"error": "Authentication failed"})
            return HttpResponseRedirect(f"{frontend_url}?{params}")

        refresh = RefreshToken.for_user(user)
        access_jwt = refresh.access_token

        if remember_me:
            refresh.set_exp(lifetime=settings.JWT_REMEMBER_ME_REFRESH_TOKEN_LIFETIME)
            access_jwt.set_exp(lifetime=settings.JWT_REMEMBER_ME_ACCESS_TOKEN_LIFETIME)

        access_jwt["username"] = user.username
        access_jwt["email"] = user.email
        access_jwt["is_staff"] = user.is_staff
        access_jwt["is_superuser"] = user.is_superuser

        if "orcid_state" in request.session:
            del request.session["orcid_state"]
        if "orcid_remember_me" in request.session:
            del request.session["orcid_remember_me"]

        auth_code = secrets.token_urlsafe(32)
        cache_key = f"{ORCID_CODE_CACHE_PREFIX}{auth_code}"
        cache.set(
            cache_key,
            {
                "access_token": str(access_jwt),
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "orcid_id": orcid_id,
                },
            },
            ORCID_CODE_EXPIRY,
        )

        logger.info(f"ORCID login successful for user {user.username}, redirecting with auth code")
        return HttpResponseRedirect(f"{frontend_url}?auth_code={auth_code}")

    except ValueError as e:
        logger.error(f"ORCID configuration error: {e}")
        params = urlencode({"error": "ORCID authentication not properly configured"})
        return HttpResponseRedirect(f"{frontend_url}?{params}")
    except Exception as e:
        logger.error(f"Error in ORCID callback: {e}")
        params = urlencode({"error": "Authentication processing failed"})
        return HttpResponseRedirect(f"{frontend_url}?{params}")


@csrf_exempt
@require_POST
def orcid_token_exchange(request):
    """
    Alternative endpoint for token-based authentication.

    Useful for frontend applications that handle the OAuth flow client-side.
    Expects: {"access_token": "...", "orcid_id": "...", "remember_me": false}
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    access_token = data.get("access_token")
    orcid_id = data.get("orcid_id")
    remember_me = data.get("remember_me", False)

    if not access_token or not orcid_id:
        return JsonResponse({"error": "access_token and orcid_id are required"}, status=400)

    try:
        user = authenticate(request, orcid_token=access_token, orcid_id=orcid_id)

        if not user:
            return JsonResponse({"error": "Authentication failed"}, status=401)

        refresh = RefreshToken.for_user(user)
        access_jwt = refresh.access_token

        if remember_me:
            refresh.set_exp(lifetime=settings.JWT_REMEMBER_ME_REFRESH_TOKEN_LIFETIME)
            access_jwt.set_exp(lifetime=settings.JWT_REMEMBER_ME_ACCESS_TOKEN_LIFETIME)

        access_jwt["username"] = user.username
        access_jwt["email"] = user.email
        access_jwt["is_staff"] = user.is_staff
        access_jwt["is_superuser"] = user.is_superuser

        return JsonResponse(
            {
                "access_token": str(access_jwt),
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "orcid_id": orcid_id,
                },
            }
        )

    except Exception as e:
        logger.error(f"Error in ORCID token exchange: {e}")
        return JsonResponse({"error": "Authentication processing failed"}, status=500)


@require_GET
def auth_status(request):
    """
    Check authentication status and return user info if authenticated.
    """
    if request.user.is_authenticated:
        return JsonResponse(
            {
                "authenticated": True,
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                },
            }
        )
    else:
        return JsonResponse({"authenticated": False})


@csrf_exempt
@require_POST
def exchange_auth_code(request):
    """
    Exchange a short-lived auth code for JWT tokens.

    This endpoint is used after ORCID OAuth callback to securely
    transfer tokens to the frontend without exposing them in URLs.

    Expected payload: {"auth_code": "..."}
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    auth_code = data.get("auth_code")

    if not auth_code:
        return JsonResponse({"error": "auth_code is required"}, status=400)

    cache_key = f"{ORCID_CODE_CACHE_PREFIX}{auth_code}"
    token_data = cache.get(cache_key)

    if not token_data:
        return JsonResponse({"error": "Invalid or expired auth code"}, status=401)

    cache.delete(cache_key)

    return JsonResponse(
        {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "user": token_data["user"],
        }
    )
