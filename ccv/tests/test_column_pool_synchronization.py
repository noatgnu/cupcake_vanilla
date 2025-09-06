"""
Test column synchronization between metadata tables and their associated pools.

Tests that adding or removing columns from a metadata table automatically
synchronizes with all pools belonging to that table.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccv.models import SamplePool
from tests.factories import LabGroupFactory, MetadataTableFactory, UserFactory

User = get_user_model()


class ColumnPoolSynchronizationTest(TestCase):
    """Test that column operations synchronize between tables and pools."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.lab_group = LabGroupFactory.create_lab_group()

        # Create a metadata table
        self.metadata_table = MetadataTableFactory.create_basic_table(
            user=self.user, lab_group=self.lab_group, name="Test Synchronization Table", sample_count=10
        )

        # Create a couple of sample pools
        self.pool1 = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Pool 1",
            pool_description="First test pool",
            pooled_only_samples=[1, 2, 3],
            created_by=self.user,
        )

        self.pool2 = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Pool 2",
            pool_description="Second test pool",
            pooled_only_samples=[4, 5, 6],
            created_by=self.user,
        )

    def test_add_column_synchronizes_to_pools(self):
        """Test that adding a column to a table adds it to all pools."""
        initial_pool1_columns = self.pool1.metadata_columns.count()
        initial_pool2_columns = self.pool2.metadata_columns.count()

        # Add a column to the metadata table
        column_data = {
            "name": "characteristics[organism]",
            "type": "characteristics",
            "value": "homo sapiens",
            "mandatory": True,
        }

        column = self.metadata_table.add_column(column_data)

        # Verify column was created in main table
        self.assertEqual(self.metadata_table.columns.count(), 1)
        self.assertEqual(column.name, "characteristics[organism]")

        # Verify column was added to both pools
        self.assertEqual(self.pool1.metadata_columns.count(), initial_pool1_columns + 1)
        self.assertEqual(self.pool2.metadata_columns.count(), initial_pool2_columns + 1)

        # Verify the pool columns have the same properties as the main column
        pool1_column = self.pool1.metadata_columns.filter(name="characteristics[organism]").first()
        pool2_column = self.pool2.metadata_columns.filter(name="characteristics[organism]").first()

        self.assertIsNotNone(pool1_column)
        self.assertIsNotNone(pool2_column)
        self.assertEqual(pool1_column.name, column.name)
        self.assertEqual(pool1_column.type, column.type)
        self.assertEqual(pool1_column.value, column.value)
        self.assertEqual(pool2_column.name, column.name)
        self.assertEqual(pool2_column.type, column.type)
        self.assertEqual(pool2_column.value, column.value)

    def test_remove_column_synchronizes_to_pools(self):
        """Test that removing a column from a table removes it from all pools."""
        # First add a column to establish synchronization
        column_data = {
            "name": "characteristics[tissue]",
            "type": "characteristics",
            "value": "liver",
            "mandatory": False,
        }

        column = self.metadata_table.add_column(column_data)

        # Verify it was added to pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[tissue]").count(), 1)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[tissue]").count(), 1)

        # Now remove the column
        success = self.metadata_table.remove_column(column.id)
        self.assertTrue(success)

        # Verify column was removed from main table
        self.assertEqual(self.metadata_table.columns.count(), 0)

        # Verify column was removed from both pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[tissue]").count(), 0)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[tissue]").count(), 0)

    def test_add_column_with_auto_reorder_synchronizes_to_pools(self):
        """Test that add_column_with_auto_reorder also synchronizes to pools."""
        # Add a column using the auto-reorder method
        column_data = {"name": "source name", "type": "", "value": "sample_001", "mandatory": True}

        result = self.metadata_table.add_column_with_auto_reorder(column_data, auto_reorder=False)
        column = result["column"]

        # Verify column was created in main table
        self.assertEqual(self.metadata_table.columns.count(), 1)

        # Verify column was added to both pools
        pool1_columns = self.pool1.metadata_columns.filter(name="source name")
        pool2_columns = self.pool2.metadata_columns.filter(name="source name")

        self.assertEqual(pool1_columns.count(), 1)
        self.assertEqual(pool2_columns.count(), 1)

        pool1_column = pool1_columns.first()
        self.assertEqual(pool1_column.name, column.name)
        self.assertEqual(pool1_column.type, column.type)
        self.assertEqual(pool1_column.value, column.value)

    def test_multiple_columns_synchronization(self):
        """Test synchronization with multiple columns."""
        columns_data = [
            {"name": "source name", "type": "", "value": "sample_001"},
            {"name": "characteristics[organism]", "type": "characteristics", "value": "homo sapiens"},
            {"name": "assay name", "type": "", "value": "assay_001"},
        ]

        created_columns = []
        for column_data in columns_data:
            column = self.metadata_table.add_column(column_data)
            created_columns.append(column)

        # Verify all columns were created in main table
        self.assertEqual(self.metadata_table.columns.count(), 3)

        # Verify all columns were added to both pools
        for column_data in columns_data:
            self.assertEqual(self.pool1.metadata_columns.filter(name=column_data["name"]).count(), 1)
            self.assertEqual(self.pool2.metadata_columns.filter(name=column_data["name"]).count(), 1)

        # Remove the middle column
        middle_column = created_columns[1]
        success = self.metadata_table.remove_column(middle_column.id)
        self.assertTrue(success)

        # Verify it was removed from main table
        self.assertEqual(self.metadata_table.columns.count(), 2)

        # Verify it was removed from pools
        self.assertEqual(self.pool1.metadata_columns.filter(name="characteristics[organism]").count(), 0)
        self.assertEqual(self.pool2.metadata_columns.filter(name="characteristics[organism]").count(), 0)

        # Verify other columns are still there
        self.assertEqual(self.pool1.metadata_columns.filter(name="source name").count(), 1)
        self.assertEqual(self.pool1.metadata_columns.filter(name="assay name").count(), 1)

    def test_no_pools_scenario(self):
        """Test that column operations work normally when table has no pools."""
        # Create a table with no pools
        table_no_pools = MetadataTableFactory.create_basic_table(user=self.user, name="Table Without Pools")

        # Add a column - should work normally
        column_data = {"name": "test column", "type": "test", "value": "test value"}

        column = table_no_pools.add_column(column_data)

        # Verify column was created
        self.assertEqual(table_no_pools.columns.count(), 1)
        self.assertEqual(column.name, "test column")

        # Remove the column - should work normally
        success = table_no_pools.remove_column(column.id)
        self.assertTrue(success)
        self.assertEqual(table_no_pools.columns.count(), 0)

    def test_pool_column_properties_match_main_column(self):
        """Test that pool columns have all the same properties as main columns."""
        # Add a column with various properties
        column_data = {
            "name": "characteristics[disease]",
            "type": "characteristics",
            "value": "cancer",
            "modifiers": [{"samples": "1,2", "value": "breast cancer"}],
            "mandatory": True,
            "hidden": False,
            "ontology_type": "mondo",
            "staff_only": False,
            "readonly": False,
            "auto_generated": False,
            "not_applicable": False,
        }

        main_column = self.metadata_table.add_column(column_data)

        # Check pool columns have matching properties
        pool_column = self.pool1.metadata_columns.filter(name="characteristics[disease]").first()

        self.assertIsNotNone(pool_column)
        self.assertEqual(pool_column.name, main_column.name)
        self.assertEqual(pool_column.type, main_column.type)
        self.assertEqual(pool_column.value, main_column.value)
        self.assertEqual(pool_column.modifiers, main_column.modifiers)
        self.assertEqual(pool_column.mandatory, main_column.mandatory)
        self.assertEqual(pool_column.hidden, main_column.hidden)
        self.assertEqual(pool_column.ontology_type, main_column.ontology_type)
        self.assertEqual(pool_column.staff_only, main_column.staff_only)
        self.assertEqual(pool_column.readonly, main_column.readonly)
        self.assertEqual(pool_column.auto_generated, main_column.auto_generated)
        self.assertEqual(pool_column.not_applicable, main_column.not_applicable)
