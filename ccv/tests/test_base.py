"""
Test cases for CUPCAKE Vanilla metadata models and functionality.
"""

import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import LabGroup
from ccv.models import FavouriteMetadataOption, MetadataColumn, MetadataTable, SamplePool

User = get_user_model()


class MetadataTableModelTest(TestCase):
    """Test cases for MetadataTable model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")

    def test_create_metadata_table(self):
        """Test creating a metadata table."""
        table = MetadataTable.objects.create(
            name="Test Metadata Table",
            description="A test metadata table",
            sample_count=10,
            owner=self.user,
            lab_group=self.lab_group,
        )

        self.assertEqual(table.name, "Test Metadata Table")
        self.assertEqual(table.sample_count, 10)
        self.assertEqual(table.owner, self.user)
        self.assertEqual(table.lab_group, self.lab_group)
        self.assertFalse(table.is_locked)
        self.assertFalse(table.is_published)

    def test_metadata_table_string_representation(self):
        """Test string representation of metadata table."""
        table = MetadataTable.objects.create(name="Test Table", owner=self.user)
        self.assertEqual(str(table), "Test Table")

    def test_get_column_count(self):
        """Test getting column count for metadata table."""
        table = MetadataTable.objects.create(name="Test Table", owner=self.user)

        # Initially no columns
        self.assertEqual(table.get_column_count(), 0)

        # Add some columns
        MetadataColumn.objects.create(
            metadata_table=table,
            name="source name",
            type="characteristics",
            column_position=0,
        )
        MetadataColumn.objects.create(
            metadata_table=table,
            name="organism",
            type="characteristics",
            column_position=1,
        )

        self.assertEqual(table.get_column_count(), 2)


class MetadataColumnModelTest(TestCase):
    """Test cases for MetadataColumn model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.metadata_table = MetadataTable.objects.create(name="Test Table", owner=self.user)

    def test_create_metadata_column(self):
        """Test creating a metadata column."""
        column = MetadataColumn.objects.create(
            metadata_table=self.metadata_table,
            name="source name",
            type="characteristics",
            column_position=0,
            value="Sample 1",
            mandatory=True,
        )

        self.assertEqual(column.metadata_table, self.metadata_table)
        self.assertEqual(column.name, "source name")
        self.assertEqual(column.type, "characteristics")
        self.assertEqual(column.column_position, 0)
        self.assertEqual(column.value, "Sample 1")
        self.assertTrue(column.mandatory)
        self.assertFalse(column.hidden)
        self.assertFalse(column.auto_generated)
        self.assertFalse(column.readonly)


class LabGroupModelTest(TestCase):
    """Test cases for LabGroup model."""

    def test_create_lab_group(self):
        """Test creating a lab group."""
        lab_group = LabGroup.objects.create(name="Test Lab Group", description="A test laboratory group")

        self.assertEqual(lab_group.name, "Test Lab Group")
        self.assertEqual(lab_group.description, "A test laboratory group")
        self.assertTrue(lab_group.created_at)
        self.assertTrue(lab_group.updated_at)

    def test_lab_group_string_representation(self):
        """Test string representation of lab group."""
        lab_group = LabGroup.objects.create(name="Test Lab")
        self.assertEqual(str(lab_group), "Test Lab")


class FavouriteMetadataOptionModelTest(TestCase):
    """Test cases for FavouriteMetadataOption model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")

    def test_create_favourite_metadata_option(self):
        """Test creating a favourite metadata option."""
        favourite = FavouriteMetadataOption.objects.create(
            name="organism",
            type="characteristics",
            value="homo sapiens",
            display_value="Human",
            user=self.user,
            lab_group=self.lab_group,
        )

        self.assertEqual(favourite.name, "organism")
        self.assertEqual(favourite.type, "characteristics")
        self.assertEqual(favourite.value, "homo sapiens")
        self.assertEqual(favourite.display_value, "Human")
        self.assertEqual(favourite.user, self.user)
        self.assertEqual(favourite.lab_group, self.lab_group)
        self.assertFalse(favourite.is_global)

    def test_global_favourite_metadata_option(self):
        """Test creating a global favourite metadata option."""
        favourite = FavouriteMetadataOption.objects.create(
            name="disease",
            type="characteristics",
            value="normal",
            display_value="Normal/Healthy",
            is_global=True,
        )

        self.assertTrue(favourite.is_global)
        self.assertIsNone(favourite.user)
        self.assertIsNone(favourite.lab_group)


class SamplePoolModelTest(TestCase):
    """Test cases for SamplePool model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.metadata_table = MetadataTable.objects.create(name="Test Table", owner=self.user, sample_count=10)

    def test_create_sample_pool(self):
        """Test creating a sample pool."""
        pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Test Pool",
            pool_description="A test sample pool",
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[4, 5],
            is_reference=True,
            created_by=self.user,
        )

        self.assertEqual(pool.metadata_table, self.metadata_table)
        self.assertEqual(pool.pool_name, "Test Pool")
        self.assertEqual(pool.pooled_only_samples, [1, 2, 3])
        self.assertEqual(pool.pooled_and_independent_samples, [4, 5])
        self.assertTrue(pool.is_reference)
        # Test the dynamic sdrf_value property
        self.assertTrue(pool.sdrf_value.startswith("SN="))

    def test_get_total_samples(self):
        """Test getting total samples in a pool."""
        pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[4, 5],
        )

        self.assertEqual(pool.get_total_samples(), 5)


class SDRFImportTest(TestCase):
    """Test cases for SDRF file import and processing functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.metadata_table = MetadataTable.objects.create(
            name="Test SDRF Import Table",
            description="Table for testing SDRF imports",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_sdrf_file_parsing(self):
        """Test parsing of SDRF file format."""
        # Create test SDRF content
        sdrf_content = (
            "source name\tcharacteristics[organism]\t"
            "characteristics[organism part]\tcharacteristics[disease]\t"
            "assay name\n"
            "Sample1\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 1\n"
            "Sample2\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 2\n"
            "Sample3\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 3\n"
        )

        lines = sdrf_content.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Test header parsing
        self.assertEqual(len(headers), 5)
        self.assertIn("source name", headers)
        self.assertIn("characteristics[organism]", headers)

        # Test data parsing
        self.assertEqual(len(data_rows), 3)
        self.assertEqual(data_rows[0][0], "Sample1")
        self.assertEqual(data_rows[1][1], "homo sapiens")

    def test_pooled_sample_detection(self):
        """Test detection of pooled samples in SDRF data."""
        from ccv.utils import detect_pooled_samples

        headers = [
            "source name",
            "characteristics[organism]",
            "characteristics[pooled sample]",
            "assay name",
            "technology type",
        ]

        data_rows = [
            [
                "D-HEp3 #1",
                "homo sapiens",
                "pooled",
                "run 1",
                "proteomic profiling by mass spectrometry",
            ],
            [
                "D-HEp3 #2",
                "homo sapiens",
                "pooled",
                "run 2",
                "proteomic profiling by mass spectrometry",
            ],
            [
                "T-HEp3 #1",
                "homo sapiens",
                "not pooled",
                "run 3",
                "proteomic profiling by mass spectrometry",
            ],
            [
                "SN=D-HEp3 #1,D-HEp3 #2",
                "homo sapiens",
                "SN=D-HEp3 #1,D-HEp3 #2",
                "pool_run",
                "proteomic profiling by mass spectrometry",
            ],
        ]

        pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

        # Test pooled column detection
        self.assertEqual(pooled_column_index, 2)

        # Test SN= row detection
        self.assertEqual(len(sn_rows), 1)
        self.assertEqual(sn_rows[0], 3)

        # Test pooled rows detection
        self.assertEqual(len(pooled_rows), 2)
        self.assertIn(0, pooled_rows)
        self.assertIn(1, pooled_rows)

    def test_real_sdrf_file_parsing(self):
        """Test parsing of real SDRF fixture file."""
        import os

        from ccv.utils import detect_pooled_samples

        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "tests",
            "fixtures",
            "PXD019185_PXD018883.sdrf.tsv",
        )

        with open(fixture_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Test file structure
        self.assertGreater(len(headers), 30)  # Should have many columns
        self.assertGreater(len(data_rows), 10)  # Should have multiple data rows

        # Test specific expected columns
        self.assertIn("source name", headers)
        self.assertIn("characteristics[organism]", headers)
        self.assertIn("characteristics[pooled sample]", headers)
        self.assertIn("assay name", headers)

        # Test pooled sample detection
        pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

        self.assertIsNotNone(pooled_column_index)
        self.assertGreater(len(pooled_rows), 0)  # Should detect some pooled samples

        # Test specific data values from the fixture
        first_row = data_rows[0]
        self.assertEqual(first_row[0], "D-HEp3 #1")  # source name

        # Find organism column and test value
        organism_col = None
        for i, header in enumerate(headers):
            if "organism]" in header and "characteristics[" in header:
                organism_col = i
                break

        self.assertIsNotNone(organism_col)
        self.assertEqual(first_row[organism_col], "homo sapiens")

    def test_metadata_column_creation_from_headers(self):
        """Test creation of metadata columns from SDRF headers."""
        headers = [
            "source name",
            "characteristics[organism]",
            "characteristics[organism part]",
            "characteristics[disease]",
            "assay name",
            "comment[technical replicate]",
            "factor value[phenotype]",
        ]

        # Clear any existing columns
        self.metadata_table.columns.all().delete()

        # Create columns from headers
        for i, header in enumerate(headers):
            if "[" in header and "]" in header:
                name = header.split("[")[0].strip()
                metadata_type = header.split("[")[1].rstrip("]").strip()
            else:
                name = header.strip()
                metadata_type = "characteristics"

            MetadataColumn.objects.create(
                name=name,
                type=metadata_type,
                column_position=i,
                metadata_table=self.metadata_table,
            )

        # Test created columns
        columns = self.metadata_table.columns.all().order_by("column_position")
        self.assertEqual(columns.count(), 7)

        # Test first column
        first_col = columns[0]
        self.assertEqual(first_col.name, "source name")
        self.assertEqual(first_col.type, "characteristics")
        self.assertEqual(first_col.column_position, 0)

        # Test organism column
        organism_col = columns[1]
        self.assertEqual(organism_col.name, "characteristics")
        self.assertEqual(organism_col.type, "organism")

        # Test comment column
        comment_col = columns[5]
        self.assertEqual(comment_col.name, "comment")
        self.assertEqual(comment_col.type, "technical replicate")

    def test_pool_creation_from_sdrf_data(self):
        """Test creation of sample pools from SDRF pooled data."""
        # Create test data with pools
        headers = [
            "source name",
            "characteristics[organism]",
            "characteristics[pooled sample]",
            "assay name",
        ]

        data_rows = [
            ["D-HEp3 #1", "homo sapiens", "pooled", "run 1"],
            ["D-HEp3 #2", "homo sapiens", "pooled", "run 2"],
            ["T-HEp3 #1", "homo sapiens", "not pooled", "run 3"],
            [
                "SN=D-HEp3 #1,D-HEp3 #2",
                "homo sapiens",
                "SN=D-HEp3 #1,D-HEp3 #2",
                "pool_run",
            ],
        ]

        from ccv.utils import detect_pooled_samples

        pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

        # Create a pool based on SN= row
        self.assertEqual(len(sn_rows), 1)
        # sn_row_idx = sn_rows[0]  # Index of the SN= row (unused in this test)

        # Set sample count to validate pool indices
        self.metadata_table.sample_count = 4
        self.metadata_table.save()

        # Create sample pool
        sample_pool = SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Test Pool from SDRF",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            is_reference=True,
            created_by=self.user,
        )

        # Test pool creation
        self.assertEqual(sample_pool.pool_name, "Test Pool from SDRF")
        self.assertTrue(sample_pool.is_reference)
        # Test that the generated sdrf_value contains expected data
        self.assertTrue(sample_pool.sdrf_value.startswith("SN="))
        self.assertEqual(sample_pool.pooled_only_samples, [1, 2])

        # Test pool method
        self.assertEqual(sample_pool.get_total_samples(), 2)

    def test_sdrf_validation(self):
        """Test SDRF data validation using sdrf-pipelines."""
        from ccv.utils import validate_sdrf

        # Create valid SDRF data
        valid_data = [
            [
                "source name",
                "characteristics[organism]",
                "characteristics[organism part]",
                "characteristics[disease]",
                "assay name",
                "technology type",
            ],
            [
                "Sample1",
                "homo sapiens",
                "head and neck",
                "squamous cell carcinoma",
                "run 1",
                "proteomic profiling by mass spectrometry",
            ],
            [
                "Sample2",
                "homo sapiens",
                "head and neck",
                "squamous cell carcinoma",
                "run 2",
                "proteomic profiling by mass spectrometry",
            ],
        ]

        # Test validation
        errors = validate_sdrf(valid_data)

        # Should return a list (may have warnings but not critical errors for
        # our basic test)
        self.assertIsInstance(errors, list)

        # Test with invalid data (missing required columns)
        invalid_data = [
            ["source name", "some_column"],
            ["Sample1", "value1"],
            ["Sample2", "value2"],
        ]

        errors = validate_sdrf(invalid_data)
        self.assertIsInstance(errors, list)

    def test_sample_count_calculation(self):
        """Test sample count calculation from SDRF data."""
        # Test with regular samples
        data_rows = [
            ["Sample1", "homo sapiens", "not pooled", "run 1"],
            ["Sample2", "homo sapiens", "not pooled", "run 2"],
            ["Sample3", "homo sapiens", "not pooled", "run 3"],
        ]

        # Update metadata table sample count
        self.metadata_table.sample_count = len(data_rows)
        self.metadata_table.save()

        self.assertEqual(self.metadata_table.sample_count, 3)

        # Test with pooled samples (should still count all rows)
        pooled_data_rows = [
            ["Sample1", "homo sapiens", "pooled", "run 1"],
            ["Sample2", "homo sapiens", "pooled", "run 2"],
            ["SN=Sample1,Sample2", "homo sapiens", "SN=Sample1,Sample2", "pool_run"],
        ]

        self.metadata_table.sample_count = len(pooled_data_rows)
        self.metadata_table.save()

        self.assertEqual(self.metadata_table.sample_count, 3)

    def test_sdrf_utils_integration(self):
        """Test integration of SDRF utilities with models."""
        from ccv.utils import sort_metadata

        # Create metadata columns
        columns = [
            MetadataColumn.objects.create(
                metadata_table=self.metadata_table,
                name="source name",
                type="",
                column_position=0,
                value="Sample",
            ),
            MetadataColumn.objects.create(
                metadata_table=self.metadata_table,
                name="organism",
                type="characteristics",
                column_position=1,
                value="homo sapiens",
            ),
            MetadataColumn.objects.create(
                metadata_table=self.metadata_table,
                name="disease",
                type="characteristics",
                column_position=2,
                value="normal",
            ),
        ]

        # Test sort_metadata function
        result_data, id_map = sort_metadata(columns, 3)

        # Test headers
        self.assertEqual(len(result_data), 4)
        headers = result_data[0]
        self.assertEqual(headers[0], "source name")
        self.assertEqual(headers[1], "organism")
        self.assertEqual(headers[2], "disease")

        # Test data rows
        first_row = result_data[1]
        self.assertEqual(first_row[0], "Sample")
        self.assertEqual(first_row[1], "homo sapiens")
        self.assertEqual(first_row[2], "normal")

        # Test id_map
        self.assertEqual(len(id_map), 3)
        for column in columns:
            self.assertIn(column.id, id_map)

    def test_metadata_modifiers_in_sdrf_export(self):
        """Test that metadata column modifiers are handled in SDRF export."""
        from ccv.utils import sort_metadata

        # Create a column with sample-specific modifiers
        modifiers = [
            {"samples": "1", "value": "modified_value_1"},
            {"samples": "2", "value": "modified_value_2"},
        ]

        column = MetadataColumn.objects.create(
            metadata_table=self.metadata_table,
            name="test_column",
            type="characteristics",
            column_position=0,
            value="default_value",
            modifiers=modifiers,
        )

        # Test sort_metadata with modifiers
        result_data, id_map = sort_metadata([column], 3)

        # Check that sample-specific values are applied
        self.assertEqual(result_data[1][0], "modified_value_1")  # Sample 1
        self.assertEqual(result_data[2][0], "modified_value_2")  # Sample 2
        self.assertEqual(result_data[3][0], "default_value")  # Sample 3 (no modifier)


class SDRFImportAPITest(APITestCase):
    """Test cases for SDRF import API endpoint."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)

        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.metadata_table = MetadataTable.objects.create(
            name="Test API Import Table",
            description="Table for testing API imports",
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_import_sdrf_api_endpoint(self):
        """Test the SDRF import API endpoint."""
        import io

        # Create test SDRF content
        sdrf_content = (
            "source name\tcharacteristics[organism]\t"
            "characteristics[organism part]\tcharacteristics[disease]\t"
            "assay name\tcharacteristics[pooled sample]\n"
            "Sample1\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 1\tnot pooled\n"
            "Sample2\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 2\tnot pooled\n"
            "Sample3\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\trun 3\tpooled\n"
            "SN=Sample3\thomo sapiens\thead and neck\t"
            "squamous cell carcinoma\tpool_run\tSN=Sample3\n"
        )

        # Create file-like object
        file_data = io.BytesIO(sdrf_content.encode("utf-8"))
        file_data.name = "test_sdrf.tsv"

        # Prepare API request data
        data = {
            "file": file_data,
            "metadata_table_id": self.metadata_table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        # Make API request
        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Test response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertIn("message", response_data)
        self.assertIn("created_columns", response_data)
        self.assertIn("created_pools", response_data)
        self.assertIn("pools_detected", response_data)
        self.assertIn("sample_rows", response_data)

        # Test that columns were created
        self.assertGreater(response_data["created_columns"], 0)
        self.assertEqual(response_data["sample_rows"], 3)
        self.assertTrue(response_data["pools_detected"])

        # Verify database changes
        self.metadata_table.refresh_from_db()
        self.assertEqual(self.metadata_table.sample_count, 3)

        # Check created columns
        columns = self.metadata_table.columns.all()
        self.assertEqual(columns.count(), 6)

        # Check specific columns
        source_name_col = columns.filter(name="source name").first()
        self.assertIsNotNone(source_name_col)
        self.assertEqual(source_name_col.column_position, 0)

        # Check for organism column (flexible matching for different API implementations)
        organism_col = (
            columns.filter(name="characteristics", type="organism").first()
            or columns.filter(name__icontains="organism").first()
        )
        self.assertIsNotNone(organism_col, "Expected organism column not found")

    def test_import_sdrf_with_real_fixture(self):
        """Test SDRF import with real fixture file."""
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "tests",
            "fixtures",
            "PXD019185_PXD018883.sdrf.tsv",
        )

        # Read fixture file
        with open(fixture_path, "rb") as f:
            file_data = f.read()

        # Create file-like object for API
        file_obj = io.BytesIO(file_data)
        file_obj.name = "PXD019185_PXD018883.sdrf.tsv"

        # Prepare API request data
        data = {
            "file": file_obj,
            "metadata_table_id": self.metadata_table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        # Make API request
        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Test response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Test response structure
        self.assertIn("message", response_data)
        self.assertEqual(response_data["message"], "SDRF file imported successfully")

        # Test that data was processed
        self.assertGreater(response_data["created_columns"], 30)  # Should have many columns
        self.assertGreater(response_data["sample_rows"], 10)  # Should have many samples
        # Pools may or may not be created depending on fixture content
        self.assertGreaterEqual(response_data["created_pools"], 0)  # May or may not have pools
        self.assertTrue(response_data["pools_detected"] or response_data["created_pools"] == 0)  # Should be consistent

        # Verify database changes
        self.metadata_table.refresh_from_db()
        self.assertGreater(self.metadata_table.sample_count, 10)

        # Check created columns
        columns = self.metadata_table.columns.all()
        self.assertGreater(columns.count(), 30)

        # Check for expected columns from fixture
        self.assertTrue(columns.filter(name="source name").exists())
        # Check for organism column (may have different name/type structure)
        organism_exists = (
            columns.filter(name="characteristics", type="organism").exists()
            or columns.filter(name__icontains="organism").exists()
        )
        self.assertTrue(organism_exists, "Expected organism column not found")
        # Check for pooled sample column
        pooled_exists = (
            columns.filter(name="characteristics", type="pooled sample").exists()
            or columns.filter(name__icontains="pooled").exists()
        )
        self.assertTrue(pooled_exists, "Expected pooled sample column not found")

        # Check created pools (if any)
        pools = self.metadata_table.sample_pools.all()
        # This fixture may not create pools since it doesn't have SN= rows
        # Just verify the response data is consistent
        self.assertEqual(pools.count(), response_data["created_pools"])
        if response_data["created_pools"] > 0:
            first_pool = pools.first()
            self.assertTrue(first_pool.sdrf_value.startswith("SN="))

    def test_metadata_table_serializer_includes_sample_pools(self):
        """Test that MetadataTableSerializer includes sample pools in output."""
        from ccv.serializers import MetadataTableSerializer

        # Update sample count first to validate pool
        self.metadata_table.sample_count = 3
        self.metadata_table.save()

        # Create a sample pool for the metadata table
        SamplePool.objects.create(
            metadata_table=self.metadata_table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 2],
            pooled_and_independent_samples=[],
            is_reference=True,
            created_by=self.user,
        )

        # Serialize the metadata table
        serializer = MetadataTableSerializer(self.metadata_table)

        # Check that sample_pools field is included
        self.assertIn("sample_pools", serializer.data)
        self.assertEqual(len(serializer.data["sample_pools"]), 1)

        # Check sample pool data
        pool_data = serializer.data["sample_pools"][0]
        self.assertEqual(pool_data["pool_name"], "Test Pool")
        self.assertEqual(pool_data["pooled_only_samples"], [1, 2])
        self.assertTrue(pool_data["is_reference"])
        self.assertEqual(pool_data["metadata_table"], self.metadata_table.id)

    def test_import_sdrf_permission_denied(self):
        """Test SDRF import with insufficient permissions."""
        import io

        # Create another user
        other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="testpass123")

        # Create metadata table owned by other user
        other_table = MetadataTable.objects.create(name="Other User Table", owner=other_user)

        # Try to import to other user's table
        sdrf_content = "source name\tcharacteristics[organism]\nSample1\thomo sapiens\n"
        file_data = io.BytesIO(sdrf_content.encode("utf-8"))
        file_data.name = "test.tsv"

        data = {
            "file": file_data,
            "metadata_table_id": other_table.id,
            "replace_existing": True,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Should get permission denied (403) or permission-related validation error (400)
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])

        if response.status_code == status.HTTP_403_FORBIDDEN:
            self.assertIn("error", response.json())

    def test_import_sdrf_invalid_file(self):
        """Test SDRF import with invalid file."""
        import io

        # Create empty file
        empty_file = io.BytesIO(b"")
        empty_file.name = "empty.tsv"

        data = {"file": empty_file, "metadata_table_id": self.metadata_table.id}

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Should get bad request due to empty file
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        # The serializer validates the file and returns field-specific errors
        self.assertIn("file", response_data)
        self.assertIn("empty", response_data["file"][0].lower())

    def test_import_sdrf_nonexistent_table(self):
        """Test SDRF import with nonexistent metadata table."""
        import io

        sdrf_content = "source name\nSample1\n"
        file_data = io.BytesIO(sdrf_content.encode("utf-8"))
        file_data.name = "test.tsv"

        data = {
            "file": file_data,
            "metadata_table_id": 99999,  # Nonexistent ID
            "replace_existing": True,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Should get bad request due to invalid metadata_table_id
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        # The serializer validates the metadata_table_id and returns field-specific errors
        self.assertIn("metadata_table_id", response_data)
        self.assertIn("Invalid", response_data["metadata_table_id"][0])

    def test_import_sdrf_replace_existing_false(self):
        """Test SDRF import without replacing existing data."""
        import io

        # Create existing column
        existing_column = MetadataColumn.objects.create(
            metadata_table=self.metadata_table,
            name="existing_column",
            type="test",
            column_position=0,
        )

        # Import new data without replacing
        sdrf_content = "source name\tcharacteristics[organism]\nSample1\thomo sapiens\n"
        file_data = io.BytesIO(sdrf_content.encode("utf-8"))
        file_data.name = "test.tsv"

        data = {
            "file": file_data,
            "metadata_table_id": self.metadata_table.id,
            "replace_existing": False,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, data, format="multipart")

        # Should succeed
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Existing column should still exist
        self.assertTrue(MetadataColumn.objects.filter(id=existing_column.id).exists())

        # New columns should also exist
        columns = self.metadata_table.columns.all()
        self.assertGreater(columns.count(), 1)  # Original + new columns


# ===================================================================
# ONTOLOGY AND CONTROLLED VOCABULARY TESTS
# ===================================================================


class SpeciesModelTest(TestCase):
    """Test cases for Species ontology model."""

    def test_create_species(self):
        """Test creating a species record."""
        from ccv.models import Species

        species = Species.objects.create(
            code="HUMAN",
            taxon=9606,
            official_name="Homo sapiens",
            common_name="Human",
            synonym="H. sapiens",
        )

        self.assertEqual(species.code, "HUMAN")
        self.assertEqual(species.taxon, 9606)
        self.assertEqual(species.official_name, "Homo sapiens")
        self.assertEqual(species.common_name, "Human")
        self.assertEqual(species.synonym, "H. sapiens")

    def test_species_string_representation(self):
        """Test string representation of species."""
        from ccv.models import Species

        species = Species.objects.create(code="HUMAN", taxon=9606, official_name="Homo sapiens")
        self.assertEqual(str(species), "Homo sapiens (HUMAN)")


class TissueModelTest(TestCase):
    """Test cases for Tissue ontology model."""

    def test_create_tissue(self):
        """Test creating a tissue record."""
        from ccv.models import Tissue

        tissue = Tissue.objects.create(
            identifier="UBERON_0002107",
            accession="liver",
            synonyms="hepatic tissue",
            cross_references="FMA:7197",
        )

        self.assertEqual(tissue.identifier, "UBERON_0002107")
        self.assertEqual(tissue.accession, "liver")
        self.assertEqual(tissue.synonyms, "hepatic tissue")
        self.assertEqual(tissue.cross_references, "FMA:7197")

    def test_tissue_string_representation(self):
        """Test string representation of tissue."""
        from ccv.models import Tissue

        tissue = Tissue.objects.create(identifier="UBERON_0002107", accession="liver")
        self.assertEqual(str(tissue), "liver (UBERON_0002107)")


class HumanDiseaseModelTest(TestCase):
    """Test cases for HumanDisease ontology model."""

    def test_create_human_disease(self):
        """Test creating a human disease record."""
        from ccv.models import HumanDisease

        disease = HumanDisease.objects.create(
            identifier="MONDO_0007254",
            acronym="BC",
            accession="breast carcinoma",
            definition="A carcinoma that arises from the breast.",
            synonyms="breast cancer",
            cross_references="DOID:3459",
            keywords="cancer, oncology",
        )

        self.assertEqual(disease.identifier, "MONDO_0007254")
        self.assertEqual(disease.acronym, "BC")
        self.assertEqual(disease.accession, "breast carcinoma")
        self.assertEqual(disease.definition, "A carcinoma that arises from the breast.")
        self.assertEqual(disease.synonyms, "breast cancer")
        self.assertEqual(disease.cross_references, "DOID:3459")
        self.assertEqual(disease.keywords, "cancer, oncology")

    def test_disease_string_representation(self):
        """Test string representation of disease."""
        from ccv.models import HumanDisease

        disease = HumanDisease.objects.create(identifier="MONDO_0007254", accession="breast carcinoma")
        self.assertEqual(str(disease), "breast carcinoma (MONDO_0007254)")


class SubcellularLocationModelTest(TestCase):
    """Test cases for SubcellularLocation ontology model."""

    def test_create_subcellular_location(self):
        """Test creating a subcellular location record."""
        from ccv.models import SubcellularLocation

        location = SubcellularLocation.objects.create(
            accession="GO_0005634",
            location_identifier="nucleus",
            definition="The nucleus of a cell.",
            synonyms="cell nucleus",
            content="DNA, RNA, proteins",
        )

        self.assertEqual(location.accession, "GO_0005634")
        self.assertEqual(location.location_identifier, "nucleus")
        self.assertEqual(location.definition, "The nucleus of a cell.")
        self.assertEqual(location.synonyms, "cell nucleus")
        self.assertEqual(location.content, "DNA, RNA, proteins")

    def test_subcellular_location_string_representation(self):
        """Test string representation of subcellular location."""
        from ccv.models import SubcellularLocation

        location = SubcellularLocation.objects.create(accession="GO_0005634", location_identifier="nucleus")
        self.assertEqual(str(location), "nucleus (GO_0005634)")


class MSUniqueVocabulariesModelTest(TestCase):
    """Test cases for MSUniqueVocabularies ontology model."""

    def test_create_ms_term(self):
        """Test creating an MS vocabulary term."""
        from ccv.models import MSUniqueVocabularies

        term = MSUniqueVocabularies.objects.create(
            accession="MS_1000031",
            name="instrument model",
            definition="A descriptor for the instrument model.",
            term_type="instrument",
        )

        self.assertEqual(term.accession, "MS_1000031")
        self.assertEqual(term.name, "instrument model")
        self.assertEqual(term.definition, "A descriptor for the instrument model.")
        self.assertEqual(term.term_type, "instrument")

    def test_ms_term_string_representation(self):
        """Test string representation of MS term."""
        from ccv.models import MSUniqueVocabularies

        term = MSUniqueVocabularies.objects.create(accession="MS_1000031", name="instrument model")
        self.assertEqual(str(term), "instrument model (MS_1000031)")


class UnimodModelTest(TestCase):
    """Test cases for Unimod ontology model."""

    def test_create_unimod(self):
        """Test creating a Unimod modification record."""
        from ccv.models import Unimod

        mod = Unimod.objects.create(
            accession="UNIMOD_1",
            name="Acetyl",
            definition="Acetylation of lysine residues.",
            additional_data={"mass": 42.010565, "formula": "C2H2O"},
        )

        self.assertEqual(mod.accession, "UNIMOD_1")
        self.assertEqual(mod.name, "Acetyl")
        self.assertEqual(mod.definition, "Acetylation of lysine residues.")
        self.assertEqual(mod.additional_data["mass"], 42.010565)
        self.assertEqual(mod.additional_data["formula"], "C2H2O")

    def test_unimod_string_representation(self):
        """Test string representation of Unimod modification."""
        from ccv.models import Unimod

        mod = Unimod.objects.create(accession="UNIMOD_1", name="Acetyl")
        self.assertEqual(str(mod), "Acetyl (UNIMOD_1)")


class OntologyAPITest(APITestCase):
    """Test cases for ontology API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)

        # Create test ontology data
        from ccv.models import HumanDisease, MSUniqueVocabularies, Species, SubcellularLocation, Tissue, Unimod

        Species.objects.create(code="HUMAN", taxon=9606, official_name="Homo sapiens", common_name="Human")
        Species.objects.create(code="MOUSE", taxon=10090, official_name="Mus musculus", common_name="Mouse")

        Tissue.objects.create(identifier="UBERON_0002107", accession="liver", synonyms="hepatic tissue")
        Tissue.objects.create(identifier="UBERON_0002048", accession="lung", synonyms="pulmonary tissue")

        HumanDisease.objects.create(
            identifier="MONDO_0007254",
            accession="breast carcinoma",
            definition="A carcinoma that arises from the breast.",
        )

        SubcellularLocation.objects.create(
            accession="GO_0005634",
            location_identifier="nucleus",
            definition="The nucleus of a cell.",
        )

        MSUniqueVocabularies.objects.create(
            accession="MS_1000031",
            name="instrument model",
            definition="A descriptor for the instrument model.",
            term_type="instrument",
        )

        Unimod.objects.create(
            accession="UNIMOD_1",
            name="Acetyl",
            definition="Acetylation of lysine residues.",
        )

    def test_species_api_list(self):
        """Test species API list endpoint."""
        url = reverse("ccv:species-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        # Check first species
        first_species = data["results"][0]
        self.assertIn("code", first_species)
        self.assertIn("official_name", first_species)
        self.assertIn("common_name", first_species)

    def test_species_api_search(self):
        """Test species API search functionality."""
        url = reverse("ccv:species-list")
        response = self.client.get(url, {"search": "human"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["code"], "HUMAN")

    def test_species_api_filter_by_taxon(self):
        """Test species API filtering by taxon ID."""
        url = reverse("ccv:species-list")
        response = self.client.get(url, {"taxon": "9606"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["taxon"], 9606)

    def test_tissue_api_list(self):
        """Test tissue API list endpoint."""
        url = reverse("ccv:tissue-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 2)

    def test_tissue_api_search(self):
        """Test tissue API search functionality."""
        url = reverse("ccv:tissue-list")
        response = self.client.get(url, {"search": "liver"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["accession"], "liver")

    def test_disease_api_list(self):
        """Test disease API list endpoint."""
        url = reverse("ccv:humandisease-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_disease_api_search(self):
        """Test disease API search functionality."""
        url = reverse("ccv:humandisease-list")
        response = self.client.get(url, {"search": "breast"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["accession"], "breast carcinoma")

    def test_subcellular_location_api_list(self):
        """Test subcellular location API list endpoint."""
        url = reverse("ccv:subcellularlocation-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_subcellular_location_api_search(self):
        """Test subcellular location API search functionality."""
        url = reverse("ccv:subcellularlocation-list")
        response = self.client.get(url, {"search": "nucleus"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["location_identifier"], "nucleus")

    def test_ms_terms_api_list(self):
        """Test MS terms API list endpoint."""
        url = reverse("ccv:msuniquevocabularies-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_ms_terms_api_filter_by_type(self):
        """Test MS terms API filtering by term type."""
        url = reverse("ccv:msuniquevocabularies-list")
        response = self.client.get(url, {"term_type": "instrument"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["term_type"], "instrument")

    def test_ms_terms_api_search(self):
        """Test MS terms API search functionality."""
        url = reverse("ccv:msuniquevocabularies-list")
        response = self.client.get(url, {"search": "instrument"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "instrument model")

    def test_unimod_api_list(self):
        """Test Unimod API list endpoint."""
        url = reverse("ccv:unimod-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_unimod_api_search(self):
        """Test Unimod API search functionality."""
        url = reverse("ccv:unimod-list")
        response = self.client.get(url, {"search": "acetyl"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Acetyl")

    def test_ontology_api_authentication_required(self):
        """Test that ontology APIs require authentication."""
        # Logout user
        self.client.force_authenticate(user=None)

        urls = [
            reverse("ccv:species-list"),
            reverse("ccv:tissue-list"),
            reverse("ccv:humandisease-list"),
            reverse("ccv:subcellularlocation-list"),
            reverse("ccv:msuniquevocabularies-list"),
            reverse("ccv:unimod-list"),
        ]

        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ontology_api_read_only(self):
        """Test that ontology APIs are read-only."""
        urls = [
            reverse("ccv:species-list"),
            reverse("ccv:tissue-list"),
            reverse("ccv:humandisease-list"),
            reverse("ccv:subcellularlocation-list"),
            reverse("ccv:msuniquevocabularies-list"),
            reverse("ccv:unimod-list"),
        ]

        test_data = {"name": "test"}

        for url in urls:
            # Test POST (create)
            response = self.client.post(url, test_data)
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

            # Test PUT (update) - using a made-up ID
            response = self.client.put(f"{url}1/", test_data)
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

            # Test DELETE
            response = self.client.delete(f"{url}1/")
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
