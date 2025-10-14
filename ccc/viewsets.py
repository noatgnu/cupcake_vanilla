"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Views.

This module contains ViewSets for user management, lab group collaboration,
and site administration functionality.
"""

import json
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.db import models
from django.db.models import Q
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

from .models import (
    Annotation,
    AnnotationFolder,
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

logger = logging.getLogger(__name__)


class SiteConfigViewSet(viewsets.ModelViewSet, FilterMixin):
    """ViewSet for site configuration management."""

    queryset = SiteConfig.objects.all()
    serializer_class = SiteConfigSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["site_name", "site_description"]
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
                # Use the serializer to get all fields including installed_apps
                serializer = self.get_serializer(site_config)
                # Return only public fields plus installed_apps
                data = {
                    "site_name": serializer.data["site_name"],
                    "logo_url": serializer.data["logo_url"],
                    "primary_color": serializer.data["primary_color"],
                    "show_powered_by": serializer.data["show_powered_by"],
                    "allow_user_registration": serializer.data["allow_user_registration"],
                    "enable_orcid_login": serializer.data["enable_orcid_login"],
                    "installed_apps": serializer.data["installed_apps"],
                }
                return Response(data)
            else:
                # Default response when no config exists - include installed_apps
                serializer = self.get_serializer()
                default_config = SiteConfig()  # Temporary instance for serializer
                temp_serializer = self.get_serializer(default_config)
                return Response(
                    {
                        "site_name": "CUPCAKE",
                        "primary_color": "#1976d2",
                        "show_powered_by": True,
                        "allow_user_registration": False,
                        "enable_orcid_login": False,
                        "installed_apps": temp_serializer.data["installed_apps"],
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
            if site_config:
                serializer = SiteConfigSerializer(site_config)
                return Response(serializer.data)
            return Response({"error": "Site configuration not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to get site config: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
            from django.contrib.auth.models import User

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

    @action(detail=False, methods=["get"])
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

    @action(detail=False, methods=["get"])
    def auth_config(self, request):
        """
        Get authentication configuration for the frontend.
        Returns which authentication methods are enabled.
        """
        try:
            site_config = SiteConfig.objects.first()

            config = {
                "registration_enabled": site_config.allow_user_registration if site_config else False,
                "orcid_login_enabled": site_config.enable_orcid_login if site_config else False,
                "regular_login_enabled": True,  # Regular login is always enabled
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
        """Return annotations accessible to the current user."""
        user = self.request.user
        if user.is_staff:
            # Admins can see all annotations
            return Annotation.objects.filter(is_active=True, scratched=False)
        else:
            # Regular users can only see annotations they can view
            return (
                Annotation.objects.filter(is_active=True, scratched=False)
                .filter(
                    # Owner can see their annotations
                    # Public annotations can be seen by anyone
                    # Group annotations can be seen by lab group members
                    Q(owner=user)
                    | Q(visibility="public")
                    | (Q(visibility="group") & Q(lab_group__members=user))
                )
                .distinct()
            )

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

    @action(detail=True, methods=["get"], permission_classes=[])
    def download(self, request, pk=None):
        """
        Download annotation file with signed token verification.

        No authentication required - token contains all necessary validation.

        Security: Checks both annotation-level AND parent resource permissions
        (Instrument, StoredReagent, Session, etc.) via Annotation.can_view().
        """
        from django.http import HttpResponse

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
            import os

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
            try:
                response["Content-Length"] = annotation.file.size
            except Exception:
                pass
            response["Cache-Control"] = "private, max-age=300"
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Download-Options"] = "noopen"

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
