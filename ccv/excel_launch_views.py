"""
Views for Excel launch code functionality.

These endpoints allow users to generate one-time codes for opening metadata tables
directly in the Excel add-in from the web application.
"""

from datetime import timedelta

from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import ExcelLaunchCode, MetadataTable


class LaunchCodeClaimThrottle(AnonRateThrottle):
    """Rate limit for launch code claim attempts to prevent brute force."""

    rate = "10/minute"


def get_client_ip(request):
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def user_can_access_table(user, table):
    """Check if user has access to the specified table."""
    if table.owner == user:
        return True
    if table.lab_group and user in table.lab_group.members.all():
        return True
    if user.is_superuser:
        return True
    return False


class ExcelLaunchCreateView(APIView):
    """Create a new launch code for opening a table in Excel."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a new launch code."""
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

        if not user_can_access_table(request.user, table):
            return Response(
                {"detail": "You do not have access to this table"},
                status=status.HTTP_403_FORBIDDEN,
            )

        code = ExcelLaunchCode.generate_code()
        while ExcelLaunchCode.objects.filter(code=code).exists():
            code = ExcelLaunchCode.generate_code()

        launch_code = ExcelLaunchCode.objects.create(
            code=code,
            user=request.user,
            table=table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        return Response(
            {
                "code": launch_code.code,
                "tableId": table.id,
                "tableName": table.name,
                "expiresAt": launch_code.expires_at.isoformat(),
                "createdAt": launch_code.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class ExcelLaunchPendingView(APIView):
    """Get the most recent pending launch code for the current user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the most recent unclaimed, unexpired launch code."""
        pending = (
            ExcelLaunchCode.objects.filter(
                user=request.user,
                claimed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

        if not pending:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {
                "code": pending.code,
                "tableId": pending.table_id,
                "tableName": pending.table.name,
                "userId": pending.user_id,
            }
        )


class ExcelLaunchClaimView(APIView):
    """Exchange a launch code for authentication tokens and table information."""

    permission_classes = [AllowAny]
    throttle_classes = [LaunchCodeClaimThrottle]

    def post(self, request, code):
        """Claim a launch code and receive JWT tokens."""
        code = code.upper().strip()

        try:
            launch_code = ExcelLaunchCode.objects.select_related("user", "table").get(code=code)
        except ExcelLaunchCode.DoesNotExist:
            return Response(
                {"detail": "Invalid launch code"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if launch_code.is_claimed():
            return Response(
                {"detail": "This launch code has already been used"},
                status=status.HTTP_410_GONE,
            )

        if launch_code.is_expired():
            return Response(
                {"detail": "This launch code has expired"},
                status=status.HTTP_410_GONE,
            )

        launch_code.claimed_at = timezone.now()
        launch_code.claimed_ip = get_client_ip(request)
        launch_code.save()

        refresh = RefreshToken.for_user(launch_code.user)

        return Response(
            {
                "accessToken": str(refresh.access_token),
                "refreshToken": str(refresh),
                "tableId": launch_code.table_id,
                "tableName": launch_code.table.name,
                "user": {
                    "id": launch_code.user.id,
                    "username": launch_code.user.username,
                    "email": launch_code.user.email,
                },
            }
        )


class ExcelLaunchDeleteView(APIView):
    """Cancel a pending launch code."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, code):
        """Delete an unclaimed launch code belonging to the current user."""
        code = code.upper().strip()

        deleted, _ = ExcelLaunchCode.objects.filter(
            code=code,
            user=request.user,
            claimed_at__isnull=True,
        ).delete()

        if deleted == 0:
            return Response(
                {"detail": "Launch code not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
