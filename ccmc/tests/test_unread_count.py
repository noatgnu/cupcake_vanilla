"""How many messages of a thread a participant has not read yet."""

from django.contrib.auth.models import User

from rest_framework.test import APITestCase

from ccmc.models import Message, MessageThread, ThreadParticipant


class UnreadCountTests(APITestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", password="pw")
        self.grace = User.objects.create_user("grace", password="pw")
        self.thread = MessageThread.objects.create(title="Weekend shifts", creator=self.ada)
        ThreadParticipant.objects.create(thread=self.thread, user=self.ada, is_moderator=True)
        ThreadParticipant.objects.create(thread=self.thread, user=self.grace)

    def unread(self, user):
        self.client.force_authenticate(user)
        return self.client.get("/api/v1/threads/").data["results"][0]["unread_count"]

    def test_messages_from_others_are_unread_until_the_thread_is_read(self):
        Message.objects.create(thread=self.thread, sender=self.ada, content="Who takes Saturday?")
        Message.objects.create(thread=self.thread, sender=self.ada, content="And Sunday?")
        self.assertEqual(self.unread(self.grace), 2)
        self.assertEqual(self.client.post(f"/api/v1/threads/{self.thread.id}/mark_read/").status_code, 200)
        self.assertEqual(self.unread(self.grace), 0)

    def test_your_own_messages_are_never_unread(self):
        Message.objects.create(thread=self.thread, sender=self.ada, content="Who takes Saturday?")
        self.assertEqual(self.unread(self.ada), 0)

    def test_new_messages_after_reading_are_unread(self):
        Message.objects.create(thread=self.thread, sender=self.ada, content="Who takes Saturday?")
        self.client.force_authenticate(self.grace)
        self.client.post(f"/api/v1/threads/{self.thread.id}/mark_read/")
        Message.objects.create(thread=self.thread, sender=self.ada, content="I will be in from 8")
        self.assertEqual(self.unread(self.grace), 1)
