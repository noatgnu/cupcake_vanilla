"""
Custom JWT authentication views and utilities for CUPCAKE Core.
"""

import json

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token serializer that includes additional user information.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims
        token["username"] = user.username
        token["email"] = user.email
        token["is_staff"] = user.is_staff
        token["is_superuser"] = user.is_superuser

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        request = self.context.get("request")
        remember_me = False
        if request and hasattr(request, "data"):
            remember_me = request.data.get("remember_me", False)

        if remember_me:
            refresh = RefreshToken.for_user(self.user)
            refresh.set_exp(lifetime=settings.JWT_REMEMBER_ME_REFRESH_TOKEN_LIFETIME)
            access = refresh.access_token
            access.set_exp(lifetime=settings.JWT_REMEMBER_ME_ACCESS_TOKEN_LIFETIME)

            access["username"] = self.user.username
            access["email"] = self.user.email
            access["is_staff"] = self.user.is_staff
            access["is_superuser"] = self.user.is_superuser

            data["access"] = str(access)
            data["refresh"] = str(refresh)

        data.update(
            {
                "user": {
                    "id": self.user.id,
                    "username": self.user.username,
                    "email": self.user.email,
                    "first_name": self.user.first_name,
                    "last_name": self.user.last_name,
                    "is_staff": self.user.is_staff,
                    "is_superuser": self.user.is_superuser,
                    "date_joined": self.user.date_joined,
                    "last_login": self.user.last_login,
                }
            }
        )

        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom JWT token obtain view with enhanced user information.
    """

    serializer_class = CustomTokenObtainPairSerializer


@csrf_exempt
@require_POST
def login_view(request):
    """
    Alternative login endpoint that returns JWT tokens.

    Expected payload:
    {
        "username": "your_username",
        "password": "your_password",
        "remember_me": false
    }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    username = data.get("username")
    password = data.get("password")
    remember_me = data.get("remember_me", False)

    if not username or not password:
        return JsonResponse({"error": "Username and password are required"}, status=400)

    user = authenticate(username=username, password=password)

    if user:
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token

        if remember_me:
            refresh.set_exp(lifetime=settings.JWT_REMEMBER_ME_REFRESH_TOKEN_LIFETIME)
            access_token.set_exp(lifetime=settings.JWT_REMEMBER_ME_ACCESS_TOKEN_LIFETIME)

        access_token["username"] = user.username
        access_token["email"] = user.email
        access_token["is_staff"] = user.is_staff
        access_token["is_superuser"] = user.is_superuser

        return JsonResponse(
            {
                "access_token": str(access_token),
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "date_joined": user.date_joined.isoformat() if user.date_joined else None,
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                },
            }
        )
    else:
        return JsonResponse({"error": "Invalid credentials"}, status=401)


@api_view(["POST"])
def logout_view(request):
    """
    Logout endpoint that blacklists the refresh token.

    Expected payload:
    {
        "refresh": "your_refresh_token"
    }
    """
    try:
        refresh_token = request.data.get("refresh_token") or request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": "Refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = RefreshToken(refresh_token)
        token.blacklist()

        return Response({"message": "Successfully logged out"}, status=status.HTTP_200_OK)
    except Exception:
        return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def user_profile_view(request):
    """
    Get current user profile information.
    Requires authentication.
    """
    if request.user.is_authenticated:
        return Response(
            {
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                    "is_staff": request.user.is_staff,
                    "is_superuser": request.user.is_superuser,
                    "date_joined": request.user.date_joined,
                    "last_login": request.user.last_login,
                }
            },
            status=status.HTTP_200_OK,
        )
    else:
        return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
