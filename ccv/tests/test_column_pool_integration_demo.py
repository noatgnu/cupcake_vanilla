"""
Integration test demonstrating the complete column-pool synchronization workflow.

This test shows how the synchronization feature works in a realistic scenario
with multiple pools and various column operations.
"""

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.models import SamplePool
from tests.factories import LabGroupFactory, MetadataTableFactory, UserFactory

User = get_user_model()


class ColumnPoolIntegrationDemo(APITestCase):
    """Demonstrate the complete column-pool synchronization workflow."""

    def setUp(self):
        """Set up a realistic scenario with a metadata table and multiple pools."""
        self.user = UserFactory.create_user(username="researcher")
        self.lab_group = LabGroupFactory.create_lab_group(name="Proteomics Lab")
        self.client.force_authenticate(user=self.user)

        # Create a proteomics metadata table
        self.metadata_table = MetadataTableFactory.create_basic_table(
            user=self.user,
            lab_group=self.lab_group,
            name="Multi-Pool Proteomics Study",
            description="A proteomics study with multiple sample pools",
            sample_count=20,
        )

        # Create multiple sample pools representing different experimental conditions
        self.control_pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Control Group",
            pool_description="Control samples for baseline comparison",
            pooled_only_samples=[1, 2, 3, 4, 5],
            created_by=self.user,
        )

        self.treatment_a_pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Treatment A",
            pool_description="Samples treated with compound A",
            pooled_only_samples=[6, 7, 8, 9, 10],
            created_by=self.user,
        )

        self.treatment_b_pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Treatment B",
            pool_description="Samples treated with compound B",
            pooled_only_samples=[11, 12, 13, 14, 15],
            created_by=self.user,
        )

        self.replicates_pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Technical Replicates",
            pool_description="Technical replicate samples",
            pooled_only_samples=[16, 17, 18, 19, 20],
            created_by=self.user,
        )

    def test_complete_column_management_workflow(self):
        """Test a complete workflow of adding and managing columns across pools."""

        # Initially, all pools should have no columns
        self.assertEqual(self.control_pool.metadata_columns.count(), 0)
        self.assertEqual(self.treatment_a_pool.metadata_columns.count(), 0)
        self.assertEqual(self.treatment_b_pool.metadata_columns.count(), 0)
        self.assertEqual(self.replicates_pool.metadata_columns.count(), 0)

        # Step 1: Add basic sample identification columns
        print("\n=== Step 1: Adding basic identification columns ===")

        basic_columns = [
            {
                "name": "source name",
                "type": "",
                "value": "sample_001",
                "mandatory": True,
            },
            {
                "name": "characteristics[organism]",
                "type": "characteristics",
                "value": "homo sapiens",
                "ontology_type": "species",
                "mandatory": True,
            },
            {
                "name": "characteristics[organism part]",
                "type": "characteristics",
                "value": "blood plasma",
                "ontology_type": "tissue",
                "mandatory": True,
            },
        ]

        for column_data in basic_columns:
            url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column/"
            data = {"column_data": column_data}
            response = self.client.post(url, data, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            print(f"✓ Added column: {column_data['name']}")

        # Verify all pools now have these columns
        self.assertEqual(self.control_pool.metadata_columns.count(), 3)
        self.assertEqual(self.treatment_a_pool.metadata_columns.count(), 3)
        self.assertEqual(self.treatment_b_pool.metadata_columns.count(), 3)
        self.assertEqual(self.replicates_pool.metadata_columns.count(), 3)

        # Verify the columns have the correct properties
        for pool in [self.control_pool, self.treatment_a_pool, self.treatment_b_pool, self.replicates_pool]:
            organism_col = pool.metadata_columns.filter(name="characteristics[organism]").first()
            self.assertIsNotNone(organism_col)
            self.assertEqual(organism_col.value, "homo sapiens")
            self.assertEqual(organism_col.ontology_type, "species")
            self.assertTrue(organism_col.mandatory)

        print(f"✓ All 4 pools now have {basic_columns.__len__()} synchronized columns")

        # Step 2: Add treatment-specific columns with auto-reorder
        print("\n=== Step 2: Adding experimental design columns ===")

        experimental_columns = [
            {
                "name": "characteristics[disease]",
                "type": "characteristics",
                "value": "healthy",
                "ontology_type": "human_disease",
                "mandatory": False,
            },
            {
                "name": "factor value[treatment]",
                "type": "factor value",
                "value": "control",
                "mandatory": True,
            },
        ]

        for column_data in experimental_columns:
            url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column_with_auto_reorder/"
            data = {"column_data": column_data, "auto_reorder": True}
            response = self.client.post(url, data, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            result = response.json()
            print(f"✓ Added column: {column_data['name']} (reordered: {result.get('reordered', False)})")

        # Verify all pools now have 5 columns
        self.assertEqual(self.control_pool.metadata_columns.count(), 5)
        self.assertEqual(self.treatment_a_pool.metadata_columns.count(), 5)
        self.assertEqual(self.treatment_b_pool.metadata_columns.count(), 5)
        self.assertEqual(self.replicates_pool.metadata_columns.count(), 5)

        print("✓ All 4 pools now have 5 synchronized columns")

        # Step 3: Add analytical columns
        print("\n=== Step 3: Adding analytical metadata columns ===")

        analytical_columns = [
            {
                "name": "assay name",
                "type": "",
                "value": "LC-MS/MS_assay_001",
                "mandatory": True,
            },
            {
                "name": "technology type",
                "type": "technology type",
                "value": "mass spectrometry",
                "mandatory": True,
            },
            {
                "name": "comment[instrument]",
                "type": "comment",
                "value": "Orbitrap Fusion Lumos",
                "mandatory": False,
            },
        ]

        for column_data in analytical_columns:
            url = f"/api/v1/metadata-tables/{self.metadata_table.id}/add_column/"
            data = {"column_data": column_data}
            response = self.client.post(url, data, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            print(f"✓ Added column: {column_data['name']}")

        # Verify all pools now have 8 columns
        total_columns = 8
        self.assertEqual(self.control_pool.metadata_columns.count(), total_columns)
        self.assertEqual(self.treatment_a_pool.metadata_columns.count(), total_columns)
        self.assertEqual(self.treatment_b_pool.metadata_columns.count(), total_columns)
        self.assertEqual(self.replicates_pool.metadata_columns.count(), total_columns)

        print(f"✓ All 4 pools now have {total_columns} synchronized columns")

        # Step 4: Remove an unnecessary column
        print("\n=== Step 4: Removing an unnecessary column ===")

        # Find and remove the disease column (let's say it's not needed for this study)
        disease_column = self.metadata_table.columns.filter(name="characteristics[disease]").first()
        self.assertIsNotNone(disease_column)

        url = f"/api/v1/metadata-tables/{self.metadata_table.id}/remove_column/"
        data = {"column_id": disease_column.id}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        print("✓ Removed column: characteristics[disease]")

        # Verify all pools now have 7 columns (disease column removed from all)
        final_columns = 7
        self.assertEqual(self.control_pool.metadata_columns.count(), final_columns)
        self.assertEqual(self.treatment_a_pool.metadata_columns.count(), final_columns)
        self.assertEqual(self.treatment_b_pool.metadata_columns.count(), final_columns)
        self.assertEqual(self.replicates_pool.metadata_columns.count(), final_columns)

        # Verify the disease column is gone from all pools
        for pool in [self.control_pool, self.treatment_a_pool, self.treatment_b_pool, self.replicates_pool]:
            disease_cols = pool.metadata_columns.filter(name="characteristics[disease]")
            self.assertEqual(disease_cols.count(), 0)

        print(f"✓ All 4 pools now have {final_columns} columns (disease column removed from all)")

        # Step 5: Verify final state
        print("\n=== Step 5: Verifying final synchronized state ===")

        main_table_columns = set(self.metadata_table.columns.values_list("name", flat=True))

        for pool_name, pool in [
            ("Control", self.control_pool),
            ("Treatment A", self.treatment_a_pool),
            ("Treatment B", self.treatment_b_pool),
            ("Technical Replicates", self.replicates_pool),
        ]:
            pool_columns = set(pool.metadata_columns.values_list("name", flat=True))
            self.assertEqual(main_table_columns, pool_columns)
            print(f"✓ {pool_name} pool has identical columns to main table")

        # Verify key columns are present in all pools
        expected_final_columns = {
            "source name",
            "characteristics[organism]",
            "characteristics[organism part]",
            "factor value[treatment]",
            "assay name",
            "technology type",
            "comment[instrument]",
        }

        self.assertEqual(main_table_columns, expected_final_columns)

        print("\n🎉 SUCCESS: Complete workflow tested successfully!")
        print(f"   - Main table has {len(main_table_columns)} columns")
        print(f"   - All 4 pools have identical {len(main_table_columns)} columns")
        print("   - Column synchronization working perfectly!")

        # Final verification: Check that a sample of properties are correctly synchronized
        for pool in [self.control_pool, self.treatment_a_pool, self.treatment_b_pool, self.replicates_pool]:
            # Check organism column properties
            pool_organism = pool.metadata_columns.filter(name="characteristics[organism]").first()
            main_organism = self.metadata_table.columns.filter(name="characteristics[organism]").first()

            self.assertEqual(pool_organism.value, main_organism.value)
            self.assertEqual(pool_organism.ontology_type, main_organism.ontology_type)
            self.assertEqual(pool_organism.mandatory, main_organism.mandatory)

            # Check technology type column properties
            pool_tech = pool.metadata_columns.filter(name="technology type").first()
            main_tech = self.metadata_table.columns.filter(name="technology type").first()

            self.assertEqual(pool_tech.value, main_tech.value)
            self.assertEqual(pool_tech.type, main_tech.type)
            self.assertEqual(pool_tech.mandatory, main_tech.mandatory)
