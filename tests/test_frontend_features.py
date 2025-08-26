"""
Tests for new frontend features like column visibility toggle and filtering.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from ccv.models import LabGroup, MetadataColumn, MetadataTable


class FrontendFeaturesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test table with columns
        self.table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        self.column1 = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[organism]",
            type="characteristics",
            column_position=0,
            hidden=False,
        )

        self.column2 = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[organism part]",
            type="characteristics",
            column_position=1,
            hidden=False,
        )

    def test_toggle_column_visibility(self):
        """Test that column visibility can be toggled via API."""
        url = f"/api/v1/metadata-columns/{self.column1.id}/"

        # Toggle to hidden
        response = self.client.patch(url, {"hidden": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.column1.refresh_from_db()
        self.assertTrue(self.column1.hidden)

        # Toggle back to visible
        response = self.client.patch(url, {"hidden": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.column1.refresh_from_db()
        self.assertFalse(self.column1.hidden)

    def test_hidden_column_sync_signal(self):
        """Test that hidden property syncs to pool columns via signal."""
        # Create a sample pool
        from ccv.models import SamplePool

        pool = SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        # Create pool metadata columns
        from ccv.utils import create_pool_metadata_from_table_columns

        create_pool_metadata_from_table_columns(pool)

        # Find the pool column that corresponds to our table column
        pool_column = pool.metadata_columns.filter(column_position=self.column1.column_position).first()
        self.assertIsNotNone(pool_column)
        self.assertFalse(pool_column.hidden)

        # Update table column hidden property
        self.column1.hidden = True
        self.column1.save()

        # Pool column should be synced
        pool_column.refresh_from_db()
        self.assertTrue(pool_column.hidden)

    def test_metadata_table_serializer_includes_sample_pools(self):
        """Test that the serializer includes sample pools with metadata columns."""
        from ccv.models import SamplePool

        SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        url = f"/api/v1/metadata-tables/{self.table.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Should include sample_pools
        self.assertIn("sample_pools", data)
        self.assertEqual(len(data["sample_pools"]), 1)
        self.assertEqual(data["sample_pools"][0]["pool_name"], "Test Pool")

        # Sample pool should include metadata_columns
        self.assertIn("metadata_columns", data["sample_pools"][0])
