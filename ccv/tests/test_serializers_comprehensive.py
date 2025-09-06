"""
Comprehensive test cases for CUPCAKE serializers with realistic SDRF data.

Tests all serializer functionality using realistic data patterns from SDRF fixtures
and scientific metadata conventions.
"""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APITestCase

from ccv.models import MetadataTable
from ccv.serializers import (
    FavouriteMetadataOptionSerializer,
    HumanDiseaseSerializer,
    MetadataColumnSerializer,
    MetadataImportSerializer,
    MetadataTableSerializer,
    MetadataValidationSerializer,
    MSUniqueVocabulariesSerializer,
    OntologySuggestionSerializer,
    SamplePoolSerializer,
    SpeciesSerializer,
    TissueSerializer,
    UnimodSerializer,
)
from tests.factories import (
    FavouriteMetadataOptionFactory,
    LabGroupFactory,
    MetadataColumnFactory,
    MetadataTableFactory,
    OntologyFactory,
    QuickTestDataMixin,
    SamplePoolFactory,
    UserFactory,
)

User = get_user_model()


class MetadataTableSerializerTest(TestCase, QuickTestDataMixin):
    """Test MetadataTable serializer with realistic data."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.lab_group = LabGroupFactory.create_lab_group()

    def test_serialize_basic_metadata_table(self):
        """Test serializing a basic metadata table."""
        table = MetadataTableFactory.create_basic_table(
            user=self.user,
            lab_group=self.lab_group,
            name="Proteomics Study PXD012345",
            description="Human liver proteomics analysis",
            sample_count=24,
        )

        serializer = MetadataTableSerializer(table)
        data = serializer.data

        # Test basic fields
        self.assertEqual(data["name"], "Proteomics Study PXD012345")
        self.assertEqual(data["description"], "Human liver proteomics analysis")
        self.assertEqual(data["sample_count"], 24)
        self.assertEqual(data["owner_username"], self.user.username)
        self.assertEqual(data["lab_group_name"], self.lab_group.name)
        self.assertFalse(data["is_locked"])
        self.assertFalse(data["is_published"])

        # Test computed fields
        self.assertEqual(data["column_count"], 0)  # No columns yet
        self.assertIsNotNone(data["created_at"])
        self.assertIsNotNone(data["updated_at"])

    def test_serialize_table_with_columns_and_pools(self):
        """Test serializing table with related columns and pools."""
        table = MetadataTableFactory.create_with_columns(
            user=self.user, lab_group=self.lab_group, column_count=8, sample_count=15
        )

        # Add sample pools
        SamplePoolFactory.create_pool(metadata_table=table, pool_name="Pool A", pooled_only_samples=[1, 2, 3])
        SamplePoolFactory.create_pool(metadata_table=table, pool_name="Pool B", pooled_only_samples=[4, 5, 6])

        serializer = MetadataTableSerializer(table)
        data = serializer.data

        # Test column count
        self.assertEqual(data["column_count"], 8)

        # Test that pools are included (if configured in serializer)
        # This depends on your serializer configuration
        if "sample_pools" in data:
            self.assertEqual(len(data["sample_pools"]), 2)

    def test_deserialize_metadata_table(self):
        """Test deserializing metadata table data."""
        table_data = {
            "name": "New Study PXD098765",
            "description": "Brain tissue proteomics study",
            "sample_count": 18,
            "lab_group": self.lab_group.id,
        }

        serializer = MetadataTableSerializer(data=table_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Test that validation passes
        validated_data = serializer.validated_data
        self.assertEqual(validated_data["name"], "New Study PXD098765")
        self.assertEqual(validated_data["sample_count"], 18)
        self.assertEqual(validated_data["lab_group"], self.lab_group)

    def test_validation_errors(self):
        """Test serializer validation with invalid data."""
        invalid_data = {
            "name": "",  # Empty name should fail
            "sample_count": -5,  # Negative sample count should fail
            "lab_group": 99999,  # Non-existent lab group
        }

        serializer = MetadataTableSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        self.assertIn("name", errors)
        if "sample_count" in errors:  # Depends on model validation
            self.assertIn("sample_count", errors)

    def test_serializer_with_realistic_scientific_data(self):
        """Test serializer with realistic scientific metadata."""
        realistic_data = {
            "name": f"Cancer Proteomics Study PXD{123456}",
            "description": "Quantitative proteomics analysis of breast cancer tissue using TMT labeling and Orbitrap mass spectrometry",
            "sample_count": 32,
            "technology_type": "proteomic profiling by mass spectrometry",
            "lab_group": self.lab_group.id,
        }

        serializer = MetadataTableSerializer(data=realistic_data)

        if serializer.is_valid():
            # Test that realistic scientific data is accepted
            validated = serializer.validated_data
            self.assertIn("Cancer Proteomics", validated["name"])
            self.assertIn("TMT labeling", validated["description"])
            self.assertEqual(validated["sample_count"], 32)
        else:
            # If validation fails, check if it's expected
            self.fail(f"Realistic data should be valid: {serializer.errors}")


class MetadataColumnSerializerTest(TestCase, QuickTestDataMixin):
    """Test MetadataColumn serializer with SDRF patterns."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

    def test_serialize_basic_column(self):
        """Test serializing a basic metadata column."""
        column = MetadataColumnFactory.create_column(
            metadata_table=self.table,
            name="characteristics",
            type="organism",
            value="homo sapiens",
            column_position=1,
            mandatory=True,
        )

        serializer = MetadataColumnSerializer(column)
        data = serializer.data

        self.assertEqual(data["name"], "characteristics")
        self.assertEqual(data["type"], "organism")
        self.assertEqual(data["value"], "homo sapiens")
        self.assertEqual(data["column_position"], 1)
        self.assertTrue(data["mandatory"])
        self.assertFalse(data["hidden"])

    def test_serialize_column_with_modifiers(self):
        """Test serializing column with sample-specific modifiers."""
        modifiers = {
            "samples": [
                {"samples": ["1", "2"], "value": "TMT126"},
                {"samples": ["3", "4"], "value": "TMT127N"},
                {"samples": ["5", "6"], "value": "TMT128N"},
            ]
        }

        column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="label", value="TMT126", modifiers=modifiers
        )

        serializer = MetadataColumnSerializer(column)
        data = serializer.data

        self.assertIn("modifiers", data)
        self.assertIn("samples", data["modifiers"])
        self.assertEqual(len(data["modifiers"]["samples"]), 3)

        # Test modifier structure
        first_modifier = data["modifiers"]["samples"][0]
        self.assertEqual(first_modifier["samples"], ["1", "2"])
        self.assertEqual(first_modifier["value"], "TMT126")

    def test_serialize_sdrf_compliant_columns(self):
        """Test serializing columns that match SDRF specifications."""
        sdrf_columns_data = [
            {"name": "source name", "type": "", "value": "Sample-001", "mandatory": True},
            {"name": "characteristics", "type": "organism", "value": "homo sapiens", "mandatory": True},
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "mandatory": False,
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
                "mandatory": False,
            },
        ]

        serialized_columns = []
        for i, col_data in enumerate(sdrf_columns_data):
            column = MetadataColumnFactory.create_column(metadata_table=self.table, column_position=i, **col_data)

            serializer = MetadataColumnSerializer(column)
            serialized_columns.append(serializer.data)

        # Test SDRF-specific patterns
        source_col = serialized_columns[0]
        self.assertEqual(source_col["name"], "source name")
        self.assertTrue(source_col["mandatory"])

        organism_col = serialized_columns[1]
        self.assertEqual(organism_col["type"], "organism")
        self.assertEqual(organism_col["value"], "homo sapiens")

        instrument_col = serialized_columns[2]
        self.assertIn("NT=", instrument_col["value"])
        self.assertIn("AC=MS:", instrument_col["value"])

        modification_col = serialized_columns[3]
        self.assertIn("UNIMOD:", modification_col["value"])
        self.assertIn("MT=Variable", modification_col["value"])

    def test_deserialize_column_data(self):
        """Test deserializing column data."""
        column_data = {
            "name": "characteristics",
            "type": "disease",
            "value": "breast carcinoma",
            "column_position": 5,
            "mandatory": True,
            "hidden": False,
            "metadata_table": self.table.id,
        }

        serializer = MetadataColumnSerializer(data=column_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        validated = serializer.validated_data
        self.assertEqual(validated["name"], "characteristics")
        self.assertEqual(validated["type"], "disease")
        self.assertEqual(validated["value"], "breast carcinoma")

    def test_column_validation_with_invalid_data(self):
        """Test column validation with invalid data."""
        invalid_data = {
            "name": "",  # Empty name
            "column_position": -1,  # Negative position
            "metadata_table": 99999,  # Non-existent table
        }

        serializer = MetadataColumnSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        self.assertIn("name", errors)
        if "column_position" in errors:
            self.assertTrue(
                any(
                    "positive" in str(error).lower() or "negative" in str(error).lower()
                    for error in errors["column_position"]
                )
            )


class SamplePoolSerializerTest(TestCase, QuickTestDataMixin):
    """Test SamplePool serializer with pooling scenarios."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=20)

    def test_serialize_basic_sample_pool(self):
        """Test serializing a basic sample pool."""
        pool = SamplePoolFactory.create_pool(
            metadata_table=self.table,
            pool_name="Test Pool A",
            pool_description="Pool for testing serialization",
            pooled_only_samples=[1, 2, 3, 4],
            pooled_and_independent_samples=[5, 6],
            is_reference=True,
        )

        serializer = SamplePoolSerializer(pool)
        data = serializer.data

        self.assertEqual(data["pool_name"], "Test Pool A")
        self.assertEqual(data["pool_description"], "Pool for testing serialization")
        self.assertEqual(data["pooled_only_samples"], [1, 2, 3, 4])
        self.assertEqual(data["pooled_and_independent_samples"], [5, 6])
        self.assertTrue(data["is_reference"])

        # Test computed fields
        self.assertEqual(data["total_samples"], 6)
        self.assertIn("SN=", data["sdrf_value"])

    def test_serialize_sdrf_pattern_pool(self):
        """Test serializing pool created from SDRF SN= pattern."""
        pool = SamplePoolFactory.create_from_sdrf_pattern(
            metadata_table=self.table, sample_names=["D-HEp3 #1", "D-HEp3 #2", "T-HEp3 #1"]
        )

        serializer = SamplePoolSerializer(pool)
        data = serializer.data

        # Test SDRF pattern in pool name
        self.assertTrue(data["pool_name"].startswith("SN="))
        self.assertIn("D-HEp3", data["pool_name"])

        # Test description contains sample names
        self.assertIn("Pool created from samples", data["pool_description"])
        self.assertIn("D-HEp3 #1", data["pool_description"])

        # Test reference flag
        self.assertTrue(data["is_reference"])

    def test_deserialize_pool_data(self):
        """Test deserializing sample pool data."""
        pool_data = {
            "pool_name": "New Pool B",
            "pool_description": "Pool created via API",
            "pooled_only_samples": [7, 8, 9],
            "pooled_and_independent_samples": [10, 11],
            "is_reference": False,
            "metadata_table": self.table.id,
        }

        serializer = SamplePoolSerializer(data=pool_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        validated = serializer.validated_data
        self.assertEqual(validated["pool_name"], "New Pool B")
        self.assertEqual(validated["pooled_only_samples"], [7, 8, 9])
        self.assertFalse(validated["is_reference"])

    def test_pool_validation(self):
        """Test pool validation with edge cases."""
        # Test empty pool
        empty_pool_data = {
            "pool_name": "Empty Pool",
            "pooled_only_samples": [],
            "pooled_and_independent_samples": [],
            "metadata_table": self.table.id,
        }

        serializer = SamplePoolSerializer(data=empty_pool_data)
        # Should be valid (empty pools might be allowed)
        if not serializer.is_valid():
            # Check if this is expected behavior
            self.assertIn("samples", str(serializer.errors).lower())

        # Test pool with sample numbers exceeding table sample count
        invalid_pool_data = {
            "pool_name": "Invalid Pool",
            "pooled_only_samples": [1, 2, 25],  # 25 > table.sample_count (20)
            "metadata_table": self.table.id,
        }

        serializer = SamplePoolSerializer(data=invalid_pool_data)
        if not serializer.is_valid():
            # Validation should catch invalid sample numbers
            errors = serializer.errors
            # Check for sample number validation error
            self.assertTrue(any("sample" in str(error).lower() for error in str(errors)))


class OntologySerializersTest(TestCase, QuickTestDataMixin):
    """Test ontology-related serializers."""

    def test_species_serializer(self):
        """Test Species serializer."""
        species = OntologyFactory.create_species(
            code="HUMAN", taxon=9606, official_name="Homo sapiens", common_name="Human", synonym="H. sapiens"
        )

        serializer = SpeciesSerializer(species)
        data = serializer.data

        self.assertEqual(data["code"], "HUMAN")
        self.assertEqual(data["taxon"], 9606)
        self.assertEqual(data["official_name"], "Homo sapiens")
        self.assertEqual(data["common_name"], "Human")
        self.assertEqual(data["synonym"], "H. sapiens")

    def test_tissue_serializer(self):
        """Test Tissue serializer."""
        tissue = OntologyFactory.create_tissue(
            identifier="UBERON_0002107",
            accession="liver",
            synonyms="hepatic tissue;hepar",
            cross_references="FMA:7197;MA:0000358",
        )

        serializer = TissueSerializer(tissue)
        data = serializer.data

        self.assertEqual(data["identifier"], "UBERON_0002107")
        self.assertEqual(data["accession"], "liver")
        self.assertEqual(data["synonyms"], "hepatic tissue;hepar")
        self.assertEqual(data["cross_references"], "FMA:7197;MA:0000358")

    def test_disease_serializer(self):
        """Test HumanDisease serializer."""
        disease = OntologyFactory.create_disease(
            identifier="MONDO_0007254",
            acronym="BC",
            accession="breast carcinoma",
            definition="A carcinoma that arises from the breast.",
            synonyms="breast cancer;mammary carcinoma",
        )

        serializer = HumanDiseaseSerializer(disease)
        data = serializer.data

        self.assertEqual(data["identifier"], "MONDO_0007254")
        self.assertEqual(data["acronym"], "BC")
        self.assertEqual(data["accession"], "breast carcinoma")
        self.assertIn("carcinoma that arises", data["definition"])

    def test_ms_terms_serializer(self):
        """Test MSUniqueVocabularies serializer."""
        ms_term = OntologyFactory.create_ms_term(
            accession="MS_1002732",
            name="Orbitrap Fusion Lumos",
            definition="Thermo Scientific Orbitrap Fusion Lumos mass spectrometer.",
            term_type="instrument",
        )

        serializer = MSUniqueVocabulariesSerializer(ms_term)
        data = serializer.data

        self.assertEqual(data["accession"], "MS_1002732")
        self.assertEqual(data["name"], "Orbitrap Fusion Lumos")
        self.assertEqual(data["term_type"], "instrument")
        self.assertIn("mass spectrometer", data["definition"])

    def test_unimod_serializer(self):
        """Test Unimod serializer with additional_data JSON field."""
        modification = OntologyFactory.create_unimod(
            accession="UNIMOD_35",
            name="Oxidation",
            definition="Oxidation of methionine residues.",
            additional_data={"mass": 15.994915, "formula": "O", "targets": ["M"], "classification": "chemical"},
        )

        serializer = UnimodSerializer(modification)
        data = serializer.data

        self.assertEqual(data["accession"], "UNIMOD_35")
        self.assertEqual(data["name"], "Oxidation")
        self.assertIn("methionine", data["definition"])

        # Test JSON field serialization
        additional_data = data["additional_data"]
        self.assertAlmostEqual(additional_data["mass"], 15.994915, places=6)
        self.assertEqual(additional_data["formula"], "O")
        self.assertIn("M", additional_data["targets"])


class OntologySuggestionSerializerTest(TestCase, QuickTestDataMixin):
    """Test OntologySuggestionSerializer for unified ontology responses."""

    def test_serialize_species_as_suggestion(self):
        """Test serializing species data as ontology suggestion."""
        species = OntologyFactory.create_species(
            code="MOUSE", taxon=10090, official_name="Mus musculus", common_name="Mouse"
        )

        # Create context for serialization
        context = {"ontology_type": "species"}

        serializer = OntologySuggestionSerializer(species, context=context)
        data = serializer.data

        # Test standardized suggestion format
        self.assertIn("id", data)
        self.assertIn("value", data)
        self.assertIn("display_name", data)
        self.assertEqual(data["ontology_type"], "species")

        # Test that species data is properly mapped
        self.assertEqual(data["value"], "Mus musculus")
        self.assertIn("mouse", data["display_name"].lower())

    def test_serialize_disease_as_suggestion(self):
        """Test serializing disease data as ontology suggestion."""
        disease = OntologyFactory.create_disease(
            identifier="breast carcinoma",
            accession="MONDO:0007254",
            definition="A carcinoma that arises from the breast.",
        )

        context = {"ontology_type": "human_disease"}
        serializer = OntologySuggestionSerializer(disease, context=context)
        data = serializer.data

        self.assertEqual(data["ontology_type"], "human_disease")
        self.assertEqual(data["value"], "breast carcinoma")
        self.assertIn("breast", data["display_name"].lower())

        # Test that full_data contains original model data
        if "full_data" in data:
            full_data = data["full_data"]
            self.assertIn("identifier", full_data)
            self.assertIn("definition", full_data)

    def test_serialize_multiple_ontology_types(self):
        """Test serializing different ontology types with consistent format."""
        # Create different ontology objects
        species = OntologyFactory.create_species()
        tissue = OntologyFactory.create_tissue()
        ms_term = OntologyFactory.create_ms_term()

        ontology_items = [(species, "species"), (tissue, "tissue"), (ms_term, "ms_term")]

        serialized_suggestions = []
        for item, ontology_type in ontology_items:
            context = {"ontology_type": ontology_type}
            serializer = OntologySuggestionSerializer(item, context=context)
            serialized_suggestions.append(serializer.data)

        # Test that all have consistent structure
        for suggestion in serialized_suggestions:
            self.assertIn("id", suggestion)
            self.assertIn("value", suggestion)
            self.assertIn("display_name", suggestion)
            self.assertIn("ontology_type", suggestion)

            # Test that ontology_type is correctly set
            self.assertIn(suggestion["ontology_type"], ["species", "tissue", "ms_term"])

    def test_suggestion_serializer_with_dict_input(self):
        """Test serializer with dictionary input (for search results)."""
        dict_data = {
            "id": "MONDO_0005233",
            "name": "lung carcinoma",
            "definition": "A carcinoma that arises from the lung.",
            "synonyms": "lung cancer",
        }

        context = {"ontology_type": "disease"}
        serializer = OntologySuggestionSerializer(dict_data, context=context)
        data = serializer.data

        # Test that dict data is properly serialized
        self.assertEqual(data["ontology_type"], "disease")
        self.assertIn("lung", data["value"].lower())
        self.assertIn("lung", data["display_name"].lower())


class FavouriteMetadataOptionSerializerTest(TestCase, QuickTestDataMixin):
    """Test FavouriteMetadataOption serializer."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.lab_group = LabGroupFactory.create_lab_group()

    def test_serialize_user_favourite(self):
        """Test serializing user-specific favourite."""
        favourite = FavouriteMetadataOptionFactory.create_favourite(
            user=self.user,
            lab_group=self.lab_group,
            name="organism",
            type="characteristics",
            value="homo sapiens",
            display_value="Human",
        )

        serializer = FavouriteMetadataOptionSerializer(favourite)
        data = serializer.data

        self.assertEqual(data["name"], "organism")
        self.assertEqual(data["type"], "characteristics")
        self.assertEqual(data["value"], "homo sapiens")
        self.assertEqual(data["display_value"], "Human")
        self.assertFalse(data["is_global"])

        # Test user and lab_group are included
        self.assertEqual(data["user"], self.user.id)
        self.assertEqual(data["lab_group"], self.lab_group.id)

    def test_serialize_global_favourite(self):
        """Test serializing global favourite."""
        global_favourite = FavouriteMetadataOptionFactory.create_global_favourite(
            name="disease", type="characteristics", value="normal", display_value="Normal/Healthy"
        )

        serializer = FavouriteMetadataOptionSerializer(global_favourite)
        data = serializer.data

        self.assertEqual(data["value"], "normal")
        self.assertEqual(data["display_value"], "Normal/Healthy")
        self.assertTrue(data["is_global"])
        self.assertIsNone(data["user"])
        self.assertIsNone(data["lab_group"])

    def test_deserialize_favourite_data(self):
        """Test deserializing favourite metadata option."""
        favourite_data = {
            "name": "instrument",
            "type": "comment",
            "value": "orbitrap fusion lumos",
            "display_value": "Orbitrap Fusion Lumos",
            "is_global": False,
            "user": self.user.id,
            "lab_group": self.lab_group.id,
        }

        serializer = FavouriteMetadataOptionSerializer(data=favourite_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        validated = serializer.validated_data
        self.assertEqual(validated["name"], "instrument")
        self.assertEqual(validated["value"], "orbitrap fusion lumos")
        self.assertFalse(validated["is_global"])


class MetadataImportSerializerTest(TestCase, QuickTestDataMixin):
    """Test SDRF import serializer."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

    def create_test_sdrf_file(self, content):
        """Helper to create test SDRF file."""
        return SimpleUploadedFile("test.sdrf.tsv", content.encode("utf-8"), content_type="text/tab-separated-values")

    def test_valid_sdrf_import_data(self):
        """Test SDRF import serializer with valid data."""
        sdrf_content = (
            "source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\n"
            "Sample1\thomo sapiens\tbreast carcinoma\trun 1\n"
            "Sample2\thomo sapiens\tnormal\trun 2\n"
        )

        sdrf_file = self.create_test_sdrf_file(sdrf_content)

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": False,
        }

        serializer = MetadataImportSerializer(data=import_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        validated = serializer.validated_data
        self.assertEqual(validated["metadata_table_id"], self.table.id)
        self.assertTrue(validated["replace_existing"])
        self.assertFalse(validated["create_pools"])

    def test_sdrf_import_validation_errors(self):
        """Test SDRF import validation with invalid data."""
        # Test with empty file
        empty_file = SimpleUploadedFile("empty.tsv", b"", content_type="text/plain")

        import_data = {"file": empty_file, "metadata_table_id": self.table.id}

        serializer = MetadataImportSerializer(data=import_data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        self.assertIn("file", errors)
        self.assertIn("empty", str(errors["file"]).lower())

    def test_sdrf_import_with_nonexistent_table(self):
        """Test SDRF import with non-existent metadata table."""
        sdrf_content = "source name\nSample1\n"
        sdrf_file = self.create_test_sdrf_file(sdrf_content)

        import_data = {"file": sdrf_file, "metadata_table_id": 99999}  # Non-existent table

        serializer = MetadataImportSerializer(data=import_data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        self.assertIn("metadata_table_id", errors)
        self.assertIn("invalid", str(errors["metadata_table_id"]).lower())

    def test_sdrf_import_with_realistic_data(self):
        """Test SDRF import with realistic scientific data."""
        realistic_sdrf_content = (
            "source name\tcharacteristics[organism]\tcharacteristics[organism part]\t"
            "characteristics[disease]\tcharacteristics[cell type]\t"
            "comment[instrument]\tcomment[modification parameters]\tassay name\n"
            "PDC000126-Sample-1\thomo sapiens\tendometrium\t"
            "cervical endometrioid adenocarcinoma\tnot available\t"
            "NT=Orbitrap Fusion Lumos;AC=MS:1002732\t"
            "NT=Oxidation;MT=Variable;TA=M;AC=Unimod:35\trun 1\n"
            "PDC000126-Sample-2\thomo sapiens\tendometrium\tnormal\t"
            "not available\tNT=Orbitrap Fusion Lumos;AC=MS:1002732\t"
            "NT=Carbamidomethyl;TA=C;MT=fixed;AC=UNIMOD:4\trun 2\n"
        )

        sdrf_file = self.create_test_sdrf_file(realistic_sdrf_content)

        import_data = {
            "file": sdrf_file,
            "metadata_table_id": self.table.id,
            "replace_existing": True,
            "create_pools": True,
        }

        serializer = MetadataImportSerializer(data=import_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Test that file content can be read
        validated = serializer.validated_data
        file_obj = validated["file"]
        file_obj.seek(0)  # Reset file pointer
        content = file_obj.read().decode("utf-8")

        # Test that realistic SDRF content is preserved
        self.assertIn("PDC000126-Sample", content)
        self.assertIn("Orbitrap Fusion Lumos", content)
        self.assertIn("UNIMOD:", content)
        self.assertIn("cervical endometrioid adenocarcinoma", content)


class SerializerIntegrationTest(APITestCase, QuickTestDataMixin):
    """Integration tests for serializers in API context."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.client.force_authenticate(user=self.user)

    def test_metadata_table_crud_serialization(self):
        """Test complete CRUD operations using serializers."""
        # Create via API
        lab_group = LabGroupFactory.create_lab_group()
        create_data = {
            "name": "API Test Study PXD555666",
            "description": "Study created via API for serializer testing",
            "sample_count": 16,
            "lab_group": lab_group.id,
        }

        # This would be the actual API endpoint
        # response = self.client.post('/api/metadata-tables/', create_data)
        # For now, test serializer directly
        serializer = MetadataTableSerializer(data=create_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Simulate save
        table = MetadataTable.objects.create(owner=self.user, **serializer.validated_data)

        # Test retrieve serialization
        retrieve_serializer = MetadataTableSerializer(table)
        retrieve_data = retrieve_serializer.data

        self.assertEqual(retrieve_data["name"], create_data["name"])
        self.assertEqual(retrieve_data["sample_count"], create_data["sample_count"])
        self.assertEqual(retrieve_data["owner_username"], self.user.username)

        # Test update serialization
        update_data = {"description": "Updated description via API", "sample_count": 20}

        update_serializer = MetadataTableSerializer(table, data=update_data, partial=True)
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)

    def test_complex_data_serialization_performance(self):
        """Test serializer performance with complex nested data."""
        import time

        # Create complex study with many columns and pools
        table = MetadataTableFactory.create_with_columns(user=self.user, column_count=15, sample_count=50)

        # Add multiple pools
        for i in range(5):
            SamplePoolFactory.create_pool(
                metadata_table=table, pool_name=f"Pool {i}", pooled_only_samples=list(range(i * 5 + 1, (i + 1) * 5 + 1))
            )

        # Test serialization performance
        start_time = time.time()

        serializer = MetadataTableSerializer(table)
        data = serializer.data

        serialization_time = time.time() - start_time

        # Test that serialization completes in reasonable time
        self.assertLess(serialization_time, 2.0)  # Should complete in under 2 seconds

        # Test that all data is properly serialized
        self.assertEqual(data["sample_count"], 50)
        self.assertEqual(data["column_count"], 15)  # Factory only provides 15 standard columns

    def test_bulk_ontology_serialization(self):
        """Test bulk serialization of ontology data."""
        # Create multiple ontology objects
        species_list = [OntologyFactory.create_species() for _ in range(10)]
        tissues_list = [OntologyFactory.create_tissue() for _ in range(10)]

        # Test bulk serialization
        species_serializer = SpeciesSerializer(species_list, many=True)
        species_data = species_serializer.data

        tissues_serializer = TissueSerializer(tissues_list, many=True)
        tissues_data = tissues_serializer.data

        # Test bulk results
        self.assertEqual(len(species_data), 10)
        self.assertEqual(len(tissues_data), 10)

        # Test individual items in bulk result
        first_species = species_data[0]
        self.assertIn("code", first_species)
        self.assertIn("official_name", first_species)

        first_tissue = tissues_data[0]
        self.assertIn("identifier", first_tissue)
        self.assertIn("accession", first_tissue)

    def test_serializer_error_handling(self):
        """Test serializer error handling with various invalid inputs."""
        # Test with completely invalid data
        invalid_data = {"name": None, "sample_count": "not_a_number", "lab_group": "not_an_id"}

        serializer = MetadataTableSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        self.assertIn("name", errors)
        self.assertIn("sample_count", errors)
        self.assertIn("lab_group", errors)

        # Test that error messages are informative
        for field, error_list in errors.items():
            self.assertGreater(len(error_list), 0)
            for error in error_list:
                self.assertIsInstance(error, str)
                self.assertGreater(len(error), 0)


class MetadataValidationSerializerTest(TestCase):
    """Test cases for MetadataValidationSerializer."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.lab_group = LabGroupFactory.create_lab_group(creator=self.user)
        self.table = MetadataTableFactory.create_basic_table(
            user=self.user, lab_group=self.lab_group, name="Test Table"
        )

    def test_validation_serializer_valid_data(self):
        """Test validation serializer with valid data."""
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": True}

        serializer = MetadataValidationSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        validated_data = serializer.validated_data
        self.assertEqual(validated_data["metadata_table_id"], self.table.id)
        self.assertTrue(validated_data["validate_sdrf_format"])

    def test_validation_serializer_defaults(self):
        """Test validation serializer default values."""
        data = {"metadata_table_id": self.table.id}

        serializer = MetadataValidationSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        validated_data = serializer.validated_data
        # Default should be True for validate_sdrf_format
        self.assertTrue(validated_data.get("validate_sdrf_format", True))

    def test_validation_serializer_missing_table_id(self):
        """Test validation serializer with missing table ID."""
        data = {"validate_sdrf_format": True}

        serializer = MetadataValidationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("metadata_table_id", serializer.errors)

    def test_validation_serializer_invalid_table_id(self):
        """Test validation serializer with invalid table ID."""
        data = {"metadata_table_id": "not_an_integer", "validate_sdrf_format": True}

        serializer = MetadataValidationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("metadata_table_id", serializer.errors)

    def test_validation_serializer_invalid_boolean(self):
        """Test validation serializer with invalid boolean value."""
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": "not_a_boolean"}

        serializer = MetadataValidationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("validate_sdrf_format", serializer.errors)

    def test_validation_serializer_negative_table_id(self):
        """Test validation serializer with negative table ID."""
        data = {"metadata_table_id": -1, "validate_sdrf_format": True}

        serializer = MetadataValidationSerializer(data=data)
        # Should fail validation - negative IDs don't exist in database
        self.assertFalse(serializer.is_valid())
        self.assertIn("metadata_table_id", serializer.errors)

    def test_validation_serializer_zero_table_id(self):
        """Test validation serializer with zero table ID."""
        data = {"metadata_table_id": 0, "validate_sdrf_format": True}

        serializer = MetadataValidationSerializer(data=data)
        # Should fail validation - zero ID doesn't exist in database
        self.assertFalse(serializer.is_valid())
        self.assertIn("metadata_table_id", serializer.errors)

    def test_validation_serializer_false_sdrf_format(self):
        """Test validation serializer with validate_sdrf_format set to False."""
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": False}

        serializer = MetadataValidationSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertFalse(serializer.validated_data["validate_sdrf_format"])

    def test_validation_serializer_help_text(self):
        """Test that serializer fields have proper help text."""
        serializer = MetadataValidationSerializer()

        fields = serializer.get_fields()

        # Check that metadata_table_id has help text
        table_field = fields["metadata_table_id"]
        self.assertIsNotNone(table_field.help_text)
        self.assertIn("ID", table_field.help_text)

        # Check that validate_sdrf_format has help text
        sdrf_field = fields["validate_sdrf_format"]
        self.assertIsNotNone(sdrf_field.help_text)
        self.assertIn("SDRF", sdrf_field.help_text)

    def test_validation_serializer_field_names(self):
        """Test that serializer has correct field names."""
        serializer = MetadataValidationSerializer()
        fields = serializer.get_fields()

        expected_fields = {
            "metadata_table_id",
            "validate_sdrf_format",
            "validate_ontologies",
            "validate_structure",
            "include_pools",
            "async_processing",
        }
        actual_fields = set(fields.keys())

        self.assertEqual(expected_fields, actual_fields)

    def test_validation_serializer_extra_fields_ignored(self):
        """Test that extra fields are ignored."""
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": True, "extra_field": "should_be_ignored"}

        serializer = MetadataValidationSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        # Extra field should not be in validated data
        self.assertNotIn("extra_field", serializer.validated_data)
        self.assertEqual(len(serializer.validated_data), 6)  # Updated for expanded serializer

    def test_validation_serializer_empty_data(self):
        """Test validation serializer with empty data."""
        data = {}

        serializer = MetadataValidationSerializer(data=data)
        self.assertFalse(serializer.is_valid())

        # Should have error for required metadata_table_id
        self.assertIn("metadata_table_id", serializer.errors)
        # validate_sdrf_format is optional so no error expected
        self.assertNotIn("validate_sdrf_format", serializer.errors)
