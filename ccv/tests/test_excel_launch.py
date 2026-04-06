"""
Tests for Excel launch code functionality.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from ccc.models import LabGroup

from ..models import ExcelLaunchCode, MetadataTable


class ExcelLaunchCodeModelTests(TestCase):
    """Tests for the ExcelLaunchCode model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_generate_code_length(self):
        """Test that generated codes have the correct length."""
        code = ExcelLaunchCode.generate_code()
        self.assertEqual(len(code), 6)

    def test_generate_code_characters(self):
        """Test that generated codes only contain valid characters."""
        valid_chars = set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        for _ in range(100):
            code = ExcelLaunchCode.generate_code()
            self.assertTrue(all(c in valid_chars for c in code))

    def test_is_expired(self):
        """Test expiration detection."""
        expired_code = ExcelLaunchCode.objects.create(
            code="EXPIR1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertTrue(expired_code.is_expired())

        valid_code = ExcelLaunchCode.objects.create(
            code="VALID1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(valid_code.is_expired())

    def test_is_claimed(self):
        """Test claimed status detection."""
        unclaimed = ExcelLaunchCode.objects.create(
            code="UNCLM1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(unclaimed.is_claimed())

        claimed = ExcelLaunchCode.objects.create(
            code="CLAIM1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
            claimed_at=timezone.now(),
        )
        self.assertTrue(claimed.is_claimed())

    def test_is_valid(self):
        """Test validity check combines expiration and claimed status."""
        valid = ExcelLaunchCode.objects.create(
            code="VALID2",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertTrue(valid.is_valid())

        expired = ExcelLaunchCode.objects.create(
            code="EXPIR2",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(expired.is_valid())

        claimed = ExcelLaunchCode.objects.create(
            code="CLAIM2",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
            claimed_at=timezone.now(),
        )
        self.assertFalse(claimed.is_valid())


class ExcelLaunchCreateViewTests(TestCase):
    """Tests for creating launch codes."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.lab_group.members.add(self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_create_launch_code_requires_auth(self):
        """Test that creating a launch code requires authentication."""
        response = self.client.post("/api/v1/excel-launch/", {"tableId": self.table.id})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_launch_code_success(self):
        """Test successful launch code creation."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/v1/excel-launch/",
            {"tableId": self.table.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("code", response.data)
        self.assertEqual(len(response.data["code"]), 6)
        self.assertEqual(response.data["tableId"], self.table.id)
        self.assertEqual(response.data["tableName"], self.table.name)

    def test_create_launch_code_table_not_found(self):
        """Test error when table doesn't exist."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/v1/excel-launch/",
            {"tableId": 99999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_launch_code_no_access(self):
        """Test error when user doesn't have access to the table."""
        other_user = User.objects.create_user(username="other", password="pass")
        other_lab = LabGroup.objects.create(name="Other Lab", creator=other_user)
        other_table = MetadataTable.objects.create(
            name="Other Table",
            owner=other_user,
            lab_group=other_lab,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/v1/excel-launch/",
            {"tableId": other_table.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_launch_code_missing_table_id(self):
        """Test error when tableId is missing."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/v1/excel-launch/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
class ExcelLaunchClaimViewTests(TestCase):
    """Tests for claiming launch codes."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass",
            email="test@example.com",
        )
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_claim_launch_code_success(self, mock_throttle):
        """Test successful launch code claim."""
        code = ExcelLaunchCode.objects.create(
            code="ABC123",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post(f"/api/v1/excel-launch/{code.code}/claim/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["tableId"], self.table.id)
        self.assertEqual(response.data["tableName"], self.table.name)
        self.assertEqual(response.data["user"]["id"], self.user.id)
        self.assertEqual(response.data["user"]["username"], self.user.username)

    def test_claim_launch_code_case_insensitive(self, mock_throttle):
        """Test that code matching is case insensitive."""
        ExcelLaunchCode.objects.create(
            code="ABC123",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post("/api/v1/excel-launch/abc123/claim/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_claim_launch_code_invalid(self, mock_throttle):
        """Test error for invalid code."""
        response = self.client.post("/api/v1/excel-launch/INVALID/claim/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_claim_launch_code_already_claimed(self, mock_throttle):
        """Test error when code has already been claimed."""
        code = ExcelLaunchCode.objects.create(
            code="ABC123",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
            claimed_at=timezone.now(),
        )

        response = self.client.post(f"/api/v1/excel-launch/{code.code}/claim/")
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_claim_launch_code_expired(self, mock_throttle):
        """Test error when code has expired."""
        code = ExcelLaunchCode.objects.create(
            code="ABC123",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.post(f"/api/v1/excel-launch/{code.code}/claim/")
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_cannot_claim_twice(self, mock_throttle):
        """Test that a code cannot be claimed twice."""
        code = ExcelLaunchCode.objects.create(
            code="ABC123",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response1 = self.client.post(f"/api/v1/excel-launch/{code.code}/claim/")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        response2 = self.client.post(f"/api/v1/excel-launch/{code.code}/claim/")
        self.assertEqual(response2.status_code, status.HTTP_410_GONE)


class ExcelLaunchPendingViewTests(TestCase):
    """Tests for getting pending launch codes."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_pending_requires_auth(self):
        """Test that getting pending codes requires authentication."""
        response = self.client.get("/api/v1/excel-launch/pending/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_returns_most_recent(self):
        """Test that the most recent pending code is returned."""
        self.client.force_authenticate(user=self.user)

        ExcelLaunchCode.objects.create(
            code="OLDER1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        newer = ExcelLaunchCode.objects.create(
            code="NEWER1",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.get("/api/v1/excel-launch/pending/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], newer.code)

    def test_pending_excludes_claimed(self):
        """Test that claimed codes are excluded."""
        self.client.force_authenticate(user=self.user)

        ExcelLaunchCode.objects.create(
            code="CLAIM3",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
            claimed_at=timezone.now(),
        )

        response = self.client.get("/api/v1/excel-launch/pending/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_pending_excludes_expired(self):
        """Test that expired codes are excluded."""
        self.client.force_authenticate(user=self.user)

        ExcelLaunchCode.objects.create(
            code="EXPIR3",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get("/api/v1/excel-launch/pending/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_no_pending_codes(self):
        """Test response when user has no pending codes."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/excel-launch/pending/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class ExcelLaunchDeleteViewTests(TestCase):
    """Tests for deleting launch codes."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_delete_requires_auth(self):
        """Test that deleting a code requires authentication."""
        response = self.client.delete("/api/v1/excel-launch/ABC123/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_success(self):
        """Test successful deletion of a launch code."""
        self.client.force_authenticate(user=self.user)

        code = ExcelLaunchCode.objects.create(
            code="DELETE",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.delete(f"/api/v1/excel-launch/{code.code}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ExcelLaunchCode.objects.filter(code=code.code).exists())

    def test_delete_other_users_code(self):
        """Test that users cannot delete other users' codes."""
        other_user = User.objects.create_user(username="other", password="pass")

        code = ExcelLaunchCode.objects.create(
            code="OTHER1",
            user=other_user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/v1/excel-launch/{code.code}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(ExcelLaunchCode.objects.filter(code=code.code).exists())

    def test_delete_claimed_code(self):
        """Test that claimed codes cannot be deleted."""
        self.client.force_authenticate(user=self.user)

        code = ExcelLaunchCode.objects.create(
            code="CLAIMD",
            user=self.user,
            table=self.table,
            expires_at=timezone.now() + timedelta(minutes=5),
            claimed_at=timezone.now(),
        )

        response = self.client.delete(f"/api/v1/excel-launch/{code.code}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_nonexistent(self):
        """Test deleting a code that doesn't exist."""
        self.client.force_authenticate(user=self.user)
        response = self.client.delete("/api/v1/excel-launch/NOCODE/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
