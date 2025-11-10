"""
ViewSets for CUPCAKE Core Macaron Communication (CCMC) models.

Provides REST API endpoints for messaging, notifications, and communication functionality.
"""

from django.db.models import Q
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    DeliveryStatus,
    Message,
    MessageThread,
    Notification,
    NotificationPriority,
    NotificationType,
    ThreadParticipant,
    WebRTCSession,
)
from .serializers import (
    MessageDetailSerializer,
    MessageSerializer,
    MessageThreadCreateSerializer,
    MessageThreadDetailSerializer,
    MessageThreadSerializer,
    NotificationCreateSerializer,
    NotificationSerializer,
    ThreadParticipantSerializer,
    WebRTCSessionSerializer,
)


class CCMCBasePermission(permissions.BasePermission):
    """Base permission class for CCMC models."""

    def has_permission(self, request, view):
        """All authenticated users can access CCMC endpoints."""
        return request.user and request.user.is_authenticated


class NotificationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing notifications."""

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["notification_type", "priority", "delivery_status", "sender"]
    search_fields = ["title", "message"]
    ordering_fields = ["created_at", "priority", "delivery_status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        """Use different serializers for create vs other actions."""
        if self.action == "create":
            return NotificationCreateSerializer
        return NotificationSerializer

    def get_queryset(self):
        """Filter notifications based on user permissions."""
        user = self.request.user

        # Staff users can see all notifications they sent or received
        if user.is_staff:
            return Notification.objects.filter(Q(recipient=user) | Q(sender=user)).select_related(
                "recipient", "sender", "content_type"
            )

        # Regular users can see notifications they sent or received
        return Notification.objects.filter(Q(recipient=user) | Q(sender=user)).select_related(
            "recipient", "sender", "content_type"
        )

    def perform_create(self, serializer):
        """Set sender when creating notification."""
        serializer.save(sender=self.request.user)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark notification as read."""
        notification = self.get_object()

        # Only recipient can mark as read
        if notification.recipient != request.user:
            return Response(
                {"error": "Only the recipient can mark this notification as read"}, status=status.HTTP_403_FORBIDDEN
            )

        notification.mark_as_read()

        serializer = self.get_serializer(notification)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def unread(self, request):
        """Get unread notifications for current user."""
        queryset = self.get_queryset().filter(
            delivery_status__in=[DeliveryStatus.PENDING, DeliveryStatus.SENT, DeliveryStatus.DELIVERED],
            read_at__isnull=True,
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark all unread notifications as read for current user."""
        updated_count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
            read_at=timezone.now(), delivery_status=DeliveryStatus.READ
        )

        return Response({"success": True, "message": f"Marked {updated_count} notifications as read"})

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Get notification statistics for current user."""
        queryset = self.get_queryset()

        stats = {
            "total": queryset.count(),
            "unread": queryset.filter(read_at__isnull=True).count(),
            "by_type": {},
            "by_priority": {},
        }

        # Count by type
        for choice in NotificationType.choices:
            count = queryset.filter(notification_type=choice[0]).count()
            stats["by_type"][choice[1]] = count

        # Count by priority
        for choice in NotificationPriority.choices:
            count = queryset.filter(priority=choice[0]).count()
            stats["by_priority"][choice[1]] = count

        return Response(stats)


class MessageThreadViewSet(viewsets.ModelViewSet):
    """ViewSet for managing message threads."""

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_private", "is_archived", "creator"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "last_message_at", "title"]
    ordering = ["-last_message_at"]

    def get_serializer_class(self):
        """Use different serializers for different actions."""
        if self.action == "create":
            return MessageThreadCreateSerializer
        elif self.action == "retrieve":
            return MessageThreadDetailSerializer
        return MessageThreadSerializer

    def get_queryset(self):
        """Filter threads based on user participation."""
        user = self.request.user

        # Users can see threads they participate in
        return (
            MessageThread.objects.filter(participants=user)
            .select_related("creator", "content_type")
            .prefetch_related("participants", "threadparticipant_set__user")
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        """Create thread and return full representation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        thread = serializer.save()

        # Return the created object using the regular serializer
        output_serializer = MessageThreadSerializer(thread, context=self.get_serializer_context())
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=["post"])
    def add_participant(self, request, pk=None):
        """Add participant to thread."""
        thread = self.get_object()
        username = request.data.get("username")

        if not username:
            return Response({"error": "Username is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if user can add participants (creator or moderator)
        participant = ThreadParticipant.objects.filter(thread=thread, user=request.user).first()

        if not participant or (not participant.is_moderator and thread.creator != request.user):
            return Response({"error": "Only moderators can add participants"}, status=status.HTTP_403_FORBIDDEN)

        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user_to_add = User.objects.get(username=username, is_active=True)

            participant, created = ThreadParticipant.objects.get_or_create(
                thread=thread, user=user_to_add, defaults={"is_moderator": False}
            )

            if created:
                return Response(
                    {
                        "message": f"Added {username} to thread",
                        "participant": ThreadParticipantSerializer(participant).data,
                    }
                )
            else:
                return Response({"error": "User is already a participant"}, status=status.HTTP_400_BAD_REQUEST)

        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["post"])
    def remove_participant(self, request, pk=None):
        """Remove participant from thread."""
        thread = self.get_object()
        username = request.data.get("username")

        if not username:
            return Response({"error": "Username is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check permissions
        current_participant = ThreadParticipant.objects.filter(thread=thread, user=request.user).first()

        if not current_participant or (not current_participant.is_moderator and thread.creator != request.user):
            return Response({"error": "Only moderators can remove participants"}, status=status.HTTP_403_FORBIDDEN)

        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user_to_remove = User.objects.get(username=username)

            # Cannot remove creator
            if user_to_remove == thread.creator:
                return Response({"error": "Cannot remove thread creator"}, status=status.HTTP_400_BAD_REQUEST)

            participant = ThreadParticipant.objects.filter(thread=thread, user=user_to_remove).first()

            if participant:
                participant.delete()
                return Response({"message": f"Removed {username} from thread"})
            else:
                return Response({"error": "User is not a participant"}, status=status.HTTP_404_NOT_FOUND)

        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["get"])
    def participants(self, request, pk=None):
        """Get thread participants."""
        thread = self.get_object()
        participants = ThreadParticipant.objects.filter(thread=thread).select_related("user")

        page = self.paginate_queryset(participants)
        if page is not None:
            serializer = ThreadParticipantSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ThreadParticipantSerializer(participants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """Archive/unarchive thread."""
        thread = self.get_object()

        # Only creator can archive
        if thread.creator != request.user:
            return Response({"error": "Only thread creator can archive"}, status=status.HTTP_403_FORBIDDEN)

        thread.is_archived = not thread.is_archived
        thread.save(update_fields=["is_archived"])

        return Response(
            {
                "message": f'Thread {"archived" if thread.is_archived else "unarchived"}',
                "is_archived": thread.is_archived,
            }
        )


class MessageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing messages within threads."""

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["thread", "message_type", "sender", "is_deleted"]
    search_fields = ["content"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["created_at"]

    def get_serializer_class(self):
        """Use detailed serializer for retrieve action."""
        if self.action == "retrieve":
            return MessageDetailSerializer
        return MessageSerializer

    def get_queryset(self):
        """Filter messages based on thread participation."""
        user = self.request.user

        # Users can see messages in threads they participate in
        return (
            Message.objects.filter(thread__participants=user, is_deleted=False)
            .select_related("sender", "thread", "reply_to")
            .prefetch_related("annotations")
        )

    def perform_create(self, serializer):
        """Set sender and update thread timestamp."""
        message = serializer.save(sender=self.request.user)

        # Update thread last_message_at
        message.thread.last_message_at = timezone.now()
        message.thread.save(update_fields=["last_message_at"])

        return message

    def perform_update(self, serializer):
        """Mark message as edited when updated."""
        message = serializer.save(is_edited=True)
        return message

    @action(detail=True, methods=["post"])
    def soft_delete(self, request, pk=None):
        """Soft delete message."""
        message = self.get_object()

        # Only sender can delete their message
        if message.sender != request.user:
            return Response({"error": "Only message sender can delete this message"}, status=status.HTTP_403_FORBIDDEN)

        message.is_deleted = True
        message.save(update_fields=["is_deleted"])

        return Response({"message": "Message deleted"})

    @action(detail=False, methods=["get"])
    def thread_messages(self, request):
        """Get messages for a specific thread."""
        thread_id = request.query_params.get("thread_id")

        if not thread_id:
            return Response({"error": "thread_id parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if user participates in thread
        try:
            from uuid import UUID

            thread_uuid = UUID(thread_id)
            thread = MessageThread.objects.get(id=thread_uuid, participants=request.user)
        except (ValueError, MessageThread.DoesNotExist):
            return Response({"error": "Thread not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        messages = self.get_queryset().filter(thread=thread)

        page = self.paginate_queryset(messages)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(messages, many=True)
        return Response(serializer.data)


class ThreadParticipantViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only ViewSet for thread participants."""

    permission_classes = [IsAuthenticated]
    serializer_class = ThreadParticipantSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["thread", "is_moderator", "notifications_enabled"]
    ordering_fields = ["joined_at", "last_read_at"]
    ordering = ["-joined_at"]

    def get_queryset(self):
        """Filter participants based on thread access."""
        user = self.request.user

        # Users can see participants of threads they participate in
        return ThreadParticipant.objects.filter(thread__participants=user).select_related("user", "thread")

    @action(detail=True, methods=["post"])
    def update_settings(self, request, pk=None):
        """Update participant settings (only own settings)."""
        participant = self.get_object()

        # Users can only update their own participant settings
        if participant.user != request.user:
            return Response({"error": "Can only update your own settings"}, status=status.HTTP_403_FORBIDDEN)

        notifications_enabled = request.data.get("notifications_enabled")

        if notifications_enabled is not None:
            participant.notifications_enabled = notifications_enabled
            participant.save(update_fields=["notifications_enabled"])

        serializer = self.get_serializer(participant)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark thread as read for participant."""
        participant = self.get_object()

        # Users can only update their own read status
        if participant.user != request.user:
            return Response({"error": "Can only update your own read status"}, status=status.HTTP_403_FORBIDDEN)

        participant.last_read_at = timezone.now()
        participant.save(update_fields=["last_read_at"])

        return Response({"message": "Thread marked as read", "last_read_at": participant.last_read_at})


class WebRTCSessionViewSet(viewsets.ModelViewSet):
    queryset = WebRTCSession.objects.all()
    serializer_class = WebRTCSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return (
                WebRTCSession.objects.all()
                .select_related("initiated_by")
                .prefetch_related("peers__user", "ccrv_sessions")
            )

        return (
            WebRTCSession.objects.filter(Q(initiated_by=user) | Q(peers__user=user) | Q(ccrv_sessions__owner=user))
            .distinct()
            .select_related("initiated_by")
            .prefetch_related("peers__user", "ccrv_sessions")
        )

    def check_edit_permission(self, webrtc_session):
        """Check if user can edit this WebRTC session based on CCRV session permissions."""
        user = self.request.user

        if user.is_superuser or webrtc_session.initiated_by == user:
            return True

        ccrv_sessions = webrtc_session.ccrv_sessions.all()
        if not ccrv_sessions.exists():
            return webrtc_session.initiated_by == user

        for ccrv_session in ccrv_sessions:
            if ccrv_session.can_edit(user):
                return True

        return False

    def perform_update(self, serializer):
        if not self.check_edit_permission(serializer.instance):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to edit this WebRTC session")
        serializer.save()

    def perform_destroy(self, instance):
        if not self.check_edit_permission(instance):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to delete this WebRTC session")
        instance.delete()

    @action(detail=True, methods=["post"])
    def end_session(self, request, pk=None):
        session = self.get_object()

        if not self.check_edit_permission(session):
            return Response(
                {"error": "You don't have permission to end this session"}, status=status.HTTP_403_FORBIDDEN
            )

        session.session_status = "ended"
        session.ended_at = timezone.now()
        session.save(update_fields=["session_status", "ended_at"])

        return Response({"message": "Session ended", "session_id": session.id})
