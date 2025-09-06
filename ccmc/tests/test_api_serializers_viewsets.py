"""
Test CCMC API serializers and viewsets.

Tests the REST API functionality for communication, messaging, notifications,
and thread management functionality.
"""


from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

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
from ccmc.serializers import (
    MessageSerializer,
    MessageThreadCreateSerializer,
    NotificationCreateSerializer,
    ThreadParticipantSerializer,
)

User = get_user_model()


class CCMCSerializerTests(TestCase):
    """Test CCMC model serializers."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="testuser1", email="test1@example.com", password="testpass123")
        self.user2 = User.objects.create_user(username="testuser2", email="test2@example.com", password="testpass123")

    def test_notification_serializer(self):
        """Test NotificationSerializer."""
        notification_data = {
            "title": "Test Notification",
            "message": "This is a test notification message",
            "notification_type": NotificationType.SYSTEM,
            "priority": NotificationPriority.NORMAL,
            "recipient": self.user1.id,
            "data": {"test_key": "test_value"},
        }

        serializer = NotificationCreateSerializer(data=notification_data)
        self.assertTrue(serializer.is_valid())

        notification = serializer.save(sender=self.user2)
        self.assertEqual(notification.title, "Test Notification")
        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.sender, self.user2)
        self.assertEqual(notification.data["test_key"], "test_value")

    def test_notification_serializer_validation(self):
        """Test NotificationSerializer validation."""
        # Test missing required fields
        notification_data = {"message": "Missing title and recipient"}

        serializer = NotificationCreateSerializer(data=notification_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)
        self.assertIn("recipient", serializer.errors)

    def test_message_thread_create_serializer(self):
        """Test MessageThreadCreateSerializer."""
        thread_data = {
            "title": "Test Thread",
            "description": "A test discussion thread",
            "is_private": False,
            "participant_usernames": ["testuser2"],
        }

        # Mock request context
        class MockRequest:
            user = self.user1

        context = {"request": MockRequest()}
        serializer = MessageThreadCreateSerializer(data=thread_data, context=context)
        self.assertTrue(serializer.is_valid())

        thread = serializer.save()
        self.assertEqual(thread.title, "Test Thread")
        self.assertEqual(thread.creator, self.user1)
        self.assertEqual(thread.participants.count(), 2)  # Creator + added participant

        # Check participants
        participants = ThreadParticipant.objects.filter(thread=thread)
        self.assertEqual(participants.count(), 2)

        creator_participant = participants.get(user=self.user1)
        self.assertTrue(creator_participant.is_moderator)

        added_participant = participants.get(user=self.user2)
        self.assertFalse(added_participant.is_moderator)

    def test_message_serializer(self):
        """Test MessageSerializer."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        message_data = {
            "thread": thread.id,
            "content": "Hello, this is a test message!",
            "message_type": MessageType.THREAD,
        }

        serializer = MessageSerializer(data=message_data)
        self.assertTrue(serializer.is_valid())

        message = serializer.save(sender=self.user1)
        self.assertEqual(message.content, "Hello, this is a test message!")
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.thread, thread)

    def test_thread_participant_serializer(self):
        """Test ThreadParticipantSerializer."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        participant = ThreadParticipant.objects.create(
            thread=thread, user=self.user2, is_moderator=False, notifications_enabled=True
        )

        serializer = ThreadParticipantSerializer(participant)
        data = serializer.data

        self.assertEqual(data["user"], self.user2.id)
        self.assertEqual(data["username"], "testuser2")
        self.assertFalse(data["is_moderator"])
        self.assertTrue(data["notifications_enabled"])
        self.assertIn("user_details", data)


class CCMCViewSetTests(APITestCase):
    """Test CCMC API viewsets."""

    def _get_results_from_response(self, response):
        """Helper to get results from potentially paginated API response."""
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def _get_count_from_response(self, response):
        """Helper to get count from potentially paginated API response."""
        if isinstance(response.data, dict) and "results" in response.data:
            return len(response.data["results"])
        return len(response.data)

    def setUp(self):
        # Clean up any existing test data to ensure test isolation
        Notification.objects.all().delete()
        MessageThread.objects.all().delete()
        ThreadParticipant.objects.all().delete()
        Message.objects.all().delete()

        self.user1 = User.objects.create_user(username="testuser1", email="test1@example.com", password="testpass123")
        self.user2 = User.objects.create_user(username="testuser2", email="test2@example.com", password="testpass123")
        self.staff_user = User.objects.create_user(
            username="staffuser", email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_authenticate(user=self.user1)

    def test_notification_list_create(self):
        """Test notification list and create endpoints."""
        url = "/api/v1/notifications/"
        initial_response = self.client.get(url)
        initial_count = self._get_count_from_response(initial_response)

        # Test create notification
        data = {
            "title": "Test Notification",
            "message": "This is a test notification",
            "notification_type": NotificationType.SYSTEM,
            "priority": NotificationPriority.HIGH,
            "recipient": self.user2.id,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Test Notification")
        self.assertEqual(response.data["recipient"], self.user2.id)

        # Test list - should have one more item
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        final_count = self._get_count_from_response(response)
        self.assertEqual(final_count, initial_count + 1)

    def test_notification_permissions(self):
        """Test notification access permissions."""
        # Create notification for user2
        notification = Notification.objects.create(
            title="Private Notification", message="Private message", recipient=self.user2, sender=self.user1
        )

        # User1 (sender) should see it
        url = "/api/v1/notifications/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results_from_response(response)
        notification_ids = [n["id"] for n in results]
        self.assertIn(str(notification.id), notification_ids)

        # User2 (recipient) should see it
        self.client.force_authenticate(user=self.user2)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results_from_response(response)
        notification_ids = [n["id"] for n in results]
        self.assertIn(str(notification.id), notification_ids)

    def test_notification_mark_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            title="Test Notification", message="Test message", recipient=self.user1, sender=self.user2
        )

        # Only recipient can mark as read
        url = f"/api/v1/notifications/{notification.id}/mark_read/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("read_at", response.data)

        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)
        self.assertEqual(notification.delivery_status, DeliveryStatus.READ)

    def test_notification_unread_endpoint(self):
        """Test unread notifications endpoint."""
        # Create read and unread notifications
        read_notification = Notification.objects.create(
            title="Read Notification",
            message="This has been read",
            recipient=self.user1,
            sender=self.user2,
            read_at=timezone.now(),
            delivery_status=DeliveryStatus.READ,
        )

        unread_notification = Notification.objects.create(
            title="Unread Notification",
            message="This has not been read",
            recipient=self.user1,
            sender=self.user2,
            delivery_status=DeliveryStatus.SENT,
        )

        url = "/api/v1/notifications/unread/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = self._get_results_from_response(response)
        unread_ids = [n["id"] for n in results]
        self.assertIn(str(unread_notification.id), unread_ids)
        self.assertNotIn(str(read_notification.id), unread_ids)

    def test_message_thread_creation(self):
        """Test message thread creation."""
        url = "/api/v1/threads/"
        data = {
            "title": "Test Thread",
            "description": "A test discussion",
            "is_private": False,
            "participant_usernames": ["testuser2"],
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Test Thread")
        self.assertEqual(response.data["creator"], self.user1.id)

        # Check participants were created
        thread_id = response.data["id"]
        thread = MessageThread.objects.get(id=thread_id)
        self.assertEqual(thread.participants.count(), 2)

    def test_thread_add_participant(self):
        """Test adding participant to thread."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        # Add user2 as participant
        url = f"/api/v1/threads/{thread.id}/add_participant/"
        data = {"username": "testuser2"}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(thread.participants.count(), 2)

        # Check participant was created
        participant = ThreadParticipant.objects.get(thread=thread, user=self.user2)
        self.assertFalse(participant.is_moderator)

    def test_thread_remove_participant(self):
        """Test removing participant from thread."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)
        ThreadParticipant.objects.create(thread=thread, user=self.user2, is_moderator=False)

        # Remove user2 as participant
        url = f"/api/v1/threads/{thread.id}/remove_participant/"
        data = {"username": "testuser2"}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(thread.participants.count(), 1)

        # Check participant was removed
        self.assertFalse(ThreadParticipant.objects.filter(thread=thread, user=self.user2).exists())

    def test_thread_archive(self):
        """Test thread archiving."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        url = f"/api/v1/threads/{thread.id}/archive/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_archived"])

        thread.refresh_from_db()
        self.assertTrue(thread.is_archived)

    def test_message_creation(self):
        """Test message creation in thread."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        url = "/api/v1/messages/"
        data = {
            "thread": str(thread.id),
            "content": "Hello, this is a test message!",
            "message_type": MessageType.THREAD,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["content"], "Hello, this is a test message!")
        self.assertEqual(response.data["sender"], self.user1.id)

    def test_message_soft_delete(self):
        """Test soft deleting messages."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        message = Message.objects.create(thread=thread, content="Test message to delete", sender=self.user1)

        url = f"/api/v1/messages/{message.id}/soft_delete/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        message.refresh_from_db()
        self.assertTrue(message.is_deleted)

    def test_message_permissions(self):
        """Test message access permissions."""
        # Create thread with user1 as participant
        thread = MessageThread.objects.create(title="Private Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        message = Message.objects.create(thread=thread, content="Private message", sender=self.user1)

        # User1 (participant) should see message
        url = "/api/v1/messages/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results_from_response(response)
        message_ids = [m["id"] for m in results]
        self.assertIn(str(message.id), message_ids)

        # User2 (non-participant) should not see message
        self.client.force_authenticate(user=self.user2)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results_from_response(response)
        message_ids = [m["id"] for m in results]
        self.assertNotIn(str(message.id), message_ids)

    def test_thread_messages_endpoint(self):
        """Test getting messages for specific thread."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        ThreadParticipant.objects.create(thread=thread, user=self.user1, is_moderator=True)

        # Create messages in thread
        Message.objects.create(thread=thread, content="First message", sender=self.user1)
        Message.objects.create(thread=thread, content="Second message", sender=self.user1)

        url = f"/api/v1/messages/thread_messages/?thread_id={thread.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = self._get_results_from_response(response)
        self.assertEqual(len(results), 2)

        message_contents = [m["content"] for m in results]
        self.assertIn("First message", message_contents)
        self.assertIn("Second message", message_contents)

    def test_participant_settings(self):
        """Test updating participant settings."""
        thread = MessageThread.objects.create(title="Test Thread", creator=self.user1)
        participant = ThreadParticipant.objects.create(
            thread=thread, user=self.user1, is_moderator=True, notifications_enabled=True
        )

        url = f"/api/v1/participants/{participant.id}/update_settings/"
        data = {"notifications_enabled": False}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["notifications_enabled"])

        participant.refresh_from_db()
        self.assertFalse(participant.notifications_enabled)

    def test_notification_stats(self):
        """Test notification statistics endpoint."""
        # Create notifications of different types and priorities
        Notification.objects.create(
            title="System Notification",
            message="System message",
            notification_type=NotificationType.SYSTEM,
            priority=NotificationPriority.HIGH,
            recipient=self.user1,
            sender=self.user2,
        )

        Notification.objects.create(
            title="Maintenance Notification",
            message="Maintenance message",
            notification_type=NotificationType.MAINTENANCE,
            priority=NotificationPriority.NORMAL,
            recipient=self.user1,
            sender=self.user2,
            read_at=timezone.now(),
        )

        url = "/api/v1/notifications/stats/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        stats = response.data
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["unread"], 1)
        self.assertIn("by_type", stats)
        self.assertIn("by_priority", stats)
        self.assertEqual(stats["by_type"]["System"], 1)
        self.assertEqual(stats["by_type"]["Maintenance"], 1)
