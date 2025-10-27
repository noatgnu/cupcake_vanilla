"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Serializers.

This module contains serializers for user management, lab group collaboration,
and site administration functionality.
"""

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.urls import reverse

from rest_framework import serializers

from .models import (
    AccountMergeRequest,
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

logger = logging.getLogger(__name__)


class SiteConfigSerializer(serializers.ModelSerializer):
    """Serializer for site configuration settings."""

    installed_apps = serializers.SerializerMethodField()

    class Meta:
        model = SiteConfig
        fields = [
            "site_name",
            "logo_url",
            "logo_image",
            "primary_color",
            "show_powered_by",
            "allow_user_registration",
            "enable_orcid_login",
            "booking_deletion_window_minutes",
            "installed_apps",
            "created_at",
            "updated_at",
            "updated_by",
        ]
        read_only_fields = ["created_at", "updated_at", "updated_by", "installed_apps"]

    def get_installed_apps(self, obj):
        """Return information about which CUPCAKE apps are installed."""
        from django.apps import apps
        from django.conf import settings

        # Get installed app names from Django registry
        installed_app_names = [app.name for app in apps.get_app_configs()]

        # Define the mapping of app configs to app information
        cupcake_apps = {
            "ccv": {
                "name": "CUPCAKE Vanilla",
                "code": "ccv",
                "description": "Core metadata management and validation",
                "installed": "ccv" in installed_app_names,
            },
            "ccc": {
                "name": "CUPCAKE Core",
                "code": "ccc",
                "description": "Authentication, permissions, and core functionality",
                "installed": "ccc" in installed_app_names,
            },
            "ccm": {
                "name": "CUPCAKE Macaron",
                "code": "ccm",
                "description": "Instrument and reagent management",
                "installed": "ccm" in installed_app_names
                and hasattr(settings, "ENABLE_CUPCAKE_MACARON")
                and settings.ENABLE_CUPCAKE_MACARON,
            },
            "ccmc": {
                "name": "CUPCAKE Mint Chocolate",
                "code": "ccmc",
                "description": "Communications",
                "installed": "ccmc" in installed_app_names
                and hasattr(settings, "ENABLE_CUPCAKE_MINT_CHOCOLATE")
                and settings.ENABLE_CUPCAKE_MINT_CHOCOLATE,
            },
            "ccsc": {
                "name": "CUPCAKE Salted Caramel",
                "code": "ccsc",
                "description": "Billing & Finance",
                "installed": "ccsc" in installed_app_names
                and hasattr(settings, "ENABLE_CUPCAKE_SALTED_CARAMEL")
                and settings.ENABLE_CUPCAKE_SALTED_CARAMEL,
            },
            "ccrv": {
                "name": "CUPCAKE Red Velvet",
                "code": "ccrv",
                "description": "Protocol management and experimental workflows",
                "installed": "ccrv" in installed_app_names
                and hasattr(settings, "ENABLE_CUPCAKE_RED_VELVET")
                and settings.ENABLE_CUPCAKE_RED_VELVET,
            },
        }

        return cupcake_apps


class LabGroupSerializer(serializers.ModelSerializer):
    """Serializer for lab group objects."""

    member_count = serializers.SerializerMethodField()
    is_creator = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    can_invite = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()
    can_process_jobs = serializers.SerializerMethodField()
    creator_name = serializers.SerializerMethodField()
    parent_group_name = serializers.CharField(source="parent_group.name", read_only=True)
    full_path = serializers.SerializerMethodField()
    sub_groups_count = serializers.SerializerMethodField()

    class Meta:
        model = LabGroup
        fields = [
            "id",
            "name",
            "description",
            "parent_group",
            "parent_group_name",
            "full_path",
            "creator",
            "creator_name",
            "is_active",
            "allow_member_invites",
            "allow_process_jobs",
            "member_count",
            "sub_groups_count",
            "is_creator",
            "is_member",
            "can_invite",
            "can_manage",
            "can_process_jobs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "creator",
            "created_at",
            "updated_at",
            "parent_group_name",
            "full_path",
            "sub_groups_count",
        ]

    def get_member_count(self, obj):
        """Return the number of members in this lab group."""
        return obj.members.count()

    def get_is_creator(self, obj):
        """Check if current user is the creator."""
        user = self.context.get("request").user
        return obj.is_creator(user) if user.is_authenticated else False

    def get_is_member(self, obj):
        """Check if current user is a member."""
        user = self.context.get("request").user
        return obj.is_member(user) if user.is_authenticated else False

    def get_can_invite(self, obj):
        """Check if current user can invite others."""
        user = self.context.get("request").user
        return obj.can_invite(user) if user.is_authenticated else False

    def get_can_manage(self, obj):
        """Check if current user can manage this group."""
        user = self.context.get("request").user
        return obj.can_manage(user) if user.is_authenticated else False

    def get_can_process_jobs(self, obj):
        """Check if current user can process instrument jobs."""
        user = self.context.get("request").user
        return obj.can_process_jobs(user) if user.is_authenticated else False

    def get_creator_name(self, obj):
        """Return the creator's display name."""
        if obj.creator:
            return obj.creator.get_full_name() or obj.creator.username
        return None

    def get_full_path(self, obj):
        """Get the full hierarchical path to root."""
        return obj.get_full_path()

    def get_sub_groups_count(self, obj):
        """Return the number of direct sub groups."""
        return obj.sub_groups.filter(is_active=True).count()

    def create(self, validated_data):
        """Create a new lab group with the current user as creator."""
        user = self.context["request"].user
        lab_group = LabGroup.objects.create(creator=user, **validated_data)
        # Add creator as a member
        lab_group.members.add(user)
        return lab_group


class LabGroupInvitationSerializer(serializers.ModelSerializer):
    """Serializer for lab group invitation objects."""

    inviter_name = serializers.SerializerMethodField()
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)
    can_accept = serializers.SerializerMethodField()

    class Meta:
        model = LabGroupInvitation
        fields = [
            "id",
            "lab_group",
            "lab_group_name",
            "inviter",
            "inviter_name",
            "invited_user",
            "invited_email",
            "status",
            "message",
            "invitation_token",
            "expires_at",
            "responded_at",
            "can_accept",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "inviter",
            "invitation_token",
            "expires_at",
            "responded_at",
            "created_at",
            "updated_at",
        ]

    def get_inviter_name(self, obj):
        """Return the inviter's display name."""
        return obj.inviter.get_full_name() or obj.inviter.username

    def get_can_accept(self, obj):
        """Check if this invitation can be accepted."""
        return obj.can_accept()

    def create(self, validated_data):
        """Create a new invitation with the current user as inviter."""
        user = self.context["request"].user
        return LabGroupInvitation.objects.create(inviter=user, **validated_data)


class LabGroupPermissionSerializer(serializers.ModelSerializer):
    """Serializer for lab group permission objects."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_display_name = serializers.SerializerMethodField()
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)

    class Meta:
        model = LabGroupPermission
        fields = [
            "id",
            "user",
            "user_username",
            "user_display_name",
            "lab_group",
            "lab_group_name",
            "can_view",
            "can_invite",
            "can_manage",
            "can_process_jobs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "user_username", "user_display_name", "lab_group_name"]

    def get_user_display_name(self, obj):
        """Get user's display name."""
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        return obj.user.username

    def validate(self, data):
        """Validate that only staff/admin users can manually change can_process_jobs permission."""
        request = self.context.get("request")
        if request:
            requesting_user = request.user
            can_process_jobs = data.get("can_process_jobs")

            if can_process_jobs is not None:
                if self.instance:
                    is_changing = self.instance.can_process_jobs != can_process_jobs
                else:
                    is_changing = can_process_jobs is True

                if is_changing and not (requesting_user.is_staff or requesting_user.is_superuser):
                    raise serializers.ValidationError(
                        {
                            "can_process_jobs": "Only staff or admin users can manually change can_process_jobs permission"
                        }
                    )

        return data


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details (read-only)."""

    has_orcid = serializers.SerializerMethodField()
    orcid_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "is_active",
            "date_joined",
            "last_login",
            "has_orcid",
            "orcid_id",
        ]

    def get_has_orcid(self, obj):
        """Check if user has ORCID profile linked."""
        return hasattr(obj, "orcid_profile")

    def get_orcid_id(self, obj):
        """Get user's ORCID ID if available."""
        if hasattr(obj, "orcid_profile"):
            return obj.orcid_profile.orcid_id
        return None


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for admin-only user creation."""

    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "password_confirm",
            "is_staff",
            "is_superuser",
            "is_active",
        ]

    def validate(self, data):
        """Validate passwords match."""
        if data["password"] != data["password_confirm"]:
            raise serializers.ValidationError("Passwords don't match.")
        return data

    def create(self, validated_data):
        """Create user with hashed password."""
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for public user registration."""

    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "password", "password_confirm"]

    def validate(self, data):
        """Validate passwords match."""
        if data["password"] != data["password_confirm"]:
            raise serializers.ValidationError("Passwords don't match.")
        return data

    def create(self, validated_data):
        """Create user with hashed password."""
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserOrcidProfileSerializer(serializers.ModelSerializer):
    """Serializer for ORCID profile information."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = UserOrcidProfile
        fields = [
            "user",
            "user_username",
            "user_email",
            "orcid_id",
            "orcid_name",
            "orcid_email",
            "verified",
            "linked_at",
        ]
        read_only_fields = ["user", "linked_at"]


class AccountLinkingSerializer(serializers.Serializer):
    """Serializer for linking ORCID account to existing user."""

    orcid_id = serializers.CharField(max_length=19)

    def validate_orcid_id(self, value):
        """Validate ORCID ID format."""
        import re

        if not re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", value):
            raise serializers.ValidationError("Invalid ORCID ID format.")
        return value


class DuplicateAccountDetectionSerializer(serializers.Serializer):
    """Serializer for detecting potential duplicate accounts."""

    email = serializers.EmailField(required=False)
    orcid_id = serializers.CharField(max_length=19, required=False)
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)

    def validate(self, data):
        """Ensure at least one search field is provided."""
        if not any([data.get("email"), data.get("orcid_id"), data.get("first_name"), data.get("last_name")]):
            raise serializers.ValidationError("At least one search field must be provided.")
        return data


class AccountMergeRequestSerializer(serializers.ModelSerializer):
    """Serializer for account merge requests."""

    primary_user_username = serializers.CharField(source="primary_user.username", read_only=True)
    duplicate_user_username = serializers.CharField(source="duplicate_user.username", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    reviewed_by_username = serializers.CharField(source="reviewed_by.username", read_only=True)

    class Meta:
        model = AccountMergeRequest
        fields = [
            "id",
            "primary_user",
            "primary_user_username",
            "duplicate_user",
            "duplicate_user_username",
            "requested_by",
            "requested_by_username",
            "reason",
            "status",
            "reviewed_by",
            "reviewed_by_username",
            "admin_notes",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["id", "requested_by", "created_at", "updated_at", "completed_at"]

    def create(self, validated_data):
        """Create merge request with current user as requester."""
        user = self.context["request"].user
        return AccountMergeRequest.objects.create(requested_by=user, **validated_data)


class PasswordChangeSerializer(serializers.Serializer):
    """Serializer for user password changes."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        """Validate current password."""
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, data):
        """Validate new passwords match."""
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("New passwords don't match.")
        return data

    def save(self):
        """Update user password."""
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class AdminPasswordResetSerializer(serializers.Serializer):
    """Serializer for admin password resets."""

    user_id = serializers.IntegerField()
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
    force_password_change = serializers.BooleanField(default=False)
    reason = serializers.CharField(required=False)

    def validate(self, data):
        """Validate passwords match."""
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords don't match.")
        return data

    def validate_user_id(self, value):
        """Validate user exists."""
        try:
            User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        return value

    def save(self):
        """Reset user password."""
        user = User.objects.get(id=self.validated_data["user_id"])
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset requests via email."""

    email = serializers.EmailField()

    def validate_email(self, value):
        """Validate email exists in system."""
        if not User.objects.filter(email__iexact=value).exists():
            # For security, don't reveal if email exists or not
            # But still validate the request
            pass
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        """Validate passwords match."""
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords don't match.")
        return data


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for user profile updates (self-service)."""

    current_password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "current_password"]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
            "email": {"required": False},
        }

    def validate_current_password(self, value):
        """Validate current password if email is being changed."""
        if not value:
            return value

        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_email(self, value):
        """Validate email is unique."""
        user = self.context["request"].user
        if value and value != user.email:
            if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
                raise serializers.ValidationError("This email address is already in use.")
        return value

    def validate(self, data):
        """Require current password for email changes."""
        if "email" in data and data["email"] != self.context["request"].user.email:
            if not data.get("current_password"):
                raise serializers.ValidationError("Current password is required to change email address.")
        return data

    def update(self, instance, validated_data):
        """Update user profile."""
        # Remove current_password from validated_data as it's not a model field
        validated_data.pop("current_password", None)

        # Track if email changed for verification
        email_changed = "email" in validated_data and validated_data["email"] != instance.email

        # Update the instance
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # If email changed, mark as unverified (optional feature)
        if email_changed:
            # You could add an email_verified field to track this
            # instance.email_verified = False
            pass

        instance.save()
        return instance


class EmailChangeRequestSerializer(serializers.Serializer):
    """Serializer for requesting email change with verification."""

    new_email = serializers.EmailField()
    current_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        """Validate current password."""
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_email(self, value):
        """Validate new email is unique."""
        user = self.context["request"].user
        if value == user.email:
            raise serializers.ValidationError("New email must be different from current email.")

        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email address is already in use.")
        return value


class EmailChangeConfirmSerializer(serializers.Serializer):
    """Serializer for confirming email change with token."""

    token = serializers.CharField()

    def validate_token(self, value):
        """Validate email change token and extract new email."""
        import json

        from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

        if not value:
            raise serializers.ValidationError("Token is required.")

        try:
            signer = TimestampSigner()
            # Token expires after 24 hours (86400 seconds)
            unsigned_data = signer.unsign(value, max_age=86400)

            # Parse the JSON data from the token
            try:
                token_data = json.loads(unsigned_data)
                user_id = token_data.get("user_id")
                new_email = token_data.get("new_email")

                if not user_id or not new_email:
                    raise serializers.ValidationError("Invalid token format.")

                # Verify the user ID matches the current user
                current_user = self.context["request"].user
                if current_user.id != user_id:
                    raise serializers.ValidationError("Token is not valid for this user.")

                # Store the new email for use in the view
                self._new_email = new_email

            except (json.JSONDecodeError, KeyError):
                raise serializers.ValidationError("Invalid token format.")

        except SignatureExpired:
            raise serializers.ValidationError("Email change token has expired. Please request a new one.")
        except BadSignature:
            raise serializers.ValidationError("Invalid email change token.")

        return value

    def get_new_email(self):
        """Get the new email from the validated token."""
        return getattr(self, "_new_email", None)


class AnnotationFolderSerializer(serializers.ModelSerializer):
    """Serializer for annotation folders with hierarchical organization."""

    full_path = serializers.SerializerMethodField()
    child_folders_count = serializers.SerializerMethodField()
    annotations_count = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_view = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = AnnotationFolder
        fields = [
            "id",
            "folder_name",
            "parent_folder",
            "is_shared_document_folder",
            "owner",
            "owner_name",
            "lab_group",
            "visibility",
            "resource_type",
            "is_active",
            "is_locked",
            "created_at",
            "updated_at",
            "full_path",
            "child_folders_count",
            "annotations_count",
            "can_edit",
            "can_view",
            "can_delete",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "full_path",
            "child_folders_count",
            "annotations_count",
            "resource_type",
        ]

    def get_full_path(self, obj):
        """Get the full hierarchical path."""
        return obj.get_full_path()

    def get_child_folders_count(self, obj):
        """Get count of child folders."""
        return obj.child_folders.filter(is_active=True).count()

    def get_annotations_count(self, obj):
        """Get count of annotations in this folder."""
        return obj.annotations.filter(is_active=True).count()

    def get_can_edit(self, obj):
        """Check if current user can edit this folder."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_edit(request.user)
        return False

    def get_can_view(self, obj):
        """Check if current user can view this folder."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_view(request.user)
        return False

    def get_can_delete(self, obj):
        """Check if current user can delete this folder."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_delete(request.user)
        return False

    def get_owner_name(self, obj):
        """Get owner display name."""
        if obj.owner:
            return obj.owner.get_full_name() or obj.owner.username
        return None

    def create(self, validated_data):
        """Set owner to current user and default resource type."""
        request = self.context["request"]
        validated_data["owner"] = request.user
        validated_data["resource_type"] = "file"
        return super().create(validated_data)


class AnnotationSerializer(serializers.ModelSerializer):
    """Serializer for annotations with file upload support."""

    FILE_ANNOTATION_TYPES = ["file", "image", "video", "audio", "sketch"]

    file_url = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    folder_path = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_view = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    auto_transcribe = serializers.BooleanField(
        write_only=True,
        required=False,
        default=True,
        help_text="Whether to automatically transcribe audio/video files. Set to false if providing own transcription.",
    )

    class Meta:
        model = Annotation
        fields = [
            "id",
            "annotation",
            "annotation_type",
            "file",
            "file_url",
            "file_size",
            "folder",
            "folder_path",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "owner",
            "owner_name",
            "lab_group",
            "visibility",
            "resource_type",
            "is_active",
            "is_locked",
            "created_at",
            "updated_at",
            "can_edit",
            "can_view",
            "can_delete",
            "auto_transcribe",
        ]
        read_only_fields = ["created_at", "updated_at", "file_url", "file_size", "folder_path", "resource_type"]

    def get_file_url(self, obj):
        """
        Get signed download URL if file exists.

        Returns a time-limited signed URL that can be used to download the file.
        Only generates URLs for annotation types that support file uploads.
        """
        if obj.annotation_type not in self.FILE_ANNOTATION_TYPES:
            return None

        if not obj.file:
            return None

        request = self.context.get("request")
        if not request or not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        if not obj.can_view(request.user):
            return None

        try:
            token = obj.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.id})
            download_url = request.build_absolute_uri(f"{download_path}?token={token}")
            return download_url
        except Exception:
            return None

    def get_file_size(self, obj):
        """
        Get file size if file exists.

        Only returns size for annotation types that support file uploads.
        """
        if obj.annotation_type not in self.FILE_ANNOTATION_TYPES:
            return None

        if obj.file:
            try:
                return obj.file.size
            except (OSError, ValueError):
                return None
        return None

    def get_folder_path(self, obj):
        """Get folder path if folder exists."""
        if obj.folder:
            return obj.folder.get_full_path()
        return None

    def get_can_edit(self, obj):
        """Check if current user can edit this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_edit(request.user)
        return False

    def get_can_view(self, obj):
        """Check if current user can view this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_view(request.user)
        return False

    def get_can_delete(self, obj):
        """Check if current user can delete this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_delete(request.user)
        return False

    def get_owner_name(self, obj):
        """Get owner display name."""
        if obj.owner:
            return obj.owner.get_full_name() or obj.owner.username
        return None

    def create(self, validated_data):
        """
        Set owner to current user and default resource type.
        Automatically queue transcription for audio/video files if auto_transcribe is True.
        """
        request = self.context["request"]
        validated_data["owner"] = request.user
        validated_data["resource_type"] = "file"

        auto_transcribe = validated_data.pop("auto_transcribe", True)

        annotation = super().create(validated_data)

        if (
            auto_transcribe
            and getattr(settings, "USE_WHISPER", False)
            and getattr(settings, "ENABLE_CUPCAKE_RED_VELVET", False)
        ):
            annotation_type = annotation.annotation_type

            if annotation_type in ["audio", "video"] and annotation.file:
                if not annotation.transcribed:
                    try:
                        from ccc.tasks.transcribe_tasks import transcribe_audio, transcribe_audio_from_video

                        file_path = annotation.file.path
                        model_path = settings.WHISPERCPP_DEFAULT_MODEL

                        if annotation_type == "audio":
                            transcribe_audio.delay(
                                audio_path=file_path,
                                model_path=model_path,
                                annotation_id=annotation.id,
                                language="auto",
                                translate=True,
                            )
                            logger.info(f"Queued audio transcription for annotation {annotation.id}")
                        elif annotation_type == "video":
                            transcribe_audio_from_video.delay(
                                video_path=file_path,
                                model_path=model_path,
                                annotation_id=annotation.id,
                                language="auto",
                                translate=True,
                            )
                            logger.info(f"Queued video transcription for annotation {annotation.id}")

                    except Exception as e:
                        logger.error(f"Failed to queue transcription for annotation {annotation.id}: {str(e)}")

        return annotation


class RemoteHostSerializer(serializers.ModelSerializer):
    """Serializer for remote host configuration."""

    class Meta:
        model = RemoteHost
        fields = [
            "id",
            "host_name",
            "host_port",
            "host_protocol",
            "host_description",
            "host_token",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"host_token": {"write_only": True}}  # Don't expose tokens in responses


class ResourcePermissionSerializer(serializers.ModelSerializer):
    """Serializer for resource permissions."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_display_name = serializers.SerializerMethodField()
    granted_by_username = serializers.CharField(source="granted_by.username", read_only=True)
    resource_type_name = serializers.CharField(source="resource_content_type.name", read_only=True)
    resource_model = serializers.CharField(source="resource_content_type.model", read_only=True)

    class Meta:
        model = ResourcePermission
        fields = [
            "id",
            "user",
            "user_username",
            "user_display_name",
            "resource_content_type",
            "resource_type_name",
            "resource_model",
            "resource_object_id",
            "role",
            "granted_by",
            "granted_by_username",
            "granted_at",
        ]
        read_only_fields = ["id", "granted_by", "granted_at"]

    def get_user_display_name(self, obj):
        """Get user's display name."""
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        return obj.user.username

    def create(self, validated_data):
        """Set granted_by to current user."""
        request = self.context["request"]
        validated_data["granted_by"] = request.user
        return super().create(validated_data)
