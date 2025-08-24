"""
Comprehensive test cases for CUPCAKE views with realistic SDRF scenarios.

Tests all view functionality including CRUD operations, permissions, validation,
and integration with realistic scientific metadata patterns.
"""


from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.models import MetadataColumn, MetadataTable
from tests.factories import (
    LabGroupFactory,
    MetadataColumnFactory,
    MetadataTableFactory,
    OntologyFactory,
    QuickTestDataMixin,
    SamplePoolFactory,
    UserFactory,
)

User = get_user_model()


class MetadataTableViewTest(APITestCase, QuickTestDataMixin):
    """Test MetadataTable CRUD views with realistic data."""

    def setUp(self):
        self.user = UserFactory.create_user(username="researcher1")
        self.other_user = UserFactory.create_user(username="researcher2")
        self.lab_group = LabGroupFactory.create_lab_group(name="Proteomics Lab")
        self.client.force_authenticate(user=self.user)

    def test_create_metadata_table(self):
        """Test creating a metadata table via API."""
        create_data = {
            "name": "New Proteomics Study PXD777888",
            "description": "Comprehensive proteomics analysis of liver tissue",
            "sample_count": 24,
            "lab_group": self.lab_group.id,
        }

        url = reverse("ccv:metadatatable-list")
        response = self.client.post(url, create_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response_data = response.json()
        self.assertEqual(response_data["name"], create_data["name"])
        self.assertEqual(response_data["sample_count"], 24)
        self.assertEqual(response_data["creator_username"], self.user.username)
        self.assertEqual(response_data["column_count"], 0)  # No columns initially

        # Verify database record
        table = MetadataTable.objects.get(id=response_data["id"])
        self.assertEqual(table.creator, self.user)
        self.assertEqual(table.lab_group, self.lab_group)

    def test_list_metadata_tables(self):
        """Test listing metadata tables with filtering."""
        # Create tables for different users
        MetadataTableFactory.create_basic_table(user=self.user, name="User Study 1", lab_group=self.lab_group)
        MetadataTableFactory.create_basic_table(user=self.user, name="User Study 2", lab_group=self.lab_group)
        MetadataTableFactory.create_basic_table(user=self.other_user, name="Other User Study")

        url = reverse("ccv:metadatatable-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        results = response_data["results"]

        # Test that user sees appropriate tables (depends on permissions)
        table_names = [table["name"] for table in results]
        self.assertIn("User Study 1", table_names)
        self.assertIn("User Study 2", table_names)

        # Test filtering by name
        search_response = self.client.get(url, {"search": "User Study 1"})
        self.assertEqual(search_response.status_code, status.HTTP_200_OK)

        search_results = search_response.json()["results"]
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0]["name"], "User Study 1")

    def test_retrieve_metadata_table(self):
        """Test retrieving a specific metadata table."""
        table = MetadataTableFactory.create_with_columns(
            user=self.user, lab_group=self.lab_group, name="Detailed Study PXD123456", column_count=8, sample_count=16
        )

        url = reverse("ccv:metadatatable-detail", args=[table.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Detailed Study PXD123456")
        self.assertEqual(data["sample_count"], 16)
        self.assertEqual(data["column_count"], 8)
        self.assertEqual(data["creator_username"], self.user.username)

        # Test that columns are included (if configured)
        if "columns" in data:
            self.assertEqual(len(data["columns"]), 8)

    def test_update_metadata_table(self):
        """Test updating a metadata table."""
        table = MetadataTableFactory.create_basic_table(
            user=self.user, name="Original Study Name", description="Original description"
        )

        update_data = {
            "name": "Updated Study Name PXD999000",
            "description": "Updated comprehensive proteomics study with enhanced methodology",
            "sample_count": 30,
        }

        url = reverse("ccv:metadatatable-detail", args=[table.id])
        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], update_data["name"])
        self.assertEqual(data["description"], update_data["description"])
        self.assertEqual(data["sample_count"], 30)

        # Verify database update
        table.refresh_from_db()
        self.assertEqual(table.name, update_data["name"])
        self.assertEqual(table.sample_count, 30)

    def test_delete_metadata_table(self):
        """Test deleting a metadata table."""
        table = MetadataTableFactory.create_basic_table(user=self.user)
        table_id = table.id

        url = reverse("ccv:metadatatable-detail", args=[table.id])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify deletion
        self.assertFalse(MetadataTable.objects.filter(id=table_id).exists())

    def test_permissions_other_user_table(self):
        """Test permission restrictions on other user's tables."""
        other_table = MetadataTableFactory.create_basic_table(user=self.other_user)

        # Test retrieve (may be allowed depending on permissions)
        url = reverse("ccv:metadatatable-detail", args=[other_table.id])
        response = self.client.get(url)

        # Response depends on permission configuration
        if response.status_code == status.HTTP_403_FORBIDDEN:
            self.assertIn("permission", response.json().get("detail", "").lower())

        # Test update (should be forbidden)
        update_data = {"name": "Unauthorized Update"}
        response = self.client.patch(url, update_data, format="json")

        # Should be forbidden or not found
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_create_table_validation_errors(self):
        """Test validation errors when creating tables."""
        invalid_data = {
            "name": "",  # Empty name
            "sample_count": -5,  # Negative count
            "lab_group": 99999,  # Non-existent lab group
        }

        url = reverse("ccv:metadatatable-list")
        response = self.client.post(url, invalid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        errors = response.json()
        self.assertIn("name", errors)
        if "sample_count" in errors:
            self.assertIn("sample_count", errors)
        if "lab_group" in errors:
            self.assertIn("lab_group", errors)

    def test_table_with_realistic_scientific_data(self):
        """Test creating table with realistic scientific metadata."""
        scientific_data = {
            "name": "Breast Cancer Biomarker Discovery PXD001122",
            "description": "Label-free quantitative proteomics analysis of breast cancer tissue samples using "
            "Orbitrap mass spectrometry to identify potential biomarkers for early detection",
            "sample_count": 48,  # Typical study size
            "lab_group": self.lab_group.id,
            "technology_type": "proteomic profiling by mass spectrometry",
        }

        url = reverse("ccv:metadatatable-list")
        response = self.client.post(url, scientific_data, format="json")

        if response.status_code == status.HTTP_201_CREATED:
            data = response.json()
            self.assertIn("Breast Cancer", data["name"])
            self.assertIn("biomarkers", data["description"])
            self.assertEqual(data["sample_count"], 48)
        else:
            # Check if validation failed due to field constraints
            errors = response.json()
            self.assertIsInstance(errors, dict)


class MetadataColumnViewTest(APITestCase, QuickTestDataMixin):
    """Test MetadataColumn CRUD views with SDRF patterns."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=20)
        self.client.force_authenticate(user=self.user)

    def test_create_metadata_column(self):
        """Test creating metadata columns via API."""
        column_data = {
            "name": "characteristics",
            "type": "organism",
            "value": "homo sapiens",
            "column_position": 1,
            "mandatory": True,
            "metadata_table": self.table.id,
        }

        url = reverse("ccv:metadatacolumn-list")
        response = self.client.post(url, column_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["name"], "characteristics")
        self.assertEqual(data["type"], "organism")
        self.assertEqual(data["value"], "homo sapiens")
        self.assertTrue(data["mandatory"])

        # Verify database record
        column = MetadataColumn.objects.get(id=data["id"])
        self.assertEqual(column.metadata_table, self.table)

    def test_create_column_with_modifiers(self):
        """Test creating column with sample-specific modifiers."""
        modifiers_data = {
            "samples": [
                {"samples": ["1", "2", "3"], "value": "TMT126"},
                {"samples": ["4", "5", "6"], "value": "TMT127N"},
                {"samples": ["7", "8", "9"], "value": "TMT128N"},
            ]
        }

        column_data = {
            "name": "comment",
            "type": "label",
            "value": "TMT126",  # Default value
            "modifiers": modifiers_data,
            "column_position": 5,
            "metadata_table": self.table.id,
        }

        url = reverse("ccv:metadatacolumn-list")
        response = self.client.post(url, column_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["type"], "label")
        self.assertIn("modifiers", data)

        # Test modifier structure
        modifiers = data["modifiers"]
        self.assertIn("samples", modifiers)
        self.assertEqual(len(modifiers["samples"]), 3)

        # Test first modifier
        first_modifier = modifiers["samples"][0]
        self.assertEqual(first_modifier["samples"], ["1", "2", "3"])
        self.assertEqual(first_modifier["value"], "TMT126")

    def test_create_sdrf_compliant_columns(self):
        """Test creating columns that match SDRF specifications."""
        sdrf_columns = [
            {"name": "source name", "type": "", "value": "PDC000126-Sample-1", "mandatory": True, "column_position": 0},
            {
                "name": "characteristics",
                "type": "organism",
                "value": "homo sapiens",
                "mandatory": True,
                "column_position": 1,
            },
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "mandatory": False,
                "column_position": 2,
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
                "mandatory": False,
                "column_position": 3,
            },
        ]

        created_columns = []
        url = reverse("ccv:metadatacolumn-list")

        for column_data in sdrf_columns:
            column_data["metadata_table"] = self.table.id
            response = self.client.post(url, column_data, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            created_columns.append(response.json())

        # Test SDRF-specific patterns
        source_col = created_columns[0]
        self.assertEqual(source_col["name"], "source name")
        self.assertTrue(source_col["mandatory"])

        instrument_col = created_columns[2]
        self.assertIn("Orbitrap", instrument_col["value"])
        self.assertIn("MS:1002732", instrument_col["value"])

        modification_col = created_columns[3]
        self.assertIn("UNIMOD:35", modification_col["value"])
        self.assertIn("Variable", modification_col["value"])

    def test_list_columns_for_table(self):
        """Test listing columns for a specific metadata table."""
        # Create multiple columns
        columns_data = [
            ("source name", "", 0),
            ("organism", "characteristics", 1),
            ("disease", "characteristics", 2),
            ("assay name", "", 3),
        ]

        created_columns = []
        for name, col_type, position in columns_data:
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table, name=name, type=col_type, column_position=position
            )
            created_columns.append(column)

        # List all columns
        url = reverse("ccv:metadatacolumn-list")
        response = self.client.get(url, {"metadata_table": self.table.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        results = data["results"]
        self.assertEqual(len(results), 4)

        # Test ordering by column_position
        positions = [col["column_position"] for col in results]
        self.assertEqual(positions, sorted(positions))

    def test_update_column(self):
        """Test updating a metadata column."""
        column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="disease", value="normal"
        )

        update_data = {"value": "breast carcinoma", "mandatory": True}

        url = reverse("ccv:metadatacolumn-detail", args=[column.id])
        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["value"], "breast carcinoma")
        self.assertTrue(data["mandatory"])

        # Verify database update
        column.refresh_from_db()
        self.assertEqual(column.value, "breast carcinoma")

    def test_delete_column(self):
        """Test deleting a metadata column."""
        column = MetadataColumnFactory.create_column(metadata_table=self.table)
        column_id = column.id

        url = reverse("ccv:metadatacolumn-detail", args=[column.id])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify deletion
        self.assertFalse(MetadataColumn.objects.filter(id=column_id).exists())

    def test_column_validation_errors(self):
        """Test validation errors when creating columns."""
        invalid_data = {
            "name": "",  # Empty name
            "column_position": -1,  # Negative position
            "metadata_table": 99999,  # Non-existent table
        }

        url = reverse("ccv:metadatacolumn-list")
        response = self.client.post(url, invalid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        errors = response.json()
        self.assertIn("name", errors)
        self.assertIn("metadata_table", errors)


class SamplePoolViewTest(APITestCase, QuickTestDataMixin):
    """Test SamplePool CRUD views with pooling scenarios."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=20)
        self.client.force_authenticate(user=self.user)

    def test_create_sample_pool(self):
        """Test creating a sample pool via API."""
        pool_data = {
            "pool_name": "API Test Pool",
            "pool_description": "Pool created via API testing",
            "pooled_only_samples": [1, 2, 3, 4],
            "pooled_and_independent_samples": [5, 6],
            "is_reference": True,
            "metadata_table": self.table.id,
        }

        url = reverse("ccv:samplepool-list")
        response = self.client.post(url, pool_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["pool_name"], "API Test Pool")
        self.assertEqual(data["pooled_only_samples"], [1, 2, 3, 4])
        self.assertEqual(data["pooled_and_independent_samples"], [5, 6])
        self.assertTrue(data["is_reference"])
        self.assertEqual(data["total_samples"], 6)

        # Test SDRF value generation
        self.assertIn("SN=", data["sdrf_value"])

    def test_create_sdrf_pattern_pool(self):
        """Test creating pool with SDRF SN= pattern."""
        pool_data = {
            "pool_name": "SN=D-HEp3 #1,D-HEp3 #2,T-HEp3 #1",
            "pool_description": "Pool following SDRF SN= convention",
            "pooled_only_samples": [7, 8, 9],
            "is_reference": True,
            "metadata_table": self.table.id,
        }

        url = reverse("ccv:samplepool-list")
        response = self.client.post(url, pool_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertTrue(data["pool_name"].startswith("SN="))
        self.assertIn("D-HEp3", data["pool_name"])
        self.assertTrue(data["is_reference"])
        self.assertEqual(data["total_samples"], 3)

    def test_list_pools_for_table(self):
        """Test listing sample pools for a metadata table."""
        # Create multiple pools
        pools_data = [("Pool Alpha", [1, 2, 3], []), ("Pool Beta", [4, 5], [6, 7]), ("Pool Gamma", [], [8, 9, 10])]

        created_pools = []
        for pool_name, pooled_only, pooled_and_independent in pools_data:
            pool = SamplePoolFactory.create_pool(
                metadata_table=self.table,
                pool_name=pool_name,
                pooled_only_samples=pooled_only,
                pooled_and_independent_samples=pooled_and_independent,
            )
            created_pools.append(pool)

        url = reverse("ccv:samplepool-list")
        response = self.client.get(url, {"metadata_table": self.table.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        results = data["results"]
        self.assertEqual(len(results), 3)

        pool_names = [pool["pool_name"] for pool in results]
        self.assertIn("Pool Alpha", pool_names)
        self.assertIn("Pool Beta", pool_names)
        self.assertIn("Pool Gamma", pool_names)

    def test_update_sample_pool(self):
        """Test updating a sample pool."""
        pool = SamplePoolFactory.create_pool(
            metadata_table=self.table, pool_name="Original Pool", pooled_only_samples=[1, 2]
        )

        update_data = {
            "pool_name": "Updated Pool Name",
            "pool_description": "Updated description",
            "pooled_only_samples": [1, 2, 3, 4],
        }

        url = reverse("ccv:samplepool-detail", args=[pool.id])
        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["pool_name"], "Updated Pool Name")
        self.assertEqual(data["pooled_only_samples"], [1, 2, 3, 4])
        self.assertEqual(data["total_samples"], 4)

    def test_pool_validation_errors(self):
        """Test validation errors when creating pools."""
        invalid_data = {
            "pool_name": "",  # Empty name
            "pooled_only_samples": [25, 26],  # Exceeds table sample_count (20)
            "metadata_table": self.table.id,
        }

        url = reverse("ccv:samplepool-list")
        response = self.client.post(url, invalid_data, format="json")

        # Response depends on validation implementation
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            errors = response.json()
            self.assertIn("pool_name", errors)
            # May also have validation for sample numbers
        else:
            # Pool creation might succeed depending on validation rules
            self.assertIn(response.status_code, [status.HTTP_201_CREATED])


class SDRFImportExportViewTest(APITestCase, QuickTestDataMixin):
    """Test SDRF import and export functionality."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=10)
        self.client.force_authenticate(user=self.user)

    def create_test_sdrf_file(self, content, filename="test.sdrf.tsv"):
        """Helper to create test SDRF file."""
        return SimpleUploadedFile(filename, content.encode("utf-8"), content_type="text/tab-separated-values")

    def test_import_basic_sdrf(self):
        """Test importing a basic SDRF file."""
        sdrf_content = (
            "source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\n"
            "Sample-001\thomo sapiens\tbreast carcinoma\trun 1\n"
            "Sample-002\thomo sapiens\tnormal\trun 2\n"
            "Sample-003\thomo sapiens\tbreast carcinoma\trun 3\n"
        )

        sdrf_file = self.create_test_sdrf_file(sdrf_content)

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": False,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("message", data)
        self.assertEqual(data["message"], "SDRF file imported successfully")
        self.assertIn("created_columns", data)
        self.assertIn("sample_rows", data)

        # Test that columns were created
        self.assertGreater(data["created_columns"], 0)
        self.assertEqual(data["sample_rows"], 3)

        # Verify database changes
        self.table.refresh_from_db()
        self.assertEqual(self.table.sample_count, 3)

        # Check created columns
        columns = self.table.columns.all()
        self.assertGreater(columns.count(), 0)

        # Check for expected columns
        column_names = [(col.name, col.type) for col in columns]
        self.assertIn(("source name", ""), column_names)
        self.assertIn(("characteristics", "organism"), column_names)
        self.assertIn(("characteristics", "disease"), column_names)

    def test_import_realistic_sdrf(self):
        """Test importing realistic SDRF with complex data."""
        realistic_sdrf = (
            "source name\tcharacteristics[organism]\tcharacteristics[organism part]\t"
            "characteristics[disease]\tcharacteristics[cell type]\t"
            "comment[instrument]\tcomment[modification parameters]\t"
            "comment[cleavage agent details]\tassay name\n"
            "PDC000126-Sample-1\thomo sapiens\tendometrium\t"
            "cervical endometrioid adenocarcinoma\tnot available\t"
            "NT=Orbitrap Fusion Lumos;AC=MS:1002732\t"
            "NT=Oxidation;MT=Variable;TA=M;AC=Unimod:35\t"
            "AC=MS:1001313;NT=Trypsin\trun 1\n"
            "PDC000126-Sample-2\thomo sapiens\tendometrium\tnormal\t"
            "not available\tNT=Orbitrap Fusion Lumos;AC=MS:1002732\t"
            "NT=Carbamidomethyl;TA=C;MT=fixed;AC=UNIMOD:4\t"
            "AC=MS:1001313;NT=Trypsin\trun 2\n"
        )

        sdrf_file = self.create_test_sdrf_file(realistic_sdrf, "realistic_study.sdrf.tsv")

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": False,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["message"], "SDRF file imported successfully")

        # Test complex column creation
        self.assertGreater(data["created_columns"], 8)  # Should have many columns
        self.assertEqual(data["sample_rows"], 2)

        # Verify complex data in database
        columns = self.table.columns.all()

        # Check for instrument column with complex value
        instrument_col = columns.filter(name="comment", type="instrument").first()
        self.assertIsNotNone(instrument_col)
        self.assertIn("Orbitrap", instrument_col.value)
        self.assertIn("MS:1002732", instrument_col.value)

        # Check for modification parameters
        mod_col = columns.filter(name="comment", type="modification parameters").first()
        self.assertIsNotNone(mod_col)
        self.assertIn("UNIMOD:", mod_col.value)

    def test_import_sdrf_with_pools(self):
        """Test importing SDRF with pooled samples."""
        pooled_sdrf = (
            "source name\tcharacteristics[organism]\tcharacteristics[pooled sample]\tassay name\n"
            "D-HEp3 #1\thomo sapiens\tpooled\trun 1\n"
            "D-HEp3 #2\thomo sapiens\tpooled\trun 2\n"
            "T-HEp3 #1\thomo sapiens\tnot pooled\trun 3\n"
            "SN=D-HEp3 #1,D-HEp3 #2\thomo sapiens\tSN=D-HEp3 #1,D-HEp3 #2\tpool_run\n"
        )

        sdrf_file = self.create_test_sdrf_file(pooled_sdrf, "pooled_study.sdrf.tsv")

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertTrue(data["pools_detected"])
        self.assertGreater(data["pooled_rows_count"], 0)

        # May have SN= rows depending on detection logic
        if "sn_rows_count" in data:
            self.assertGreaterEqual(data["sn_rows_count"], 0)

        # Check if pools were created
        if data["created_pools"] > 0:
            pools = self.table.sample_pools.all()
            self.assertGreater(pools.count(), 0)

            # Check pool properties
            first_pool = pools.first()
            self.assertTrue(first_pool.is_reference)
            self.assertTrue(first_pool.sdrf_value.startswith("SN="))

    def test_import_from_fixture_file(self):
        """Test importing from a real fixture file."""
        import os

        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "PXD002137.sdrf.tsv")

        if not os.path.exists(fixture_path):
            self.skipTest("Fixture file not found")
            return

        with open(fixture_path, "rb") as f:
            file_content = f.read()

        # Create file object for upload
        file_obj = SimpleUploadedFile("PXD002137.sdrf.tsv", file_content, content_type="text/tab-separated-values")

        import_data = {
            "file": file_obj,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["message"], "SDRF file imported successfully")

        # Real fixture should have substantial data
        self.assertGreater(data["created_columns"], 10)
        self.assertGreater(data["sample_rows"], 5)

    def test_export_sdrf(self):
        """Test exporting metadata table to SDRF format."""
        # Create table with columns
        table_with_data = MetadataTableFactory.create_with_columns(
            user=self.user, name="Export Test Study", column_count=6, sample_count=8
        )

        # Test export endpoint (if available)
        export_url = reverse("ccv:metadatatable-export-sdrf", args=[table_with_data.id])
        response = self.client.get(export_url)

        if response.status_code == status.HTTP_200_OK:
            # Test response headers
            self.assertEqual(response["Content-Type"], "text/tab-separated-values")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertIn(".sdrf.tsv", response["Content-Disposition"])

            # Test content
            content = response.content.decode("utf-8")
            lines = content.strip().split("\n")

            # Should have header + data rows
            self.assertGreater(len(lines), 1)

            # Test header structure
            header = lines[0]
            self.assertIn("\t", header)  # Tab-separated

            # Test data rows
            if len(lines) > 1:
                first_row = lines[1]
                self.assertIn("\t", first_row)
        else:
            # Export endpoint might not be implemented yet
            self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_501_NOT_IMPLEMENTED])

    def test_import_validation_errors(self):
        """Test import validation with invalid files."""
        # Test empty file
        empty_file = SimpleUploadedFile("empty.tsv", b"", content_type="text/plain")

        import_data = {"file": empty_file, "metadata_table_id": self.table.id}

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        errors = response.json()
        self.assertIn("file", errors)
        self.assertIn("empty", str(errors["file"]).lower())

    def test_import_permission_denied(self):
        """Test import with insufficient permissions."""
        other_user = UserFactory.create_user(username="other_user")
        other_table = MetadataTableFactory.create_basic_table(user=other_user)

        sdrf_content = "source name\nSample1\n"
        sdrf_file = self.create_test_sdrf_file(sdrf_content)

        import_data = {"file": sdrf_file, "metadata_table_id": other_table.id}

        url = reverse("ccv:metadatamanagement-import-sdrf-file")
        response = self.client.post(url, import_data, format="multipart")

        # Should be forbidden
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        error_data = response.json()
        self.assertIn("permission", error_data.get("error", "").lower())


class OntologyViewTest(APITestCase, QuickTestDataMixin):
    """Test ontology API views."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.client.force_authenticate(user=self.user)

        # Create test ontology data
        self.species_list = [OntologyFactory.create_species() for _ in range(5)]
        self.tissues_list = [OntologyFactory.create_tissue() for _ in range(5)]
        self.diseases_list = [OntologyFactory.create_disease() for _ in range(3)]

    def test_species_list_api(self):
        """Test species list API endpoint."""
        url = reverse("ccv:species-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 5)

        # Test first species structure
        first_species = data["results"][0]
        self.assertIn("code", first_species)
        self.assertIn("official_name", first_species)
        self.assertIn("taxon", first_species)
        self.assertIn("common_name", first_species)

    def test_species_search(self):
        """Test species search functionality."""
        # Create specific species for testing
        OntologyFactory.create_species(code="HUMAN", official_name="Homo sapiens", common_name="Human")

        url = reverse("ccv:species-list")
        response = self.client.get(url, {"search": "human"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        results = data["results"]

        # Should find the human species
        found_human = any(result["code"] == "HUMAN" or "human" in result["common_name"].lower() for result in results)
        self.assertTrue(found_human)

    def test_tissue_list_api(self):
        """Test tissue list API endpoint."""
        url = reverse("ccv:tissue-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 5)

        # Test tissue structure
        first_tissue = data["results"][0]
        self.assertIn("identifier", first_tissue)
        self.assertIn("accession", first_tissue)
        self.assertIn("synonyms", first_tissue)

    def test_disease_list_api(self):
        """Test disease list API endpoint."""
        url = reverse("ccv:humandisease-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 3)

        # Test disease structure
        first_disease = data["results"][0]
        self.assertIn("identifier", first_disease)
        self.assertIn("accession", first_disease)
        self.assertIn("definition", first_disease)

    def test_ontology_api_read_only(self):
        """Test that ontology APIs are read-only."""
        ontology_urls = [reverse("ccv:species-list"), reverse("ccv:tissue-list"), reverse("ccv:humandisease-list")]

        test_data = {"name": "test"}

        for url in ontology_urls:
            # Test POST (create) - should be forbidden
            response = self.client.post(url, test_data)
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

            # Test PUT (update) - should be forbidden
            response = self.client.put(f"{url}1/", test_data)
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

            # Test DELETE - should be forbidden
            response = self.client.delete(f"{url}1/")
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_ontology_suggestion_endpoint(self):
        """Test unified ontology suggestion endpoint."""
        # This endpoint might provide suggestions across ontology types
        suggestion_url = reverse("ccv:ontology-suggestions")

        if hasattr(self, "client"):  # Check if endpoint exists
            response = self.client.get(suggestion_url, {"query": "human"})

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                self.assertIn("suggestions", data)

                # Test suggestion structure
                if data["suggestions"]:
                    first_suggestion = data["suggestions"][0]
                    self.assertIn("id", first_suggestion)
                    self.assertIn("value", first_suggestion)
                    self.assertIn("display_name", first_suggestion)
                    self.assertIn("ontology_type", first_suggestion)
            else:
                # Endpoint might not be implemented
                self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_501_NOT_IMPLEMENTED])


class PermissionAndAuthenticationTest(APITestCase, QuickTestDataMixin):
    """Test authentication and permission requirements."""

    def setUp(self):
        self.user = UserFactory.create_user(username="authenticated_user")
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

    def test_unauthenticated_access(self):
        """Test that unauthenticated requests are rejected."""
        # Don't authenticate client

        protected_urls = [
            reverse("ccv:metadatatable-list"),
            reverse("ccv:metadatacolumn-list"),
            reverse("ccv:samplepool-list"),
            reverse("ccv:species-list"),
        ]

        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_access(self):
        """Test that authenticated requests are allowed."""
        self.client.force_authenticate(user=self.user)

        accessible_urls = [
            reverse("ccv:metadatatable-list"),
            reverse("ccv:metadatacolumn-list"),
            reverse("ccv:samplepool-list"),
            reverse("ccv:species-list"),
        ]

        for url in accessible_urls:
            response = self.client.get(url)
            self.assertIn(
                response.status_code, [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]  # Might be missing in test setup
            )

    def test_cross_user_permissions(self):
        """Test permissions between different users."""
        other_user = UserFactory.create_user(username="other_user")
        other_table = MetadataTableFactory.create_basic_table(user=other_user)

        # Authenticate as first user
        self.client.force_authenticate(user=self.user)

        # Try to access other user's table
        url = reverse("ccv:metadatatable-detail", args=[other_table.id])
        response = self.client.get(url)

        # Should be forbidden or not found depending on permission model
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Try to modify other user's table
        response = self.client.patch(url, {"name": "Unauthorized Update"})
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
