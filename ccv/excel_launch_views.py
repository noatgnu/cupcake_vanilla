"""
Views for Excel launch code functionality.

Uses stateless signed tokens (django.core.signing.TimestampSigner) -
no database models or cache storage required.
"""

from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .excel_launch_utils import EXCEL_LAUNCH_MAX_AGE, create_launch_code, verify_launch_code
from .models import MetadataTable

User = get_user_model()


class LaunchCodeClaimThrottle(AnonRateThrottle):
    """Rate limit for launch code claim attempts to prevent brute force."""

    rate = "10/minute"


def _user_can_access_table(user, table):
    """Check if user has read access to the specified table."""
    if table.owner == user:
        return True
    if table.lab_group and user in table.lab_group.members.all():
        return True
    if user.is_superuser:
        return True
    return False


class ExcelLaunchCreateView(APIView):
    """Create a signed launch code for opening a table in the Excel add-in."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create and return a signed launch code."""
        table_id = request.data.get("tableId")

        if not table_id:
            return Response(
                {"detail": "tableId is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            table = MetadataTable.objects.get(id=table_id)
        except MetadataTable.DoesNotExist:
            return Response(
                {"detail": "Table not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _user_can_access_table(request.user, table):
            return Response(
                {"detail": "You do not have access to this table"},
                status=status.HTTP_403_FORBIDDEN,
            )

        code = create_launch_code(request.user.id, table.id)

        return Response(
            {
                "code": code,
                "tableId": table.id,
                "tableName": table.name,
                "expiresIn": EXCEL_LAUNCH_MAX_AGE,
            },
            status=status.HTTP_201_CREATED,
        )


class ExcelLaunchClaimView(APIView):
    """Exchange a signed launch code for JWT tokens and table information."""

    permission_classes = [AllowAny]
    throttle_classes = [LaunchCodeClaimThrottle]

    def post(self, request):
        """Verify a launch code and return JWT tokens."""
        code = request.data.get("code", "").strip()

        if not code:
            return Response(
                {"detail": "Launch code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = verify_launch_code(code)
        except SignatureExpired:
            return Response(
                {"detail": "This launch code has expired"},
                status=status.HTTP_410_GONE,
            )
        except BadSignature:
            return Response(
                {"detail": "Invalid launch code"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(id=payload["user_id"])
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            table = MetadataTable.objects.get(id=payload["table_id"])
        except MetadataTable.DoesNotExist:
            return Response(
                {"detail": "Table not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "accessToken": str(refresh.access_token),
                "refreshToken": str(refresh),
                "tableId": table.id,
                "tableName": table.name,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            }
        )
