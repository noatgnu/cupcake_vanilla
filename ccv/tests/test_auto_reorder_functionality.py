"""
Test cases for auto-reordering functionality in metadata tables and templates.

Tests the add_column_with_auto_reorder methods for both MetadataTable and
MetadataTableTemplate models using realistic SDRF fixture data.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.models import MetadataColumn, MetadataTableTemplate, Schema
from tests.factories import LabGroupFactory, MetadataTableFactory, UserFactory, get_fixture_path

User = get_user_model()


class AutoReorderTestMixin:
    """Mixin to ensure schemas are synced before running auto-reorder tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Sync builtin schemas before running tests
        print("Syncing builtin schemas for auto-reorder tests...")
        call_command("sync_schemas", verbosity=0)

        # Verify schemas were created
        schema_count = Schema.objects.filter(is_builtin=True, is_active=True).count()
        print(f"Available builtin schemas: {schema_count}")

        if schema_count == 0:
            print("Warning: No builtin schemas found. Auto-reorder functionality may not work as expected.")


class MetadataTableAutoReorderTest(AutoReorderTestMixin, TestCase):
    """Tests for MetadataTable.add_column_with_auto_reorder method."""

    def setUp(self):
        self.user = UserFactory.create_user(username="researcher1")
        self.lab_group = LabGroupFactory.create_lab_group(name="Test Lab")

    def test_add_column_with_auto_reorder_from_fixture(self):
        """Test adding organism column with auto-reorder using SDRF fixture."""
        # Create table from SDRF fixture
        fixture_path = get_fixture_path("PXD019185_PXD018883.sdrf.tsv")

        if not os.path.exists(fixture_path):
            self.skipTest(f"SDRF fixture not found at {fixture_path}")

        # Create metadata table from fixture
        table = MetadataTableFactory.from_sdrf_file(
            sdrf_file_path=fixture_path, created_by=self.user, lab_group=self.lab_group
        )

        # Verify table was created successfully
        self.assertIsNotNone(table)
        self.assertTrue(table.columns.exists())

        # Find existing organism column position
        organism_columns = table.columns.filter(name__icontains="organism")
        if not organism_columns.exists():
            self.skipTest("No organism column found in fixture")

        original_position = organism_columns.first().column_position

        # Get initial column count and order
        initial_column_count = table.columns.count()

        # Add a new organism column with auto-reorder
        new_organism_data = {
            "name": "characteristics[organism part]",
            "type": "text",
            "value": "liver",
            "ontology_type": "tissue",
        }

        result = table.add_column_with_auto_reorder(column_data=new_organism_data, auto_reorder=True)

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("column", result)
        self.assertIn("reordered", result)
        self.assertIn("schema_ids_used", result)
        self.assertIn("message", result)

        # Verify new column was created
        new_column = result["column"]
        self.assertEqual(new_column.name, "characteristics[organism part]")
        self.assertEqual(new_column.value, "liver")

        # Verify column count increased
        self.assertEqual(table.columns.count(), initial_column_count + 1)

        # Verify the new column is positioned near the existing organism column
        new_position = new_column.column_position

        # The new organism column should be positioned close to the existing one
        # (exact position depends on schema ordering, but should be in characteristics section)
        characteristics_columns = table.columns.filter(name__startswith="characteristics")
        characteristics_positions = list(characteristics_columns.values_list("column_position", flat=True))

        # New column should be among characteristics columns
        self.assertIn(new_position, characteristics_positions)

        print(f"Original organism column position: {original_position}")
        print(f"New organism column position: {new_position}")
        print(f"Reordering applied: {result['reordered']}")
        print(f"Message: {result['message']}")

    def test_add_column_without_auto_reorder(self):
        """Test adding column without auto-reorder for comparison."""
        # Create simple table
        table = MetadataTableFactory.create_basic_table(user=self.user, name="Simple Test Table", sample_count=5)

        # Add a column without auto-reorder
        column_data = {"name": "test column", "type": "text", "value": "test value"}

        result = table.add_column_with_auto_reorder(column_data=column_data, auto_reorder=False)

        # Should not trigger reordering
        self.assertFalse(result["reordered"])
        self.assertEqual(result["schema_ids_used"], [])
        self.assertEqual(result["message"], "Column added successfully")

    def test_add_column_to_empty_table(self):
        """Test adding column to table with no existing columns."""
        table = MetadataTableFactory.create_basic_table(user=self.user, name="Empty Test Table", sample_count=1)

        # Remove any default columns
        table.columns.all().delete()

        column_data = {"name": "first column", "type": "text", "value": "first value"}

        result = table.add_column_with_auto_reorder(column_data=column_data, auto_reorder=True)

        # Should succeed - reordering may or may not occur depending on available schemas
        self.assertEqual(table.columns.count(), 1)

        # Check that the result is valid regardless of reordering
        self.assertIn("added", result["message"].lower())

        # Log the actual result for debugging
        print(f"Empty table test - Reordered: {result['reordered']}, Message: '{result['message']}')")


class MetadataTableTemplateAutoReorderTest(AutoReorderTestMixin, TestCase):
    """Tests for MetadataTableTemplate.add_column_with_auto_reorder method."""

    def setUp(self):
        self.user = UserFactory.create_user(username="researcher1")
        self.lab_group = LabGroupFactory.create_lab_group(name="Test Lab")

    def test_add_column_with_auto_reorder_to_template(self):
        """Test adding organism column with auto-reorder to template."""
        # Create template with some characteristics columns
        template = MetadataTableTemplate.objects.create(
            name="Test Auto-Reorder Template",
            owner=self.user,
            lab_group=self.lab_group,
            description="Test template for auto-reorder functionality",
        )

        # Add some initial columns to establish context
        initial_columns = [
            {"name": "source name", "type": "text", "value": ""},
            {"name": "characteristics[organism]", "type": "text", "value": "homo sapiens"},
            {"name": "characteristics[tissue]", "type": "text", "value": "liver"},
        ]

        for col_data in initial_columns:
            template.add_column_to_template(col_data)

        # Add new organism-related column with auto-reorder
        new_organism_data = {
            "name": "characteristics[organism part]",
            "type": "text",
            "value": "liver",
            "ontology_type": "tissue",
        }

        result = template.add_column_with_auto_reorder(column_data=new_organism_data, auto_reorder=True)

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("column", result)
        self.assertIn("reordered", result)
        self.assertIn("message", result)

        # Verify new column was created
        new_column = result["column"]
        self.assertEqual(new_column.name, "characteristics[organism part]")
        self.assertEqual(new_column.value, "liver")

        # Verify column count increased
        self.assertEqual(template.user_columns.count(), 4)

        print(f"Template reordering result: {result['reordered']}")
        print(f"Message: {result['message']}")

    def test_add_column_without_schemas(self):
        """Test adding column to template without available schemas."""
        template = MetadataTableTemplate.objects.create(
            name="No Schema Template", owner=self.user, description="Template without schemas for testing"
        )

        column_data = {"name": "custom column", "type": "text", "value": "custom value"}

        result = template.add_column_with_auto_reorder(column_data=column_data, auto_reorder=True)

        # Should succeed but no reordering since no schemas available
        self.assertFalse(result["reordered"])
        self.assertEqual(result["schema_ids_used"], [])


class MetadataTableAutoReorderAPITest(AutoReorderTestMixin, APITestCase):
    """Tests for metadata table auto-reorder API endpoint."""

    def setUp(self):
        self.user = UserFactory.create_user(username="api_user")
        self.lab_group = LabGroupFactory.create_lab_group(name="API Test Lab")
        self.client.force_authenticate(user=self.user)

    def test_add_column_with_auto_reorder_api(self):
        """Test the API endpoint for adding column with auto-reorder."""
        table = MetadataTableFactory.create_basic_table(user=self.user, name="API Test Table", sample_count=3)

        # Add some initial columns
        table.add_column({"name": "characteristics[organism]", "type": "text", "value": "homo sapiens"})

        url = f"/api/v1/metadata-tables/{table.id}/add_column_with_auto_reorder/"
        data = {
            "column_data": {"name": "characteristics[organism part]", "type": "text", "value": "liver tissue"},
            "auto_reorder": True,
        }

        response = self.client.post(url, data, format="json")

        # Verify API response
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertIn("message", response_data)
        self.assertIn("column", response_data)
        self.assertIn("reordered", response_data)
        self.assertIn("schema_ids_used", response_data)

        # Verify column was created in database
        new_column = MetadataColumn.objects.get(id=response_data["column"]["id"])
        self.assertEqual(new_column.name, "characteristics[organism part]")
        self.assertEqual(new_column.metadata_table, table)

    def test_add_column_permission_denied(self):
        """Test API endpoint with insufficient permissions."""
        other_user = UserFactory.create_user(username="other_user")
        table = MetadataTableFactory.create_basic_table(user=other_user, name="Other User's Table")

        url = f"/api/v1/metadata-tables/{table.id}/add_column_with_auto_reorder/"
        data = {"column_data": {"name": "test column", "type": "text", "value": "test"}}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MetadataTableTemplateAutoReorderAPITest(AutoReorderTestMixin, APITestCase):
    """Tests for metadata table template auto-reorder API endpoint."""

    def setUp(self):
        self.user = UserFactory.create_user(username="api_user")
        self.lab_group = LabGroupFactory.create_lab_group(name="API Test Lab")
        self.client.force_authenticate(user=self.user)

    def test_add_column_with_auto_reorder_template_api(self):
        """Test the API endpoint for adding column with auto-reorder to template."""
        template = MetadataTableTemplate.objects.create(
            name="API Test Template",
            owner=self.user,
            lab_group=self.lab_group,
            description="API test template for auto-reorder",
        )

        # Add initial column
        template.add_column_to_template({"name": "characteristics[organism]", "type": "text", "value": "homo sapiens"})

        url = f"/api/v1/metadata-table-templates/{template.id}/add_column_with_auto_reorder/"
        data = {
            "column_data": {"name": "characteristics[cell type]", "type": "text", "value": "hepatocyte"},
            "auto_reorder": True,
        }

        response = self.client.post(url, data, format="json")

        # Verify API response
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertIn("message", response_data)
        self.assertIn("column", response_data)
        self.assertIn("reordered", response_data)
        self.assertIn("schema_ids_used", response_data)

        # Verify column was created in database
        new_column = MetadataColumn.objects.get(id=response_data["column"]["id"])
        self.assertEqual(new_column.name, "characteristics[cell type]")

    def test_add_column_template_permission_denied(self):
        """Test template API endpoint with insufficient permissions."""
        other_user = UserFactory.create_user(username="other_user")
        template = MetadataTableTemplate.objects.create(
            name="Other User's Template", owner=other_user, description="Template owned by another user"
        )

        url = f"/api/v1/metadata-table-templates/{template.id}/add_column_with_auto_reorder/"
        data = {"column_data": {"name": "test column", "type": "text", "value": "test"}}

        response = self.client.post(url, data, format="json")
        # Could be 403 (permission denied) or 404 (not found due to permissions)
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
