"""
Integration tests for metadata table validation functionality.

Tests validation using real fixture data through import/export workflows.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccv.tasks.import_utils import import_sdrf_data
from ccv.tasks.validation_tasks import validate_metadata_table_task
from ccv.tasks.validation_utils import validate_metadata_table
from tests.factories import MetadataTableFactory, QuickTestDataMixin, UserFactory, read_fixture_content

User = get_user_model()


class ValidationIntegrationTest(TestCase, QuickTestDataMixin):
    """Test validation functionality using import/export workflows with fixture data."""

    def setUp(self):
        self.user = UserFactory.create_user()

    def import_sdrf_fixture(self, filename):
        """Import SDRF fixture file and return the metadata table."""
        content = read_fixture_content(filename)
        if not content:
            self.skipTest(f"Fixture file not found: {filename}")
            return None

        # Create empty metadata table first
        table_name = f"Imported_{filename.replace('.sdrf.tsv', '')}"
        metadata_table = MetadataTableFactory.create_basic_table(
            user=self.user,
            name=table_name,
            description=f"Imported from fixture {filename}",
            sample_count=1,  # Will be updated by import
        )

        # Import SDRF data into the table
        import_result = import_sdrf_data(
            file_content=content,
            metadata_table=metadata_table,
            user=self.user,
            replace_existing=True,
            validate_ontologies=False,  # Skip validation for faster testing
            create_pools=True,
        )

        if not import_result.get("success"):
            self.fail(f"Import failed for {filename}: {import_result.get('error', 'Unknown error')}")

        # Refresh from database to get updated sample_count
        metadata_table.refresh_from_db()
        return metadata_table

    def test_validation_with_pdc000126_fixture(self):
        """Test validation using PDC000126 fixture data."""
        # Import the fixture
        table = self.import_sdrf_fixture("PDC000126.sdrf.tsv")
        if not table:
            self.skipTest("PDC000126 fixture not available")

        # Test validation
        validation_result = validate_metadata_table(
            metadata_table=table, user=self.user, validation_options={"include_pools": True}
        )

        # Assertions
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)
        self.assertIn("metadata_table_id", validation_result)
        self.assertIn("validation_timestamp", validation_result)
        self.assertIn("errors", validation_result)
        self.assertEqual(validation_result["metadata_table_id"], table.id)
        self.assertEqual(validation_result["metadata_table_name"], table.name)

    def test_validation_with_pxd002137_fixture(self):
        """Test validation using PXD002137 fixture data."""
        # Import the fixture
        table = self.import_sdrf_fixture("PXD002137.sdrf.tsv")
        if not table:
            self.skipTest("PXD002137 fixture not available")

        # Test validation
        validation_result = validate_metadata_table(
            metadata_table=table, user=self.user, validation_options={"include_pools": True}
        )

        # Assertions
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)
        self.assertIn("errors", validation_result)
        self.assertEqual(validation_result["metadata_table_id"], table.id)

    def test_validation_with_pooled_samples_fixture(self):
        """Test validation using PXD019185_PXD018883 fixture which contains pooled samples."""
        # Import the fixture
        table = self.import_sdrf_fixture("PXD019185_PXD018883.sdrf.tsv")
        if not table:
            self.skipTest("PXD019185_PXD018883 fixture not available")

        # Test validation with pools included
        validation_result = validate_metadata_table(
            metadata_table=table, user=self.user, validation_options={"include_pools": True}
        )

        # Assertions
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)
        self.assertEqual(validation_result["metadata_table_id"], table.id)

        # Test validation without pools
        validation_result_no_pools = validate_metadata_table(
            metadata_table=table, user=self.user, validation_options={"include_pools": False}
        )

        self.assertIsInstance(validation_result_no_pools, dict)
        self.assertIn("success", validation_result_no_pools)

    def test_validation_error_handling(self):
        """Test validation error handling with malformed data."""
        # Create a table with minimal/problematic data
        table = MetadataTableFactory.create_basic_table(user=self.user, name="Problem Table", sample_count=0)

        # Test validation with empty table
        validation_result = validate_metadata_table(metadata_table=table, user=self.user)

        # Should handle gracefully
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)
        self.assertIn("errors", validation_result)

        if not validation_result["success"]:
            self.assertTrue(len(validation_result["errors"]) > 0)

    def test_validation_permission_handling(self):
        """Test validation permission handling."""
        # Create table with different user
        other_user = UserFactory.create_user(username="other_user")
        table = MetadataTableFactory.create_basic_table(user=other_user)

        # Test validation with wrong user should fail
        with self.assertRaises(PermissionError):
            validate_metadata_table(metadata_table=table, user=self.user)

    @patch("ccv.tasks.validation_utils.export_sdrf_data")
    def test_validation_with_mocked_export(self, mock_export):
        """Test validation with mocked export data."""
        # Setup mock
        mock_export.return_value = {"success": True, "sdrf_content": "source name\torganism\nassay1\thomo sapiens"}

        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Test validation
        validation_result = validate_metadata_table(metadata_table=table, user=self.user)

        # Verify mock was called
        mock_export.assert_called_once()

        # Check result structure
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)

    @patch("ccv.tasks.validation_utils.export_sdrf_data")
    @patch("ccv.tasks.validation_utils.SchemaValidator")
    @patch("ccv.tasks.validation_utils.SchemaRegistry")
    def test_validation_with_sdrf_pipelines_error(self, mock_registry, mock_validator, mock_export):
        """Test validation handling of sdrf_pipelines validation errors."""
        # Setup mocks
        mock_export.return_value = {"success": True, "sdrf_content": "source name\torganism\nassay1\thomo sapiens"}

        # Mock validator to return errors
        mock_validator_instance = MagicMock()
        mock_validator.return_value = mock_validator_instance
        mock_validator_instance.validate.return_value = [
            "Error: Missing required column",
            "Warning: Suspicious value detected",
        ]

        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Test validation
        validation_result = validate_metadata_table(metadata_table=table, user=self.user)

        # Check that errors are properly categorized
        self.assertIsInstance(validation_result, dict)
        self.assertIn("success", validation_result)
        self.assertIn("errors", validation_result)
        self.assertIn("warnings", validation_result)
        self.assertFalse(validation_result["success"])
        self.assertTrue(len(validation_result["errors"]) > 0)


class AsyncValidationTaskTest(TestCase, QuickTestDataMixin):
    """Test async validation task functionality."""

    def setUp(self):
        self.user = UserFactory.create_user()

    @patch("ccv.tasks.validation_tasks.validate_metadata_table")
    def test_async_validation_task(self, mock_validate):
        """Test the async validation task."""
        # Setup mock
        mock_validate.return_value = {
            "success": True,
            "metadata_table_id": 1,
            "metadata_table_name": "Test Table",
            "errors": [],
            "warnings": [],
        }

        # Create test data
        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Run task
        result = validate_metadata_table_task(
            metadata_table_id=table.id, user_id=self.user.id, validation_options={"include_pools": True}
        )

        # Verify result
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("metadata_table_id", result)

        # Verify mock was called with correct parameters
        mock_validate.assert_called_once()
        args, kwargs = mock_validate.call_args
        self.assertEqual(kwargs["metadata_table"], table)
        self.assertEqual(kwargs["user"], self.user)
        self.assertEqual(kwargs["validation_options"], {"include_pools": True})

    def test_async_validation_task_with_nonexistent_table(self):
        """Test async validation task with nonexistent table."""
        # Test with invalid table ID
        result = validate_metadata_table_task(metadata_table_id=99999, user_id=self.user.id)

        # Should handle gracefully
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("error", result)  # Task returns "error" (singular) not "errors"
        self.assertIn("traceback", result)

    def test_async_validation_task_with_nonexistent_user(self):
        """Test async validation task with nonexistent user."""
        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Test with invalid user ID
        result = validate_metadata_table_task(metadata_table_id=table.id, user_id=99999)

        # Should handle gracefully
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("error", result)  # Task returns "error" (singular) not "errors"
        self.assertIn("traceback", result)


class ValidationOptionsTest(TestCase, QuickTestDataMixin):
    """Test different validation options."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_with_columns(user=self.user)

    @patch("ccv.tasks.validation_utils.export_sdrf_data")
    def test_validation_with_different_templates(self, mock_export):
        """Test validation with different template options."""
        mock_export.return_value = {"success": True, "sdrf_content": "source name\torganism\nassay1\thomo sapiens"}

        # Test with default template
        result_default = validate_metadata_table(
            metadata_table=self.table, user=self.user, validation_options={"template": "default"}
        )

        self.assertIn("success", result_default)

        # Test with human template (if exists)
        result_human = validate_metadata_table(
            metadata_table=self.table, user=self.user, validation_options={"template": "human"}
        )

        self.assertIn("success", result_human)

    @patch("ccv.tasks.validation_utils.export_sdrf_data")
    def test_validation_with_ols_cache_option(self, mock_export):
        """Test validation with OLS cache option."""
        mock_export.return_value = {"success": True, "sdrf_content": "source name\torganism\nassay1\thomo sapiens"}

        # Test with OLS cache only
        result = validate_metadata_table(
            metadata_table=self.table,
            user=self.user,
            validation_options={"use_ols_cache_only": True, "include_pools": True},
        )

        self.assertIn("success", result)
        self.assertIn("validation_timestamp", result)

    def test_validation_options_defaults(self):
        """Test that validation options have proper defaults."""
        # Test with no options
        result = validate_metadata_table(metadata_table=self.table, user=self.user)

        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

        # Test with empty options
        result_empty = validate_metadata_table(metadata_table=self.table, user=self.user, validation_options={})

        self.assertIsInstance(result_empty, dict)
        self.assertIn("success", result_empty)
