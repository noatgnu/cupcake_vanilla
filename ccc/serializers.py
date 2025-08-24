"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Serializers.

This module contains serializers for user management, lab group collaboration,
and site administration functionality.
"""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from rest_framework import serializers

from .models import AccountMergeRequest, LabGroup, LabGroupInvitation, SiteConfig, UserOrcidProfile


class SiteConfigSerializer(serializers.ModelSerializer):
    """Serializer for site configuration settings."""

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
            "created_at",
            "updated_at",
            "updated_by",
        ]
        read_only_fields = ["created_at", "updated_at", "updated_by"]


class LabGroupSerializer(serializers.ModelSerializer):
    """Serializer for lab group objects."""

    member_count = serializers.SerializerMethodField()
    is_creator = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    can_invite = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()
    creator_name = serializers.SerializerMethodField()

    class Meta:
        model = LabGroup
        fields = [
            "id",
            "name",
            "description",
            "creator",
            "creator_name",
            "is_active",
            "allow_member_invites",
            "member_count",
            "is_creator",
            "is_member",
            "can_invite",
            "can_manage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "creator", "created_at", "updated_at"]

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

    def get_creator_name(self, obj):
        """Return the creator's display name."""
        if obj.creator:
            return obj.creator.get_full_name() or obj.creator.username
        return None

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
