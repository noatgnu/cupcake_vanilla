"""
Authentication views for ORCID OAuth2 integration.
"""

import logging

from django.contrib.auth import authenticate

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from ..auth_backends import ORCIDOAuth2Helper

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def orcid_login_initiate(request):
    """
    Initiate ORCID OAuth2 authentication flow.

    Returns authorization URL that the frontend should redirect to.
    """
    try:
        authorization_url, state = ORCIDOAuth2Helper.get_authorization_url(request)

        # Store state in session for CSRF protection
        request.session["orcid_state"] = state

        return Response({"authorization_url": authorization_url, "state": state})

    except ValueError as e:
        logger.error(f"ORCID configuration error: {e}")
        return Response(
            {"error": "ORCID authentication not properly configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error initiating ORCID login: {e}")
        return Response(
            {"error": "Failed to initiate ORCID authentication"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def orcid_callback(request):
    """
    Handle ORCID OAuth2 callback.

    Exchange authorization code for access token and authenticate user.
    """
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")

    # Check for error from ORCID
    if error:
        logger.warning(f"ORCID authentication error: {error}")
        return Response({"error": f"ORCID authentication failed: {error}"}, status=status.HTTP_400_BAD_REQUEST)

    # Validate required parameters
    if not code or not state:
        return Response({"error": "Missing required parameters"}, status=status.HTTP_400_BAD_REQUEST)

    # Verify state for CSRF protection
    stored_state = request.session.get("orcid_state")
    if not stored_state or stored_state != state:
        logger.warning("ORCID state mismatch - possible CSRF attack")
        return Response({"error": "Invalid state parameter"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Exchange code for token
        token_data = ORCIDOAuth2Helper.exchange_code_for_token(request, code, state)
        if not token_data:
            return Response({"error": "Failed to exchange code for token"}, status=status.HTTP_400_BAD_REQUEST)

        # Extract ORCID ID and access token
        orcid_id = token_data.get("orcid")
        access_token = token_data.get("access_token")

        if not orcid_id or not access_token:
            return Response({"error": "Invalid token response from ORCID"}, status=status.HTTP_400_BAD_REQUEST)

        # Authenticate user using our custom backend
        user = authenticate(request, orcid_token=access_token, orcid_id=orcid_id)

        if not user:
            return Response({"error": "Authentication failed"}, status=status.HTTP_401_UNAUTHORIZED)

        # Generate JWT tokens for the user
        refresh = RefreshToken.for_user(user)
        access_jwt = refresh.access_token

        # Clean up session
        if "orcid_state" in request.session:
            del request.session["orcid_state"]

        # Return user data and tokens
        return Response(
            {
                "access_token": str(access_jwt),
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "orcid_id": orcid_id,
                },
            }
        )

    except ValueError as e:
        logger.error(f"ORCID configuration error: {e}")
        return Response(
            {"error": "ORCID authentication not properly configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error in ORCID callback: {e}")
        return Response({"error": "Authentication processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([AllowAny])
def orcid_token_exchange(request):
    """
    Alternative endpoint for token-based authentication.

    Useful for frontend applications that handle the OAuth flow client-side.
    Expects: {"access_token": "...", "orcid_id": "..."}
    """
    access_token = request.data.get("access_token")
    orcid_id = request.data.get("orcid_id")

    if not access_token or not orcid_id:
        return Response({"error": "access_token and orcid_id are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Authenticate user using our custom backend
        user = authenticate(request, orcid_token=access_token, orcid_id=orcid_id)

        if not user:
            return Response({"error": "Authentication failed"}, status=status.HTTP_401_UNAUTHORIZED)

        # Generate JWT tokens for the user
        refresh = RefreshToken.for_user(user)
        access_jwt = refresh.access_token

        return Response(
            {
                "access_token": str(access_jwt),
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "orcid_id": orcid_id,
                },
            }
        )

    except Exception as e:
        logger.error(f"Error in ORCID token exchange: {e}")
        return Response({"error": "Authentication processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([AllowAny])
def auth_status(request):
    """
    Check authentication status and return user info if authenticated.
    """
    if request.user.is_authenticated:
        return Response(
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
        return Response({"authenticated": False})
