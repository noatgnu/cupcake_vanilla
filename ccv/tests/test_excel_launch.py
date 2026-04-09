"""
Tests for Excel launch code functionality.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.signing import BadSignature, SignatureExpired
from django.test import TestCase

from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from ccc.models import LabGroup

from ..excel_launch_utils import EXCEL_LAUNCH_MAX_AGE, create_launch_code, verify_launch_code
from ..models import MetadataTable


class LaunchCodeUtilTests(TestCase):
    """Tests for the launch code signing utilities."""

    def test_create_and_verify_code(self):
        """Valid code should decode to original user_id and table_id."""
        code = create_launch_code(user_id=123, table_id=456)
        payload = verify_launch_code(code)

        self.assertEqual(payload["user_id"], 123)
        self.assertEqual(payload["table_id"], 456)

    def test_code_uniqueness(self):
        """Each code should be unique due to nonce."""
        code1 = create_launch_code(user_id=123, table_id=456)
        code2 = create_launch_code(user_id=123, table_id=456)

        self.assertNotEqual(code1, code2)

    @freeze_time("2024-01-15 10:00:00")
    def test_expired_code(self):
        """Code created in the past should raise SignatureExpired."""
        code = create_launch_code(user_id=123, table_id=456)

        with freeze_time("2024-01-15 10:06:00"):
            with self.assertRaises(SignatureExpired):
                verify_launch_code(code)

    @freeze_time("2024-01-15 10:00:00")
    def test_code_valid_within_window(self):
        """Code should be valid within the expiration window."""
        code = create_launch_code(user_id=123, table_id=456)

        with freeze_time("2024-01-15 10:04:00"):
            payload = verify_launch_code(code)
            self.assertEqual(payload["user_id"], 123)

    def test_tampered_code(self):
        """Tampered code should raise BadSignature."""
        code = create_launch_code(user_id=123, table_id=456)
        tampered = code[:-4] + "XXXX"

        with self.assertRaises(BadSignature):
            verify_launch_code(tampered)

    def test_invalid_code(self):
        """Completely invalid code should raise BadSignature."""
        with self.assertRaises(BadSignature):
            verify_launch_code("COMPLETELY_INVALID_CODE")

    def test_empty_code(self):
        """Empty code should raise BadSignature."""
        with self.assertRaises(BadSignature):
            verify_launch_code("")


class ExcelLaunchAPITests(TestCase):
    """Tests for the Excel launch API endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass",
            email="test@example.com",
        )
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        self.lab_group.members.add(self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_create_launch_code_authenticated(self):
        """Authenticated user can create launch code for accessible table."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/v1/excel-launch/", {"tableId": self.table.id}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("code", response.data)
        self.assertEqual(response.data["tableId"], self.table.id)
        self.assertEqual(response.data["tableName"], self.table.name)
        self.assertEqual(response.data["expiresIn"], EXCEL_LAUNCH_MAX_AGE)

    def test_create_launch_code_unauthenticated(self):
        """Unauthenticated request should return 401."""
        response = self.client.post("/api/v1/excel-launch/", {"tableId": self.table.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_launch_code_missing_table_id(self):
        """Missing tableId should return 400."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/v1/excel-launch/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_launch_code_invalid_table(self):
        """Non-existent table should return 404."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/v1/excel-launch/", {"tableId": 99999}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_launch_code_no_access(self):
        """User without table access should get 403."""
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        self.client.force_authenticate(user=other_user)

        response = self.client.post("/api/v1/excel-launch/", {"tableId": self.table.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_launch_code_success(self, mock_throttle):
        """Valid code should return JWT tokens and table info."""
        code = create_launch_code(self.user.id, self.table.id)

        response = self.client.post("/api/v1/excel-launch/claim/", {"code": code}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["tableId"], self.table.id)
        self.assertEqual(response.data["tableName"], self.table.name)
        self.assertEqual(response.data["user"]["id"], self.user.id)
        self.assertEqual(response.data["user"]["username"], self.user.username)

    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_launch_code_missing_code(self, mock_throttle):
        """Missing code should return 400."""
        response = self.client.post("/api/v1/excel-launch/claim/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_invalid_code(self, mock_throttle):
        """Invalid code should return 400."""
        response = self.client.post("/api/v1/excel-launch/claim/", {"code": "INVALID_CODE"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @freeze_time("2024-01-15 10:00:00")
    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_expired_code(self, mock_throttle):
        """Expired code should return 410."""
        code = create_launch_code(self.user.id, self.table.id)

        with freeze_time("2024-01-15 10:06:00"):
            response = self.client.post("/api/v1/excel-launch/claim/", {"code": code}, format="json")

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertIn("expired", response.data["detail"].lower())

    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_code_nonexistent_user(self, mock_throttle):
        """Code referencing a non-existent user should return 400."""
        code = create_launch_code(user_id=999999, table_id=self.table.id)

        response = self.client.post("/api/v1/excel-launch/claim/", {"code": code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("ccv.excel_launch_views.LaunchCodeClaimThrottle.allow_request", return_value=True)
    def test_claim_code_deleted_table(self, mock_throttle):
        """Code for deleted table should return 404."""
        code = create_launch_code(self.user.id, self.table.id)
        self.table.delete()

        response = self.client.post("/api/v1/excel-launch/claim/", {"code": code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
