"""
CUPCAKE Mint Chocolate (CCMC) Models.

Communication and notification system models for CUPCAKE.
Provides messaging, system notifications, and external communication integration.

Note: This app leverages the existing Annotation system from CCC for file attachments
rather than creating duplicate functionality.
"""

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords


class NotificationType(models.TextChoices):
    """Types of system notifications."""

    SYSTEM = "system", "System"
    MAINTENANCE = "maintenance", "Maintenance"
    INVENTORY = "inventory", "Inventory"
    BILLING = "billing", "Billing"
    PROJECT = "project", "Project"
    PROTOCOL = "protocol", "Protocol"
    DOCUMENT = "document", "Document"
    USER = "user", "User"


class NotificationPriority(models.TextChoices):
    """Priority levels for notifications."""

    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class DeliveryStatus(models.TextChoices):
    """Status of notification delivery."""

    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    READ = "read", "Read"


class MessageType(models.TextChoices):
    """Types of messages in the system."""

    DIRECT = "direct", "Direct Message"
    THREAD = "thread", "Thread Reply"
    BROADCAST = "broadcast", "Broadcast"
    SYSTEM = "system", "System Message"


class Notification(models.Model):
    """
    System notification model for cross-app communication.

    Provides a unified notification system that can be used by all CUPCAKE apps
    to send notifications to users about various events and activities.
    """

    history = HistoricalRecords()

    # Core notification data
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=20, choices=NotificationType.choices, default=NotificationType.SYSTEM
    )
    priority = models.CharField(
        max_length=10, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL
    )

    # Generic relation to any model that triggered this notification
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    related_object = GenericForeignKey("content_type", "object_id")

    # User targeting
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_received"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="notifications_sent", blank=True, null=True
    )

    # Delivery tracking
    delivery_status = models.CharField(max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    sent_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)

    # Metadata
    data = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccmc"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "delivery_status"]),
            models.Index(fields=["notification_type", "priority"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.title} -> {self.recipient.username}"

    def mark_as_read(self):
        """Mark notification as read."""
        if not self.read_at:
            self.read_at = timezone.now()
            self.delivery_status = DeliveryStatus.READ
            self.save(update_fields=["read_at", "delivery_status"])

    def is_expired(self):
        """Check if notification has expired."""
        return self.expires_at and timezone.now() > self.expires_at


class MessageThread(models.Model):
    """
    Message thread for group conversations and project discussions.

    Uses the existing Annotation system from CCC for file attachments via GenericRelation.
    """

    history = HistoricalRecords()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Participants
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_threads")
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ThreadParticipant", related_name="message_threads"
    )

    # Optional relation to any model (project, instrument, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    related_object = GenericForeignKey("content_type", "object_id")

    # File attachments via ManyToMany to reuse existing annotation system
    annotations = models.ManyToManyField(
        "ccc.Annotation",
        related_name="attached_message_threads",
        blank=True,
        help_text="Annotations/files attached to this thread",
    )

    # Thread settings
    is_private = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    allow_external_participants = models.BooleanField(default=False)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ccmc"
        ordering = ["-last_message_at"]

    def __str__(self):
        return self.title


class ThreadParticipant(models.Model):
    """
    Through model for thread participants with additional metadata.
    """

    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # Participation metadata
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(auto_now_add=True)
    is_moderator = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)

    class Meta:
        app_label = "ccmc"
        unique_together = ["thread", "user"]

    def __str__(self):
        return f"{self.user.username} in {self.thread.title}"


class Message(models.Model):
    """
    Individual message within a thread or direct message.

    Uses the existing Annotation system from CCC for file attachments via GenericRelation.
    """

    history = HistoricalRecords()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")

    # Message content
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MessageType.choices, default=MessageType.THREAD)

    # Author and recipients
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")

    # File attachments via ManyToMany to reuse existing annotation system
    annotations = models.ManyToManyField(
        "ccc.Annotation",
        related_name="attached_messages",
        blank=True,
        help_text="Annotations/files attached to this message",
    )

    # Message metadata
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, blank=True, null=True, related_name="replies")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccmc"
        ordering = ["created_at"]

    def __str__(self):
        return f"Message from {self.sender.username} in {self.thread.title}"
