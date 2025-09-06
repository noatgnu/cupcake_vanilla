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
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
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
            "pool_name": f"Test Pool {self.table.id}",  # Make unique per table
            "pooled_only_samples": [1, 2, 3],
            "pooled_and_independent_samples": [],
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        if response.status_code != status.HTTP_201_CREATED:
            print(f"POST failed with {response.status_code}: {response.content}")
            print(f"Data sent: {data}")
            print(f"Table sample_count: {self.table.sample_count}")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check that pooled sample column was updated
        self.pooled_column.refresh_from_db()

        # Should have modifiers for the pooled samples
        modifiers = self.pooled_column.modifiers or []
        sn_modifier = next((m for m in modifiers if m["value"].startswith("SN=")), None)
        self.assertIsNotNone(sn_modifier)
        # SN value should contain the source names of pooled samples, not pool name
        self.assertTrue(sn_modifier["value"].startswith("SN="))
        self.assertIn("sample", sn_modifier["value"])  # Should contain sample source names

    def test_pooled_sample_column_update_on_pool_modification(self):
        """Test that pooled sample column updates when pool is modified."""
        # Create initial pool
        pool = SamplePool.objects.create(
            metadata_table=self.table,
            pool_name="Test Pool Unique",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        # Update pool via API
        url = f"/api/v1/sample-pools/{pool.id}/"
        data = {"pooled_only_samples": [1, 2, 3, 4], "pooled_and_independent_samples": []}  # Add more samples

        import json

        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        if response.status_code != status.HTTP_200_OK:
            print(f"PATCH failed with {response.status_code}: {response.content}")
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

        # Should have modifiers for both pools - find by checking if samples match
        pool1_modifier = None
        pool2_modifier = None
        for m in modifiers:
            # Pool 1 has samples 1,2,3 - check if any are in this modifier's samples
            if any(str(i) in m["samples"] for i in [1, 2, 3]):
                pool1_modifier = m
            # Pool 2 has samples 7,8 - check if any are in this modifier's samples
            elif any(str(i) in m["samples"] for i in [7, 8]):
                pool2_modifier = m

        self.assertIsNotNone(pool1_modifier)
        self.assertIsNotNone(pool2_modifier)

        # Pool 1 samples (1,2,3) should be SN=source names, not pool name
        self.assertTrue(pool1_modifier["value"].startswith("SN="))
        self.assertIn(
            "sample", pool1_modifier["value"]
        )  # Should contain source names like "sample 1,sample 2,sample 3"
        self.assertIn("1", pool1_modifier["samples"])
        self.assertIn("3", pool1_modifier["samples"])

        # Pool 2 pooled_only samples (7,8) should be SN=source names, not pool name
        self.assertTrue(pool2_modifier["value"].startswith("SN="))
        self.assertIn("sample", pool2_modifier["value"])  # Should contain source names like "sample 7,sample 8"
        self.assertIn("7", pool2_modifier["samples"])
        self.assertIn("8", pool2_modifier["samples"])

    def test_pool_metadata_creation(self):
        """Test that pool metadata columns are created correctly."""
        from ccv.tasks.import_utils import create_pool_metadata_from_table_columns

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
            pool_name="Test Pool Unique",
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
        # SN value should contain source names of pooled samples, not pool name
        self.assertTrue(pool_pooled_column.value.startswith("SN="))
        self.assertIn("sample", pool_pooled_column.value)
