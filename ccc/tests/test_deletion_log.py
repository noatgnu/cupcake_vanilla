"""Tests for the DeletionLog model and the mobile delta-sync deletion feed endpoint."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import DeletionLog, LabGroup

User = get_user_model()


class DeletionLogEndpointTests(APITestCase):
    """Test GET /api/v1/deletions/ scoping and `since` filtering."""

    def setUp(self):
        self.user = User.objects.create_user(username="deleter", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123")

        self.lab_group = LabGroup.objects.create(name="Test Lab")
        self.lab_group.members.add(self.user)

        content_type = ContentType.objects.get_for_model(LabGroup)

        self.own_log = DeletionLog.objects.create(content_type=content_type, object_id=1, deleted_by=self.user)
        self.lab_group_log = DeletionLog.objects.create(
            content_type=content_type, object_id=2, deleted_by=self.other_user, lab_group=self.lab_group
        )
        self.unrelated_log = DeletionLog.objects.create(
            content_type=content_type, object_id=3, deleted_by=self.other_user
        )

    def test_user_sees_own_and_lab_group_deletions_only(self):
        """A regular user sees deletions they made plus deletions scoped to their lab groups."""
        self.client.force_authenticate(user=self.user)

        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.own_log.id, self.lab_group_log.id})

    def test_superuser_sees_all_deletions(self):
        """A superuser sees every tombstone regardless of who deleted it."""
        self.client.force_authenticate(user=self.superuser)

        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.own_log.id, self.lab_group_log.id, self.unrelated_log.id})

    def test_since_filter_excludes_older_deletions(self):
        """`?since=` excludes tombstones recorded before the given cursor."""
        self.client.force_authenticate(user=self.superuser)

        cursor = self.unrelated_log.deleted_at + timedelta(seconds=1)
        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url, {"since": cursor.isoformat()})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_since_filter_includes_recent_deletions(self):
        """`?since=` includes tombstones recorded at or after the given cursor."""
        self.client.force_authenticate(user=self.superuser)

        cursor = self.own_log.deleted_at - timedelta(seconds=1)
        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url, {"since": cursor.isoformat()})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.own_log.id, self.lab_group_log.id, self.unrelated_log.id})

    def test_since_filter_rejects_invalid_timestamp(self):
        """An unparseable `since` value returns 400, not a 500 from the ORM."""
        self.client.force_authenticate(user=self.superuser)

        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url, {"since": "not-a-timestamp"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_endpoint_requires_authentication(self):
        """Unauthenticated requests are rejected."""
        url = reverse("ccc:deletionlog-list")
        response = self.client.get(url)

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_endpoint_is_read_only(self):
        """The deletion feed cannot be written to via the API."""
        self.client.force_authenticate(user=self.superuser)

        url = reverse("ccc:deletionlog-list")
        response = self.client.post(url, {"object_id": 99}, format="json")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
