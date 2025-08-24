"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Models.

This module contains the core user management, lab group collaboration,
and site administration functionality that can be reused across CUPCAKE applications.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords


class ResourceType(models.TextChoices):
    """Enumeration of different resource types in CUPCAKE applications."""

    METADATA_TABLE = "metadata_table", "Metadata Table"
    METADATA_TABLE_TEMPLATE = "metadata_table_template", "Metadata Table Template"
    METADATA_COLUMN_TEMPLATE = "metadata_column_template", "Metadata Column Template"
    FILE = "file", "File"
    DATASET = "dataset", "Dataset"
    SCHEMA = "schema", "Schema"


class ResourceVisibility(models.TextChoices):
    """Enumeration of resource visibility levels."""

    PRIVATE = "private", "Private"
    GROUP = "group", "Lab Group"
    PUBLIC = "public", "Public"


class ResourceRole(models.TextChoices):
    """Enumeration of resource access roles."""

    OWNER = "owner", "Owner"
    ADMIN = "admin", "Administrator"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class AbstractResource(models.Model):
    """
    Abstract base model that provides standardized resource management functionality.

    This model handles ownership, permissions, visibility, and audit trails for any
    resource type in CUPCAKE applications. Models that inherit from this get
    consistent access control patterns.
    """

    # Resource identification
    resource_type = models.CharField(max_length=50, choices=ResourceType.choices, help_text="Type of resource")

    # Ownership and access
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_%(class)s",
        blank=True,
        null=True,
        help_text="User who owns this resource",
    )
    lab_group = models.ForeignKey(
        "ccc.LabGroup",
        on_delete=models.SET_NULL,
        related_name="%(class)s_resources",
        blank=True,
        null=True,
        help_text="Lab group that has access to this resource",
    )

    # Visibility and access control
    visibility = models.CharField(
        max_length=20,
        choices=ResourceVisibility.choices,
        default=ResourceVisibility.PRIVATE,
        help_text="Who can access this resource",
    )

    # Resource status
    is_active = models.BooleanField(default=True, help_text="Whether this resource is active/available")
    is_locked = models.BooleanField(default=False, help_text="Whether this resource is locked for editing")

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True

    def can_view(self, user):
        """Check if a user can view this resource."""
        if not user or not user.is_authenticated:
            return self.visibility == ResourceVisibility.PUBLIC

        # Owner can always view
        if self.owner == user:
            return True

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Public resources can be viewed by anyone
        if self.visibility == ResourceVisibility.PUBLIC:
            return True

        # Group resources can be viewed by lab group members
        if self.visibility == ResourceVisibility.GROUP and self.lab_group:
            return user in self.lab_group.members.all()

        # Check explicit permissions
        return self.resource_permissions.filter(
            user=user, role__in=[ResourceRole.OWNER, ResourceRole.ADMIN, ResourceRole.EDITOR, ResourceRole.VIEWER]
        ).exists()

    def can_edit(self, user):
        """Check if a user can edit this resource."""
        if not user or not user.is_authenticated:
            return False

        # Cannot edit locked resources (unless owner/admin)
        if self.is_locked and self.owner != user and not user.is_staff:
            return False

        # Owner can always edit
        if self.owner == user:
            return True

        # Staff/superuser can always edit
        if user.is_staff or user.is_superuser:
            return True

        # Check explicit permissions
        return self.resource_permissions.filter(
            user=user, role__in=[ResourceRole.OWNER, ResourceRole.ADMIN, ResourceRole.EDITOR]
        ).exists()

    def can_delete(self, user):
        """Check if a user can delete this resource."""
        if not user or not user.is_authenticated:
            return False

        # Owner can always delete
        if self.owner == user:
            return True

        # Staff/superuser can always delete
        if user.is_staff or user.is_superuser:
            return True

        # Check explicit permissions
        return self.resource_permissions.filter(user=user, role__in=[ResourceRole.OWNER, ResourceRole.ADMIN]).exists()

    def can_share(self, user):
        """Check if a user can share this resource."""
        if not user or not user.is_authenticated:
            return False

        # Owner can always share
        if self.owner == user:
            return True

        # Staff/superuser can always share
        if user.is_staff or user.is_superuser:
            return True

        # Check explicit permissions
        return self.resource_permissions.filter(user=user, role__in=[ResourceRole.OWNER, ResourceRole.ADMIN]).exists()

    def get_user_role(self, user):
        """Get the user's role for this resource."""
        if not user or not user.is_authenticated:
            return None

        if self.owner == user:
            return ResourceRole.OWNER

        if user.is_staff or user.is_superuser:
            return ResourceRole.ADMIN

        permission = self.resource_permissions.filter(user=user).first()
        return permission.role if permission else None

    def add_permission(self, user, role):
        """Add or update a user's permission for this resource."""
        permission, created = ResourcePermission.objects.get_or_create(
            resource_content_type=self._meta.get_content_type(),
            resource_object_id=self.pk,
            user=user,
            defaults={"role": role},
        )
        if not created and permission.role != role:
            permission.role = role
            permission.save()
        return permission

    def remove_permission(self, user):
        """Remove a user's explicit permission for this resource."""
        ResourcePermission.objects.filter(
            resource_content_type=self._meta.get_content_type(), resource_object_id=self.pk, user=user
        ).delete()


class ResourcePermission(models.Model):
    """
    Explicit permissions for resources beyond the default ownership/lab group access.
    """

    # Generic foreign key to any resource that inherits from AbstractResource
    resource_content_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.CASCADE, help_text="Type of resource this permission applies to"
    )
    resource_object_id = models.PositiveIntegerField(help_text="ID of the specific resource instance")

    # Permission details
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="resource_permissions",
        help_text="User who has this permission",
    )
    role = models.CharField(max_length=20, choices=ResourceRole.choices, help_text="Level of access this user has")

    # Permission metadata
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="granted_permissions",
        blank=True,
        null=True,
        help_text="User who granted this permission",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ccc"
        unique_together = [["resource_content_type", "resource_object_id", "user"]]
        indexes = [
            models.Index(fields=["resource_content_type", "resource_object_id"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.role} - {self.resource_content_type}"


class SiteConfig(models.Model):
    """
    Site-specific configuration settings for CUPCAKE applications.
    Singleton model - only one instance should exist.
    """

    # Site branding
    site_name = models.CharField(max_length=255, default="CUPCAKE", help_text="Name of the site displayed in UI")
    logo_url = models.URLField(blank=True, null=True, help_text="URL to site logo image")
    logo_image = models.FileField(
        upload_to="site_logos/",
        blank=True,
        null=True,
        help_text="Upload custom logo image file (overrides logo_url if provided)",
    )
    primary_color = models.CharField(
        max_length=7, default="#1976d2", help_text="Primary color for the site theme (hex format: #RRGGBB)"
    )
    show_powered_by = models.BooleanField(default=True, help_text="Show 'Powered by CUPCAKE' branding")
    allow_user_registration = models.BooleanField(default=False, help_text="Allow public user registration")
    enable_orcid_login = models.BooleanField(default=False, help_text="Enable ORCID OAuth login")

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User who last updated the configuration"
    )

    class Meta:
        app_label = "ccc"
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

    def __str__(self):
        return f"Site Config: {self.site_name}"


class LabGroup(models.Model):
    """
    Represents a laboratory group for organizing users and resources.
    """

    name = models.CharField(max_length=255, help_text="Name of the lab group")
    description = models.TextField(blank=True, null=True, help_text="Description of the lab group")

    # Group ownership
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_lab_groups",
        blank=True,
        null=True,
        help_text="User who created this lab group",
    )

    # Group membership
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="lab_groups",
        blank=True,
        help_text="Users who are members of this lab group",
    )

    # Group settings
    is_active = models.BooleanField(default=True, help_text="Whether this lab group is active")
    allow_member_invites = models.BooleanField(
        default=True, help_text="Whether members can invite other users to this lab group"
    )

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "ccc"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def is_creator(self, user):
        """Check if user is the creator of this lab group."""
        return self.creator == user

    def is_member(self, user):
        """Check if user is a member of this lab group."""
        return self.members.filter(id=user.id).exists()

    def can_invite(self, user):
        """Check if user can invite others to this lab group."""
        return self.is_creator(user) or (self.allow_member_invites and self.is_member(user))

    def can_manage(self, user):
        """Check if user can manage this lab group."""
        return self.is_creator(user)


class LabGroupInvitation(models.Model):
    """
    Represents an invitation to join a lab group.
    """

    class InvitationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    lab_group = models.ForeignKey(
        LabGroup, on_delete=models.CASCADE, related_name="invitations", help_text="Lab group the invitation is for"
    )

    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_lab_invitations",
        help_text="User who sent the invitation",
    )

    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_lab_invitations",
        blank=True,
        null=True,
        help_text="User who was invited (if registered)",
    )

    invited_email = models.EmailField(help_text="Email address of the invited person")

    status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
        help_text="Current status of the invitation",
    )

    message = models.TextField(blank=True, null=True, help_text="Optional message from the inviter")

    # Token for secure invitation acceptance
    invitation_token = models.CharField(max_length=64, unique=True, help_text="Unique token for invitation acceptance")

    expires_at = models.DateTimeField(help_text="When this invitation expires")

    # Response tracking
    responded_at = models.DateTimeField(blank=True, null=True, help_text="When the invitation was responded to")

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "ccc"
        ordering = ["-created_at"]
        unique_together = [["lab_group", "invited_email"]]

    def __str__(self):
        return f"Invitation to {self.lab_group.name} for {self.invited_email}"

    def save(self, *args, **kwargs):
        if not self.invitation_token:
            import secrets

            self.invitation_token = secrets.token_urlsafe(48)

        if not self.expires_at:
            from datetime import timedelta

            from django.utils import timezone

            self.expires_at = timezone.now() + timedelta(days=7)  # 7 days expiry

        super().save(*args, **kwargs)

    def is_expired(self):
        """Check if this invitation has expired."""
        return timezone.now() > self.expires_at

    def can_accept(self):
        """Check if this invitation can be accepted."""
        return self.status == self.InvitationStatus.PENDING and not self.is_expired()

    def accept(self, user):
        """Accept the invitation and add user to lab group."""
        if not self.can_accept():
            raise ValueError("Invitation cannot be accepted")

        if user.email.lower() != self.invited_email.lower():
            raise ValueError("Email does not match invitation")

        # Add user to lab group
        self.lab_group.members.add(user)

        # Update invitation status
        self.status = self.InvitationStatus.ACCEPTED
        self.invited_user = user
        self.responded_at = timezone.now()
        self.save()

    def reject(self, user=None):
        """Reject the invitation."""
        if not self.can_accept():
            raise ValueError("Invitation cannot be rejected")

        self.status = self.InvitationStatus.REJECTED
        if user:
            self.invited_user = user
        self.responded_at = timezone.now()
        self.save()


class UserOrcidProfile(models.Model):
    """
    Links user accounts with ORCID profiles and handles account merging.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="orcid_profile",
        help_text="User account linked to this ORCID profile",
    )

    orcid_id = models.CharField(max_length=19, unique=True, help_text="ORCID identifier (e.g., 0000-0000-0000-0000)")

    orcid_name = models.CharField(max_length=255, blank=True, null=True, help_text="Full name from ORCID profile")

    orcid_email = models.EmailField(blank=True, null=True, help_text="Email from ORCID profile (if public)")

    # Verification and linking information
    verified = models.BooleanField(default=False, help_text="Whether this ORCID link has been verified")

    linked_at = models.DateTimeField(auto_now_add=True, help_text="When this ORCID was linked to the user account")

    # OAuth tokens (optional, for future API access)
    access_token = models.TextField(blank=True, null=True, help_text="ORCID OAuth access token (encrypted)")

    refresh_token = models.TextField(blank=True, null=True, help_text="ORCID OAuth refresh token (encrypted)")

    token_expires_at = models.DateTimeField(blank=True, null=True, help_text="When the access token expires")

    class Meta:
        app_label = "ccc"
        verbose_name = "User ORCID Profile"
        verbose_name_plural = "User ORCID Profiles"
        indexes = [
            models.Index(fields=["orcid_id"]),
            models.Index(fields=["orcid_email"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.orcid_id}"


class AccountMergeRequest(models.Model):
    """
    Tracks requests to merge duplicate user accounts.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("completed", "Completed"),
    ]

    # The accounts to merge
    primary_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="merge_requests_as_primary",
        help_text="The account to keep (target account)",
    )

    duplicate_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="merge_requests_as_duplicate",
        help_text="The account to merge and remove (source account)",
    )

    # Request information
    requested_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="initiated_merge_requests",
        help_text="User who requested the merge",
    )

    reason = models.TextField(help_text="Reason for the merge request")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", help_text="Current status of the merge request"
    )

    # Admin handling
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_merge_requests",
        help_text="Admin who reviewed this request",
    )

    admin_notes = models.TextField(blank=True, null=True, help_text="Notes from admin review")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True, help_text="When the merge was completed")

    class Meta:
        app_label = "ccc"
        verbose_name = "Account Merge Request"
        verbose_name_plural = "Account Merge Requests"
        unique_together = [
            ("primary_user", "duplicate_user"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Merge {self.duplicate_user.username} → {self.primary_user.username}"

    def clean(self):
        """Validate that primary and duplicate users are different."""
        if self.primary_user == self.duplicate_user:
            raise ValidationError("Primary and duplicate users must be different.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
