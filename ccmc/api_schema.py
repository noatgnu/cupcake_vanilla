"""Request and response shapes of the CUPCAKE Mint Chocolate custom actions, for the OpenAPI schema."""

from rest_framework import serializers

from .serializers import ThreadParticipantSerializer


class NotificationsMarkedReadSerializer(serializers.Serializer):
    """How many notifications were marked as read."""

    success = serializers.BooleanField()
    message = serializers.CharField()


class NotificationStatsSerializer(serializers.Serializer):
    """Counts of the user's notifications."""

    total = serializers.IntegerField()
    unread = serializers.IntegerField()
    by_type = serializers.DictField(child=serializers.IntegerField(), help_text="Counts keyed by type label")
    by_priority = serializers.DictField(child=serializers.IntegerField(), help_text="Counts keyed by priority label")


class ThreadUsernameSerializer(serializers.Serializer):
    """A user, by username."""

    username = serializers.CharField()


class ParticipantAddedSerializer(serializers.Serializer):
    """The participant that was added."""

    message = serializers.CharField()
    participant = ThreadParticipantSerializer()


class ThreadParticipantPageSerializer(serializers.Serializer):
    """A page of thread participants."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ThreadParticipantSerializer(many=True)


class ThreadArchivedSerializer(serializers.Serializer):
    """The thread's new archived state."""

    message = serializers.CharField()
    is_archived = serializers.BooleanField()


class ParticipantSettingsSerializer(serializers.Serializer):
    """Notification settings of the user's own participation."""

    notifications_enabled = serializers.BooleanField(required=False)


class ThreadReadSerializer(serializers.Serializer):
    """When the thread was marked as read."""

    message = serializers.CharField()
    last_read_at = serializers.DateTimeField()


class WebRTCSessionEndedSerializer(serializers.Serializer):
    """The session that was ended."""

    message = serializers.CharField()
    session_id = serializers.UUIDField()
