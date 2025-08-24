"""
CUPCAKE Core (CCC) - Django Admin Configuration.

This module configures the Django admin interface for user management,
lab groups, and site administration functionality.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import AccountMergeRequest, LabGroup, LabGroupInvitation, ResourcePermission, SiteConfig, UserOrcidProfile


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    """
    Admin interface for site configuration settings.
    Provides a clean interface for managing global site settings.
    """

    list_display = ["site_name", "allow_user_registration", "enable_orcid_login", "updated_at", "updated_by"]
    list_filter = ["allow_user_registration", "enable_orcid_login", "show_powered_by"]
    search_fields = ["site_name"]
    readonly_fields = ["created_at", "updated_at", "updated_by"]

    fieldsets = (
        ("Site Branding", {"fields": ("site_name", "logo_url", "logo_image", "primary_color", "show_powered_by")}),
        ("Authentication Settings", {"fields": ("allow_user_registration", "enable_orcid_login")}),
        ("Audit Information", {"fields": ("created_at", "updated_at", "updated_by"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        """Track who updated the configuration."""
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(LabGroup)
class LabGroupAdmin(admin.ModelAdmin):
    """
    Admin interface for lab group management.
    Allows administrators to manage lab groups and their memberships.
    """

    list_display = ["name", "creator", "member_count", "is_active", "allow_member_invites", "created_at"]
    list_filter = ["is_active", "allow_member_invites", "created_at"]
    search_fields = ["name", "description", "creator__username", "creator__first_name", "creator__last_name"]
    filter_horizontal = ["members"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "creator")}),
        ("Membership", {"fields": ("members",)}),
        ("Settings", {"fields": ("is_active", "allow_member_invites")}),
        ("Audit Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def member_count(self, obj):
        """Display the number of members in the lab group."""
        return obj.members.count()

    member_count.short_description = "Members"


@admin.register(LabGroupInvitation)
class LabGroupInvitationAdmin(admin.ModelAdmin):
    """
    Admin interface for lab group invitations.
    Allows administrators to monitor and manage lab group invitations.
    """

    list_display = ["lab_group", "invited_email", "inviter", "status", "created_at", "expires_at"]
    list_filter = ["status", "created_at", "expires_at"]
    search_fields = ["invited_email", "lab_group__name", "inviter__username"]
    readonly_fields = ["invitation_token", "created_at", "updated_at", "responded_at"]

    fieldsets = (
        ("Invitation Details", {"fields": ("lab_group", "inviter", "invited_email", "invited_user")}),
        ("Status", {"fields": ("status", "message", "responded_at")}),
        ("Security", {"fields": ("invitation_token", "expires_at"), "classes": ("collapse",)}),
        ("Audit Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        """Make certain fields readonly after creation."""
        readonly = list(self.readonly_fields)
        if obj:  # Editing an existing object
            readonly.extend(["lab_group", "inviter", "invited_email"])
        return readonly


@admin.register(UserOrcidProfile)
class UserOrcidProfileAdmin(admin.ModelAdmin):
    """
    Admin interface for user ORCID profiles.
    Manages ORCID account linkages and verification status.
    """

    list_display = ["user", "orcid_id", "orcid_name", "verified", "linked_at"]
    list_filter = ["verified", "linked_at"]
    search_fields = ["user__username", "user__email", "orcid_id", "orcid_name"]
    readonly_fields = ["linked_at", "token_expires_at"]

    fieldsets = (
        ("User Link", {"fields": ("user",)}),
        ("ORCID Information", {"fields": ("orcid_id", "orcid_name", "orcid_email", "verified")}),
        (
            "OAuth Tokens",
            {
                "fields": ("access_token", "refresh_token", "token_expires_at"),
                "classes": ("collapse",),
                "description": "OAuth tokens for API access (encrypted)",
            },
        ),
        ("Audit Information", {"fields": ("linked_at",), "classes": ("collapse",)}),
    )


@admin.register(AccountMergeRequest)
class AccountMergeRequestAdmin(admin.ModelAdmin):
    """
    Admin interface for account merge requests.
    Allows administrators to review and process account merge requests.
    """

    list_display = ["primary_user", "duplicate_user", "requested_by", "status", "created_at", "reviewed_by"]
    list_filter = ["status", "created_at", "updated_at"]
    search_fields = [
        "primary_user__username",
        "primary_user__email",
        "duplicate_user__username",
        "duplicate_user__email",
        "requested_by__username",
    ]
    readonly_fields = ["created_at", "updated_at", "completed_at"]

    fieldsets = (
        ("Merge Request", {"fields": ("primary_user", "duplicate_user", "requested_by", "reason")}),
        ("Review", {"fields": ("status", "reviewed_by", "admin_notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "completed_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        """Make merge details readonly after creation."""
        readonly = list(self.readonly_fields)
        if obj:  # Editing an existing object
            readonly.extend(["primary_user", "duplicate_user", "requested_by", "reason"])
        return readonly

    def save_model(self, request, obj, form, change):
        """Track who reviewed the merge request."""
        if change and "status" in form.changed_data:
            obj.reviewed_by = request.user
            if obj.status == "completed":
                from django.utils import timezone

                obj.completed_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(ResourcePermission)
class ResourcePermissionAdmin(admin.ModelAdmin):
    """
    Admin interface for resource permissions.
    Manages explicit permissions for resources beyond default ownership/lab group access.
    """

    list_display = ["user", "resource_type", "resource_id", "role", "granted_by", "granted_at"]
    list_filter = ["role", "resource_content_type", "granted_at"]
    search_fields = ["user__username", "user__email", "granted_by__username"]
    readonly_fields = ["granted_at"]

    fieldsets = (
        ("Permission Details", {"fields": ("user", "role")}),
        ("Resource", {"fields": ("resource_content_type", "resource_object_id")}),
        ("Grant Information", {"fields": ("granted_by", "granted_at"), "classes": ("collapse",)}),
    )

    def resource_type(self, obj):
        """Display the resource content type."""
        return obj.resource_content_type.name if obj.resource_content_type else ""

    resource_type.short_description = "Resource Type"

    def resource_id(self, obj):
        """Display the resource object ID."""
        return obj.resource_object_id

    resource_id.short_description = "Resource ID"


# Extend the default User admin to show ORCID information
class UserOrcidInline(admin.StackedInline):
    """Inline admin for ORCID profiles within User admin."""

    model = UserOrcidProfile
    extra = 0
    readonly_fields = ["linked_at", "token_expires_at"]
    classes = ["collapse"]


class CustomUserAdmin(BaseUserAdmin):
    """
    Extended User admin that includes ORCID profile information and better organization of user data.
    """

    inlines = [UserOrcidInline]


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
