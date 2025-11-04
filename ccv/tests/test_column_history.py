"""
Test cases for MetadataColumn history endpoint.
"""

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import LabGroup
from ccv.models import MetadataColumn, MetadataTable

User = get_user_model()


class MetadataColumnHistoryTest(APITestCase):
    """Test cases for column history endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.table = MetadataTable.objects.create(
            name="Test Table", sample_count=100, owner=self.user, lab_group=self.lab_group
        )
        self.column = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="test_column",
            type="text",
            value="initial_value",
            column_position=1,
        )
        self.client.force_authenticate(user=self.user)

    def test_history_endpoint_exists(self):
        """Test that history endpoint is accessible."""
        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_history_returns_creation_record(self):
        """Test that history includes the creation record."""
        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("history", response.data)
        self.assertGreater(len(response.data["history"]), 0)

        first_record = response.data["history"][-1]
        self.assertEqual(first_record["history_type"], "Created")
        self.assertEqual(first_record["snapshot"]["name"], "test_column")
        self.assertEqual(first_record["snapshot"]["value"], "initial_value")

    def test_history_tracks_value_changes(self):
        """Test that value changes are tracked in history."""
        self.column.value = "updated_value"
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

        latest_record = response.data["history"][0]
        self.assertEqual(latest_record["history_type"], "Changed")
        self.assertEqual(latest_record["snapshot"]["value"], "updated_value")

        value_change = next((c for c in latest_record["changes"] if c["field"] == "value"), None)
        self.assertIsNotNone(value_change)
        self.assertEqual(value_change["old_value"], "initial_value")
        self.assertEqual(value_change["new_value"], "updated_value")

    def test_history_tracks_multiple_field_changes(self):
        """Test that multiple field changes are tracked."""
        self.column.value = "new_value"
        self.column.mandatory = True
        self.column.hidden = True
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        latest_record = response.data["history"][0]
        changes = latest_record["changes"]

        self.assertEqual(len(changes), 3)

        change_fields = {c["field"] for c in changes}
        self.assertIn("value", change_fields)
        self.assertIn("mandatory", change_fields)
        self.assertIn("hidden", change_fields)

    def test_history_tracks_modifier_changes(self):
        """Test that modifier changes are tracked."""
        self.column.modifiers = [{"samples": "1-5", "value": "modified_value"}]
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        latest_record = response.data["history"][0]
        modifier_change = next((c for c in latest_record["changes"] if c["field"] == "modifiers"), None)

        self.assertIsNotNone(modifier_change)
        self.assertEqual(modifier_change["old_value"], [])
        self.assertEqual(len(modifier_change["new_value"]), 1)

    def test_history_pagination(self):
        """Test history pagination with limit and offset."""
        for i in range(10):
            self.column.value = f"value_{i}"
            self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/?limit=5&offset=0"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["history"]), 5)
        self.assertEqual(response.data["limit"], 5)
        self.assertEqual(response.data["offset"], 0)
        self.assertTrue(response.data["has_more"])
        self.assertEqual(response.data["count"], 11)

    def test_history_pagination_second_page(self):
        """Test fetching second page of history."""
        for i in range(10):
            self.column.value = f"value_{i}"
            self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/?limit=5&offset=5"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["history"]), 5)
        self.assertTrue(response.data["has_more"])

    def test_history_max_limit(self):
        """Test that limit is capped at 200."""
        url = f"/api/v1/metadata-columns/{self.column.id}/history/?limit=500"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["limit"], 200)

    def test_history_includes_user_information(self):
        """Test that history includes user who made the change."""
        self.column.value = "updated_by_user"
        self.column._change_reason = "Testing user tracking"
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        creation_record = response.data["history"][-1]

        if creation_record["history_user"]:
            self.assertEqual(creation_record["history_user"], self.user.username)
            self.assertEqual(creation_record["history_user_id"], self.user.id)

    def test_history_chronological_order(self):
        """Test that history is returned in reverse chronological order."""
        for i in range(5):
            self.column.value = f"value_{i}"
            self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        history = response.data["history"]
        dates = [record["history_date"] for record in history]

        for i in range(len(dates) - 1):
            self.assertGreaterEqual(dates[i], dates[i + 1])

    def test_history_snapshot_completeness(self):
        """Test that history snapshot includes all important fields."""
        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        snapshot = response.data["history"][0]["snapshot"]
        required_fields = [
            "name",
            "type",
            "value",
            "column_position",
            "mandatory",
            "hidden",
            "readonly",
            "modifiers",
            "ontology_type",
            "not_applicable",
            "not_available",
        ]

        for field in required_fields:
            self.assertIn(field, snapshot)

    def test_history_permission_denied_for_unauthenticated(self):
        """Test that unauthenticated users cannot access history."""
        self.client.force_authenticate(user=None)
        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_history_permission_denied_for_non_owner(self):
        """Test that users without permission cannot access history."""
        other_user = User.objects.create_user(username="other", email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=other_user)

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_history_no_changes_returns_empty_changes_list(self):
        """Test that first record has empty changes list."""
        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        first_record = response.data["history"][-1]
        self.assertEqual(len(first_record["changes"]), 0)

    def test_history_tracks_ontology_type_changes(self):
        """Test that ontology_type changes are tracked."""
        self.column.ontology_type = "species"
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        latest_record = response.data["history"][0]
        ontology_change = next((c for c in latest_record["changes"] if c["field"] == "ontology_type"), None)

        self.assertIsNotNone(ontology_change)
        self.assertIsNone(ontology_change["old_value"])
        self.assertEqual(ontology_change["new_value"], "species")

    def test_history_complex_modifier_updates(self):
        """Test tracking complex modifier changes."""
        self.column.modifiers = [
            {"samples": "1-10", "value": "value_a"},
            {"samples": "11-20", "value": "value_b"},
        ]
        self.column.save()

        self.column.modifiers = [
            {"samples": "1-10", "value": "value_a"},
            {"samples": "11-20", "value": "value_c"},
            {"samples": "21-30", "value": "value_d"},
        ]
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        latest_record = response.data["history"][0]
        modifier_change = next((c for c in latest_record["changes"] if c["field"] == "modifiers"), None)

        self.assertIsNotNone(modifier_change)
        self.assertEqual(len(modifier_change["new_value"]), 3)

    def test_history_default_pagination(self):
        """Test that default pagination returns 50 records."""
        for i in range(60):
            self.column.value = f"value_{i}"
            self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["history"]), 50)
        self.assertEqual(response.data["limit"], 50)

    def test_history_column_position_changes(self):
        """Test that column_position changes are tracked."""
        self.column.column_position = 5
        self.column.save()

        url = f"/api/v1/metadata-columns/{self.column.id}/history/"
        response = self.client.get(url)

        latest_record = response.data["history"][0]
        position_change = next((c for c in latest_record["changes"] if c["field"] == "column_position"), None)

        self.assertIsNotNone(position_change)
        self.assertEqual(position_change["old_value"], 1)
        self.assertEqual(position_change["new_value"], 5)
