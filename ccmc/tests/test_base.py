"""
Tests for CCMC (CUPCAKE Mint Chocolate) models and functionality.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from ccmc.models import (
    DeliveryStatus,
    Message,
    MessageThread,
    MessageType,
    Notification,
    NotificationPriority,
    NotificationType,
    ThreadParticipant,
)

User = get_user_model()


class NotificationModelTest(TestCase):
    """Test Notification model functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@test.com")
        self.user2 = User.objects.create_user(username="user2", email="user2@test.com")

    def test_notification_creation(self):
        """Test basic notification creation."""
        notification = Notification.objects.create(
            title="Test Notification",
            message="This is a test notification",
            recipient=self.user1,
            sender=self.user2,
            notification_type=NotificationType.SYSTEM,
            priority=NotificationPriority.NORMAL,
        )

        notification.refresh_from_db()
        self.assertEqual(notification.title, "Test Notification")
        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.sender, self.user2)
        self.assertEqual(notification.delivery_status, DeliveryStatus.SENT)
        self.assertIsNone(notification.read_at)

    def test_notification_mark_as_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            title="Test Notification", message="Test message", recipient=self.user1
        )

        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)
        self.assertEqual(notification.delivery_status, DeliveryStatus.SENT)

        notification.mark_as_read()

        self.assertIsNotNone(notification.read_at)
        self.assertEqual(notification.delivery_status, DeliveryStatus.READ)

    def test_notification_mark_as_read_idempotent(self):
        """Test that marking as read multiple times doesn't change timestamp."""
        notification = Notification.objects.create(
            title="Test Notification", message="Test message", recipient=self.user1
        )

        notification.mark_as_read()
        first_read_time = notification.read_at

        notification.mark_as_read()
        second_read_time = notification.read_at

        self.assertEqual(first_read_time, second_read_time)

    def test_notification_is_expired(self):
        """Test notification expiration check."""
        # Non-expired notification
        future_time = timezone.now() + timedelta(hours=1)
        notification1 = Notification.objects.create(
            title="Future Notification", message="Test message", recipient=self.user1, expires_at=future_time
        )

        # Expired notification
        past_time = timezone.now() - timedelta(hours=1)
        notification2 = Notification.objects.create(
            title="Expired Notification", message="Test message", recipient=self.user1, expires_at=past_time
        )

        # No expiration
        notification3 = Notification.objects.create(
            title="No Expiry Notification", message="Test message", recipient=self.user1
        )

        self.assertFalse(notification1.is_expired())
        self.assertTrue(notification2.is_expired())
        self.assertFalse(notification3.is_expired())

    def test_notification_generic_relation(self):
        """Test notification with generic foreign key to related object."""
        # Use User as a test related object
        notification = Notification.objects.create(
            title="User Notification",
            message="Test message about user",
            recipient=self.user1,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user2.pk,
        )

        self.assertEqual(notification.related_object, self.user2)

    def test_notification_string_representation(self):
        """Test notification string representation."""
        notification = Notification.objects.create(title="Test Title", message="Test message", recipient=self.user1)

        expected = f"Test Title -> {self.user1.username}"
        self.assertEqual(str(notification), expected)


class MessageThreadModelTest(TestCase):
    """Test MessageThread model functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@test.com")
        self.user2 = User.objects.create_user(username="user2", email="user2@test.com")
        self.user3 = User.objects.create_user(username="user3", email="user3@test.com")

    def test_message_thread_creation(self):
        """Test basic message thread creation."""
        thread = MessageThread.objects.create(
            title="Test Thread", description="This is a test thread", creator=self.user1
        )

        self.assertEqual(thread.title, "Test Thread")
        self.assertEqual(thread.creator, self.user1)
        self.assertFalse(thread.is_private)
        self.assertFalse(thread.is_archived)

    def test_message_thread_participants(self):
        """Test adding participants to a thread."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)

        # Add participants
        thread.participants.add(self.user1, self.user2)

        self.assertEqual(thread.participants.count(), 2)
        self.assertIn(self.user1, thread.participants.all())
        self.assertIn(self.user2, thread.participants.all())

    def test_thread_participant_metadata(self):
        """Test ThreadParticipant through model metadata."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)

        # Add participant with metadata
        participant = ThreadParticipant.objects.create(
            thread=thread, user=self.user2, is_moderator=True, notifications_enabled=False
        )

        self.assertTrue(participant.is_moderator)
        self.assertFalse(participant.notifications_enabled)
        self.assertIsNotNone(participant.joined_at)
        self.assertIsNotNone(participant.last_read_at)

    def test_message_thread_string_representation(self):
        """Test message thread string representation."""
        thread = MessageThread.objects.create(title="My Test Thread", creator=self.user1)

        self.assertEqual(str(thread), "My Test Thread")


class MessageModelTest(TestCase):
    """Test Message model functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@test.com")
        self.user2 = User.objects.create_user(username="user2", email="user2@test.com")

        self.thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)

    def test_message_creation(self):
        """Test basic message creation."""
        message = Message.objects.create(
            thread=self.thread, content="This is a test message", sender=self.user1, message_type=MessageType.THREAD
        )

        self.assertEqual(message.content, "This is a test message")
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.thread, self.thread)
        self.assertFalse(message.is_edited)
        self.assertFalse(message.is_deleted)

    def test_message_reply(self):
        """Test message replies."""
        original_message = Message.objects.create(thread=self.thread, content="Original message", sender=self.user1)

        reply_message = Message.objects.create(
            thread=self.thread, content="Reply to original", sender=self.user2, reply_to=original_message
        )

        self.assertEqual(reply_message.reply_to, original_message)
        self.assertEqual(original_message.replies.count(), 1)
        self.assertEqual(original_message.replies.first(), reply_message)

    def test_message_string_representation(self):
        """Test message string representation."""
        message = Message.objects.create(thread=self.thread, content="Test message content", sender=self.user1)

        expected = f"Message from {self.user1.username} in {self.thread.title}"
        self.assertEqual(str(message), expected)


class NotificationChoicesTest(TestCase):
    """Test notification choice fields."""

    def test_notification_type_choices(self):
        """Test NotificationType choices."""
        choices = dict(NotificationType.choices)

        self.assertIn("system", choices)
        self.assertIn("maintenance", choices)
        self.assertIn("inventory", choices)
        self.assertEqual(choices["system"], "System")
        self.assertEqual(choices["maintenance"], "Maintenance")

    def test_notification_priority_choices(self):
        """Test NotificationPriority choices."""
        choices = dict(NotificationPriority.choices)

        self.assertIn("low", choices)
        self.assertIn("normal", choices)
        self.assertIn("high", choices)
        self.assertIn("urgent", choices)

    def test_delivery_status_choices(self):
        """Test DeliveryStatus choices."""
        choices = dict(DeliveryStatus.choices)

        self.assertIn("pending", choices)
        self.assertIn("sent", choices)
        self.assertIn("delivered", choices)
        self.assertIn("failed", choices)
        self.assertIn("read", choices)


class MessageThreadIntegrationTest(TestCase):
    """Test MessageThread integration with CCC Annotation system."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@test.com")

    def test_thread_without_annotations(self):
        """Test thread creation without annotations."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)

        self.assertEqual(thread.annotations.count(), 0)

    def test_message_without_annotations(self):
        """Test message creation without annotations."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)

        message = Message.objects.create(thread=thread, content="Test message", sender=self.user1)

        self.assertEqual(message.annotations.count(), 0)
