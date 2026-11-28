"""Who may message and notify whom: lab groups, staff and blocks."""

from django.contrib.auth.models import User

from rest_framework.test import APITestCase

from ccc.models import LabGroup
from ccmc.models import Message, MessageThread, Notification, ThreadParticipant, UserBlock


class ContactRuleTests(APITestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", password="pw")
        self.grace = User.objects.create_user("grace", password="pw")
        self.outsider = User.objects.create_user("outsider", password="pw")
        self.staff = User.objects.create_user("staff-sender", password="pw", is_staff=True)
        self.core = LabGroup.objects.create(name="Proteomics core", creator=self.ada)
        self.core.members.add(self.ada, self.grace)

    def start_thread(self, sender, *usernames):
        self.client.force_authenticate(sender)
        return self.client.post(
            "/api/v1/threads/", {"title": "Shipment", "participant_usernames": list(usernames)}, format="json"
        )

    def notify(self, sender, recipient, kind="user"):
        self.client.force_authenticate(sender)
        return self.client.post(
            "/api/v1/notifications/",
            {
                "title": "Hello",
                "message": "Samples arrive Tuesday",
                "notification_type": kind,
                "recipient": recipient.id,
            },
            format="json",
        )

    def test_members_of_a_lab_group_message_each_other(self):
        self.assertEqual(self.start_thread(self.ada, "grace").status_code, 201)

    def test_people_outside_your_lab_groups_cannot_be_messaged(self):
        response = self.start_thread(self.ada, "outsider")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MessageThread.objects.filter(title="Shipment").exists())

    def test_members_of_a_sub_group_count_for_its_parent(self):
        sub_group = LabGroup.objects.create(name="Phospho team", creator=self.staff, parent_group=self.core)
        sub_group.members.add(self.outsider)
        self.assertEqual(self.start_thread(self.ada, "outsider").status_code, 201)

    def test_staff_message_anyone(self):
        self.assertEqual(self.start_thread(self.staff, "outsider").status_code, 201)

    def test_adding_someone_outside_your_lab_groups_to_a_thread_is_refused(self):
        thread_id = self.start_thread(self.ada, "grace").data["id"]
        response = self.client.post(f"/api/v1/threads/{thread_id}/add_participant/", {"username": "outsider"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ThreadParticipant.objects.filter(thread_id=thread_id, user=self.outsider).exists())

    def test_notifications_follow_the_same_rule(self):
        self.assertEqual(self.notify(self.ada, self.grace).status_code, 201)
        self.assertEqual(self.notify(self.ada, self.outsider).status_code, 403)
        self.assertEqual(self.notify(self.staff, self.outsider).status_code, 201)

    def test_only_staff_send_system_notifications_and_messages(self):
        self.assertEqual(self.notify(self.ada, self.grace, kind="system").status_code, 403)
        self.assertEqual(self.notify(self.staff, self.grace, kind="system").status_code, 201)
        thread_id = self.start_thread(self.ada, "grace").data["id"]
        response = self.client.post(
            "/api/v1/messages/", {"thread": thread_id, "content": "Hi all", "message_type": "broadcast"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_a_block_stops_contact_both_ways(self):
        self.client.force_authenticate(self.grace)
        self.assertEqual(self.client.post("/api/v1/blocks/", {"blocked": self.ada.id}).status_code, 201)
        self.assertEqual(self.start_thread(self.ada, "grace").status_code, 400)
        self.assertEqual(self.notify(self.ada, self.grace).status_code, 403)
        self.assertEqual(self.notify(self.grace, self.ada).status_code, 403)

    def test_a_blocked_users_messages_and_notifications_are_hidden_from_the_blocker(self):
        thread = MessageThread.objects.create(title="Older thread", creator=self.ada)
        ThreadParticipant.objects.create(thread=thread, user=self.ada, is_moderator=True)
        ThreadParticipant.objects.create(thread=thread, user=self.grace)
        Message.objects.create(thread=thread, sender=self.ada, content="Before the block")
        Notification.objects.create(title="Before", message="Earlier", recipient=self.grace, sender=self.ada)
        UserBlock.objects.create(blocker=self.grace, blocked=self.ada)
        self.client.force_authenticate(self.grace)
        messages = self.client.get("/api/v1/messages/", {"thread": str(thread.id)}).data["results"]
        notifications = self.client.get("/api/v1/notifications/").data["results"]
        self.assertEqual(messages, [])
        self.assertEqual(notifications, [])
        threads = self.client.get("/api/v1/threads/").data["results"]
        self.assertIsNone(threads[0]["latest_message"])
        self.assertEqual(threads[0]["messages_count"], 0)

    def test_blocks_are_listed_and_removed_by_their_owner(self):
        self.client.force_authenticate(self.grace)
        block = self.client.post("/api/v1/blocks/", {"blocked": self.ada.id}).data
        self.assertEqual([b["blocked_username"] for b in self.client.get("/api/v1/blocks/").data["results"]], ["ada"])
        self.client.force_authenticate(self.ada)
        self.assertEqual(self.client.delete(f"/api/v1/blocks/{block['id']}/").status_code, 404)
        self.client.force_authenticate(self.grace)
        self.assertEqual(self.client.delete(f"/api/v1/blocks/{block['id']}/").status_code, 204)
        self.assertEqual(self.start_thread(self.ada, "grace").status_code, 201)

    def test_you_cannot_block_yourself(self):
        self.client.force_authenticate(self.grace)
        self.assertEqual(self.client.post("/api/v1/blocks/", {"blocked": self.grace.id}).status_code, 400)
