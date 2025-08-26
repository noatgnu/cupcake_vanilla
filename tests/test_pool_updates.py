"""
Tests for pool metadata updates and pooled sample column synchronization.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from ccv.models import LabGroup, MetadataColumn, MetadataTable, SamplePool
from ccv.utils import update_pooled_sample_column_for_table


class PoolUpdateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test table
        self.table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=10
        )

        # Create pooled sample column
        self.pooled_column = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[pooled sample]",
            type="characteristics",
            column_position=0,
            value="not pooled",
        )

    def test_pooled_sample_column_update_on_pool_creation(self):
        """Test that pooled sample column updates when pool is created."""
        # Create a pool via API
        url = "/api/v1/sample-pools/"
        data = {
            "metadata_table": self.table.id,
            "pool_name": "Test Pool",
            "pooled_only_samples": [1, 2, 3],
            "pooled_and_independent_samples": [],
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check that pooled sample column was updated
        self.pooled_column.refresh_from_db()

        # Should have modifiers for the pooled samples
        modifiers = self.pooled_column.modifiers or []
        sn_modifier = next((m for m in modifiers if m["value"].startswith("SN=")), None)
        self.assertIsNotNone(sn_modifier)
        self.assertEqual(sn_modifier["value"], "SN=Test Pool")

    def test_pooled_sample_column_update_on_pool_modification(self):
        """Test that pooled sample column updates when pool is modified."""
        # Create initial pool
        pool = SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        # Update pool via API
        url = f"/api/v1/sample-pools/{pool.id}/"
        data = {"pooled_only_samples": [1, 2, 3, 4], "pooled_and_independent_samples": []}  # Add more samples

        response = self.client.patch(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that pooled sample column was updated
        self.pooled_column.refresh_from_db()
        modifiers = self.pooled_column.modifiers or []
        sn_modifier = next((m for m in modifiers if m["value"].startswith("SN=")), None)

        # Should include the new samples in range
        self.assertIn("1", sn_modifier["samples"])
        self.assertIn("4", sn_modifier["samples"])

    def test_update_pooled_sample_column_for_table_function(self):
        """Test the utility function for updating pooled sample columns."""
        # Create pools
        SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Pool 1",
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Pool 2",
            pooled_only_samples=[7, 8],
            pooled_and_independent_samples=[4, 5],
            created_by=self.user,
        )

        # Call the update function
        update_pooled_sample_column_for_table(self.table)

        # Check results
        self.pooled_column.refresh_from_db()
        modifiers = self.pooled_column.modifiers or []

        # Should have modifiers for both pools
        pool1_modifier = next((m for m in modifiers if "Pool 1" in m["value"]), None)
        pool2_modifier = next((m for m in modifiers if "Pool 2" in m["value"]), None)

        self.assertIsNotNone(pool1_modifier)
        self.assertIsNotNone(pool2_modifier)

        # Pool 1 samples (1,2,3) should be SN=Pool 1
        self.assertEqual(pool1_modifier["value"], "SN=Pool 1")
        self.assertIn("1", pool1_modifier["samples"])
        self.assertIn("3", pool1_modifier["samples"])

        # Pool 2 pooled_only samples (7,8) should be SN=Pool 2
        self.assertEqual(pool2_modifier["value"], "SN=Pool 2")
        self.assertIn("7", pool2_modifier["samples"])
        self.assertIn("8", pool2_modifier["samples"])

    def test_pool_metadata_creation(self):
        """Test that pool metadata columns are created correctly."""
        from ccv.utils import create_pool_metadata_from_table_columns

        # Add more columns to the table
        MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[organism]",
            type="characteristics",
            column_position=1,
            value="homo sapiens",
        )

        # Create pool
        pool = SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        # Create pool metadata
        create_pool_metadata_from_table_columns(pool)

        # Check that pool has metadata columns
        pool_columns = pool.metadata_columns.all()
        self.assertEqual(pool_columns.count(), 2)  # pooled sample + organism

        # Check that pooled sample column has correct SN value
        pool_pooled_column = pool.metadata_columns.filter(name__icontains="pooled sample").first()
        self.assertIsNotNone(pool_pooled_column)
        self.assertEqual(pool_pooled_column.value, "SN=Test Pool")
