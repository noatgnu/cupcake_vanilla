"""Staff adding users to lab groups without an invitation."""

from django.contrib.auth.models import User

from rest_framework.test import APITestCase

from ccc.models import LabGroup


class AddMemberTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff-member-adder", password="pw", is_staff=True)
        self.creator = User.objects.create_user("group-creator", password="pw")
        self.colleague = User.objects.create_user("colleague", password="pw")
        self.group = LabGroup.objects.create(name="Proteomics core", creator=self.creator)
        self.group.members.add(self.creator)
        self.url = f"/api/v1/lab-groups/{self.group.id}/add_member/"

    def test_staff_add_a_user_straight_away(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(self.url, {"user_id": self.colleague.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(self.group.members.filter(id=self.colleague.id).exists())

    def test_others_cannot_add_members_without_an_invitation(self):
        self.client.force_authenticate(self.creator)
        response = self.client.post(self.url, {"user_id": self.colleague.id}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.group.members.filter(id=self.colleague.id).exists())

    def test_adding_a_member_twice_is_refused(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(self.url, {"user_id": self.creator.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_user_is_not_found(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(self.url, {"user_id": 999999}, format="json")
        self.assertEqual(response.status_code, 404)
