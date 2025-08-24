"""
JWT Authentication utilities for CUPCAKE Core.
"""

from datetime import datetime

from django.contrib.auth.models import User

from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


def create_jwt_tokens_for_user(user):
    """
    Create JWT tokens for a given user.

    Args:
        user: Django User instance

    Returns:
        dict: Dictionary containing access and refresh tokens
    """
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token

    # Add custom claims
    access_token["username"] = user.username
    access_token["email"] = user.email
    access_token["is_staff"] = user.is_staff
    access_token["is_superuser"] = user.is_superuser

    return {
        "access": str(access_token),
        "refresh": str(refresh),
        "access_expires": access_token["exp"],
        "refresh_expires": refresh["exp"],
    }


def verify_jwt_token(token):
    """
    Verify if a JWT token is valid.

    Args:
        token: JWT token string

    Returns:
        dict: Token payload if valid, None if invalid
    """
    try:
        access_token = AccessToken(token)
        return access_token.payload
    except (TokenError, InvalidToken):
        return None


def get_user_from_token(token):
    """
    Get user instance from JWT token.

    Args:
        token: JWT token string

    Returns:
        User: Django User instance if valid, None if invalid
    """
    try:
        access_token = AccessToken(token)
        user_id = access_token.payload.get("user_id")
        if user_id:
            return User.objects.get(id=user_id)
    except (TokenError, InvalidToken, User.DoesNotExist):
        pass
    return None


def blacklist_token(refresh_token):
    """
    Blacklist a refresh token.

    Args:
        refresh_token: Refresh token string

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        return True
    except (TokenError, InvalidToken):
        return False


def get_token_expiry_info(token):
    """
    Get expiry information for a JWT token.

    Args:
        token: JWT token string

    Returns:
        dict: Expiry information or None if invalid
    """
    try:
        access_token = AccessToken(token)
        exp_timestamp = access_token.payload.get("exp")
        if exp_timestamp:
            exp_datetime = datetime.fromtimestamp(exp_timestamp)
            now = datetime.now()
            time_remaining = exp_datetime - now

            return {
                "expires_at": exp_datetime,
                "is_expired": now > exp_datetime,
                "time_remaining": time_remaining,
                "time_remaining_seconds": time_remaining.total_seconds(),
            }
    except (TokenError, InvalidToken):
        pass
    return None


def create_error_response(message, status_code=status.HTTP_400_BAD_REQUEST):
    """
    Create a standardized error response.

    Args:
        message: Error message
        status_code: HTTP status code

    Returns:
        Response: DRF Response object
    """
    return Response({"error": message}, status=status_code)


def create_success_response(data, message=None):
    """
    Create a standardized success response.

    Args:
        data: Response data
        message: Optional success message

    Returns:
        Response: DRF Response object
    """
    response_data = data.copy() if isinstance(data, dict) else {"data": data}
    if message:
        response_data["message"] = message

    return Response(response_data, status=status.HTTP_200_OK)
