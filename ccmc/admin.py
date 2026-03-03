from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import Message, MessageThread, Notification, ThreadParticipant, WebRTCPeer, WebRTCSession, WebRTCSignal


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "recipient",
        "sender",
        "notification_type",
        "priority_display",
        "delivery_status_display",
        "read_at",
        "created_at",
    ]
    list_filter = [
        "notification_type",
        "priority",
        "delivery_status",
        "created_at",
    ]
    search_fields = ["title", "message", "recipient__username", "sender__username"]
    readonly_fields = ["created_at", "updated_at", "read_at"]
    autocomplete_fields = ["recipient", "sender"]
    date_hierarchy = "created_at"
    list_per_page = 50

    fieldsets = (
        (
            "Notification Details",
            {
                "fields": (
                    "title",
                    "message",
                    "notification_type",
                    "priority",
                )
            },
        ),
        (
            "Recipients",
            {
                "fields": (
                    "recipient",
                    "sender",
                )
            },
        ),
        (
            "Delivery Status",
            {
                "fields": (
                    "delivery_status",
                    "read_at",
                )
            },
        ),
        (
            "Related Object",
            {
                "fields": (
                    "content_type",
                    "object_id",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "metadata",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def priority_display(self, obj):
        """Display priority with color coding."""
        colors = {"high": "red", "medium": "orange", "low": "gray", "normal": "blue"}
        color = colors.get(obj.priority, "gray")
        return format_html('<span style="color:{};">{}</span>', color, obj.get_priority_display())

    priority_display.short_description = "Priority"
    priority_display.admin_order_field = "priority"

    def delivery_status_display(self, obj):
        """Display delivery status with icons."""
        icons = {"pending": "⏳", "delivered": "📨", "read": "✅", "failed": "❌"}
        icon = icons.get(obj.delivery_status, "")
        return f"{icon} {obj.get_delivery_status_display()}"

    delivery_status_display.short_description = "Status"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("recipient", "sender", "content_type")

    actions = ["mark_as_read", "mark_as_delivered", "resend_notifications"]

    def mark_as_read(self, request, queryset):
        """Mark selected notifications as read."""
        updated = queryset.filter(read_at__isnull=True).update(read_at=timezone.now(), delivery_status="read")
        self.message_user(request, f"Marked {updated} notification(s) as read.")

    mark_as_read.short_description = "Mark as read"

    def mark_as_delivered(self, request, queryset):
        """Mark selected notifications as delivered."""
        updated = queryset.filter(delivery_status="pending").update(delivery_status="delivered")
        self.message_user(request, f"Marked {updated} notification(s) as delivered.")

    mark_as_delivered.short_description = "Mark as delivered"

    def resend_notifications(self, request, queryset):
        """Reset failed notifications to pending."""
        updated = queryset.filter(delivery_status="failed").update(delivery_status="pending")
        self.message_user(request, f"Reset {updated} failed notification(s) to pending.")

    resend_notifications.short_description = "Resend failed notifications"


@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "creator",
        "participants_count",
        "messages_count",
        "is_private",
        "is_archived",
        "last_message_at",
        "created_at",
    ]
    list_filter = [
        "is_private",
        "is_archived",
        "created_at",
        "last_message_at",
    ]
    search_fields = ["title", "description", "creator__username"]
    readonly_fields = ["created_at", "updated_at", "last_message_at"]
    autocomplete_fields = ["creator"]
    date_hierarchy = "created_at"
    list_per_page = 50

    fieldsets = (
        (
            "Thread Information",
            {
                "fields": (
                    "title",
                    "description",
                    "creator",
                )
            },
        ),
        (
            "Settings",
            {
                "fields": (
                    "is_private",
                    "is_archived",
                )
            },
        ),
        (
            "Related Object",
            {
                "fields": (
                    "content_type",
                    "object_id",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "last_message_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def participants_count(self, obj):
        """Display count of participants."""
        return obj.participants.count()

    participants_count.short_description = "Participants"

    def messages_count(self, obj):
        """Display count of messages."""
        return obj.messages.count()

    messages_count.short_description = "Messages"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("creator", "content_type")

    actions = ["archive_threads", "unarchive_threads"]

    def archive_threads(self, request, queryset):
        """Archive selected threads."""
        updated = queryset.update(is_archived=True)
        self.message_user(request, f"Archived {updated} thread(s).")

    archive_threads.short_description = "Archive selected threads"

    def unarchive_threads(self, request, queryset):
        """Unarchive selected threads."""
        updated = queryset.update(is_archived=False)
        self.message_user(request, f"Unarchived {updated} thread(s).")

    unarchive_threads.short_description = "Unarchive selected threads"


@admin.register(ThreadParticipant)
class ThreadParticipantAdmin(admin.ModelAdmin):
    list_display = [
        "thread",
        "user",
        "is_moderator",
        "notifications_enabled",
        "joined_at",
        "last_read_at",
    ]
    list_filter = [
        "is_moderator",
        "notifications_enabled",
        "joined_at",
    ]
    search_fields = ["thread__title", "user__username"]
    readonly_fields = ["joined_at", "last_read_at"]
    autocomplete_fields = ["thread", "user"]
    date_hierarchy = "joined_at"
    list_per_page = 50

    fieldsets = (
        (
            "Participant Information",
            {
                "fields": (
                    "thread",
                    "user",
                )
            },
        ),
        (
            "Settings",
            {
                "fields": (
                    "is_moderator",
                    "notifications_enabled",
                )
            },
        ),
        (
            "Activity",
            {
                "fields": (
                    "joined_at",
                    "last_read_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("thread", "user")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "thread",
        "sender",
        "content_preview",
        "message_type",
        "is_edited",
        "is_deleted",
        "created_at",
    ]
    list_filter = [
        "message_type",
        "is_edited",
        "is_deleted",
        "created_at",
    ]
    search_fields = ["content", "sender__username", "thread__title"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["thread", "sender", "reply_to"]
    date_hierarchy = "created_at"
    list_per_page = 100

    fieldsets = (
        (
            "Message Details",
            {
                "fields": (
                    "thread",
                    "sender",
                    "content",
                    "message_type",
                )
            },
        ),
        (
            "Reply Thread",
            {
                "fields": ("reply_to",),
                "classes": ("collapse",),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_edited",
                    "is_deleted",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "metadata",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def content_preview(self, obj):
        """Display truncated content preview."""
        if obj.content:
            return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
        return "-"

    content_preview.short_description = "Content"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("thread", "sender", "reply_to")

    actions = ["soft_delete_messages", "restore_messages"]

    def soft_delete_messages(self, request, queryset):
        """Soft delete selected messages."""
        updated = queryset.update(is_deleted=True)
        self.message_user(request, f"Soft deleted {updated} message(s).")

    soft_delete_messages.short_description = "Soft delete selected messages"

    def restore_messages(self, request, queryset):
        """Restore soft-deleted messages."""
        updated = queryset.filter(is_deleted=True).update(is_deleted=False)
        self.message_user(request, f"Restored {updated} message(s).")

    restore_messages.short_description = "Restore deleted messages"


@admin.register(WebRTCSession)
class WebRTCSessionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "session_name",
        "session_type",
        "session_status_display",
        "initiated_by",
        "peers_count",
        "duration",
        "started_at",
    ]
    list_filter = [
        "session_type",
        "session_status",
        "started_at",
    ]
    search_fields = ["initiated_by__username", "session_name"]
    readonly_fields = ["started_at", "ended_at", "created_at", "updated_at"]
    autocomplete_fields = ["initiated_by"]
    date_hierarchy = "started_at"
    list_per_page = 50

    fieldsets = (
        (
            "Session Information",
            {
                "fields": (
                    "session_name",
                    "session_type",
                    "session_status",
                    "initiated_by",
                )
            },
        ),
        (
            "Timing",
            {
                "fields": (
                    "started_at",
                    "ended_at",
                )
            },
        ),
        (
            "Configuration",
            {
                "fields": ("configuration",),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def session_status_display(self, obj):
        """Display session status with color coding."""
        colors = {"active": "green", "ended": "gray", "failed": "red", "pending": "orange"}
        color = colors.get(obj.session_status, "gray")
        return format_html('<span style="color:{};">{}</span>', color, obj.get_session_status_display())

    session_status_display.short_description = "Status"

    def peers_count(self, obj):
        """Display count of peers in session."""
        return obj.peers.count()

    peers_count.short_description = "Peers"

    def duration(self, obj):
        """Display session duration."""
        if obj.started_at and obj.ended_at:
            delta = obj.ended_at - obj.started_at
            minutes = delta.total_seconds() / 60
            return f"{minutes:.0f}m"
        elif obj.started_at and obj.session_status == "active":
            delta = timezone.now() - obj.started_at
            minutes = delta.total_seconds() / 60
            return f"{minutes:.0f}m (active)"
        return "-"

    duration.short_description = "Duration"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("initiated_by")

    actions = ["end_sessions"]

    def end_sessions(self, request, queryset):
        """End selected active sessions."""
        updated = queryset.filter(session_status="active").update(session_status="ended", ended_at=timezone.now())
        self.message_user(request, f"Ended {updated} session(s).")

    end_sessions.short_description = "End selected sessions"


@admin.register(WebRTCPeer)
class WebRTCPeerAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "session",
        "user",
        "connection_state_display",
        "joined_at",
    ]
    list_filter = [
        "connection_state",
        "joined_at",
    ]
    search_fields = ["user__username", "session__session_name"]
    readonly_fields = ["joined_at"]
    autocomplete_fields = ["session", "user"]
    date_hierarchy = "joined_at"
    list_per_page = 50

    fieldsets = (
        (
            "Peer Information",
            {
                "fields": (
                    "session",
                    "user",
                    "connection_state",
                )
            },
        ),
        (
            "Connection",
            {
                "fields": ("joined_at",),
                "classes": ("collapse",),
            },
        ),
    )

    def connection_state_display(self, obj):
        """Display connection state with color coding."""
        colors = {"connected": "green", "disconnected": "red", "connecting": "orange", "failed": "red"}
        color = colors.get(obj.connection_state, "gray")
        return format_html('<span style="color:{};">{}</span>', color, obj.get_connection_state_display())

    connection_state_display.short_description = "State"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("session", "user")


@admin.register(WebRTCSignal)
class WebRTCSignalAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "session",
        "from_peer",
        "to_peer",
        "signal_type",
        "created_at",
    ]
    list_filter = [
        "signal_type",
        "created_at",
    ]
    search_fields = ["from_peer__user__username", "to_peer__user__username", "session__session_name"]
    readonly_fields = ["created_at"]
    raw_id_fields = ["session", "from_peer", "to_peer"]
    date_hierarchy = "created_at"
    list_per_page = 100

    fieldsets = (
        (
            "Signal Information",
            {
                "fields": (
                    "session",
                    "from_peer",
                    "to_peer",
                    "signal_type",
                )
            },
        ),
        (
            "Signal Data",
            {
                "fields": ("signal_data",),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamp",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return (
            super()
            .get_queryset(request)
            .select_related("session", "from_peer", "from_peer__user", "to_peer", "to_peer__user")
        )

    actions = ["clear_old_signals"]

    def clear_old_signals(self, request, queryset):
        """Delete signals older than 24 hours."""
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=24)
        deleted, _ = queryset.filter(created_at__lt=cutoff).delete()
        self.message_user(request, f"Deleted {deleted} old signal(s).")

    clear_old_signals.short_description = "Clear signals older than 24h"
