"""
Tests for the read-only shared-table endpoint.

Covers token generation, revocation, public access without login,
permission enforcement, and the shape of the returned SDRF data.
"""

import uuid

from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from ccc.models import LabGroup
from ccv.models import MetadataColumn, MetadataTable


def _make_table(user, lab_group, name="Test Table", sample_count=2):
    table = MetadataTable.objects.create(
        name=name,
        owner=user,
        lab_group=lab_group,
        sample_count=sample_count,
    )
    MetadataColumn.objects.create(
        metadata_table=table,
        name="source name",
        type="source name",
        column_position=0,
        value="Sample1",
    )
    MetadataColumn.objects.create(
        metadata_table=table,
        name="characteristics[organism]",
        type="characteristics",
        column_position=1,
        value="homo sapiens",
    )
    return table


class GenerateShareTokenTest(TestCase):
    """Authenticated owner generates / refreshes a share token."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw")
        self.other = User.objects.create_user(username="other", password="pw")
        self.lab_group = LabGroup.objects.create(name="Lab", creator=self.owner)
        self.table = _make_table(self.owner, self.lab_group)
        self.client = APIClient()

    def test_owner_generates_token(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(f"/api/v1/metadata-tables/{self.table.id}/generate_share_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token = response.data["share_token"]
        self.assertIsNotNone(token)
        self.table.refresh_from_db()
        self.assertEqual(str(self.table.share_token), token)

    def test_refresh_token_changes_value(self):
        self.client.force_authenticate(user=self.owner)
        r1 = self.client.post(f"/api/v1/metadata-tables/{self.table.id}/generate_share_token/")
        r2 = self.client.post(f"/api/v1/metadata-tables/{self.table.id}/generate_share_token/")
        self.assertNotEqual(r1.data["share_token"], r2.data["share_token"])

    def test_non_owner_cannot_generate(self):
        """Non-owner sees the table as not found (private queryset filtering)."""
        self.client.force_authenticate(user=self.other)
        response = self.client.post(f"/api/v1/metadata-tables/{self.table.id}/generate_share_token/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_generate(self):
        """Unauthenticated request is rejected before it reaches the view."""
        response = self.client.post(f"/api/v1/metadata-tables/{self.table.id}/generate_share_token/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RevokeShareTokenTest(TestCase):
    """Owner revokes an existing share token."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", password="pw")
        self.lab_group = LabGroup.objects.create(name="Lab", creator=self.owner)
        self.table = _make_table(self.owner, self.lab_group)
        self.table.share_token = uuid.uuid4()
        self.table.save(update_fields=["share_token"])
        self.client = APIClient()

    def test_owner_revokes_token(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(f"/api/v1/metadata-tables/{self.table.id}/revoke_share_token/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.table.refresh_from_db()
        self.assertIsNone(self.table.share_token)


class SharedTableRetrieveTest(TestCase):
    """Public access via share token."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", password="pw")
        self.lab_group = LabGroup.objects.create(name="Lab", creator=self.owner)
        self.table = _make_table(self.owner, self.lab_group)
        self.token = uuid.uuid4()
        self.table.share_token = self.token
        self.table.save(update_fields=["share_token"])
        self.client = APIClient()

    def test_unauthenticated_access_with_valid_token(self):
        response = self.client.get(f"/api/v1/shared-tables/{self.token}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], self.table.name)
        self.assertEqual(response.data["sample_count"], self.table.sample_count)
        self.assertIn("headers", response.data)
        self.assertIn("rows", response.data)

    def test_response_contains_column_headers(self):
        response = self.client.get(f"/api/v1/shared-tables/{self.token}/")
        headers = response.data["headers"]
        self.assertTrue(any("source name" in h.lower() for h in headers))
        self.assertTrue(any("organism" in h.lower() for h in headers))

    def test_invalid_token_returns_404(self):
        response = self.client.get(f"/api/v1/shared-tables/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_table_without_token_not_accessible(self):
        self.table.share_token = None
        self.table.save(update_fields=["share_token"])
        response = self.client.get(f"/api/v1/shared-tables/{self.token}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authenticated_user_can_also_access(self):
        other = User.objects.create_user(username="visitor", password="pw")
        self.client.force_authenticate(user=other)
        response = self.client.get(f"/api/v1/shared-tables/{self.token}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
