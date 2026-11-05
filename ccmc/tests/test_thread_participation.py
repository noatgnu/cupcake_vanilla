"""Messages are posted, read and changed only by participants of their thread."""

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase

from ccmc.models import Message, MessageThread, ThreadParticipant

User = get_user_model()

MESSAGES = "/api/v1/messages/"


class ThreadParticipationTests(APITestCase):
    def setUp(self):
        self.sender = User.objects.create_user("sender", "sender@test.com", "pw")
        self.participant = User.objects.create_user("participant", "participant@test.com", "pw")
        self.outsider = User.objects.create_user("outsider", "outsider@test.com", "pw")
        self.thread = MessageThread.objects.create(title="Thread", creator=self.sender)
        ThreadParticipant.objects.create(thread=self.thread, user=self.sender, is_moderator=True)
        ThreadParticipant.objects.create(thread=self.thread, user=self.participant)
        self.message = Message.objects.create(thread=self.thread, content="Hello", sender=self.sender)

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def test_outsiders_cannot_post_in_the_thread(self):
        response = self.as_user(self.outsider).post(
            MESSAGES, {"thread": str(self.thread.id), "content": "Hi"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Message.objects.filter(sender=self.outsider).exists())

    def test_participants_post_in_the_thread(self):
        response = self.as_user(self.participant).post(
            MESSAGES, {"thread": str(self.thread.id), "content": "Hi"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_outsiders_cannot_see_the_messages(self):
        client = self.as_user(self.outsider)
        self.assertEqual(client.get(f"{MESSAGES}{self.message.id}/").status_code, status.HTTP_404_NOT_FOUND)
        response = client.get(f"{MESSAGES}thread_messages/", {"thread_id": str(self.thread.id)})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_replies_must_be_in_the_same_thread(self):
        other = MessageThread.objects.create(title="Other", creator=self.outsider)
        ThreadParticipant.objects.create(thread=other, user=self.outsider)
        foreign = Message.objects.create(thread=other, content="Secret", sender=self.outsider)
        response = self.as_user(self.participant).post(
            MESSAGES,
            {"thread": str(self.thread.id), "content": "Re", "reply_to": str(foreign.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_the_sender_edits_or_deletes_a_message(self):
        url = f"{MESSAGES}{self.message.id}/"
        client = self.as_user(self.participant)
        self.assertEqual(client.patch(url, {"content": "Changed"}, format="json").status_code, 403)
        self.assertEqual(client.delete(url).status_code, status.HTTP_403_FORBIDDEN)
        self.message.refresh_from_db()
        self.assertEqual(self.message.content, "Hello")
        response = self.as_user(self.sender).patch(url, {"content": "Edited"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_a_message_cannot_be_moved_to_another_thread(self):
        other = MessageThread.objects.create(title="Other", creator=self.sender)
        ThreadParticipant.objects.create(thread=other, user=self.sender)
        url = f"{MESSAGES}{self.message.id}/"
        self.as_user(self.sender).patch(url, {"thread": str(other.id)}, format="json")
        self.message.refresh_from_db()
        self.assertEqual(self.message.thread_id, self.thread.id)

    def test_participants_mark_the_thread_as_read(self):
        response = self.as_user(self.participant).post(f"/api/v1/threads/{self.thread.id}/mark_read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        participation = ThreadParticipant.objects.get(thread=self.thread, user=self.participant)
        self.assertIsNotNone(participation.last_read_at)
        outsider = self.as_user(self.outsider).post(f"/api/v1/threads/{self.thread.id}/mark_read/")
        self.assertEqual(outsider.status_code, status.HTTP_404_NOT_FOUND)
