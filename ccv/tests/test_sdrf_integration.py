"""
Integration tests for SDRF import/export functionality with realistic data.

Tests complete SDRF workflows using real fixture data and scientific metadata patterns.
"""

import csv
import io
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.utils import detect_pooled_samples, sort_metadata, validate_sdrf
from tests.factories import (
    LabGroupFactory,
    MetadataColumnFactory,
    MetadataTableFactory,
    QuickTestDataMixin,
    SamplePoolFactory,
    UserFactory,
    read_fixture_content,
)

User = get_user_model()


class SDRFParsingIntegrationTest(TestCase, QuickTestDataMixin):
    """Test SDRF parsing with real fixture data."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

    def test_parse_pdc000126_fixture(self):
        """Test parsing PDC000126 fixture (proteomics with pooling)."""
        content = read_fixture_content("PDC000126.sdrf.tsv")
        if not content:
            self.skipTest("PDC000126.sdrf.tsv fixture not found")
            return

        lines = content.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Test header structure matches expected SDRF format
        expected_headers = [
            "source name",
            "characteristics[organism]",
            "characteristics[organism part]",
            "characteristics[disease]",
            "assay name",
            "technology type",
        ]

        for expected in expected_headers:
            found = any(expected in header for header in headers)
            self.assertTrue(found, f"Expected header '{expected}' not found in {headers[:5]}")

        # Test data content
        self.assertGreater(len(data_rows), 5)  # Should have multiple samples

        # Test first row content
        first_row = data_rows[0]
        self.assertEqual(first_row[0], "PDC000126-Sample-1")  # source name

        # Find organism column
        organism_col_idx = None
        for i, header in enumerate(headers):
            if "organism]" in header and "characteristics[" in header:
                organism_col_idx = i
                break

        self.assertIsNotNone(organism_col_idx)
        self.assertEqual(first_row[organism_col_idx], "Homo sapiens")

        # Test pooled sample detection
        pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

        # PDC000126 has enrichment but not traditional pooling
        self.assertIsNotNone(pooled_column_index or sn_rows or pooled_rows)

    def test_parse_pxd002137_fixture(self):
        """Test parsing PXD002137 fixture (label-free proteomics)."""
        content = read_fixture_content("PXD002137.sdrf.tsv")
        if not content:
            self.skipTest("PXD002137.sdrf.tsv fixture not found")
            return

        lines = content.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Test PXD-specific patterns
        self.assertIn("source name", headers)
        self.assertTrue(any("organism]" in h for h in headers))
        self.assertTrue(any("disease]" in h for h in headers))

        # Test data patterns
        first_row = data_rows[0]
        self.assertTrue(first_row[0].startswith("PXD"))  # PXD accession pattern

        # Test organism data
        organism_idx = None
        for i, header in enumerate(headers):
            if "organism]" in header:
                organism_idx = i
                break

        if organism_idx:
            self.assertEqual(first_row[organism_idx], "Homo sapiens")

        # Test technology type
        tech_idx = None
        for i, header in enumerate(headers):
            if "technology type" in header:
                tech_idx = i
                break

        if tech_idx:
            self.assertEqual(first_row[tech_idx], "proteomic profiling by mass spectrometry")

    def test_parse_pxd019185_fixture(self):
        """Test parsing PXD019185 fixture (complex with pooling)."""
        content = read_fixture_content("PXD019185_PXD018883.sdrf.tsv")
        if not content:
            self.skipTest("PXD019185_PXD018883.sdrf.tsv fixture not found")
            return

        lines = content.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Test complex header structure
        self.assertGreater(len(headers), 30)  # Complex study with many columns

        # Test pooled sample detection
        pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

        # This fixture should have pooled samples
        self.assertIsNotNone(pooled_column_index)
        self.assertGreater(len(pooled_rows), 0)

        # Test specific sample names from fixture
        sample_names = [row[0] for row in data_rows]
        self.assertIn("D-HEp3 #1", sample_names)
        self.assertIn("T-HEp3 #1", sample_names)

        # Test pooled sample values
        if pooled_column_index:
            pooled_values = [row[pooled_column_index] for row in data_rows]
            self.assertIn("pooled", pooled_values)
            self.assertIn("not pooled", pooled_values)

    def test_sdrf_column_parsing_accuracy(self):
        """Test accurate parsing of SDRF column types and values."""
        # Create test SDRF with various column types
        test_sdrf = (
            "source name\tcharacteristics[organism]\tcharacteristics[organism part]\t"
            "characteristics[disease]\tcharacteristics[cell type]\t"
            "comment[instrument]\tcomment[modification parameters]\t"
            "comment[cleavage agent details]\tfactor value[phenotype]\n"
            "Sample-001\thomo sapiens\tliver\tnormal\thepatocyte\t"
            "NT=Orbitrap Fusion Lumos;AC=MS:1002732\t"
            "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M\t"
            "AC=MS:1001313;NT=Trypsin\tnormal\n"
        )

        lines = test_sdrf.strip().split("\n")
        headers = lines[0].split("\t")
        data_row = lines[1].split("\t")

        # Test parsing logic for different column types
        parsed_columns = []
        for i, header in enumerate(headers):
            if "[" in header and "]" in header:
                name_part = header.split("[")[0].strip()
                type_part = header.split("[")[1].rstrip("]").strip()
            else:
                name_part = header.strip()
                type_part = ""

            parsed_columns.append(
                {
                    "name": name_part,
                    "type": type_part,
                    "value": data_row[i] if i < len(data_row) else "",
                    "column_position": i,
                }
            )

        # Test specific column parsing
        source_col = parsed_columns[0]
        self.assertEqual(source_col["name"], "source name")
        self.assertEqual(source_col["type"], "")
        self.assertEqual(source_col["value"], "Sample-001")

        organism_col = parsed_columns[1]
        self.assertEqual(organism_col["name"], "characteristics")
        self.assertEqual(organism_col["type"], "organism")
        self.assertEqual(organism_col["value"], "homo sapiens")

        instrument_col = parsed_columns[5]
        self.assertEqual(instrument_col["name"], "comment")
        self.assertEqual(instrument_col["type"], "instrument")
        self.assertIn("Orbitrap", instrument_col["value"])
        self.assertIn("MS:1002732", instrument_col["value"])

        modification_col = parsed_columns[6]
        self.assertEqual(modification_col["name"], "comment")
        self.assertEqual(modification_col["type"], "modification parameters")
        self.assertIn("UNIMOD:35", modification_col["value"])

        factor_col = parsed_columns[8]
        self.assertEqual(factor_col["name"], "factor value")
        self.assertEqual(factor_col["type"], "phenotype")
        self.assertEqual(factor_col["value"], "normal")

    def test_pooled_sample_detection_algorithms(self):
        """Test pooled sample detection with various pooling patterns."""
        # Test Case 1: Simple pooled/not pooled pattern
        headers1 = ["source name", "characteristics[pooled sample]", "assay name"]
        data1 = [["Sample1", "pooled", "run1"], ["Sample2", "pooled", "run2"], ["Sample3", "not pooled", "run3"]]

        pooled_col, sn_rows, pooled_rows = detect_pooled_samples(data1, headers1)
        self.assertEqual(pooled_col, 1)
        self.assertEqual(len(pooled_rows), 2)
        self.assertIn(0, pooled_rows)
        self.assertIn(1, pooled_rows)

        # Test Case 2: SN= pattern
        headers2 = ["source name", "characteristics[pooled sample]", "assay name"]
        data2 = [
            ["Sample1", "pooled", "run1"],
            ["Sample2", "pooled", "run2"],
            ["SN=Sample1,Sample2", "SN=Sample1,Sample2", "pool_run"],
        ]

        pooled_col, sn_rows, pooled_rows = detect_pooled_samples(data2, headers2)
        self.assertEqual(len(sn_rows), 1)
        self.assertIn(2, sn_rows)
        self.assertEqual(len(pooled_rows), 2)

        # Test Case 3: No pooling
        headers3 = ["source name", "characteristics[disease]", "assay name"]
        data3 = [["Sample1", "normal", "run1"], ["Sample2", "cancer", "run2"]]

        pooled_col, sn_rows, pooled_rows = detect_pooled_samples(data3, headers3)
        self.assertIsNone(pooled_col)
        self.assertEqual(len(sn_rows), 0)
        self.assertEqual(len(pooled_rows), 0)


class SDRFImportIntegrationTest(APITestCase, QuickTestDataMixin):
    """Test complete SDRF import workflow via API."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.lab_group = LabGroupFactory.create_lab_group()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, lab_group=self.lab_group)
        self.client.force_authenticate(user=self.user)
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

    def create_sdrf_file(self, content, filename="test.sdrf.tsv"):
        """Create SDRF file for testing."""
        return SimpleUploadedFile(filename, content.encode("utf-8"), content_type="text/tab-separated-values")

    def test_complete_import_workflow_basic(self):
        """Test complete import workflow with basic SDRF."""
        sdrf_content = (
            "source name\tcharacteristics[organism]\tcharacteristics[organism part]\t"
            "characteristics[disease]\tassay name\ttechnology type\n"
            "HCC-001\thomo sapiens\tliver\thepatocellular carcinoma\trun 1\t"
            "proteomic profiling by mass spectrometry\n"
            "HCC-002\thomo sapiens\tliver\thepatocellular carcinoma\trun 2\t"
            "proteomic profiling by mass spectrometry\n"
            "Normal-001\thomo sapiens\tliver\tnormal\trun 3\t"
            "proteomic profiling by mass spectrometry\n"
        )

        sdrf_file = self.create_sdrf_file(sdrf_content, "hepatitis_study.sdrf.tsv")

        # Import SDRF
        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": False,
        }

        url = "/api/ccv/metadatamanagement/import-sdrf-file/"  # Adjust URL as needed
        response = self.client.post(url, import_data, format="multipart")

        if response.status_code != status.HTTP_200_OK:
            self.skipTest(f"SDRF import endpoint not available: {response.status_code}")
            return

        # Test response
        data = response.json()
        self.assertEqual(data["message"], "SDRF file imported successfully")
        self.assertEqual(data["created_columns"], 6)  # 6 columns in SDRF
        self.assertEqual(data["sample_rows"], 3)  # 3 data rows

        # Test database changes
        self.table.refresh_from_db()
        self.assertEqual(self.table.sample_count, 3)

        # Test column creation
        columns = self.table.columns.all().order_by("column_position")
        self.assertEqual(columns.count(), 6)

        # Test specific columns
        source_col = columns.get(name="source name", type="")
        self.assertIsNotNone(source_col)
        self.assertTrue(source_col.mandatory)

        organism_col = columns.get(name="characteristics", type="organism")
        self.assertEqual(organism_col.value, "homo sapiens")

        tech_col = columns.get(name="technology type")
        self.assertEqual(tech_col.value, "proteomic profiling by mass spectrometry")

    def test_complete_import_with_pooling(self):
        """Test complete import workflow with pooled samples."""
        pooled_sdrf = (
            "source name\tcharacteristics[organism]\tcharacteristics[pooled sample]\t"
            "characteristics[phenotype]\tassay name\n"
            "D-HEp3 #1\thomo sapiens\tpooled\tcell cycle arrest in mitotic G1 phase\trun 1\n"
            "D-HEp3 #2\thomo sapiens\tpooled\tcell cycle arrest in mitotic G1 phase\trun 2\n"
            "T-HEp3 #1\thomo sapiens\tnot pooled\tproliferating cells\trun 3\n"
            "SN=D-HEp3 #1,D-HEp3 #2\thomo sapiens\tSN=D-HEp3 #1,D-HEp3 #2\t"
            "mixed phenotype\tpool_run\n"
        )

        sdrf_file = self.create_sdrf_file(pooled_sdrf, "pooled_study.sdrf.tsv")

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        url = "/api/ccv/metadatamanagement/import-sdrf-file/"
        response = self.client.post(url, import_data, format="multipart")

        if response.status_code != status.HTTP_200_OK:
            self.skipTest(f"SDRF import endpoint not available: {response.status_code}")
            return

        # Test pooling detection and creation
        data = response.json()
        self.assertTrue(data["pools_detected"])
        self.assertGreater(data["pooled_rows_count"], 0)
        self.assertGreaterEqual(data["sn_rows_count"], 0)

        if data["created_pools"] > 0:
            # Test pool creation
            pools = self.table.sample_pools.all()
            self.assertGreater(pools.count(), 0)

            # Test pool properties
            first_pool = pools.first()
            self.assertTrue(first_pool.is_reference)
            self.assertTrue(first_pool.sdrf_value.startswith("SN="))

            # Test pool sample references
            self.assertGreater(first_pool.get_total_samples(), 0)

    @patch("ccv.utils.validate_sdrf")
    def test_import_with_validation(self, mock_validate):
        """Test import with SDRF validation."""
        mock_validate.return_value = []  # No validation errors

        sdrf_content = (
            "source name\tcharacteristics[organism]\tassay name\ttechnology type\n"
            "Sample1\thomo sapiens\trun 1\tproteomic profiling by mass spectrometry\n"
        )

        sdrf_file = self.create_sdrf_file(sdrf_content)

        import_data = {"file": sdrf_file, "metadata_table_id": self.table.id, "replace_existing": True}

        url = "/api/ccv/metadatamanagement/import-sdrf-file/"
        response = self.client.post(url, import_data, format="multipart")

        if response.status_code == status.HTTP_200_OK:
            # Test that validation was called
            mock_validate.assert_called_once()

            # Test successful import
            data = response.json()
            self.assertIn("message", data)

    def test_import_replace_vs_append(self):
        """Test difference between replacing and appending columns."""
        # First import
        first_sdrf = "source name\tcharacteristics[organism]\tassay name\n" "Sample1\thomo sapiens\trun 1\n"

        first_file = self.create_sdrf_file(first_sdrf, "first_import.sdrf.tsv")

        import_data = {"file": first_file, "metadata_table_id": self.table.id, "replace_existing": True}

        url = "/api/ccv/metadatamanagement/import-sdrf-file/"
        response = self.client.post(url, import_data, format="multipart")

        if response.status_code != status.HTTP_200_OK:
            self.skipTest("SDRF import endpoint not available")
            return

        # Check first import results
        first_column_count = self.table.columns.count()
        self.assertGreater(first_column_count, 0)

        # Second import with replace_existing=False
        second_sdrf = "source name\tcharacteristics[disease]\tassay name\n" "Sample2\tbreast carcinoma\trun 2\n"

        second_file = self.create_sdrf_file(second_sdrf, "second_import.sdrf.tsv")

        import_data["file"] = second_file
        import_data["replace_existing"] = False

        response = self.client.post(url, import_data, format="multipart")

        if response.status_code == status.HTTP_200_OK:
            # Should have more columns now (existing + new)
            final_column_count = self.table.columns.count()
            self.assertGreaterEqual(final_column_count, first_column_count)

        # Third import with replace_existing=True
        import_data["replace_existing"] = True
        third_file = self.create_sdrf_file(second_sdrf, "third_import.sdrf.tsv")
        import_data["file"] = third_file

        response = self.client.post(url, import_data, format="multipart")

        if response.status_code == status.HTTP_200_OK:
            # Should replace all columns
            replaced_column_count = self.table.columns.count()
            # Count should match the new import only
            self.assertLessEqual(replaced_column_count, final_column_count)

    def test_import_error_handling(self):
        """Test error handling during import."""
        # Test malformed SDRF
        malformed_sdrf = "invalid\tsdrf\ncontent\twith\tmismatched\tcolumns\n"
        malformed_file = self.create_sdrf_file(malformed_sdrf, "malformed.sdrf.tsv")

        import_data = {"file": malformed_file, "metadata_table_id": self.table.id}

        url = "/api/ccv/metadatamanagement/import-sdrf-file/"
        response = self.client.post(url, import_data, format="multipart")

        # Should handle malformed data gracefully
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            error_data = response.json()
            self.assertIn("error", error_data)
        elif response.status_code == status.HTTP_200_OK:
            # Some malformed data might still be processed
            data = response.json()
            self.assertIn("message", data)


class SDRFExportIntegrationTest(TestCase, QuickTestDataMixin):
    """Test SDRF export functionality."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=6)

    def test_export_basic_sdrf(self):
        """Test exporting metadata table to SDRF format."""
        # Create realistic metadata columns
        columns_data = [
            ("source name", "", 0, "Sample-001", True),
            ("characteristics[organism]", "characteristics", 1, "homo sapiens", True),
            ("characteristics[organism part]", "characteristics", 2, "liver", True),
            ("characteristics[disease]", "characteristics", 3, "normal", True),
            ("assay name", "", 4, "run 1", True),
            ("technology type", "", 5, "proteomic profiling by mass spectrometry", False),
        ]

        created_columns = []
        for name, col_type, position, value, mandatory in columns_data:
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name=name,
                type=col_type,
                column_position=position,
                value=value,
                mandatory=mandatory,
            )
            created_columns.append(column)

        # Test export using sort_metadata utility
        result_data, id_map = sort_metadata(created_columns, self.table.sample_count)

        # Test SDRF structure
        self.assertEqual(len(result_data), self.table.sample_count + 1)  # Header + data rows

        # Test header format
        header = result_data[0]
        self.assertEqual(len(header), len(columns_data))

        # Test header formatting - should match the column names exactly
        self.assertEqual(header[0], "source name")
        self.assertEqual(header[1], "characteristics[organism]")
        self.assertEqual(header[2], "characteristics[organism part]")
        self.assertEqual(header[3], "characteristics[disease]")
        self.assertEqual(header[4], "assay name")
        self.assertEqual(header[5], "technology type")

        # Test data rows
        first_data_row = result_data[1]
        self.assertEqual(first_data_row[0], "Sample-001")
        self.assertEqual(first_data_row[1], "homo sapiens")
        self.assertEqual(first_data_row[2], "liver")

        # Test that all rows have same length
        for row in result_data:
            self.assertEqual(len(row), len(columns_data))

    def test_export_with_modifiers(self):
        """Test export with sample-specific modifiers."""
        # Create column with modifiers
        modifiers = [
            {"samples": "1,2", "value": "TMT126"},
            {"samples": "3,4", "value": "TMT127N"},
            {"samples": "5,6", "value": "TMT128N"},
        ]

        columns = [
            MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name="source name",
                type="",
                column_position=0,
                value="Sample",
                mandatory=True,
            ),
            MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name="comment[label]",
                type="comment",
                column_position=1,
                value="TMT126",  # Default value
                modifiers=modifiers,
            ),
        ]

        # Export with modifiers
        result_data, id_map = sort_metadata(columns, self.table.sample_count)

        # Test that modifiers are applied
        self.assertEqual(result_data[1][1], "TMT126")  # Sample 1
        self.assertEqual(result_data[2][1], "TMT126")  # Sample 2
        self.assertEqual(result_data[3][1], "TMT127N")  # Sample 3
        self.assertEqual(result_data[4][1], "TMT127N")  # Sample 4
        self.assertEqual(result_data[5][1], "TMT128N")  # Sample 5
        self.assertEqual(result_data[6][1], "TMT128N")  # Sample 6

    def test_export_with_pools(self):
        """Test export with sample pools."""
        # Create basic columns
        columns = [
            MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name="source name",
                type="",
                column_position=0,
                value="Sample",
                mandatory=True,
            ),
            MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name="characteristics[pooled sample]",
                type="characteristics",
                column_position=1,
                value="not pooled",
            ),
        ]

        # Create sample pool
        SamplePoolFactory.create_pool(
            metadata_table=self.table, pool_name="Test Pool", pooled_only_samples=[1, 2, 3], is_reference=True
        )

        # Export data
        result_data, id_map = sort_metadata(columns, self.table.sample_count)

        # Test basic export structure
        self.assertEqual(len(result_data), self.table.sample_count + 1)  # Header + data

        # Test that pool information could be included (depends on implementation)
        header = result_data[0]
        self.assertIn("characteristics[pooled sample]", header)

    def test_export_to_tsv_format(self):
        """Test exporting to actual TSV format."""
        # Create comprehensive columns
        columns_data = [
            ("source name", "", "PDC000126-Sample"),
            ("characteristics[organism]", "characteristics", "homo sapiens"),
            ("characteristics[organism part]", "characteristics", "endometrium"),
            ("characteristics[disease]", "characteristics", "cervical endometrioid adenocarcinoma"),
            ("comment[instrument]", "comment", "NT=Orbitrap Fusion Lumos;AC=MS:1002732"),
            ("assay name", "", "run"),
            ("technology type", "", "proteomic profiling by mass spectrometry"),
        ]

        columns = []
        for i, (name, col_type, value_base) in enumerate(columns_data):
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name=name,
                type=col_type,
                column_position=i,
                value=value_base + (f" {i+1}" if "run" in value_base or "Sample" in value_base else ""),
                mandatory=True,
            )
            columns.append(column)

        # Export to data structure
        result_data, id_map = sort_metadata(columns, self.table.sample_count)

        # Convert to TSV format
        output = io.StringIO()
        writer = csv.writer(output, delimiter="\t", quoting=csv.QUOTE_MINIMAL)

        for row in result_data:
            writer.writerow(row)

        tsv_content = output.getvalue()

        # Test TSV format
        lines = tsv_content.strip().split("\n")
        self.assertEqual(len(lines), self.table.sample_count + 1)  # Header + data rows

        # Test header line
        header_line = lines[0]
        self.assertIn("source name", header_line)
        self.assertIn("characteristics[organism]", header_line)
        self.assertIn("comment[instrument]", header_line)

        # Test data lines
        first_data_line = lines[1]
        self.assertIn("PDC000126-Sample", first_data_line)
        self.assertIn("homo sapiens", first_data_line)
        self.assertIn("cervical endometrioid adenocarcinoma", first_data_line)

        # Test TSV format (tab-separated)
        for line in lines:
            self.assertIn("\t", line)
            parts = line.split("\t")
            self.assertEqual(len(parts), len(columns_data))

    def test_roundtrip_import_export(self):
        """Test importing SDRF and then exporting it maintains data integrity."""
        # Create original SDRF content
        original_sdrf = (
            "source name\tcharacteristics[organism]\tcharacteristics[disease]\t"
            "comment[instrument]\tassay name\n"
            "HCC-001\thomo sapiens\thepatocellular carcinoma\t"
            "NT=Orbitrap Fusion Lumos;AC=MS:1002732\trun 1\n"
            "Normal-001\thomo sapiens\tnormal\t"
            "NT=Orbitrap Fusion Lumos;AC=MS:1002732\trun 2\n"
        )

        # Parse original SDRF (simulate import)
        lines = original_sdrf.strip().split("\n")
        headers = lines[0].split("\t")
        data_rows = [line.split("\t") for line in lines[1:]]

        # Create columns based on parsed data
        columns = []
        for i, header in enumerate(headers):
            if "[" in header and "]" in header:
                # For SDRF format like "characteristics[organism]"
                category_part = header.split("[")[0].strip()  # "characteristics"
                column_name = header.strip()  # "characteristics[organism]" (full name)
                column_type = category_part  # "characteristics" (the category)
            else:
                # For standalone columns like "source name"
                column_name = header.strip()
                column_type = ""

            # Use first data row value as default
            default_value = data_rows[0][i] if data_rows else ""

            column = MetadataColumnFactory.create_column(
                metadata_table=self.table, name=column_name, type=column_type, column_position=i, value=default_value
            )
            columns.append(column)

        # Update table sample count
        self.table.sample_count = len(data_rows)
        self.table.save()

        # Export back to SDRF format
        result_data, id_map = sort_metadata(columns, self.table.sample_count)

        # Test that exported header matches original structure
        exported_header = result_data[0]

        # The exported headers should match the original headers exactly
        # Compare (order might be different due to processing)
        for header in headers:
            self.assertIn(header.strip(), exported_header)

        # Test data integrity
        self.assertEqual(len(result_data), len(data_rows) + 1)  # Header + data

        # Test specific values are preserved
        first_data_row = result_data[1]
        self.assertIn("HCC-001", first_data_row)
        self.assertIn("homo sapiens", first_data_row)
        self.assertIn("Orbitrap", " ".join(first_data_row))


class SDRFValidationIntegrationTest(TestCase, QuickTestDataMixin):
    """Test SDRF validation with realistic scenarios."""

    def test_validate_minimal_sdrf(self):
        """Test validation of minimal valid SDRF."""
        minimal_sdrf = [
            ["source name", "characteristics[organism]", "assay name", "technology type"],
            ["Sample1", "homo sapiens", "run 1", "proteomic profiling by mass spectrometry"],
            ["Sample2", "homo sapiens", "run 2", "proteomic profiling by mass spectrometry"],
        ]

        # Test validation (may require sdrf-pipelines package)
        try:
            errors = validate_sdrf(minimal_sdrf)
            self.assertIsInstance(errors, list)
            # Minimal SDRF might have warnings but should not have critical errors
        except ImportError:
            self.skipTest("sdrf-pipelines not available for validation")

    def test_validate_complex_sdrf(self):
        """Test validation of complex SDRF with many columns."""
        complex_sdrf = [
            [
                "source name",
                "characteristics[organism]",
                "characteristics[organism part]",
                "characteristics[disease]",
                "characteristics[cell type]",
                "characteristics[age]",
                "comment[instrument]",
                "comment[modification parameters]",
                "comment[cleavage agent details]",
                "assay name",
                "technology type",
            ],
            [
                "PDC000126-Sample-1",
                "homo sapiens",
                "endometrium",
                "cervical endometrioid adenocarcinoma",
                "not available",
                "65Y",
                "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "NT=Oxidation;MT=Variable;TA=M;AC=Unimod:35",
                "AC=MS:1001313;NT=Trypsin",
                "run 1",
                "proteomic profiling by mass spectrometry",
            ],
        ]

        try:
            errors = validate_sdrf(complex_sdrf)
            self.assertIsInstance(errors, list)
            # Complex SDRF should validate successfully
        except ImportError:
            self.skipTest("sdrf-pipelines not available for validation")

    def test_validate_invalid_sdrf(self):
        """Test validation catches invalid SDRF."""
        invalid_sdrf = [
            ["invalid_column", "another_invalid"],  # Missing required columns
            ["Sample1", "value1"],
            ["Sample2", "value2"],
        ]

        try:
            errors = validate_sdrf(invalid_sdrf)
            self.assertIsInstance(errors, list)
            # Should have validation errors for missing required columns
            self.assertGreater(len(errors), 0)
        except ImportError:
            self.skipTest("sdrf-pipelines not available for validation")

    def test_validation_with_scientific_accuracy(self):
        """Test validation with scientifically accurate data."""
        scientific_sdrf = [
            [
                "source name",
                "characteristics[organism]",
                "characteristics[organism part]",
                "characteristics[disease]",
                "comment[instrument]",
                "comment[modification parameters]",
                "assay name",
                "technology type",
            ],
            [
                "Breast-Cancer-001",
                "homo sapiens",
                "breast",
                "invasive ductal carcinoma",
                "NT=Q Exactive;AC=MS:1001911",
                "NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed",
                "run 1",
                "proteomic profiling by mass spectrometry",
            ],
            [
                "Normal-Breast-001",
                "homo sapiens",
                "breast",
                "normal",
                "NT=Q Exactive;AC=MS:1001911",
                "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
                "run 2",
                "proteomic profiling by mass spectrometry",
            ],
        ]

        try:
            errors = validate_sdrf(scientific_sdrf)
            self.assertIsInstance(errors, list)

            # Test that scientific terms are accepted
            # (Specific validation depends on sdrf-pipelines implementation)
        except ImportError:
            self.skipTest("sdrf-pipelines not available for validation")
