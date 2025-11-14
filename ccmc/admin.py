from django.contrib import admin

from .models import Message, MessageThread, Notification, ThreadParticipant, WebRTCPeer, WebRTCSession, WebRTCSignal


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "recipient",
        "sender",
        "notification_type",
        "priority",
        "delivery_status",
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


@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "creator",
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
    date_hierarchy = "created_at"

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
    date_hierarchy = "joined_at"

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


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "thread",
        "sender",
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


@admin.register(WebRTCSession)
class WebRTCSessionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "session_type",
        "session_status",
        "initiated_by",
        "started_at",
        "ended_at",
    ]
    list_filter = [
        "session_type",
        "session_status",
        "started_at",
    ]
    search_fields = ["initiated_by__username", "session_name"]
    readonly_fields = ["started_at", "ended_at", "created_at", "updated_at"]
    date_hierarchy = "started_at"

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


@admin.register(WebRTCPeer)
class WebRTCPeerAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "session",
        "user",
        "connection_state",
        "joined_at",
    ]
    list_filter = [
        "connection_state",
        "joined_at",
    ]
    search_fields = ["user__username", "session__session_name"]
    readonly_fields = ["joined_at"]
    date_hierarchy = "joined_at"

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
