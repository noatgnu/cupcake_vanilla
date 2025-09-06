"""
Test column synchronization via API endpoints.

Tests that adding or removing columns via API endpoints properly
synchronizes with associated pools.
"""

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.models import SamplePool
from tests.factories import LabGroupFactory, MetadataTableFactory, UserFactory

User = get_user_model()


class ColumnPoolSynchronizationAPITest(APITestCase):
    """Test column synchronization via API endpoints."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.lab_group = LabGroupFactory.create_lab_group()
        self.client.force_authenticate(user=self.user)

        # Create a metadata table
        self.metadata_table = MetadataTableFactory.create_basic_table(
            user=self.user, lab_group=self.lab_group, name="API Test Table", sample_count=10
        )

        # Create sample pools
        self.pool1 = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="API Test Pool 1",
            pool_description="First pool for API testing",
            pooled_only_samples=[1, 2, 3],
            created_by=self.user,
        )

        self.pool2 = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="API Test Pool 2",
            pool_description="Second pool for API testing",
            pooled_only_samples=[4, 5, 6],
            created_by=self.user,
        )

    def test_add_column_api_synchronizes_to_pools(self):
        """Test that the add_column API endpoint synchronizes to pools."""
        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column/"
        data = {
            "column_data": {
                "name": "characteristics[organism]",
                "type": "characteristics",
                "value": "homo sapiens",
                "mandatory": True,
            }
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify column was created in main table
        self.assertEqual(self.metadata_table.columns.count(), 1)
        main_column = self.metadata_table.columns.first()
        self.assertEqual(main_column.name, "characteristics[organism]")

        # Verify column was added to both pools
        pool1_columns = self.pool1.metadata_columns.filter(name="characteristics[organism]")
        pool2_columns = self.pool2.metadata_columns.filter(name="characteristics[organism]")

        self.assertEqual(pool1_columns.count(), 1)
        self.assertEqual(pool2_columns.count(), 1)

        # Verify properties match
        pool1_column = pool1_columns.first()
        self.assertEqual(pool1_column.type, main_column.type)
        self.assertEqual(pool1_column.value, main_column.value)
        self.assertEqual(pool1_column.mandatory, main_column.mandatory)

    def test_add_column_with_auto_reorder_api_synchronizes_to_pools(self):
        """Test that the add_column_with_auto_reorder API endpoint synchronizes to pools."""
        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column_with_auto_reorder/"
        data = {
            "column_data": {"name": "source name", "type": "", "value": "sample_001", "mandatory": True},
            "auto_reorder": True,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertIn("column", response_data)
        self.assertIn("reordered", response_data)

        # Verify column was created in main table
        self.assertEqual(self.metadata_table.columns.count(), 1)
        main_column = self.metadata_table.columns.first()
        self.assertEqual(main_column.name, "source name")

        # Verify column was added to both pools
        pool1_columns = self.pool1.metadata_columns.filter(name="source name")
        pool2_columns = self.pool2.metadata_columns.filter(name="source name")

        self.assertEqual(pool1_columns.count(), 1)
        self.assertEqual(pool2_columns.count(), 1)

    def test_remove_column_api_synchronizes_to_pools(self):
        """Test that the remove_column API endpoint synchronizes to pools."""
        # First add a column
        column_data = {"name": "characteristics[tissue]", "type": "characteristics", "value": "liver"}
        column = self.metadata_table.add_column(column_data)

        # Verify it was added to pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[tissue]").count(), 1)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[tissue]").count(), 1)

        # Now remove it via API
        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/remove_column/"
        data = {"column_id": column.id}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify column was removed from main table
        self.assertEqual(self.metadata_table.columns.count(), 0)

        # Verify column was removed from both pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[tissue]").count(), 0)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[tissue]").count(), 0)

    def test_multiple_columns_api_operations(self):
        """Test multiple column operations via API maintain synchronization."""
        # Add multiple columns via API
        columns_to_add = [
            {"name": "source name", "type": "", "value": "sample_001"},
            {"name": "characteristics[organism]", "type": "characteristics", "value": "homo sapiens"},
            {"name": "assay name", "type": "", "value": "assay_001"},
        ]

        column_ids = []
        for column_data in columns_to_add:
            url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column/"
            data = {"column_data": column_data}
            response = self.client.post(url, data, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Get the column ID from the response
            column_id = response.json()["column"]["id"]
            column_ids.append(column_id)

        # Verify all columns were added to main table
        self.assertEqual(self.metadata_table.columns.count(), 3)

        # Verify all columns were added to pools
        for column_data in columns_to_add:
            self.assertEqual(self.pool1.metadata_columns.filter(name=column_data["name"]).count(), 1)
            self.assertEqual(self.pool2.metadata_columns.filter(name=column_data["name"]).count(), 1)

        # Remove the middle column via API
        middle_column_id = column_ids[1]
        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/remove_column/"
        data = {"column_id": middle_column_id}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify it was removed from main table
        self.assertEqual(self.metadata_table.columns.count(), 2)

        # Verify it was removed from pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[organism]").count(), 0)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[organism]").count(), 0)

        # Verify other columns remain in pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="source name").count(), 1)
        self.assertEqual(self.pool1.metadata_columns.filter(name="assay name").count(), 1)
        self.assertEqual(self.pool2.metadata_columns.filter(name="source name").count(), 1)
        self.assertEqual(self.pool2.metadata_columns.filter(name="assay name").count(), 1)

    def test_api_permissions_still_work(self):
        """Test that API permissions are still enforced with synchronization."""
        # Create another user who doesn't have access to this table
        other_user = UserFactory.create_user(username="other_user")
        self.client.force_authenticate(user=other_user)

        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column/"
        data = {"column_data": {"name": "test column", "type": "test", "value": "test value"}}

        response = self.client.post(url, data, format="json")

        # Should get permission denied (403) or not found (404) due to filtering
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Verify no columns were added anywhere
        self.assertEqual(self.metadata_table.columns.count(), 0)
        self.assertEqual(self.pool1.metadata_columns.count(), 0)
        self.assertEqual(self.pool2.metadata_columns.count(), 0)

    def test_synchronization_with_table_having_no_pools(self):
        """Test that API endpoints work normally when table has no pools."""
        # Create a table with no pools
        table_no_pools = MetadataTableFactory.create_basic_table(user=self.user, name="Table Without Pools")

        url = f"/api/v1/metadata-tables/{table_no_pools.id}/add_column/"
        data = {"column_data": {"name": "test column", "type": "test", "value": "test value"}}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify column was created in main table
        self.assertEqual(table_no_pools.columns.count(), 1)
        column = table_no_pools.columns.first()
        self.assertEqual(column.name, "test column")

        # Remove the column should also work
        url = f"/api/v1/metadata-tables/{table_no_pools.id}/remove_column/"
        data = {"column_id": column.id}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(table_no_pools.columns.count(), 0)
