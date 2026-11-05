"""Paging of a lab group's member list by limit and offset."""

from django.urls import reverse

from rest_framework.test import APITestCase

from ccc.models import LabGroup
from tests.factories import UserFactory


class LabGroupMembersPagingTests(APITestCase):
    def setUp(self):
        self.creator = UserFactory.create_user(username="creator")
        self.lab_group = LabGroup.objects.create(name="Lab", creator=self.creator)
        for index in range(5):
            self.lab_group.members.add(UserFactory.create_user(username=f"member{index}"))
        self.client.force_authenticate(user=self.creator)
        self.url = reverse("ccc:labgroup-members", kwargs={"pk": self.lab_group.pk})

    def test_members_are_paged_by_limit_and_offset(self):
        first = self.client.get(self.url, {"limit": 2, "offset": 0}).data
        rest = self.client.get(self.url, {"limit": 10, "offset": 2}).data
        self.assertEqual(first["count"], 5)
        self.assertEqual(len(first["results"]), 2)
        self.assertEqual(len(rest["results"]), 3)
        self.assertFalse({m["id"] for m in first["results"]} & {m["id"] for m in rest["results"]})
