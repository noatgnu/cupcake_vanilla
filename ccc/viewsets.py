"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Views.

This module contains ViewSets for user management, lab group collaboration,
and site administration functionality.
"""

import json
import logging
import os
import re
import socket as _socket
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.db import models
from django.db.models import Q
from django.http import HttpResponse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from django_filters.rest_framework import DjangoFilterBackend
from django_filters.views import FilterMixin
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from ccc.permissions import IsSuperUser

from .models import (
    Annotation,
    AnnotationFolder,
    BackupLog,
    LabGroup,
    LabGroupInvitation,
    LabGroupPermission,
    RemoteHost,
    ResourcePermission,
    SiteConfig,
    UserOrcidProfile,
)
from .serializers import (
    AccountLinkingSerializer,
    AccountMergeRequestSerializer,
    AdminPasswordResetSerializer,
    AnnotationFolderSerializer,
    AnnotationSerializer,
    BackupLogSerializer,
    DuplicateAccountDetectionSerializer,
    EmailChangeConfirmSerializer,
    EmailChangeRequestSerializer,
    LabGroupInvitationSerializer,
    LabGroupPermissionSerializer,
    LabGroupSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RemoteHostSerializer,
    ResourcePermissionSerializer,
    SiteConfigSerializer,
    UserCreateSerializer,
    UserOrcidProfileSerializer,
    UserProfileUpdateSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)
from .tasks import run_backup as run_backup_task

logger = logging.getLogger(__name__)


class SiteConfigViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for site configuration management."""

    queryset = SiteConfig.objects.all()
    serializer_class = SiteConfigSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["site_name"]
    filterset_fields = ["allow_user_registration", "enable_orcid_login", "show_powered_by"]

    def get_queryset(self):
        """Return singleton site config."""
        return SiteConfig.objects.all()[:1]

    def create(self, request, *args, **kwargs):
        """Create site config if none exists."""
        if SiteConfig.objects.exists():
            return Response(
                {"error": "Site configuration already exists. Use update instead."}, status=status.HTTP_400_BAD_REQUEST
            )
        return super().create(request, *args, **kwargs)

    def perform_update(self, serializer):
        """Track who updated the configuration."""
        serializer.save(updated_by=self.request.user)

    def perform_create(self, serializer):
        """Track who created the configuration."""
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def public(self, request):
        """Get public site configuration (no auth required)."""
        try:
            site_config = SiteConfig.objects.first()
            if site_config:
                serializer = self.get_serializer(site_config)
                data = {
                    "site_name": serializer.data["site_name"],
                    "logo_url": serializer.data["logo_url"],
                    "primary_color": serializer.data["primary_color"],
                    "show_powered_by": serializer.data["show_powered_by"],
                    "allow_user_registration": serializer.data["allow_user_registration"],
                    "enable_orcid_login": serializer.data["enable_orcid_login"],
                    "booking_deletion_window_minutes": serializer.data["booking_deletion_window_minutes"],
                    "ui_features": serializer.data["ui_features_with_defaults"],
                    "installed_apps": serializer.data["installed_apps"],
                    "max_upload_size": serializer.data["max_upload_size"],
                    "max_chunked_upload_size": serializer.data["max_chunked_upload_size"],
                    "demo_mode": settings.DEMO_MODE,
                    "demo_cleanup_interval_minutes": settings.DEMO_CLEANUP_INTERVAL_MINUTES
                    if settings.DEMO_MODE
                    else None,
                }
                return Response(data)
            else:
                default_config = SiteConfig()
                temp_serializer = self.get_serializer(default_config)
                return Response(
                    {
                        "site_name": "CUPCAKE",
                        "primary_color": "#1976d2",
                        "show_powered_by": True,
                        "allow_user_registration": False,
                        "enable_orcid_login": False,
                        "booking_deletion_window_minutes": 30,
                        "ui_features": temp_serializer.data["ui_features_with_defaults"],
                        "installed_apps": temp_serializer.data["installed_apps"],
                        "max_upload_size": temp_serializer.data["max_upload_size"],
                        "max_chunked_upload_size": temp_serializer.data["max_chunked_upload_size"],
                        "demo_mode": settings.DEMO_MODE,
                        "demo_cleanup_interval_minutes": settings.DEMO_CLEANUP_INTERVAL_MINUTES
                        if settings.DEMO_MODE
                        else None,
                    }
                )
        except Exception as e:
            return Response(
                {"error": f"Failed to get site config: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["put"], permission_classes=[IsAdminUser])
    def update_config(self, request):
        """Update site configuration settings."""
        try:
            site_config = SiteConfig.objects.first()
            if not site_config:
                site_config = SiteConfig.objects.create()

            serializer = SiteConfigSerializer(site_config, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save(updated_by=request.user)
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to update site config: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def current(self, request):
        """Get current site configuration (admin only)."""
        try:
            site_config = SiteConfig.objects.first()
            if not site_config:
                site_config = SiteConfig.objects.create()
            serializer = SiteConfigSerializer(site_config)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {"error": f"Failed to get site config: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def available_whisper_models(self, request):
        """
        Get cached list of available Whisper.cpp models reported by transcribe worker.

        The transcribe worker scans its filesystem on startup and caches the results.
        Use the refresh_whisper_models endpoint to trigger a new scan.
        """
        try:
            site_config = SiteConfig.objects.first()
            if not site_config:
                return Response({"models": [], "count": 0, "message": "No site config found. Models not yet scanned."})

            models = site_config.cached_available_models or []
            return Response({"models": models, "count": len(models)})
        except Exception as e:
            return Response(
                {"error": f"Failed to get available models: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["post"], permission_classes=[IsAdminUser])
    def refresh_whisper_models(self, request):
        """
        Trigger transcribe worker to scan and update available Whisper.cpp models.

        This queues a job on the transcribe worker to scan its filesystem
        and update the cached list of available models.
        """
        try:
            from ccc.tasks import refresh_available_whisper_models

            job = refresh_available_whisper_models.delay()

            return Response(
                {
                    "status": "queued",
                    "message": "Model scan queued on transcribe worker",
                    "job_id": job.id,
                }
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to queue model scan: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"], permission_classes=[IsSuperUser])
    def worker_status(self, request):
        """
        Get status of all RQ workers across all queues.

        Returns information about each worker including:
        - Worker name
        - Queue names
        - Current job
        - State (idle/busy)
        - Birth time
        - Job statistics

        Only accessible to superusers.
        """
        try:
            import django_rq
            from rq.worker import Worker

            queue_names = ["default", "high", "low", "transcribe"]

            queue = django_rq.get_queue("default")
            workers = Worker.all(connection=queue.connection)

            workers_info = []
            for worker in workers:
                state = worker.get_state()
                queues = [q.name for q in worker.queues]
                current_job = worker.get_current_job()

                worker_info = {
                    "name": worker.name,
                    "hostname": worker.hostname,
                    "pid": worker.pid,
                    "state": state,
                    "queues": queues,
                    "birth": worker.birth_date.isoformat() if worker.birth_date else None,
                    "successful_job_count": worker.successful_job_count,
                    "failed_job_count": worker.failed_job_count,
                    "total_working_time": worker.total_working_time,
                    "current_job": None,
                }

                if current_job:
                    worker_info["current_job"] = {
                        "id": current_job.id,
                        "func_name": current_job.func_name,
                        "created_at": current_job.created_at.isoformat() if current_job.created_at else None,
                        "started_at": current_job.started_at.isoformat() if current_job.started_at else None,
                        "description": current_job.description,
                    }

                workers_info.append(worker_info)

            queue_stats = {}
            for queue_name in queue_names:
                try:
                    q = django_rq.get_queue(queue_name)
                    queue_stats[queue_name] = {
                        "count": len(q),
                        "failed_count": q.failed_job_registry.count,
                        "scheduled_count": q.scheduled_job_registry.count,
                        "started_count": q.started_job_registry.count,
                        "finished_count": q.finished_job_registry.count,
                    }
                except Exception as e:
                    queue_stats[queue_name] = {"error": str(e)}

            return Response(
                {
                    "workers": workers_info,
                    "worker_count": len(workers_info),
                    "queues": queue_stats,
                }
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to get worker status: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LabGroupViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for lab group management."""

    queryset = LabGroup.objects.select_related("parent_group", "creator").all()
    serializer_class = LabGroupSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["name", "description", "creator__username"]
    filterset_fields = {
        "creator": ["exact"],
        "parent_group": ["exact", "isnull"],
        "allow_member_invites": ["exact"],
        "is_active": ["exact"],
    }
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """
        Return lab groups accessible to the current user.

        Users can see:
        1. Groups they created
        2. Groups they're direct members of
        3. Parent groups of groups they're members of (bubble-up)
        """
        user = self.request.user
        if user.is_staff:
            # Admins can see all groups
            return LabGroup.objects.all()
        else:
            # Start with groups user created or is a direct member of
            accessible_groups = set()

            # Groups where user is creator or direct member
            direct_groups = LabGroup.objects.filter(Q(members=user) | Q(creator=user))

            for group in direct_groups:
                # Add the group itself
                accessible_groups.add(group.id)

                # Add all parent groups (bubble up)
                current = group.parent_group
                while current:
                    accessible_groups.add(current.id)
                    current = current.parent_group

            return LabGroup.objects.filter(id__in=accessible_groups).distinct()

    @action(detail=False, methods=["get"])
    def my_groups(self, request):
        """Get lab groups the current user is a member of or has created."""
        user = request.user
        groups = self.get_queryset()
        groups = groups.filter(Q(members=user) | Q(creator=user)).distinct()
        paginator = self.pagination_class()
        paginated_groups = paginator.paginate_queryset(groups, request)
        serializer = self.get_serializer(paginated_groups, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"])
    def invite_user(self, request, pk=None):
        """Invite a user to join this lab group."""
        lab_group = self.get_object()

        # Check permissions
        if not lab_group.can_invite(request.user):
            return Response(
                {"error": "You don't have permission to invite users to this lab group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Create invitation
        invitation_data = {
            "lab_group": lab_group.id,
            "invited_email": request.data.get("invited_email"),
            "message": request.data.get("message", ""),
        }

        serializer = LabGroupInvitationSerializer(data=invitation_data, context={"request": request})
        if serializer.is_valid():
            invitation = serializer.save()

            # Send email notification to invited user
            try:
                invited_email = invitation.invited_email
                inviter_name = request.user.get_full_name() or request.user.username
                lab_group_name = lab_group.name

                subject = f"Lab Group Invitation: {lab_group_name}"

                # Create invitation acceptance URL
                frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:4200")
                invitation_url = f"{frontend_url}/lab-groups/invitations/{invitation.id}/accept"

                message = f"""
{inviter_name} has invited you to join the lab group "{lab_group_name}".

{invitation.message if invitation.message else ""}

To accept this invitation, please click the following link:
{invitation_url}

If you don't have an account yet, you'll be prompted to create one.

If you did not expect this invitation, you can safely ignore this email.

Best regards,
The Team
                """.strip()

                send_mail(
                    subject,
                    message,
                    getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                    [invited_email],
                    fail_silently=True,  # Don't fail the invitation if email fails
                )
            except Exception as e:
                # Log the error but don't fail the invitation creation
                # Could be logged to a proper logging system in production
                print(f"Failed to send invitation email: {str(e)}")

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        """
        Get members of this lab group.

        Query Parameters:
            - direct_only: 'true' to get only direct members, default is 'false' (includes sub-group members)
            - page: Page number for pagination
            - page_size: Number of items per page (default: 100)
        """
        lab_group = self.get_object()

        # Check if user can view members (staff can always view)
        if not (request.user.is_staff or lab_group.is_member(request.user) or lab_group.is_creator(request.user)):
            return Response(
                {"error": "You don't have permission to view members of this lab group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get query parameter for direct members only
        direct_only = request.query_params.get("direct_only", "false").lower() == "true"

        # Get members based on parameter
        members = lab_group.get_all_members(include_subgroups=not direct_only)

        # Pagination
        page_size = int(request.query_params.get("page_size", 100))
        paginator = self.pagination_class()
        paginator.page_size = page_size

        page = paginator.paginate_queryset(members, request)
        serializer = UserSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"])
    def check_membership(self, request, pk=None):
        """
        Check if a user is a member of this lab group.

        Query Parameters:
            - user_id: User ID to check (optional, defaults to current user)

        Returns:
            - is_member: Boolean indicating membership status
            - is_direct_member: Boolean indicating direct membership (not through subgroup)
            - user_id: ID of the checked user
        """
        lab_group = self.get_object()
        user_id = request.query_params.get("user_id")

        if user_id:
            try:
                check_user = get_user_model().objects.get(id=user_id)
            except get_user_model().DoesNotExist:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            check_user = request.user

        is_member = lab_group.is_member(check_user)
        is_direct_member = lab_group.members.filter(id=check_user.id).exists()

        return Response(
            {
                "is_member": is_member,
                "is_direct_member": is_direct_member,
                "user_id": check_user.id,
                "user_username": check_user.username,
            }
        )

    @action(detail=True, methods=["get"])
    def invitations(self, request, pk=None):
        """Get invitations for this lab group."""
        lab_group = self.get_object()

        # Check permissions
        if not lab_group.can_manage(request.user):
            return Response(
                {"error": "You don't have permission to view invitations for this lab group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        invitations = lab_group.invitations.all()
        serializer = LabGroupInvitationSerializer(invitations, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        """Leave this lab group."""
        lab_group = self.get_object()

        if not lab_group.is_member(request.user):
            return Response(
                {"error": "You are not a member of this lab group"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Creator cannot leave unless they transfer ownership first
        if lab_group.is_creator(request.user):
            return Response(
                {"error": "Group creator cannot leave. Transfer ownership first or delete the group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lab_group.members.remove(request.user)
        return Response({"message": "Successfully left the lab group"})

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        """Remove a member from this lab group (admin/manager only)."""
        lab_group = self.get_object()

        # Check permissions - only staff, creator, or group managers can remove members
        if not (request.user.is_staff or lab_group.is_creator(request.user) or lab_group.can_manage(request.user)):
            return Response(
                {"error": "You don't have permission to remove members from this lab group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get user_id from request data
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"error": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user_to_remove = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if user is actually a member
        if not lab_group.is_member(user_to_remove):
            return Response(
                {"error": "User is not a member of this lab group"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Creator cannot be removed
        if lab_group.is_creator(user_to_remove):
            return Response(
                {"error": "Group creator cannot be removed. Transfer ownership first or delete the group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Remove the member
        lab_group.members.remove(user_to_remove)
        return Response({"message": f"Successfully removed {user_to_remove.username} from {lab_group.name}"})


class LabGroupInvitationViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for managing lab group invitations."""

    queryset = LabGroupInvitation.objects.all()
    serializer_class = LabGroupInvitationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["lab_group", "status", "invited_email"]
    search_fields = ["invited_email", "lab_group__name"]

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def my_pending_invitations(self, request):
        """Get current user's pending invitations."""
        pending_invitations = LabGroupInvitation.objects.filter(
            invited_email__iexact=request.user.email, status=LabGroupInvitation.InvitationStatus.PENDING
        )
        serializer = LabGroupInvitationSerializer(pending_invitations, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def accept_invitation(self, request, pk=None):
        """Accept a lab group invitation."""
        invitation = self.get_object()

        # Verify the invitation is for the current user
        if invitation.invited_email.lower() != request.user.email.lower():
            return Response(
                {"error": "You can only accept invitations sent to your email address"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check if invitation is still pending
        if invitation.status != LabGroupInvitation.InvitationStatus.PENDING:
            return Response({"error": "This invitation is no longer pending"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if invitation has expired
        if invitation.is_expired():
            invitation.status = LabGroupInvitation.InvitationStatus.EXPIRED
            invitation.save()
            return Response({"error": "This invitation has expired"}, status=status.HTTP_400_BAD_REQUEST)

        # Accept the invitation (this handles adding to group and permissions)
        invitation.accept(request.user)
        lab_group = invitation.lab_group

        return Response(
            {
                "message": f"Successfully joined {lab_group.name}",
                "lab_group": {"id": lab_group.id, "name": lab_group.name},
            }
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def reject_invitation(self, request, pk=None):
        """Reject a lab group invitation."""
        invitation = self.get_object()

        # Verify the invitation is for the current user
        if invitation.invited_email.lower() != request.user.email.lower():
            return Response(
                {"error": "You can only reject invitations sent to your email address"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check if invitation is still pending
        if invitation.status != LabGroupInvitation.InvitationStatus.PENDING:
            return Response({"error": "This invitation is no longer pending"}, status=status.HTTP_400_BAD_REQUEST)

        # Update invitation status
        invitation.status = LabGroupInvitation.InvitationStatus.REJECTED
        invitation.save()

        return Response({"message": f"Invitation to join {invitation.lab_group.name} has been rejected"})

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def cancel_invitation(self, request, pk=None):
        """Cancel a lab group invitation (for group admins)."""
        invitation = self.get_object()
        lab_group = invitation.lab_group

        # Check if user can manage the lab group
        if not lab_group.can_manage(request.user):
            return Response(
                {"error": "You don't have permission to manage this lab group"}, status=status.HTTP_403_FORBIDDEN
            )

        # Check if invitation is still pending
        if invitation.status != LabGroupInvitation.InvitationStatus.PENDING:
            return Response({"error": "Only pending invitations can be cancelled"}, status=status.HTTP_400_BAD_REQUEST)

        # Update invitation status
        invitation.status = LabGroupInvitation.InvitationStatus.CANCELLED
        invitation.save()

        return Response({"message": f"Invitation to {invitation.invited_email} has been cancelled"})


class LabGroupPermissionViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for managing lab group permissions."""

    queryset = LabGroupPermission.objects.all()
    serializer_class = LabGroupPermissionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["lab_group", "user", "can_view", "can_invite", "can_manage"]
    search_fields = ["user__username", "user__email", "lab_group__name"]

    def get_queryset(self):
        """Return permissions for lab groups the user can manage."""
        user = self.request.user
        if user.is_staff:
            return LabGroupPermission.objects.all()
        else:
            # Users can only see permissions for lab groups they can manage
            managed_groups = LabGroup.objects.filter(Q(creator=user))
            return LabGroupPermission.objects.filter(lab_group__in=managed_groups)

    def perform_create(self, serializer):
        """Check if user can manage the lab group before creating permission."""
        lab_group = serializer.validated_data.get("lab_group")
        if not lab_group.can_manage(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to manage this lab group")
        serializer.save()

    def perform_update(self, serializer):
        """Check if user can manage the lab group before updating permission."""
        lab_group = serializer.instance.lab_group
        if not lab_group.can_manage(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to manage this lab group")
        serializer.save()

    def perform_destroy(self, instance):
        """Check if user can manage the lab group before deleting permission."""
        if not instance.lab_group.can_manage(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to manage this lab group")
        instance.delete()


class UserManagementViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for user management operations."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_staff", "is_active"]
    search_fields = ["username", "email", "first_name", "last_name"]

    def create(self, request, *args, **kwargs):
        """Disable default create - use custom actions instead."""

        return Response(
            {"error": "Use /users/register/ for registration or /users/admin_create/ for admin user creation"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        """Disable default update - use custom actions instead."""
        if self.request.user.is_authenticated:
            if self.request.user.is_staff:
                return super().update(request, *args, **kwargs)
        return Response(
            {"error": "Use /users/update_profile/ to update user profiles"}, status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def partial_update(self, request, *args, **kwargs):
        """Disable default partial update - use custom actions instead."""
        if self.request.user.is_authenticated:
            if self.request.user.is_staff:
                return super().partial_update(request, *args, **kwargs)
        return Response(
            {"error": "Use /users/update_profile/ to update user profiles"}, status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def destroy(self, request, *args, **kwargs):
        """Disable default delete - admin should use Django admin for user deletion."""
        if self.request.user.is_authenticated:
            if self.request.user.is_staff:
                return super().destroy(request, *args, **kwargs)
        return Response(
            {"error": "User deletion should be done through Django admin interface"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["post"], permission_classes=[IsAdminUser])
    def admin_create(self, request):
        """
        Admin-only endpoint to create new users.
        Only users with admin/staff privileges can access this endpoint.
        """
        serializer = UserCreateSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                response_serializer = UserSerializer(user)
                return Response(
                    {"message": "User created successfully", "user": response_serializer.data},
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to create user: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def register(self, request):
        """
        Public user registration endpoint.
        Access to this endpoint is controlled by the site configuration setting 'allow_user_registration'.
        """
        # Check if user registration is enabled in site config
        try:
            site_config = SiteConfig.objects.first()
            if not site_config or not site_config.allow_user_registration:
                return Response({"error": "User registration is currently disabled"}, status=status.HTTP_403_FORBIDDEN)
        except SiteConfig.DoesNotExist:
            return Response(
                {"error": "Site configuration not found. User registration is disabled"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                response_serializer = UserSerializer(user)
                return Response(
                    {"message": "User registered successfully", "user": response_serializer.data},
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to register user: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def registration_status(self, request):
        """
        Check if user registration is currently enabled.
        Public endpoint that returns the registration status from site configuration.
        """
        try:
            site_config = SiteConfig.objects.first()
            registration_enabled = site_config.allow_user_registration if site_config else False

            return Response(
                {
                    "registration_enabled": registration_enabled,
                    "message": "Registration is enabled" if registration_enabled else "Registration is disabled",
                }
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to check registration status: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def auth_config(self, request):
        """
        Get authentication configuration for the frontend.
        Returns which authentication methods are enabled and JWT token lifetimes.
        """
        try:
            site_config = SiteConfig.objects.first()

            default_access_lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
            default_refresh_lifetime = settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME")
            remember_me_access_lifetime = getattr(settings, "JWT_REMEMBER_ME_ACCESS_TOKEN_LIFETIME", None)
            remember_me_refresh_lifetime = getattr(settings, "JWT_REMEMBER_ME_REFRESH_TOKEN_LIFETIME", None)

            config = {
                "registration_enabled": site_config.allow_user_registration if site_config else False,
                "orcid_login_enabled": site_config.enable_orcid_login if site_config else False,
                "regular_login_enabled": True,
                "jwt_token_lifetimes": {
                    "default": {
                        "access_token_minutes": int(default_access_lifetime.total_seconds() / 60)
                        if default_access_lifetime
                        else 60,
                        "refresh_token_days": int(default_refresh_lifetime.total_seconds() / 86400)
                        if default_refresh_lifetime
                        else 7,
                    },
                    "remember_me": {
                        "access_token_hours": int(remember_me_access_lifetime.total_seconds() / 3600)
                        if remember_me_access_lifetime
                        else 24,
                        "refresh_token_days": int(remember_me_refresh_lifetime.total_seconds() / 86400)
                        if remember_me_refresh_lifetime
                        else 30,
                    },
                },
            }

            return Response(config)
        except Exception as e:
            return Response(
                {"error": f"Failed to get auth config: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["post"])
    def link_orcid(self, request):
        """
        Link ORCID account to existing user account.
        Authenticated users can link their ORCID ID to their account.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = AccountLinkingSerializer(data=request.data)
        if serializer.is_valid():
            orcid_id = serializer.validated_data["orcid_id"]

            try:
                # Check if ORCID is already linked to another account
                existing_profile = UserOrcidProfile.objects.filter(orcid_id=orcid_id).first()
                if existing_profile:
                    if existing_profile.user == request.user:
                        return Response({"message": "ORCID already linked to your account"}, status=status.HTTP_200_OK)
                    else:
                        return Response(
                            {"error": "This ORCID is already linked to another account"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                # Check if user already has an ORCID linked
                if hasattr(request.user, "orcid_profile"):
                    return Response({"error": "User already has an ORCID linked"}, status=status.HTTP_400_BAD_REQUEST)

                # Create ORCID profile
                orcid_profile = UserOrcidProfile.objects.create(
                    user=request.user, orcid_id=orcid_id, verified=True  # Set to True for manual linking
                )

                profile_serializer = UserOrcidProfileSerializer(orcid_profile)
                return Response(
                    {"message": "ORCID successfully linked to your account", "profile": profile_serializer.data},
                    status=status.HTTP_201_CREATED,
                )

            except Exception as e:
                return Response(
                    {"error": f"Failed to link ORCID: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def unlink_orcid(self, request):
        """
        Unlink ORCID account from user account.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            if not hasattr(request.user, "orcid_profile"):
                return Response(
                    {"error": "No ORCID account linked to your profile"}, status=status.HTTP_400_BAD_REQUEST
                )

            request.user.orcid_profile.delete()
            return Response({"message": "ORCID account successfully unlinked"}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"Failed to unlink ORCID: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["post"])
    def detect_duplicates(self, request):
        """
        Detect potential duplicate accounts based on email, ORCID, or name.
        """
        serializer = DuplicateAccountDetectionSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            potential_duplicates = []

            # Search by email
            if data.get("email"):
                email_matches = User.objects.filter(email__iexact=data["email"])
                potential_duplicates.extend(email_matches)

            # Search by ORCID
            if data.get("orcid_id"):
                orcid_matches = UserOrcidProfile.objects.filter(orcid_id=data["orcid_id"]).values_list(
                    "user", flat=True
                )
                orcid_users = User.objects.filter(id__in=orcid_matches)
                potential_duplicates.extend(orcid_users)

            # Search by name
            if data.get("first_name") and data.get("last_name"):
                name_matches = User.objects.filter(
                    first_name__iexact=data["first_name"], last_name__iexact=data["last_name"]
                )
                potential_duplicates.extend(name_matches)

            # Remove duplicates and current user
            unique_duplicates = list(set(potential_duplicates))
            if request.user.is_authenticated:
                unique_duplicates = [u for u in unique_duplicates if u != request.user]

            serializer = UserSerializer(unique_duplicates, many=True)
            return Response({"potential_duplicates": serializer.data, "count": len(unique_duplicates)})

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def request_merge(self, request):
        """
        Request to merge current account with another account.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = AccountMergeRequestSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            try:
                merge_request = serializer.save()
                response_serializer = AccountMergeRequestSerializer(merge_request)
                return Response(
                    {"message": "Account merge request submitted successfully", "request": response_serializer.data},
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to submit merge request: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def change_password(self, request):
        """
        Change password for authenticated user.
        Requires current password for verification.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            try:
                serializer.save()
                return Response({"message": "Password changed successfully"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response(
                    {"error": f"Failed to change password: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def update_profile(self, request):
        """
        Update user profile (name and email).
        Authenticated users can update their own profile.
        Requires current password for email changes.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = UserProfileUpdateSerializer(
            instance=request.user, data=request.data, context={"request": request}, partial=True
        )
        if serializer.is_valid():
            try:
                user = serializer.save()
                response_serializer = UserSerializer(user)
                return Response(
                    {"message": "Profile updated successfully", "user": response_serializer.data},
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to update profile: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def request_email_change(self, request):
        """
        Request email change with verification.
        Sends verification email to new address.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = EmailChangeRequestSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            try:
                new_email = serializer.validated_data["new_email"]

                # Generate verification token using TimestampSigner
                # Create token data
                token_data = {"user_id": request.user.id, "new_email": new_email}

                # Generate signed token
                signer = TimestampSigner()
                token = signer.sign(json.dumps(token_data))

                # Send verification email
                subject = "Verify Your New Email Address"

                # Create verification URL (you may want to use your frontend URL)
                verification_url = (
                    f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:4200')}/verify-email-change?token={token}"
                )

                message = f"""
Hi {request.user.first_name or request.user.username},

You have requested to change your email address to: {new_email}

Please click the following link to verify your new email address:
{verification_url}

This link will expire in 24 hours.

If you did not request this change, please ignore this email.

Best regards,
The Team
                """.strip()

                try:
                    send_mail(
                        subject,
                        message,
                        getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                        [new_email],
                        fail_silently=False,
                    )

                    return Response(
                        {"message": f"Verification email sent to {new_email}", "new_email": new_email},
                        status=status.HTTP_200_OK,
                    )
                except Exception as email_error:
                    return Response(
                        {"error": f"Failed to send verification email: {str(email_error)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            except Exception as e:
                return Response(
                    {"error": f"Failed to request email change: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def confirm_email_change(self, request):
        """
        Confirm email change with verification token.
        """
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = EmailChangeConfirmSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            try:
                # Get the new email from the validated token
                new_email = serializer.get_new_email()

                if not new_email:
                    return Response({"error": "Could not extract email from token"}, status=status.HTTP_400_BAD_REQUEST)

                # Double-check email is still available (in case someone else took it)
                if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
                    return Response(
                        {"error": "This email address is no longer available"}, status=status.HTTP_400_BAD_REQUEST
                    )

                # Update the user's email
                old_email = request.user.email
                request.user.email = new_email
                request.user.save()

                # Send confirmation email to old address
                try:
                    subject = "Email Address Changed"
                    message = f"""
Hi {request.user.first_name or request.user.username},

Your email address has been successfully changed from {old_email} to {new_email}.

If you did not make this change, please contact support immediately.

Best regards,
The Team
                    """.strip()

                    send_mail(
                        subject,
                        message,
                        getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                        [old_email],
                        fail_silently=True,  # Don't fail if old email can't receive
                    )
                except Exception:
                    # Don't fail the email change if notification fails
                    pass

                response_serializer = UserSerializer(request.user)

                return Response(
                    {"message": "Email address updated successfully", "user": response_serializer.data},
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to confirm email change: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def reset_password(self, request, pk=None):
        """
        Admin-only endpoint to reset user password.
        """
        # Check if current user is admin
        if not request.user.is_staff:
            return Response({"error": "Admin privileges required"}, status=status.HTTP_403_FORBIDDEN)

        # Add user_id to request data
        data = request.data.copy()
        data["user_id"] = pk

        serializer = AdminPasswordResetSerializer(data=data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                return Response(
                    {"message": f"Password reset successfully for user: {user.username}"}, status=status.HTTP_200_OK
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to reset password: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def request_password_reset(self, request):
        """
        Request password reset via email.
        Public endpoint for forgotten passwords.
        """
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]

            try:
                # Find user by email
                users = User.objects.filter(email__iexact=email)

                for user in users:
                    # Generate password reset token
                    token = default_token_generator.make_token(user)
                    uid = urlsafe_base64_encode(force_bytes(user.pk))

                    # Create reset URL for frontend
                    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:4200")
                    reset_url = f"{frontend_url}/reset-password?uid={uid}&token={token}"

                    # Send email (customize template as needed)
                    subject = "Password Reset Request"
                    message = f"""
                    Hello {user.get_full_name() or user.username},

                    You have requested a password reset for your account.

                    Click the link below to reset your password:
                    {reset_url}

                    If you did not request this reset, please ignore this email.

                    This link will expire in 24 hours.
                    """

                    try:
                        send_mail(
                            subject,
                            message,
                            settings.DEFAULT_FROM_EMAIL,
                            [user.email],
                            fail_silently=False,
                        )
                    except Exception as e:
                        # Log the error but don't reveal it to user
                        print(f"Failed to send password reset email: {str(e)}")

                # Always return success to prevent email enumeration
                return Response(
                    {"message": "If an account with this email exists, a password reset link has been sent."},
                    status=status.HTTP_200_OK,
                )

            except Exception:
                return Response(
                    {"error": "Failed to process password reset request"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def confirm_password_reset(self, request):
        """
        Confirm password reset with token.
        Public endpoint for completing password reset.
        """
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        try:
            # Decode user ID
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)

            # Verify token
            if default_token_generator.check_token(user, token):
                # Reset password
                user.set_password(new_password)
                user.save()

                return Response({"message": "Password reset successfully"}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Invalid or expired reset token"}, status=status.HTTP_400_BAD_REQUEST)

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"error": "Invalid reset link"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to reset password: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AnnotationFolderViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for annotation folder management with hierarchical organization."""

    queryset = AnnotationFolder.objects.all()
    serializer_class = AnnotationFolderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["folder_name", "owner__username"]
    filterset_fields = ["parent_folder", "is_shared_document_folder", "visibility", "is_active"]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Return folders accessible to the current user."""
        user = self.request.user
        if user.is_staff:
            # Admins can see all folders
            return AnnotationFolder.objects.filter(is_active=True)
        else:
            # Regular users can only see folders they can view
            return (
                AnnotationFolder.objects.filter(is_active=True)
                .filter(
                    # Owner can see their folders
                    # Public folders can be seen by anyone
                    # Group folders can be seen by lab group members
                    Q(owner=user)
                    | Q(visibility="public")
                    | (Q(visibility="group") & Q(lab_group__members=user))
                )
                .distinct()
            )

    def perform_create(self, serializer):
        """Set owner and default values on folder creation."""
        serializer.save(owner=self.request.user, resource_type="file")

    @action(detail=True, methods=["get"])
    def children(self, request, pk=None):
        """Get child folders and annotations for this folder."""
        folder = self.get_object()

        # Check permissions
        if not folder.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this folder"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get child folders
        child_folders = folder.child_folders.filter(is_active=True)
        folder_serializer = AnnotationFolderSerializer(child_folders, many=True, context={"request": request})

        # Get annotations in this folder
        annotations = folder.annotations.filter(is_active=True)
        annotation_serializer = AnnotationSerializer(annotations, many=True, context={"request": request})

        return Response(
            {
                "folders": folder_serializer.data,
                "annotations": annotation_serializer.data,
            }
        )

    @action(detail=False, methods=["get"])
    def root_folders(self, request):
        """Get top-level folders (no parent folder)."""
        root_folders = self.get_queryset().filter(parent_folder=None)
        paginator = self.pagination_class()
        paginated_folders = paginator.paginate_queryset(root_folders, request)
        serializer = self.get_serializer(paginated_folders, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"])
    def create_child_folder(self, request, pk=None):
        """Create a child folder within this folder."""
        parent_folder = self.get_object()

        # Check permissions
        if not parent_folder.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to create folders in this location"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Add parent folder to request data
        data = request.data.copy()
        data["parent_folder"] = parent_folder.id

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AnnotationViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for annotation management with file upload support."""

    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["annotation", "owner__username"]
    filterset_fields = ["annotation_type", "folder", "visibility", "is_active", "scratched"]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """
        Return ONLY standalone annotations accessible to the current user.

        Annotations attached to parent resources (Instruments, Sessions, etc.) should
        be accessed through their dedicated endpoints:
        - /api/v1/instrument-annotations/
        - /api/v1/step-annotations/
        - /api/v1/maintenance-log-annotations/
        - etc.

        This endpoint handles:
        - Standalone annotations in shared folders
        - Personal notes not attached to any resource
        - Annotations before they're attached to a parent
        """
        user = self.request.user
        base_queryset = Annotation.objects.filter(is_active=True, scratched=False)

        base_queryset = base_queryset.filter(
            instrument_attachments__isnull=True,
            stored_reagent_attachments__isnull=True,
            maintenance_log_attachments__isnull=True,
            session_attachments__isnull=True,
            step_attachments__isnull=True,
        )

        if user.is_staff:
            return base_queryset

        return base_queryset.filter(
            Q(owner=user) | Q(visibility="public") | (Q(visibility="group") & Q(lab_group__members=user))
        ).distinct()

    def perform_create(self, serializer):
        """Set owner and default values on annotation creation."""
        serializer.save(owner=self.request.user, resource_type="file")

    @action(detail=False, methods=["post"])
    def create_with_file(self, request):
        """Create annotation with file upload (for regular form uploads, not chunked)."""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            # Check folder permissions if specified
            folder_id = request.data.get("folder")
            if folder_id:
                try:
                    folder = AnnotationFolder.objects.get(id=folder_id)
                    if not folder.can_edit(request.user):
                        return Response(
                            {"error": "Permission denied: cannot add annotations to this folder"},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                except AnnotationFolder.DoesNotExist:
                    return Response(
                        {"error": "Invalid folder_id"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def toggle_scratch(self, request, pk=None):
        """Toggle scratch status (soft delete) for annotation."""
        annotation = self.get_object()

        # Check permissions
        if not annotation.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to modify this annotation"},
                status=status.HTTP_403_FORBIDDEN,
            )

        annotation.scratched = not annotation.scratched
        annotation.save()

        action = "scratched" if annotation.scratched else "unscratched"
        return Response({"message": f"Annotation {action} successfully", "scratched": annotation.scratched})

    @action(detail=False, methods=["get"])
    def by_folder(self, request):
        """Get annotations in a specific folder."""
        folder_id = request.query_params.get("folder_id")
        if not folder_id:
            return Response(
                {"error": "folder_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            folder = AnnotationFolder.objects.get(id=folder_id)
            if not folder.can_view(request.user):
                return Response(
                    {"error": "You don't have permission to view this folder"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except AnnotationFolder.DoesNotExist:
            return Response(
                {"error": "Folder not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        annotations = self.get_queryset().filter(folder=folder)
        paginator = self.pagination_class()
        paginated_annotations = paginator.paginate_queryset(annotations, request)
        serializer = self.get_serializer(paginated_annotations, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_type(self, request):
        """Get annotations by type (image, video, audio, file, etc.)."""
        annotation_type = request.query_params.get("type")
        if not annotation_type:
            return Response(
                {"error": "type parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        annotations = self.get_queryset().filter(annotation_type=annotation_type)
        paginator = self.pagination_class()
        paginated_annotations = paginator.paginate_queryset(annotations, request)
        serializer = self.get_serializer(paginated_annotations, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get", "options"], permission_classes=[])
    def download(self, request, pk=None):
        """
        Download annotation file with signed token verification.

        No authentication required - token contains all necessary validation.

        Security: Checks both annotation-level AND parent resource permissions
        (Instrument, StoredReagent, Session, etc.) via Annotation.can_view().
        """
        signed_token = request.query_params.get("token")

        if not signed_token:
            return HttpResponse("Missing token", status=400)

        annotation, user = Annotation.verify_download_token(signed_token)

        if not annotation:
            return HttpResponse("Invalid or expired token", status=403)

        if not annotation.file:
            return HttpResponse("No file attached to this annotation", status=404)

        if not annotation.can_view(user):
            return HttpResponse("Permission denied", status=403)

        is_electron = getattr(settings, "IS_ELECTRON_ENVIRONMENT", False)

        if is_electron:
            file_path = annotation.file.path
            if not os.path.exists(file_path):
                return HttpResponse("File not found", status=404)

            with open(file_path, "rb") as f:
                file_content = f.read()

            response = HttpResponse(file_content, content_type="application/octet-stream")
            response["Content-Disposition"] = f'attachment; filename="{os.path.basename(annotation.file.name)}"'
            response["Content-Encoding"] = "identity"
        else:
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"/internal/media/{annotation.file.name}"
            response["Content-Type"] = "application/octet-stream"
            response["Content-Disposition"] = f'attachment; filename="{os.path.basename(annotation.file.name)}"'
            response["Cache-Control"] = "private, max-age=300"
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Download-Options"] = "noopen"

        origin = request.META.get("HTTP_ORIGIN")
        cors_allowed_origins = getattr(settings, "CORS_ORIGIN_WHITELIST", [])

        if origin and origin in cors_allowed_origins:
            response["X-Accel-CORS-Origin"] = origin
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response["Access-Control-Allow-Headers"] = ", ".join(getattr(settings, "CORS_ALLOW_HEADERS", []))

        return response


class RemoteHostViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing remote hosts in distributed CUPCAKE deployments.

    Provides CRUD operations for remote host configuration.
    """

    queryset = RemoteHost.objects.all()
    serializer_class = RemoteHostSerializer
    permission_classes = [IsAdminUser]  # Only admins can manage remote hosts
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["host_name", "host_description"]
    filterset_fields = ["host_protocol"]


class ResourcePermissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing explicit resource permissions.

    Provides CRUD operations for granting and revoking resource access.
    """

    queryset = ResourcePermission.objects.all()
    serializer_class = ResourcePermissionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["user__username", "user__email"]
    filterset_fields = ["role", "resource_content_type"]

    def get_queryset(self):
        """Filter permissions based on user role."""
        user = self.request.user
        queryset = ResourcePermission.objects.all()

        # Admins can see all permissions
        if user.is_staff or user.is_superuser:
            return queryset

        # Regular users can only see permissions they granted or that affect them
        return queryset.filter(models.Q(granted_by=user) | models.Q(user=user))


_STORAGE_MOUNT_POINT = "/mnt/cupcake-data"
_STORAGE_SOCK = "/run/cupcake-storage.sock"
_NETWORK_SOCK = "/run/cupcake-network.sock"
_BACKUP_ALLOWED_PREFIXES = ("/mnt/cupcake-data/", "/opt/cupcake/backups")
_SHELL_UNSAFE = re.compile(r"[;&|`$\\\n\r\x00]")
_VALID_BACKUP_TYPES = ("database", "media", "full")
_VALID_MOUNT_TYPES = ("usb", "nfs", "smb")
_WIFI_CONFIG_PATH = Path("/opt/cupcake/wifi-config.json")
_WIFI_CERT_DIR = Path("/opt/cupcake/wifi-certs")
_VALID_AUTH_TYPES = ("wpa2-personal", "wpa2-enterprise")
_VALID_EAP_METHODS = ("peap", "ttls", "tls")
_VALID_PHASE2_METHODS = ("mschapv2", "pap", "chap")
_VALID_CERT_TYPES = ("ca", "client_cert", "client_key")


class ApplianceViewSet(viewsets.ViewSet):
    """
    Admin-only ViewSet for appliance storage and backup management.

    All actions require staff (admin) privileges. Storage operations
    communicate with the cupcake-storage-manager socket service which
    runs as root with narrowly-scoped privileges.
    """

    def _require_staff(self, request):
        from rest_framework.exceptions import PermissionDenied

        if not request.user.is_staff:
            raise PermissionDenied("Admin access required.")

    def _send_storage_command(self, payload):
        """Send a JSON command to the storage manager socket and return the response."""
        client = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        client.settimeout(60)
        client.connect(_STORAGE_SOCK)
        client.sendall(json.dumps(payload).encode() + b"\n")
        data = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        client.close()
        return json.loads(data.decode())

    def _send_network_command(self, payload):
        """Send a JSON command to the network manager socket and return the response."""
        client = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        client.settimeout(60)
        client.connect(_NETWORK_SOCK)
        client.sendall(json.dumps(payload).encode() + b"\n")
        data = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        client.close()
        return json.loads(data.decode())

    def _is_mounted(self):
        """Return True if /mnt/cupcake-data is currently mounted."""
        try:
            with open("/proc/mounts") as f:
                return any(line.split()[1] == _STORAGE_MOUNT_POINT for line in f if len(line.split()) >= 3)
        except Exception:
            return False

    @staticmethod
    def _validate_storage_config(config):
        """
        Validate storage config fields for the given mountType.

        Returns an error string if invalid, or None if valid.
        """
        mount_type = config.get("mountType", "")
        if mount_type not in _VALID_MOUNT_TYPES:
            return f"mountType must be one of: {', '.join(_VALID_MOUNT_TYPES)}"

        required: dict[str, list[str]] = {
            "usb": ["label"],
            "nfs": ["host", "share"],
            "smb": ["host", "share"],
        }
        for field in required[mount_type]:
            value = config.get(field, "").strip()
            if not value:
                return f"{field} is required for {mount_type} mount"
            if _SHELL_UNSAFE.search(value):
                return f"{field} contains invalid characters"

        for field in ("host", "share", "label", "username", "password"):
            value = config.get(field, "")
            if value and _SHELL_UNSAFE.search(str(value)):
                return f"{field} contains invalid characters"

        return None

    @staticmethod
    def _validate_destination(destination):
        """
        Validate a backup destination path.

        Returns an error string if invalid, or None if valid.
        """
        if not destination:
            return "destination is required"
        if not os.path.isabs(destination):
            return "destination must be an absolute path"
        resolved = os.path.normpath(destination)
        if not any(resolved.startswith(prefix) for prefix in _BACKUP_ALLOWED_PREFIXES):
            allowed = ", ".join(_BACKUP_ALLOWED_PREFIXES)
            return f"destination must be under one of: {allowed}"
        return None

    @action(detail=False, methods=["get"], url_path="storage-status")
    def storage_status(self, request):
        """Return current mount status and saved storage config."""
        self._require_staff(request)
        config_path = Path("/opt/cupcake/storage-config.json")
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except Exception:
                pass

        mounted = False
        device = ""
        fs_type = ""
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == _STORAGE_MOUNT_POINT:
                        mounted = True
                        device = parts[0]
                        fs_type = parts[2]
                        break
        except Exception:
            pass

        return Response(
            {
                "mounted": mounted,
                "mount_point": _STORAGE_MOUNT_POINT,
                "device": device,
                "fs_type": fs_type,
                "config": config,
            }
        )

    @action(detail=False, methods=["post"], url_path="apply-storage")
    def apply_storage(self, request):
        """Write storage config and apply mount via the storage manager socket."""
        self._require_staff(request)
        config = request.data.get("config")
        if not isinstance(config, dict):
            return Response({"error": "config must be an object"}, status=status.HTTP_400_BAD_REQUEST)

        error = self._validate_storage_config(config)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = self._send_storage_command({"command": "mount", "config": config})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if result.get("ok"):
            return Response({"output": result.get("output", "")})
        return Response({"error": result.get("error", "Mount failed")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["post"], url_path="unmount-storage")
    def unmount_storage(self, request):
        """Unmount /mnt/cupcake-data via the storage manager socket."""
        self._require_staff(request)
        if not self._is_mounted():
            return Response({"error": "No storage is currently mounted"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = self._send_storage_command({"command": "unmount"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if result.get("ok"):
            return Response({"output": result.get("output", "")})
        return Response({"error": result.get("error", "Unmount failed")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["get"], url_path="block-devices")
    def block_devices(self, request):
        """List USB block devices with labels using lsblk."""
        self._require_staff(request)
        try:
            out = subprocess.check_output(["lsblk", "-J", "-o", "NAME,LABEL,SIZE,FSTYPE,TRAN"], text=True)
            data = json.loads(out)
            devices = []
            for dev in data.get("blockdevices", []):
                if dev.get("tran") == "usb":
                    for child in dev.get("children", [dev]):
                        if child.get("fstype"):
                            devices.append(
                                {
                                    "name": f"/dev/{child['name']}",
                                    "label": child.get("label") or "",
                                    "size": child.get("size") or "",
                                    "fs_type": child.get("fstype") or "",
                                }
                            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"devices": devices})

    def list(self, request):
        """List the 10 most recent backup logs."""
        self._require_staff(request)
        logs = BackupLog.objects.order_by("-started_at")[:10]
        return Response(BackupLogSerializer(logs, many=True).data)

    def retrieve(self, request, pk=None):
        """Get a single backup log for status polling."""
        self._require_staff(request)
        try:
            log = BackupLog.objects.get(pk=pk)
        except BackupLog.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(BackupLogSerializer(log).data)

    @action(detail=False, methods=["post"], url_path="run-backup")
    def run_backup(self, request):
        """Enqueue a backup job and return the BackupLog id."""
        self._require_staff(request)
        backup_type = request.data.get("backup_type", "").strip()
        destination = request.data.get("destination", "").strip()

        if backup_type not in _VALID_BACKUP_TYPES:
            return Response(
                {"error": f"backup_type must be one of: {', '.join(_VALID_BACKUP_TYPES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dest_error = self._validate_destination(destination)
        if dest_error:
            return Response({"error": dest_error}, status=status.HTTP_400_BAD_REQUEST)

        if BackupLog.objects.filter(status="running").exists():
            return Response(
                {"error": "A backup is already in progress"},
                status=status.HTTP_409_CONFLICT,
            )

        log = BackupLog.objects.create(
            backup_type=backup_type,
            destination=destination,
            triggered_by=request.user,
        )
        run_backup_task.delay(log.id)
        return Response(BackupLogSerializer(log).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="wifi-interfaces")
    def wifi_interfaces(self, request):
        """Return available wireless interface names by inspecting /sys/class/net."""
        self._require_staff(request)
        interfaces = []
        try:
            net_path = Path("/sys/class/net")
            for iface_dir in net_path.iterdir():
                if (iface_dir / "wireless").exists() or (iface_dir / "phy80211").exists():
                    interfaces.append(iface_dir.name)
        except Exception:
            pass
        return Response({"interfaces": interfaces})

    @action(detail=False, methods=["get"], url_path="wifi-status")
    def wifi_status(self, request):
        """Return current WiFi connection state and saved config (password excluded)."""
        self._require_staff(request)
        config = None
        if _WIFI_CONFIG_PATH.exists():
            try:
                cfg = json.loads(_WIFI_CONFIG_PATH.read_text())
                cfg.pop("password", None)
                config = cfg
            except Exception:
                pass

        connected = False
        ssid = None
        iface_name = (config or {}).get("interfaceName", "")
        if iface_name:
            try:
                out = subprocess.check_output(["iw", "dev", iface_name, "link"], text=True, stderr=subprocess.DEVNULL)
                connected = "Connected to" in out or "SSID" in out
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("SSID:"):
                        ssid = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass

        has_interface = bool(iface_name) or bool(
            list(Path("/sys/class/net").glob("*/wireless")) + list(Path("/sys/class/net").glob("*/phy80211"))
        )

        return Response(
            {
                "hasInterface": has_interface,
                "interfaceName": iface_name or None,
                "connected": connected,
                "ssid": ssid,
                "config": config,
            }
        )

    @staticmethod
    def _validate_wifi_config(config):
        """
        Validate WiFi config fields.

        Returns an error string if invalid, or None if valid.
        """
        ssid = config.get("ssid", "").strip()
        if not ssid:
            return "ssid is required"
        if len(ssid) > 32:
            return "ssid must be 32 characters or fewer"
        if "\x00" in ssid:
            return "ssid contains invalid characters"

        iface = config.get("interfaceName", "").strip()
        if not iface:
            return "interfaceName is required"
        if not re.match(r"^[a-zA-Z0-9_\-]+$", iface):
            return "interfaceName contains invalid characters"

        auth_type = config.get("authType", "")
        if auth_type not in _VALID_AUTH_TYPES:
            return f"authType must be one of: {', '.join(_VALID_AUTH_TYPES)}"

        if auth_type == "wpa2-personal":
            if not config.get("password", "").strip():
                return "password is required for wpa2-personal"
            return None

        eap_method = config.get("eapMethod", "")
        if eap_method not in _VALID_EAP_METHODS:
            return f"eapMethod must be one of: {', '.join(_VALID_EAP_METHODS)}"

        if not config.get("identity", "").strip():
            return "identity is required for wpa2-enterprise"

        if eap_method in ("peap", "ttls"):
            if not config.get("password", "").strip():
                return f"password is required for {eap_method}"
            phase2 = config.get("phase2Auth", "")
            if phase2 and phase2 not in _VALID_PHASE2_METHODS:
                return f"phase2Auth must be one of: {', '.join(_VALID_PHASE2_METHODS)}"

        if eap_method == "tls":
            for field in ("clientCertFilename", "clientKeyFilename"):
                name = config.get(field, "").strip()
                if not name:
                    return f"{field} is required for EAP-TLS"
                if not (_WIFI_CERT_DIR / name).exists():
                    return f"{field} not found; upload the certificate first"

        return None

    @action(detail=False, methods=["post"], url_path="apply-wifi")
    def apply_wifi(self, request):
        """Write WiFi config and apply via the network manager socket."""
        self._require_staff(request)
        config = request.data.get("config")
        if not isinstance(config, dict):
            return Response({"error": "config must be an object"}, status=status.HTTP_400_BAD_REQUEST)

        error = self._validate_wifi_config(config)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            _WIFI_CONFIG_PATH.write_text(json.dumps(config, indent=2))
        except Exception as e:
            return Response({"error": f"Could not save config: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            result = self._send_network_command({"command": "wifi-apply"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if result.get("ok"):
            return Response({"output": result.get("output", "")})
        return Response(
            {"error": result.get("error", "WiFi apply failed")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=False, methods=["post"], url_path="disable-wifi")
    def disable_wifi(self, request):
        """Remove WiFi netplan config and apply via the network manager socket."""
        self._require_staff(request)
        try:
            result = self._send_network_command({"command": "wifi-disable"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if result.get("ok"):
            _WIFI_CONFIG_PATH.unlink(missing_ok=True)
            return Response({"output": result.get("output", "")})
        return Response(
            {"error": result.get("error", "WiFi disable failed")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=False, methods=["post"], url_path="upload-wifi-cert")
    def upload_wifi_cert(self, request):
        """Upload a PEM certificate file for WiFi authentication."""
        self._require_staff(request)
        cert_type = request.data.get("cert_type", "").strip()
        if cert_type not in _VALID_CERT_TYPES:
            return Response(
                {"error": f"cert_type must be one of: {', '.join(_VALID_CERT_TYPES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        if uploaded.size > 65536:
            return Response({"error": "Certificate file too large (max 64 KB)"}, status=status.HTTP_400_BAD_REQUEST)

        content = uploaded.read()
        if not content.startswith(b"-----BEGIN"):
            return Response(
                {"error": "File does not appear to be a PEM certificate"}, status=status.HTTP_400_BAD_REQUEST
            )

        filename = f"{cert_type}.pem"
        try:
            _WIFI_CERT_DIR.mkdir(parents=True, exist_ok=True)
            dest = _WIFI_CERT_DIR / filename
            dest.write_bytes(content)
        except Exception as e:
            return Response({"error": f"Could not save certificate: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"filename": filename})

    @action(detail=False, methods=["get"], url_path="network-info", permission_classes=[])
    def network_info(self, request):
        """Return appliance hostname and all routable IPv4 addresses. No authentication required."""
        hostname = _socket.gethostname()
        try:
            raw = subprocess.check_output(["hostname", "-I"], text=True).split()
        except Exception:
            raw = []

        addresses = [ip for ip in raw if not ip.startswith(("127.", "169.254."))]

        return Response({"hostname": hostname, "addresses": addresses})


from ccc.device_token.viewsets import DeviceSummaryViewSet, DeviceTokenViewSet  # noqa: E402, F401
from ccc.plugin.viewset import PluginViewSet  # noqa: E402, F401
