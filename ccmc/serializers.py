"""
Serializers for CUPCAKE Core Macaron Communication (CCMC) models.

Provides REST API serialization for messaging, notifications, and communication functionality.
"""

from django.contrib.auth import get_user_model

from rest_framework import serializers

from .models import Message, MessageThread, Notification, ThreadParticipant, WebRTCPeer, WebRTCSession

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Basic user serializer for nested relationships."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]
        read_only_fields = ["id", "username", "first_name", "last_name", "email"]


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""

    recipient_username = serializers.CharField(source="recipient.username", read_only=True)
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    sender_name = serializers.SerializerMethodField()
    recipient_name = serializers.SerializerMethodField()
    related_object_type = serializers.CharField(source="content_type.model", read_only=True)
    related_object_app = serializers.CharField(source="content_type.app_label", read_only=True)
    is_read = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "notification_type",
            "priority",
            "recipient",
            "recipient_username",
            "recipient_name",
            "sender",
            "sender_username",
            "sender_name",
            "delivery_status",
            "sent_at",
            "read_at",
            "data",
            "expires_at",
            "created_at",
            "updated_at",
            "related_object_type",
            "related_object_app",
            "object_id",
            "is_read",
            "is_expired",
        ]
        read_only_fields = [
            "id",
            "sent_at",
            "read_at",
            "created_at",
            "updated_at",
            "recipient_username",
            "sender_username",
            "recipient_name",
            "sender_name",
            "related_object_type",
            "related_object_app",
            "is_read",
            "is_expired",
        ]

    def get_sender_name(self, obj):
        """Get full name of sender."""
        if obj.sender:
            return f"{obj.sender.first_name} {obj.sender.last_name}".strip() or obj.sender.username
        return None

    def get_recipient_name(self, obj):
        """Get full name of recipient."""
        return f"{obj.recipient.first_name} {obj.recipient.last_name}".strip() or obj.recipient.username

    def get_is_read(self, obj):
        """Check if notification has been read."""
        return bool(obj.read_at)

    def get_is_expired(self, obj):
        """Check if notification has expired."""
        return obj.is_expired()


class NotificationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating notifications."""

    class Meta:
        model = Notification
        fields = [
            "title",
            "message",
            "notification_type",
            "priority",
            "recipient",
            "data",
            "expires_at",
            "content_type",
            "object_id",
        ]

    def validate_recipient(self, value):
        """Ensure recipient exists and is active."""
        if not value.is_active:
            raise serializers.ValidationError("Cannot send notifications to inactive users.")
        return value


class ThreadParticipantSerializer(serializers.ModelSerializer):
    """Serializer for ThreadParticipant model."""

    user_details = UserBasicSerializer(source="user", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ThreadParticipant
        fields = [
            "id",
            "user",
            "username",
            "user_details",
            "joined_at",
            "last_read_at",
            "is_moderator",
            "notifications_enabled",
        ]
        read_only_fields = ["id", "joined_at", "username", "user_details"]


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for Message model."""

    sender_details = UserBasicSerializer(source="sender", read_only=True)
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    reply_to_content = serializers.CharField(source="reply_to.content", read_only=True)
    reply_to_sender = serializers.CharField(source="reply_to.sender.username", read_only=True)
    annotations_count = serializers.IntegerField(source="annotations.count", read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "thread",
            "content",
            "message_type",
            "sender",
            "sender_username",
            "sender_details",
            "is_edited",
            "is_deleted",
            "reply_to",
            "reply_to_content",
            "reply_to_sender",
            "annotations_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sender",
            "sender_username",
            "sender_details",
            "reply_to_content",
            "reply_to_sender",
            "annotations_count",
            "created_at",
            "updated_at",
        ]


class MessageDetailSerializer(MessageSerializer):
    """Detailed serializer for Message with annotations."""

    annotations = serializers.SerializerMethodField()

    class Meta(MessageSerializer.Meta):
        fields = MessageSerializer.Meta.fields + ["annotations"]

    def get_annotations(self, obj):
        """Get annotation details."""
        return [
            {
                "id": annotation.id,
                "name": annotation.file.name if annotation.file else str(annotation),
                "annotation_type": annotation.annotation_type,
                "file_size": annotation.file.size if annotation.file else None,
                "created_at": annotation.created_at,
            }
            for annotation in obj.annotations.all()
        ]


class MessageThreadSerializer(serializers.ModelSerializer):
    """Serializer for MessageThread model."""

    creator_details = UserBasicSerializer(source="creator", read_only=True)
    creator_username = serializers.CharField(source="creator.username", read_only=True)
    participants_count = serializers.IntegerField(source="participants.count", read_only=True)
    messages_count = serializers.IntegerField(source="messages.count", read_only=True)
    participants_list = ThreadParticipantSerializer(source="threadparticipant_set", many=True, read_only=True)
    related_object_type = serializers.CharField(source="content_type.model", read_only=True)
    related_object_app = serializers.CharField(source="content_type.app_label", read_only=True)
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = [
            "id",
            "title",
            "description",
            "creator",
            "creator_username",
            "creator_details",
            "participants_count",
            "messages_count",
            "participants_list",
            "related_object_type",
            "related_object_app",
            "object_id",
            "is_private",
            "is_archived",
            "allow_external_participants",
            "created_at",
            "updated_at",
            "last_message_at",
            "latest_message",
        ]
        read_only_fields = [
            "id",
            "creator_username",
            "creator_details",
            "participants_count",
            "messages_count",
            "participants_list",
            "related_object_type",
            "related_object_app",
            "created_at",
            "updated_at",
            "last_message_at",
            "latest_message",
        ]

    def get_latest_message(self, obj):
        """Get the latest message in the thread."""
        latest = obj.messages.filter(is_deleted=False).order_by("-created_at").first()
        if latest:
            return {
                "id": latest.id,
                "content": latest.content[:100] + "..." if len(latest.content) > 100 else latest.content,
                "sender_username": latest.sender.username,
                "created_at": latest.created_at,
            }
        return None


class MessageThreadDetailSerializer(MessageThreadSerializer):
    """Detailed serializer for MessageThread with recent messages."""

    recent_messages = MessageSerializer(source="messages", many=True, read_only=True)
    annotations_count = serializers.IntegerField(source="annotations.count", read_only=True)

    class Meta(MessageThreadSerializer.Meta):
        fields = MessageThreadSerializer.Meta.fields + ["recent_messages", "annotations_count"]

    def to_representation(self, instance):
        """Limit recent messages to last 50."""
        data = super().to_representation(instance)
        if "recent_messages" in data:
            # Limit to 50 most recent messages
            data["recent_messages"] = data["recent_messages"][-50:]
        return data


class MessageThreadCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating message threads."""

    participant_usernames = serializers.ListField(
        child=serializers.CharField(max_length=150),
        write_only=True,
        required=False,
        help_text="List of usernames to add as participants",
    )

    class Meta:
        model = MessageThread
        fields = [
            "title",
            "description",
            "is_private",
            "allow_external_participants",
            "content_type",
            "object_id",
            "participant_usernames",
        ]

    def create(self, validated_data):
        """Create thread with participants."""
        participant_usernames = validated_data.pop("participant_usernames", [])

        # Set creator from request user
        validated_data["creator"] = self.context["request"].user

        thread = MessageThread.objects.create(**validated_data)

        # Add creator as participant and moderator
        ThreadParticipant.objects.create(thread=thread, user=thread.creator, is_moderator=True)

        # Add other participants
        for username in participant_usernames:
            try:
                user = User.objects.get(username=username, is_active=True)
                ThreadParticipant.objects.get_or_create(thread=thread, user=user, defaults={"is_moderator": False})
            except User.DoesNotExist:
                continue  # Skip invalid usernames

        return thread


class WebRTCPeerSerializer(serializers.ModelSerializer):
    user_details = UserBasicSerializer(source="user", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = WebRTCPeer
        fields = [
            "id",
            "session",
            "user",
            "username",
            "user_details",
            "channel_id",
            "peer_role",
            "connection_state",
            "has_video",
            "has_audio",
            "has_screen_share",
            "joined_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "username",
            "user_details",
            "channel_id",
            "joined_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]


class WebRTCSessionSerializer(serializers.ModelSerializer):
    initiated_by_username = serializers.CharField(source="initiated_by.username", read_only=True)
    initiated_by_details = UserBasicSerializer(source="initiated_by", read_only=True)
    participants_list = WebRTCPeerSerializer(source="webrtcpeer_set", many=True, read_only=True)
    participants_count = serializers.IntegerField(source="webrtcpeer_set.count", read_only=True)
    ccrv_session_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = WebRTCSession
        fields = [
            "id",
            "name",
            "is_default",
            "session_type",
            "session_status",
            "initiated_by",
            "initiated_by_username",
            "initiated_by_details",
            "participants_list",
            "participants_count",
            "ccrv_session_ids",
            "can_edit",
            "can_delete",
            "started_at",
            "ended_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_default",
            "initiated_by",
            "initiated_by_username",
            "initiated_by_details",
            "participants_list",
            "participants_count",
            "can_edit",
            "can_delete",
            "started_at",
            "ended_at",
            "created_at",
            "updated_at",
        ]

    def get_can_edit(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        user = request.user
        if user.is_superuser or obj.initiated_by == user:
            return True

        ccrv_sessions = obj.ccrv_sessions.all()
        if not ccrv_sessions.exists():
            return obj.initiated_by == user

        for ccrv_session in ccrv_sessions:
            if ccrv_session.can_edit(user):
                return True

        return False

    def get_can_delete(self, obj):
        return self.get_can_edit(obj)

    def create(self, validated_data):
        ccrv_session_ids = validated_data.pop("ccrv_session_ids", [])
        validated_data["initiated_by"] = self.context["request"].user

        webrtc_session = super().create(validated_data)

        if ccrv_session_ids:
            from ccrv.models import Session

            ccrv_sessions = Session.objects.filter(id__in=ccrv_session_ids)
            webrtc_session.ccrv_sessions.set(ccrv_sessions)

        return webrtc_session
