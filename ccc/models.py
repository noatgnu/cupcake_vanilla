"""
CUPCAKE Core (CCC) - User Management, Lab Groups, and Site Administration Models.

This module contains the core user management, lab group collaboration,
and site administration functionality that can be reused across CUPCAKE applications.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords


class ResourceType(models.TextChoices):
    """
    Enumeration of different resource types in CUPCAKE applications.

    This defines the standardized types of resources that can be managed
    within the CUPCAKE ecosystem, each with specific access control patterns.

    Examples:
        >>> # Create a metadata table resource
        >>> resource_type = ResourceType.METADATA_TABLE
        >>> print(resource_type)  # "metadata_table"
        >>> print(resource_type.label)  # "Metadata Table"

        >>> # Check if a type is valid
        >>> ResourceType.METADATA_TABLE in ResourceType.values
        True

        >>> # Get all available types
        >>> for choice in ResourceType.choices:
        ...     print(f"{choice[0]}: {choice[1]}")
        metadata_table: Metadata Table
        metadata_table_template: Metadata Table Template
        ...
    """

    METADATA_TABLE = "metadata_table", "Metadata Table"
    METADATA_TABLE_TEMPLATE = "metadata_table_template", "Metadata Table Template"
    METADATA_COLUMN_TEMPLATE = "metadata_column_template", "Metadata Column Template"
    FILE = "file", "File"
    DATASET = "dataset", "Dataset"
    SCHEMA = "schema", "Schema"


class ResourceVisibility(models.TextChoices):
    """
    Enumeration of resource visibility levels for access control.

    Defines who can access a resource based on its visibility setting.
    Used in conjunction with resource ownership and explicit permissions.

    Examples:
        >>> # Set resource to private (only owner can access)
        >>> visibility = ResourceVisibility.PRIVATE
        >>> print(visibility)  # "private"

        >>> # Check if visibility allows public access
        >>> visibility = ResourceVisibility.PUBLIC
        >>> is_public = visibility == ResourceVisibility.PUBLIC
        >>> print(is_public)  # True

        >>> # Get all visibility options for UI
        >>> choices = [(v.value, v.label) for v in ResourceVisibility]
        >>> print(choices)
        [('private', 'Private'), ('group', 'Lab Group'), ('public', 'Public')]
    """

    PRIVATE = "private", "Private"
    GROUP = "group", "Lab Group"
    PUBLIC = "public", "Public"


class ResourceRole(models.TextChoices):
    """
    Enumeration of resource access roles with hierarchical permissions.

    Defines different levels of access that users can have to resources,
    with each role inheriting permissions from lower levels.

    Permission hierarchy (highest to lowest):
    - OWNER: Full control (read, write, delete, share, manage permissions)
    - ADMIN: Administrative access (read, write, delete, share)
    - EDITOR: Edit access (read, write)
    - VIEWER: Read-only access

    Examples:
        >>> # Grant editor access to a user
        >>> role = ResourceRole.EDITOR
        >>> print(role)  # "editor"
        >>> print(role.label)  # "Editor"

        >>> # Check role hierarchy
        >>> admin_roles = [ResourceRole.OWNER, ResourceRole.ADMIN]
        >>> can_delete = ResourceRole.ADMIN in admin_roles
        >>> print(can_delete)  # True

        >>> # Get roles for permission checking
        >>> edit_roles = [ResourceRole.OWNER, ResourceRole.ADMIN, ResourceRole.EDITOR]
        >>> view_roles = list(ResourceRole.values)  # All roles can view
    """

    OWNER = "owner", "Owner"
    ADMIN = "admin", "Administrator"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class AbstractResource(models.Model):
    """
    Abstract base model that provides standardized resource management functionality.

    This model handles ownership, permissions, visibility, and audit trails for any
    resource type in CUPCAKE applications. Models that inherit from this get
    consistent access control patterns, audit trails, and permission checking methods.

    Key Features:
    - Ownership tracking with user and lab group association
    - Flexible visibility controls (private, group, public)
    - Role-based permission system with explicit grants
    - Automatic audit trails with django-simple-history
    - Resource locking and status management

    Examples:
        >>> # Create a concrete resource model
        >>> class Document(AbstractResource):
        ...     name = models.CharField(max_length=200)
        ...     resource_type = ResourceType.FILE

        >>> # Create and configure a resource
        >>> doc = Document.objects.create(
        ...     name="My Document",
        ...     resource_type=ResourceType.FILE,
        ...     owner=user,
        ...     visibility=ResourceVisibility.GROUP,
        ...     lab_group=lab_group
        ... )

        >>> # Check permissions
        >>> can_view = doc.can_view(some_user)
        >>> can_edit = doc.can_edit(some_user)
        >>> user_role = doc.get_user_role(some_user)

        >>> # Grant explicit permissions
        >>> doc.add_permission(another_user, ResourceRole.EDITOR)
        >>> doc.remove_permission(another_user)

        >>> # Lock resource for editing
        >>> doc.is_locked = True
        >>> doc.save()
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

    # Generic relation to ResourcePermission for reverse lookups
    resource_permissions = GenericRelation(
        "ccc.ResourcePermission",
        content_type_field="resource_content_type",
        object_id_field="resource_object_id",
        related_query_name="resource",
    )

    class Meta:
        abstract = True

    def can_view(self, user):
        """
        Check if a user can view this resource.

        Combines ownership, visibility settings, lab group membership,
        and explicit permissions to determine view access.

        Args:
            user: Django User instance or None for anonymous users

        Returns:
            bool: True if user can view the resource, False otherwise

        Examples:
            >>> # Check view permission for resource owner
            >>> resource.owner = user1
            >>> resource.can_view(user1)  # True

            >>> # Check view permission for public resource
            >>> resource.visibility = ResourceVisibility.PUBLIC
            >>> resource.can_view(anonymous_user)  # True

            >>> # Check view permission for lab group member
            >>> resource.visibility = ResourceVisibility.GROUP
            >>> resource.lab_group.members.add(user2)
            >>> resource.can_view(user2)  # True

            >>> # Check view permission with explicit grant
            >>> resource.add_permission(user3, ResourceRole.VIEWER)
            >>> resource.can_view(user3)  # True
        """
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

        # Group resources can be viewed by lab group members (includes bubble-up from sub-groups)
        if self.visibility == ResourceVisibility.GROUP and self.lab_group:
            return self.lab_group.is_member(user)

        # Check explicit permissions
        return self.resource_permissions.filter(
            user=user, role__in=[ResourceRole.OWNER, ResourceRole.ADMIN, ResourceRole.EDITOR, ResourceRole.VIEWER]
        ).exists()

    def can_edit(self, user):
        """
        Check if a user can edit this resource.

        Considers resource locking, ownership, staff status, and explicit
        permissions to determine edit access. Locked resources can only
        be edited by owners and administrators.

        Args:
            user: Django User instance to check permissions for

        Returns:
            bool: True if user can edit the resource, False otherwise

        Examples:
            >>> # Resource owner can always edit
            >>> resource.owner = user1
            >>> resource.can_edit(user1)  # True

            >>> # Cannot edit locked resource unless owner/admin
            >>> resource.is_locked = True
            >>> resource.can_edit(regular_user)  # False
            >>> resource.can_edit(resource.owner)  # True

            >>> # Edit permission with explicit role
            >>> resource.add_permission(user2, ResourceRole.EDITOR)
            >>> resource.can_edit(user2)  # True

            >>> # Staff users can always edit
            >>> user3.is_staff = True
            >>> resource.can_edit(user3)  # True
        """
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
        """
        Check if a user can share this resource with other users.

        Only owners and administrators can share resources, as sharing
        requires the ability to grant permissions to other users.

        Args:
            user: Django User instance to check permissions for

        Returns:
            bool: True if user can share the resource, False otherwise

        Examples:
            >>> # Resource owner can share
            >>> resource.owner = user1
            >>> resource.can_share(user1)  # True

            >>> # Admin can share
            >>> resource.add_permission(user2, ResourceRole.ADMIN)
            >>> resource.can_share(user2)  # True

            >>> # Editor cannot share
            >>> resource.add_permission(user3, ResourceRole.EDITOR)
            >>> resource.can_share(user3)  # False

            >>> # Staff users can share
            >>> user4.is_staff = True
            >>> resource.can_share(user4)  # True
        """
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
        """
        Get the user's role for this resource.

        Returns the highest role that the user has for this resource,
        considering ownership, staff status, and explicit permissions.

        Args:
            user: Django User instance to check role for

        Returns:
            ResourceRole or None: The user's role, or None if no access

        Examples:
            >>> # Get owner role
            >>> resource.owner = user1
            >>> role = resource.get_user_role(user1)
            >>> print(role)  # ResourceRole.OWNER

            >>> # Get explicit role
            >>> resource.add_permission(user2, ResourceRole.EDITOR)
            >>> role = resource.get_user_role(user2)
            >>> print(role)  # ResourceRole.EDITOR

            >>> # Staff gets admin role
            >>> user3.is_staff = True
            >>> role = resource.get_user_role(user3)
            >>> print(role)  # ResourceRole.ADMIN

            >>> # No access
            >>> role = resource.get_user_role(unauthorized_user)
            >>> print(role)  # None
        """
        if not user or not user.is_authenticated:
            return None

        if self.owner == user:
            return ResourceRole.OWNER

        if user.is_staff or user.is_superuser:
            return ResourceRole.ADMIN

        permission = self.resource_permissions.filter(user=user).first()
        return permission.role if permission else None

    def add_permission(self, user, role):
        """
        Add or update a user's permission for this resource.

        Creates or updates an explicit permission record for the user.
        This is useful for granting access to users who don't have
        access through ownership, lab group membership, or visibility.

        Args:
            user: Django User instance to grant permission to
            role: ResourceRole to assign to the user

        Returns:
            ResourcePermission: The created or updated permission record

        Examples:
            >>> # Grant editor access
            >>> perm = resource.add_permission(user1, ResourceRole.EDITOR)
            >>> print(perm.role)  # ResourceRole.EDITOR

            >>> # Upgrade to admin access
            >>> perm = resource.add_permission(user1, ResourceRole.ADMIN)
            >>> print(perm.role)  # ResourceRole.ADMIN

            >>> # Grant viewer access to multiple users
            >>> for user in users:
            ...     resource.add_permission(user, ResourceRole.VIEWER)
        """
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
        """
        Remove a user's explicit permission for this resource.

        Deletes any explicit permission record for the user. Note that
        this does not affect access through ownership, lab group membership,
        or public visibility.

        Args:
            user: Django User instance to remove permission for

        Examples:
            >>> # Remove explicit permission
            >>> resource.add_permission(user1, ResourceRole.EDITOR)
            >>> resource.can_edit(user1)  # True
            >>> resource.remove_permission(user1)
            >>> resource.can_edit(user1)  # False (unless other access)

            >>> # Remove permission but user still has access as owner
            >>> resource.owner = user2
            >>> resource.add_permission(user2, ResourceRole.VIEWER)
            >>> resource.remove_permission(user2)
            >>> resource.can_edit(user2)  # Still True (owner access)
        """
        ResourcePermission.objects.filter(
            resource_content_type=self._meta.get_content_type(), resource_object_id=self.pk, user=user
        ).delete()


class ResourcePermission(models.Model):
    """
    Explicit permissions for resources beyond the default ownership/lab group access.

    This model stores fine-grained permissions that users have been explicitly
    granted for specific resources. It uses Django's ContentType framework
    to create permissions for any model that inherits from AbstractResource.

    Key Features:
    - Generic foreign key to any AbstractResource model
    - Role-based permissions with audit trail
    - Unique constraint prevents duplicate permissions
    - Indexed for efficient permission checking

    Examples:
        >>> # Grant editor access to a document
        >>> from django.contrib.contenttypes.models import ContentType
        >>> doc_type = ContentType.objects.get_for_model(Document)
        >>> permission = ResourcePermission.objects.create(
        ...     resource_content_type=doc_type,
        ...     resource_object_id=document.id,
        ...     user=user,
        ...     role=ResourceRole.EDITOR,
        ...     granted_by=admin_user
        ... )

        >>> # Check if user has permission
        >>> has_perm = ResourcePermission.objects.filter(
        ...     resource_content_type=doc_type,
        ...     resource_object_id=document.id,
        ...     user=user,
        ...     role__in=[ResourceRole.EDITOR, ResourceRole.ADMIN, ResourceRole.OWNER]
        ... ).exists()

        >>> # Get all permissions for a user
        >>> user_perms = ResourcePermission.objects.filter(user=user)
        >>> for perm in user_perms:
        ...     print(f"{perm.role} access to {perm.resource_content_type}")
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

    Singleton model that stores customizable settings for the CUPCAKE
    instance, including branding, feature toggles, and authentication
    configuration. Only one instance should exist per deployment.

    Key Features:
    - Site branding (name, logo, colors)
    - Feature toggles (user registration, ORCID login)
    - Display preferences (powered-by attribution)
    - Audit trail with update tracking

    Examples:
        >>> # Get or create site configuration
        >>> config, created = SiteConfig.objects.get_or_create(
        ...     defaults={
        ...         'site_name': 'My CUPCAKE Instance',
        ...         'primary_color': '#1976d2',
        ...         'allow_user_registration': True,
        ...         'enable_orcid_login': True
        ...     }
        ... )

        >>> # Update site branding
        >>> config.site_name = 'Proteomics Data Portal'
        >>> config.primary_color = '#4caf50'
        >>> config.logo_url = 'https://example.com/logo.png'
        >>> config.updated_by = admin_user
        >>> config.save()

        >>> # Check feature flags
        >>> if config.allow_user_registration:
        ...     # Show registration form
        ...     pass

        >>> # Get current configuration for templates
        >>> config = SiteConfig.objects.first()
        >>> site_name = config.site_name if config else 'CUPCAKE'
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

    # Booking configuration
    booking_deletion_window_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Time window (in minutes) after booking creation during which the creator can delete it. "
        "After this window, bookings become permanent and cannot be deleted by regular users. "
        "Staff and instrument managers can always delete bookings.",
    )

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

    Lab groups provide a way to organize users into collaborative teams
    and control access to shared resources. They support invitation-based
    membership and configurable permission settings.

    Key Features:
    - Creator-based ownership with member management
    - Invitation system for adding new members
    - Configurable member invitation permissions
    - Integration with resource visibility controls
    - Audit trail with timestamps

    Examples:
        >>> # Create a new lab group
        >>> lab_group = LabGroup.objects.create(
        ...     name='Proteomics Lab',
        ...     description='Research group focused on proteomics analysis',
        ...     creator=pi_user,
        ...     allow_member_invites=True
        ... )

        >>> # Add members to the group
        >>> lab_group.members.add(researcher1, researcher2)

        >>> # Check permissions
        >>> can_invite = lab_group.can_invite(researcher1)  # True if allow_member_invites
        >>> can_manage = lab_group.can_manage(pi_user)      # True for creator
        >>> is_member = lab_group.is_member(researcher1)    # True

        >>> # Use with resource visibility
        >>> document.lab_group = lab_group
        >>> document.visibility = ResourceVisibility.GROUP
        >>> document.save()  # Now accessible to all lab group members
    """

    name = models.CharField(max_length=255, help_text="Name of the lab group")
    description = models.TextField(blank=True, null=True, help_text="Description of the lab group")

    # Group hierarchy
    parent_group = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="sub_groups",
        blank=True,
        null=True,
        help_text="Parent lab group in the hierarchy",
    )

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
    allow_process_jobs = models.BooleanField(
        default=False, help_text="Whether new members automatically get can_process_jobs permission"
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

    def get_full_path(self):
        """
        Get the full hierarchical path to root as an array of objects.
        Each object contains id and name for frontend navigation.
        """
        path = []
        current = self
        while current:
            path.insert(0, {"id": current.id, "name": current.name})
            current = current.parent_group
        return path

    def get_all_sub_groups(self):
        """Get all nested sub groups recursively."""
        sub_groups = []
        for sub_group in self.sub_groups.all():
            sub_groups.append(sub_group)
            sub_groups.extend(sub_group.get_all_sub_groups())
        return sub_groups

    def is_root(self):
        """Check if this lab group is at root level (no parent)."""
        return self.parent_group is None

    def get_depth(self):
        """Get the depth/level of this lab group in the hierarchy."""
        depth = 0
        current = self.parent_group
        while current:
            depth += 1
            current = current.parent_group
        return depth

    def is_creator(self, user):
        """
        Check if user is the creator of this lab group.

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user created this lab group

        Examples:
            >>> lab_group.creator = pi_user
            >>> lab_group.is_creator(pi_user)  # True
            >>> lab_group.is_creator(student)  # False
        """
        return self.creator == user

    def is_member(self, user):
        """
        Check if user is a member of this lab group or any of its sub-groups.

        Membership bubbles up: if you're a member of a sub-group, you're
        automatically considered a member of all parent groups.

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user is in the members list or is a member of any sub-group

        Examples:
            >>> lab_group.members.add(researcher)
            >>> lab_group.is_member(researcher)  # True

            >>> # User is member of sub-group
            >>> sub_group = LabGroup.objects.create(name="Sub", parent_group=lab_group)
            >>> sub_group.members.add(researcher2)
            >>> lab_group.is_member(researcher2)  # True (bubbles up from sub-group)
        """
        # Direct membership
        if self.members.filter(id=user.id).exists():
            return True

        # Check all sub-groups recursively
        for sub_group in self.sub_groups.all():
            if sub_group.is_member(user):
                return True

        return False

    def can_invite(self, user):
        """
        Check if user can invite others to this lab group.

        Staff users can always invite. Members can invite only if
        allow_member_invites is enabled for the group. Users with
        explicit can_invite permission can also invite.

        Membership bubbles up: if user is a member of any sub-group,
        they can invite if allow_member_invites is enabled.

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user can send invitations
        """
        if user.is_authenticated and user.is_staff:
            return True

        permission = self.lab_group_permissions.filter(user=user).first()
        if permission and permission.can_invite:
            return True

        return self.allow_member_invites and self.is_member(user)

    def can_manage(self, user):
        """
        Check if user can manage this lab group.

        Staff users get management privileges. Users with explicit
        LabGroupPermission.can_manage can also manage.

        NOTE: Management permissions do NOT bubble up from sub-groups.

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user can manage the lab group
        """
        if user.is_authenticated and user.is_staff:
            return True

        permission = self.lab_group_permissions.filter(user=user).first()
        if permission and permission.can_manage:
            return True

        return False

    def can_process_jobs(self, user):
        """
        Check if user can process instrument jobs for this lab group.

        Staff users can always process jobs. Users with explicit
        can_process_jobs permission can also process jobs.

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user can process instrument jobs
        """
        if user.is_authenticated and user.is_staff:
            return True

        permission = self.lab_group_permissions.filter(user=user).first()
        if permission and permission.can_process_jobs:
            return True

        return False

    @classmethod
    def get_accessible_group_ids(cls, user):
        """
        Get all lab group IDs accessible to a user (includes bubble-up from sub-groups).

        Returns IDs of groups where the user is either:
        - A direct member
        - The creator
        - A member of any sub-group (parent groups via bubble-up)

        Args:
            user: Django User instance

        Returns:
            set: Set of lab group IDs accessible to the user

        Examples:
            >>> accessible_ids = LabGroup.get_accessible_group_ids(user)
            >>> projects = Project.objects.filter(lab_group_id__in=accessible_ids)
        """
        from django.db.models import Q

        accessible_groups = set()
        direct_groups = cls.objects.filter(Q(members=user) | Q(creator=user))

        for group in direct_groups:
            accessible_groups.add(group.id)
            # Add all parent groups (bubble up)
            current = group.parent_group
            while current:
                accessible_groups.add(current.id)
                current = current.parent_group

        return accessible_groups

    def get_all_members(self, include_subgroups=True):
        """
        Get all members of this lab group.

        Args:
            include_subgroups (bool): If True, include members from all sub-groups.
                                     If False, return only direct members.

        Returns:
            QuerySet: User objects that are members

        Examples:
            >>> # Get all members including sub-groups (default)
            >>> all_members = lab_group.get_all_members()

            >>> # Get only direct members
            >>> direct_members = lab_group.get_all_members(include_subgroups=False)
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()

        if not include_subgroups:
            return self.members.all()

        # Collect all member IDs from this group and all sub-groups
        member_ids = set(self.members.values_list("id", flat=True))

        # Recursively get members from all sub-groups
        for sub_group in self.sub_groups.all():
            sub_member_ids = sub_group.get_all_members(include_subgroups=True).values_list("id", flat=True)
            member_ids.update(sub_member_ids)

        return User.objects.filter(id__in=member_ids)


class LabGroupPermission(models.Model):
    """
    Granular permission system for lab groups.

    Provides four levels of permissions:
    - can_view: Can see lab group details and members
    - can_invite: Can invite new members to the lab group
    - can_manage: Can modify lab group settings and manage permissions
    - can_process_jobs: Can be assigned to process instrument jobs for this lab group
    """

    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_group_permissions")
    lab_group = models.ForeignKey(LabGroup, on_delete=models.CASCADE, related_name="lab_group_permissions")
    can_view = models.BooleanField(default=False, help_text="Can view lab group details and members")
    can_invite = models.BooleanField(default=False, help_text="Can invite new members to the lab group")
    can_manage = models.BooleanField(default=False, help_text="Can modify lab group settings and manage permissions")
    can_process_jobs = models.BooleanField(default=False, help_text="Can be assigned to process instrument jobs")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccc"
        unique_together = [["user", "lab_group"]]
        ordering = ["created_at"]

    def __str__(self):
        permissions = []
        if self.can_view:
            permissions.append("view")
        if self.can_invite:
            permissions.append("invite")
        if self.can_manage:
            permissions.append("manage")
        if self.can_process_jobs:
            permissions.append("process_jobs")
        permission_str = ", ".join(permissions) if permissions else "no permissions"
        return f"{self.user.username} - {self.lab_group.name} ({permission_str})"


class LabGroupInvitation(models.Model):
    """
    Represents an invitation to join a lab group.

    Manages the complete invitation lifecycle from creation to acceptance/rejection.
    Supports email-based invitations with secure tokens and expiration handling.

    Key Features:
    - Secure token-based invitation system
    - Email-based invitations for unregistered users
    - Automatic expiration handling (default 7 days)
    - Status tracking with audit trail
    - Integration with lab group membership

    Examples:
        >>> # Send invitation to existing user
        >>> invitation = LabGroupInvitation.objects.create(
        ...     lab_group=proteomics_lab,
        ...     inviter=pi_user,
        ...     invited_email='researcher@university.edu',
        ...     message='Join our proteomics research group!'
        ... )

        >>> # Check invitation status
        >>> if invitation.can_accept():
        ...     invitation.accept(invited_user)

        >>> # Handle expiration
        >>> if invitation.is_expired():
        ...     invitation.status = LabGroupInvitation.InvitationStatus.EXPIRED
        ...     invitation.save()

        >>> # Get all pending invitations for a user
        >>> pending = LabGroupInvitation.objects.filter(
        ...     invited_email=user.email,
        ...     status=LabGroupInvitation.InvitationStatus.PENDING
        ... )
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

        # Grant can_process_jobs permission if lab group allows it
        if self.lab_group.allow_process_jobs:
            permission, created = LabGroupPermission.objects.get_or_create(
                user=user, lab_group=self.lab_group, defaults={"can_process_jobs": True, "can_view": True}
            )
            if not created and not permission.can_process_jobs:
                permission.can_process_jobs = True
                permission.save(update_fields=["can_process_jobs"])

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

    Stores ORCID profile information for authenticated users and manages
    the linking between CUPCAKE user accounts and ORCID identities.
    Supports OAuth2-based authentication and profile data synchronization.

    Key Features:
    - One-to-one mapping between users and ORCID IDs
    - Verification status tracking
    - Profile data caching from ORCID API
    - Integration with authentication backend

    Examples:
        >>> # Create ORCID profile after OAuth
        >>> profile = UserOrcidProfile.objects.create(
        ...     user=researcher,
        ...     orcid_id='0000-0002-1825-0097',
        ...     orcid_name='Josiah Carberry',
        ...     orcid_email='jcarberry@example.edu',
        ...     verified=True
        ... )

        >>> # Check if user has verified ORCID
        >>> has_orcid = hasattr(user, 'orcid_profile') and user.orcid_profile.verified

        >>> # Get user by ORCID ID
        >>> try:
        ...     profile = UserOrcidProfile.objects.get(orcid_id='0000-0002-1825-0097')
        ...     user = profile.user
        ... except UserOrcidProfile.DoesNotExist:
        ...     user = None
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

    Manages the workflow for consolidating duplicate accounts that may occur
    when users register multiple times or through different authentication
    methods (e.g., email + ORCID). Provides audit trail and approval process.

    Key Features:
    - Request workflow with status tracking
    - Primary/duplicate account designation
    - Reason documentation for merges
    - Admin approval process
    - Audit trail with timestamps

    Examples:
        >>> # Request to merge duplicate accounts
        >>> merge_request = AccountMergeRequest.objects.create(
        ...     primary_user=main_account,
        ...     duplicate_user=duplicate_account,
        ...     requested_by=admin_user,
        ...     reason='User created duplicate account via ORCID login'
        ... )

        >>> # Admin reviews and approves
        >>> merge_request.status = 'approved'
        >>> merge_request.save()

        >>> # Check for pending merge requests
        >>> pending = AccountMergeRequest.objects.filter(
        ...     status='pending',
        ...     primary_user=user
        ... )

        >>> # Validate merge request before creation
        >>> merge_request = AccountMergeRequest(
        ...     primary_user=user1,
        ...     duplicate_user=user1  # Same user - will raise ValidationError
        ... )
        >>> merge_request.clean()  # ValidationError: Cannot merge user with themselves
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


class RemoteHost(models.Model):
    history = HistoricalRecords()
    host_name = models.CharField(max_length=255, default="localhost")
    host_port = models.IntegerField(default=8000)
    host_protocol = models.CharField(max_length=255, default="http")
    host_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    host_token = models.TextField(blank=True, null=True)
    host_type_choices = [
        ("cupcake", "Cupcake"),
    ]

    class Meta:
        app_label = "ccc"
        ordering = ["id"]

    def __str__(self):
        return self.host_name


class AnnotationFolder(AbstractResource):
    """
    Hierarchical folder system for organizing annotations and documents.

    Core model that can be used across all apps to organize documents,
    files, and annotations with proper access control and sharing.
    """

    folder_name = models.CharField(max_length=255, help_text="Name of the folder", default="New Folder")
    parent_folder = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="child_folders",
        blank=True,
        null=True,
        help_text="Parent folder for hierarchical organization",
    )
    is_shared_document_folder = models.BooleanField(
        default=False, help_text="Indicates if this folder is specifically for shared documents"
    )

    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "RemoteHost", on_delete=models.CASCADE, related_name="annotation_folders", blank=True, null=True
    )

    class Meta:
        app_label = "ccc"
        ordering = ["folder_name"]

    def __str__(self):
        return self.folder_name

    def get_full_path(self):
        """Get the full hierarchical path of this folder."""
        if not self.parent_folder:
            return self.folder_name
        return f"{self.parent_folder.get_full_path()}/{self.folder_name}"

    def get_all_child_folders(self):
        """Get all nested child folders recursively."""
        children = []
        for child in self.child_folders.all():
            children.append(child)
            children.extend(child.get_all_child_folders())
        return children


class Annotation(AbstractResource):
    """
    Universal annotation/document model for attaching files and notes.

    Core model that can be used across all apps to attach documents,
    files, images, and notes to any other model with proper access control.
    """

    ANNOTATION_TYPE_CHOICES = [
        ("text", "Text"),
        ("file", "File"),
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("sketch", "Sketch"),
        ("other", "Other"),
        ("checklist", "Checklist"),
        ("counter", "Counter"),
        ("table", "Table"),
        ("alignment", "Alignment"),
        ("calculator", "Calculator"),
        ("mcalculator", "Molarity Calculator"),
        ("randomization", "Randomization"),
        ("metadata", "Metadata"),
        ("booking", "Booking"),
    ]

    annotation = models.TextField(help_text="Text content or description of the annotation", default="")
    annotation_type = models.CharField(
        max_length=20, choices=ANNOTATION_TYPE_CHOICES, default="text", help_text="Type of annotation content"
    )
    file = models.FileField(blank=True, null=True, upload_to="annotations/", help_text="Optional file attachment")
    folder = models.ForeignKey(
        AnnotationFolder,
        on_delete=models.CASCADE,
        related_name="annotations",
        blank=True,
        null=True,
        help_text="Folder containing this annotation",
    )

    # Transcription and translation features
    transcribed = models.BooleanField(default=False, help_text="Whether audio/video has been transcribed")
    transcription = models.TextField(blank=True, null=True, help_text="Text transcription of audio/video content")
    language = models.CharField(max_length=10, blank=True, null=True, help_text="Language code of the content")
    translation = models.TextField(blank=True, null=True, help_text="Translation of the content")

    # Status flags
    scratched = models.BooleanField(default=False, help_text="Whether this annotation is marked as deleted/scratched")

    # Remote sync fields
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "RemoteHost", on_delete=models.CASCADE, related_name="annotations", blank=True, null=True
    )

    class Meta:
        app_label = "ccc"
        ordering = ["-created_at"]

    def __str__(self):
        if self.annotation:
            preview = self.annotation[:50]
            if len(self.annotation) > 50:
                preview += "..."
            return f"{self.get_annotation_type_display()}: {preview}"
        return f"{self.get_annotation_type_display()}: [File]"

    def _check_parent_resource_permission(self, user, permission_method):
        """
        Check permissions on parent resources via junction models.

        If this annotation is attached to a parent resource (Instrument, StoredReagent,
        Session, etc.) via a junction model, delegate permission checking to the parent
        resource to prevent unauthorized access bypassing parent permissions.

        Args:
            user: User to check permissions for
            permission_method: Name of permission method to call ('can_view', 'can_edit', 'can_delete')

        Returns:
            bool or None: True/False if attached to parent resource, None if standalone
        """
        if hasattr(self, "instrument_attachments") and self.instrument_attachments.exists():
            instrument_annotation = self.instrument_attachments.first()
            return getattr(instrument_annotation, permission_method)(user)

        if hasattr(self, "stored_reagent_attachments") and self.stored_reagent_attachments.exists():
            reagent_annotation = self.stored_reagent_attachments.first()
            return getattr(reagent_annotation, permission_method)(user)

        if hasattr(self, "maintenance_log_attachments") and self.maintenance_log_attachments.exists():
            maintenance_annotation = self.maintenance_log_attachments.first()
            return getattr(maintenance_annotation, permission_method)(user)

        if hasattr(self, "session_attachments") and self.session_attachments.exists():
            session_annotation = self.session_attachments.first()
            return getattr(session_annotation, permission_method)(user)

        if hasattr(self, "step_attachments") and self.step_attachments.exists():
            step_annotation = self.step_attachments.first()
            return getattr(step_annotation, permission_method)(user)

        return None

    def can_view(self, user):
        """
        Check if user can view this annotation.

        If annotation is attached to a parent resource (Instrument, StoredReagent,
        Session, etc.), permissions are inherited from the parent resource to prevent
        unauthorized access via the base annotation endpoint.

        Args:
            user: User to check permissions for

        Returns:
            bool: True if user can view, False otherwise
        """
        parent_permission = self._check_parent_resource_permission(user, "can_view")
        if parent_permission is not None:
            return parent_permission

        return super().can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this annotation.

        If annotation is attached to a parent resource, permissions are inherited
        from the parent resource to prevent unauthorized modifications.

        Args:
            user: User to check permissions for

        Returns:
            bool: True if user can edit, False otherwise
        """
        parent_permission = self._check_parent_resource_permission(user, "can_edit")
        if parent_permission is not None:
            return parent_permission

        return super().can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this annotation.

        If annotation is attached to a parent resource, permissions are inherited
        from the parent resource to prevent unauthorized deletions.

        Args:
            user: User to check permissions for

        Returns:
            bool: True if user can delete, False otherwise
        """
        parent_permission = self._check_parent_resource_permission(user, "can_delete")
        if parent_permission is not None:
            return parent_permission

        return super().can_delete(user)

    def generate_download_token(self, user):
        """
        Generate a signed download token for this annotation.

        Args:
            user: The user requesting the download

        Returns:
            str: Signed token containing annotation ID, user ID, and file path
        """
        from django.core.signing import TimestampSigner

        signer = TimestampSigner()
        payload = f"{self.id}:{user.id}:{self.file.name}"
        return signer.sign(payload)

    @classmethod
    def verify_download_token(cls, signed_token):
        """
        Verify a signed download token and return the Annotation if valid.

        Args:
            signed_token: The signed token to verify

        Returns:
            Tuple of (Annotation instance, User instance) if valid, (None, None) otherwise
        """
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

        signer = TimestampSigner()

        try:
            max_age = getattr(settings, "ANNOTATION_DOWNLOAD_TOKEN_MAX_AGE", 600)
            payload = signer.unsign(signed_token, max_age=max_age)

            annotation_id, user_id, file_path = payload.split(":", 2)

            User = get_user_model()
            user = User.objects.get(id=user_id)

            annotation = cls.objects.get(id=annotation_id, file=file_path)

            return annotation, user

        except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist, cls.DoesNotExist):
            return None, None


# Import the AnnotationFileUpload model so Django can detect it for migrations
from .annotation_chunked_upload import AnnotationFileUpload  # noqa: F401
