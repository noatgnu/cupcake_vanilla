"""
CUPCAKE Core (CCC) - Django Admin Configuration.

This module configures the Django admin interface for user management,
lab groups, and site administration functionality.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    AccountMergeRequest,
    Annotation,
    AnnotationFolder,
    AsyncTaskStatus,
    LabGroup,
    LabGroupInvitation,
    LabGroupPermission,
    RemoteHost,
    ResourcePermission,
    SiteConfig,
    TaskResult,
    UserOrcidProfile,
)


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    """
    Admin interface for site configuration settings.
    Provides a clean interface for managing global site settings.
    """

    list_display = [
        "site_name",
        "allow_user_registration",
        "enable_orcid_login",
        "updated_at",
        "updated_by",
    ]
    list_filter = [
        "allow_user_registration",
        "enable_orcid_login",
        "show_powered_by",
    ]
    search_fields = ["site_name"]
    readonly_fields = ["created_at", "updated_at", "updated_by"]

    fieldsets = (
        (
            "Site Branding",
            {
                "fields": (
                    "site_name",
                    "logo_url",
                    "logo_image",
                    "primary_color",
                    "show_powered_by",
                )
            },
        ),
        (
            "Authentication Settings",
            {"fields": ("allow_user_registration", "enable_orcid_login")},
        ),
        (
            "Booking Configuration",
            {"fields": ("booking_deletion_window_minutes",)},
        ),
        (
            "Transcription Configuration",
            {
                "fields": ("whisper_cpp_model",),
                "description": (
                    "Configure default Whisper.cpp model for audio/video transcription. "
                    "Available models: ggml-tiny.bin (fastest, least accurate), ggml-base.bin, "
                    "ggml-small.bin, ggml-medium.bin (balanced), ggml-large-v3.bin (slowest, most accurate)."
                ),
            },
        ),
        (
            "UI Feature Visibility",
            {
                "fields": ("ui_features",),
                "description": (
                    "Configure which UI features are visible to users. "
                    'Example: {"show_protocols": false, "show_instruments": true}. '
                    "Available features: show_metadata_tables, show_instruments, show_sessions, "
                    "show_protocols, show_messages, show_notifications, show_storage, show_webrtc, show_billing. "
                    "You can add custom feature flags as needed."
                ),
            },
        ),
        (
            "Audit Information",
            {
                "fields": ("created_at", "updated_at", "updated_by"),
                "classes": ("collapse",),
            },
        ),
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

    list_display = [
        "name",
        "creator",
        "member_count",
        "is_active",
        "allow_member_invites",
        "created_at",
    ]
    list_filter = ["is_active", "allow_member_invites", "created_at"]
    search_fields = [
        "name",
        "description",
        "creator__username",
        "creator__first_name",
        "creator__last_name",
    ]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["creator", "members"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "creator")}),
        ("Membership", {"fields": ("members",)}),
        ("Settings", {"fields": ("is_active", "allow_member_invites")}),
        (
            "Audit Information",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
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

    list_display = [
        "lab_group",
        "invited_email",
        "inviter",
        "status",
        "created_at",
        "expires_at",
    ]
    list_filter = ["status", "created_at", "expires_at"]
    search_fields = ["invited_email", "lab_group__name", "inviter__username"]
    readonly_fields = [
        "invitation_token",
        "created_at",
        "updated_at",
        "responded_at",
    ]

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

    list_display = BaseUserAdmin.list_display + ("last_login", "date_joined")
    inlines = [UserOrcidInline]


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(RemoteHost)
class RemoteHostAdmin(admin.ModelAdmin):
    """
    Admin interface for remote host configuration.
    Manages distributed CUPCAKE deployment hosts.
    """

    list_display = ["host_name", "host_protocol", "host_port", "host_description", "created_at"]
    list_filter = ["host_protocol", "created_at"]
    search_fields = ["host_name", "host_description"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Host Configuration", {"fields": ("host_name", "host_protocol", "host_port", "host_description")}),
        (
            "Security",
            {
                "fields": ("host_token",),
                "classes": ("collapse",),
                "description": "Authentication token for secure communication",
            },
        ),
        ("Audit Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(AnnotationFolder)
class AnnotationFolderAdmin(admin.ModelAdmin):
    """
    Admin interface for annotation folders.
    Manages hierarchical folder organization for annotations.
    """

    list_display = ["folder_name", "owner", "parent_folder", "is_shared_document_folder", "is_active", "created_at"]
    list_filter = ["is_shared_document_folder", "is_active", "is_locked", "visibility", "created_at"]
    search_fields = ["folder_name", "owner__username", "owner__first_name", "owner__last_name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["owner", "parent_folder", "lab_group"]

    fieldsets = (
        ("Folder Information", {"fields": ("folder_name", "parent_folder", "is_shared_document_folder")}),
        ("Ownership & Access", {"fields": ("owner", "lab_group", "visibility")}),
        ("Status", {"fields": ("is_active", "is_locked")}),
        ("Audit Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        """Include select_related for better performance."""
        return super().get_queryset(request).select_related("owner", "parent_folder", "lab_group")


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    """
    Admin interface for annotations.
    Manages user annotations with file uploads and metadata.
    """

    list_display = [
        "annotation_preview",
        "annotation_type",
        "owner",
        "folder",
        "transcribed",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "annotation_type",
        "transcribed",
        "scratched",
        "is_active",
        "is_locked",
        "visibility",
        "language",
        "created_at",
    ]
    search_fields = [
        "annotation",
        "transcription",
        "translation",
        "owner__username",
        "owner__first_name",
        "owner__last_name",
    ]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["owner", "folder", "lab_group"]

    fieldsets = (
        ("Annotation Content", {"fields": ("annotation", "annotation_type", "file")}),
        ("Organization", {"fields": ("folder",)}),
        (
            "Transcription & Translation",
            {"fields": ("transcribed", "transcription", "language", "translation"), "classes": ("collapse",)},
        ),
        ("Ownership & Access", {"fields": ("owner", "lab_group", "visibility")}),
        ("Status", {"fields": ("is_active", "is_locked", "scratched")}),
        ("Audit Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def annotation_preview(self, obj):
        """Show a preview of the annotation content."""
        if obj.annotation:
            return obj.annotation[:100] + "..." if len(obj.annotation) > 100 else obj.annotation
        return "(No content)"

    annotation_preview.short_description = "Content Preview"

    def get_queryset(self, request):
        """Include select_related for better performance."""
        return super().get_queryset(request).select_related("owner", "folder", "lab_group")


@admin.register(AsyncTaskStatus)
class AsyncTaskStatusAdmin(admin.ModelAdmin):
    """Admin interface for async task monitoring."""

    list_display = [
        "id_short",
        "task_type",
        "status",
        "user",
        "progress_display",
        "created_at",
        "completed_at",
    ]
    list_filter = ["task_type", "status", "created_at", "completed_at"]
    search_fields = ["id", "user__username", "user__email", "error_message"]
    readonly_fields = [
        "id",
        "rq_job_id",
        "created_at",
        "started_at",
        "completed_at",
        "error_message",
        "result_preview",
    ]
    date_hierarchy = "created_at"
    list_per_page = 50
    autocomplete_fields = ["user"]

    fieldsets = (
        ("Task Information", {"fields": ("id", "task_type", "status", "user", "rq_job_id")}),
        ("Progress", {"fields": ("progress", "progress_message")}),
        ("Result", {"fields": ("result_preview", "error_message"), "classes": ("collapse",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "started_at", "completed_at"), "classes": ("collapse",)},
        ),
    )

    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8] + "..."

    id_short.short_description = "Task ID"

    def progress_display(self, obj):
        """Display progress as percentage bar."""
        if obj.progress is not None:
            color = "green" if obj.status == "SUCCESS" else "blue" if obj.status == "STARTED" else "gray"
            return format_html(
                '<div style="width:100px;background:#eee;border-radius:3px;">'
                '<div style="width:{}%;background:{};height:15px;border-radius:3px;"></div>'
                "</div> {}%",
                obj.progress,
                color,
                obj.progress,
            )
        return "-"

    progress_display.short_description = "Progress"

    def result_preview(self, obj):
        """Display result data preview."""
        if obj.result_data:
            import json

            try:
                formatted = json.dumps(obj.result_data, indent=2)[:500]
                return format_html("<pre style='max-height:200px;overflow:auto;'>{}</pre>", formatted)
            except Exception:
                return str(obj.result_data)[:500]
        return "No result data"

    result_preview.short_description = "Result Data"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("user", "metadata_table")

    actions = ["cancel_tasks", "retry_failed_tasks", "clear_completed_tasks"]

    def cancel_tasks(self, request, queryset):
        """Cancel selected queued/started tasks."""
        from django_rq import get_queue
        from rq.job import Job

        cancelled = 0
        failed = 0

        for task in queryset.filter(status__in=["QUEUED", "STARTED"]):
            try:
                if task.rq_job_id:
                    queue = get_queue("default")
                    try:
                        job = Job.fetch(task.rq_job_id, connection=queue.connection)
                        job.cancel()
                    except Exception:
                        pass
                task.status = "CANCELLED"
                task.save(update_fields=["status"])
                cancelled += 1
            except Exception:
                failed += 1

        msg = f"Cancelled {cancelled} task(s)."
        if failed:
            msg += f" Failed to cancel {failed} task(s)."
        self.message_user(request, msg)

    cancel_tasks.short_description = "Cancel selected tasks"

    def retry_failed_tasks(self, request, queryset):
        """Reset failed tasks to queued status."""
        reset = queryset.filter(status="FAILURE").update(status="QUEUED", error_message="")
        self.message_user(request, f"Reset {reset} failed task(s) to queued.")

    retry_failed_tasks.short_description = "Retry failed tasks"

    def clear_completed_tasks(self, request, queryset):
        """Delete completed tasks older than 7 days."""
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=7)
        deleted, _ = queryset.filter(status="SUCCESS", completed_at__lt=cutoff).delete()
        self.message_user(request, f"Deleted {deleted} old completed task(s).")

    clear_completed_tasks.short_description = "Clear old completed tasks (7+ days)"


@admin.register(TaskResult)
class TaskResultAdmin(admin.ModelAdmin):
    """Admin interface for task result files."""

    list_display = ["id_short", "task", "file_name", "file_size_display", "created_at", "expires_at"]
    list_filter = ["created_at", "expires_at"]
    search_fields = ["task__id", "file_name"]
    readonly_fields = ["id", "created_at", "file_size"]
    date_hierarchy = "created_at"
    list_per_page = 50

    fieldsets = (
        ("Result Information", {"fields": ("id", "task", "file_name")}),
        ("File", {"fields": ("result_file", "file_size")}),
        ("Expiration", {"fields": ("expires_at",)}),
        ("Timestamps", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8] + "..."

    id_short.short_description = "Result ID"

    def file_size_display(self, obj):
        """Display file size in human-readable format."""
        if obj.file_size:
            if obj.file_size < 1024:
                return f"{obj.file_size} B"
            elif obj.file_size < 1024 * 1024:
                return f"{obj.file_size / 1024:.1f} KB"
            else:
                return f"{obj.file_size / (1024 * 1024):.1f} MB"
        return "-"

    file_size_display.short_description = "File Size"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("task", "task__user")

    actions = ["delete_expired"]

    def delete_expired(self, request, queryset):
        """Delete expired task results."""
        deleted, _ = queryset.filter(expires_at__lt=timezone.now()).delete()
        self.message_user(request, f"Deleted {deleted} expired result(s).")

    delete_expired.short_description = "Delete expired results"


@admin.register(LabGroupPermission)
class LabGroupPermissionAdmin(admin.ModelAdmin):
    """Admin interface for lab group permissions."""

    list_display = ["lab_group", "user", "can_view", "can_invite", "can_manage", "can_process_jobs", "created_at"]
    list_filter = ["can_view", "can_invite", "can_manage", "can_process_jobs", "created_at"]
    search_fields = ["lab_group__name", "user__username", "user__email"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["lab_group", "user"]

    fieldsets = (
        ("Permission Details", {"fields": ("lab_group", "user")}),
        ("Capabilities", {"fields": ("can_view", "can_invite", "can_manage", "can_process_jobs")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("lab_group", "user")
