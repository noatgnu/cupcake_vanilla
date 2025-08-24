"""
Test cases for CUPCAKE extensibility features.

Tests the base model classes and extensibility patterns for custom applications.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import LabGroup
from ccv.models import BaseMetadataTable, BaseMetadataTableTemplate, MetadataTable

User = get_user_model()


class CustomMetadataTableMixin:
    """Mixin for custom metadata table functionality testing."""

    def get_custom_fields(self):
        """Return custom fields specific to proteomics metadata."""
        return {
            "instrument_type": {
                "type": "CharField",
                "max_length": 100,
                "required": True,
                "choices": ["orbitrap_fusion_lumos", "ltq_orbitrap_velos", "q_exactive", "timstof_pro"],
            },
            "acquisition_method": {
                "type": "CharField",
                "max_length": 50,
                "choices": ["dda", "dia", "targeted"],
                "required": True,
            },
            "label_type": {
                "type": "CharField",
                "max_length": 50,
                "choices": ["label_free", "tmt", "itraq", "silac"],
                "required": False,
            },
        }

    def get_custom_validators(self):
        """Return custom validation rules for proteomics data."""
        return [
            {
                "field": "sample_count",
                "validator": lambda x: x >= 3,
                "message": "Proteomics studies require at least 3 samples for statistical significance",
            },
            {
                "field": "instrument_type",
                "validator": lambda x: x.startswith(("orbitrap", "ltq", "q_", "timstof")),
                "message": "Instrument type must be a supported mass spectrometer",
            },
        ]

    def get_export_formats(self):
        """Return available export formats including custom proteomics formats."""
        base_formats = super().get_export_formats()
        base_formats.update(
            {
                "mzid": {
                    "name": "mzIdentML Format",
                    "extension": ".mzid",
                    "mime_type": "application/xml",
                    "handler": self.export_mzid,
                },
                "pride_xml": {
                    "name": "PRIDE XML Format",
                    "extension": ".xml",
                    "mime_type": "application/xml",
                    "handler": self.export_pride_xml,
                },
            }
        )
        return base_formats

    def export_mzid(self):
        """Mock export to mzIdentML format."""
        return f"mzID export for {self.name}"

    def export_pride_xml(self):
        """Mock export to PRIDE XML format."""
        return f"PRIDE XML export for {self.name}"


class CustomMetadataTable(CustomMetadataTableMixin, BaseMetadataTable):
    """Custom implementation extending BaseMetadataTable for testing."""

    class Meta:
        abstract = True


class CustomMetadataTableTemplate(BaseMetadataTableTemplate):
    """Custom template implementation for testing extensibility."""

    def get_template_validators(self):
        """Return custom template validation rules."""
        return [
            {
                "validator": lambda t: t.column_templates.filter(name="source name").exists(),
                "message": "Template must include source name column",
            },
            {
                "validator": lambda t: t.column_templates.filter(name="characteristics", type="organism").exists(),
                "message": "Template must include organism characteristic",
            },
        ]

    def get_supported_schemas(self):
        """Return schemas supported by this custom template."""
        base_schemas = super().get_supported_schemas()
        base_schemas.extend(["proteomics_dda", "proteomics_dia", "metabolomics"])
        return base_schemas

    class Meta:
        abstract = True


class BaseMetadataTableExtensibilityTest(TestCase):
    """Test extensibility features of BaseMetadataTable."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Proteomics Lab", description="Test proteomics laboratory")

    def test_custom_fields_implementation(self):
        """Test that custom fields are properly defined."""
        # Test custom fields using mixin directly
        mixin = CustomMetadataTableMixin()

        custom_fields = mixin.get_custom_fields()

        # Test custom fields structure
        self.assertIn("instrument_type", custom_fields)
        self.assertIn("acquisition_method", custom_fields)
        self.assertIn("label_type", custom_fields)

        # Test field properties
        instrument_field = custom_fields["instrument_type"]
        self.assertEqual(instrument_field["type"], "CharField")
        self.assertEqual(instrument_field["max_length"], 100)
        self.assertTrue(instrument_field["required"])
        self.assertIn("orbitrap_fusion_lumos", instrument_field["choices"])

        acquisition_field = custom_fields["acquisition_method"]
        self.assertIn("dda", acquisition_field["choices"])
        self.assertIn("dia", acquisition_field["choices"])
        self.assertIn("targeted", acquisition_field["choices"])

    def test_custom_validators_implementation(self):
        """Test that custom validators work correctly."""
        # Test custom validators using mixin directly
        mixin = CustomMetadataTableMixin()

        validators = mixin.get_custom_validators()

        # Test validator structure
        self.assertEqual(len(validators), 2)

        # Test sample count validator
        sample_validator = validators[0]
        self.assertFalse(sample_validator["validator"](2))  # Should fail
        self.assertTrue(sample_validator["validator"](5))  # Should pass
        self.assertIn("statistical significance", sample_validator["message"])

        # Test instrument type validator
        instrument_validator = validators[1]
        self.assertTrue(instrument_validator["validator"]("orbitrap_fusion_lumos"))
        self.assertTrue(instrument_validator["validator"]("q_exactive"))
        self.assertFalse(instrument_validator["validator"]("invalid_instrument"))

    def test_custom_export_formats(self):
        """Test that custom export formats are available."""

        # Create a mock object that has base export formats
        class MockBase:
            def get_export_formats(self):
                return {
                    "sdrf": {"name": "SDRF Format", "extension": ".sdrf.tsv", "mime_type": "text/tab-separated-values"}
                }

        class TestMixin(CustomMetadataTableMixin, MockBase):
            def __init__(self):
                self.name = "Test Proteomics Table"

        test_obj = TestMixin()
        export_formats = test_obj.get_export_formats()

        # Test that base format is still available
        self.assertIn("sdrf", export_formats)

        # Test custom formats
        self.assertIn("mzid", export_formats)
        self.assertIn("pride_xml", export_formats)

        # Test format properties
        mzid_format = export_formats["mzid"]
        self.assertEqual(mzid_format["name"], "mzIdentML Format")
        self.assertEqual(mzid_format["extension"], ".mzid")
        self.assertEqual(mzid_format["mime_type"], "application/xml")

        # Test custom export methods
        mzid_result = test_obj.export_mzid()
        self.assertIn("mzID export", mzid_result)
        self.assertIn(test_obj.name, mzid_result)

        pride_result = test_obj.export_pride_xml()
        self.assertIn("PRIDE XML export", pride_result)

    def test_inheritance_from_base_class(self):
        """Test that custom class properly inherits from BaseMetadataTable."""
        # Test that the custom class has the right inheritance structure
        self.assertTrue(issubclass(CustomMetadataTable, BaseMetadataTable))
        self.assertTrue(issubclass(CustomMetadataTable, CustomMetadataTableMixin))

        # Test that custom methods are available in the class
        self.assertTrue(hasattr(CustomMetadataTable, "get_custom_fields"))
        self.assertTrue(hasattr(CustomMetadataTable, "get_custom_validators"))
        self.assertTrue(hasattr(CustomMetadataTable, "get_export_formats"))

        # Test mixin functionality directly
        mixin = CustomMetadataTableMixin()
        self.assertTrue(hasattr(mixin, "get_custom_fields"))
        self.assertTrue(hasattr(mixin, "get_custom_validators"))

    def test_base_class_default_methods(self):
        """Test default implementations in BaseMetadataTable."""
        # Test that BaseMetadataTable has default method implementations
        self.assertTrue(hasattr(BaseMetadataTable, "get_custom_fields"))
        self.assertTrue(hasattr(BaseMetadataTable, "get_custom_validators"))
        self.assertTrue(hasattr(BaseMetadataTable, "get_export_formats"))

        # Test that the methods exist and return expected defaults
        # Note: We can't instantiate abstract models, so we test the class has the methods

    def test_concrete_metadata_table_compatibility(self):
        """Test that concrete MetadataTable works alongside custom implementation."""
        # Test class inheritance compatibility
        self.assertTrue(issubclass(MetadataTable, BaseMetadataTable))
        self.assertTrue(issubclass(CustomMetadataTable, BaseMetadataTable))

        # Test that both have required methods
        self.assertTrue(hasattr(MetadataTable, "get_export_formats"))
        self.assertTrue(hasattr(CustomMetadataTable, "get_export_formats"))

        # Test mixin provides additional functionality
        mixin = CustomMetadataTableMixin()
        custom_formats = mixin.get_custom_fields()
        self.assertIn("instrument_type", custom_formats)
        self.assertIn("acquisition_method", custom_formats)


class BaseMetadataTableTemplateExtensibilityTest(TestCase):
    """Test extensibility features of BaseMetadataTableTemplate."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

    def test_custom_template_validators(self):
        """Test custom template validation logic."""
        custom_template = CustomMetadataTableTemplate(
            name="Proteomics Template", description="Custom proteomics template", creator=self.user
        )

        validators = custom_template.get_template_validators()

        # Test validator structure
        self.assertEqual(len(validators), 2)

        # Test validator messages
        source_validator = validators[0]
        organism_validator = validators[1]

        self.assertIn("source name", source_validator["message"])
        self.assertIn("organism characteristic", organism_validator["message"])

    def test_supported_schemas_extension(self):
        """Test that supported schemas can be extended."""
        custom_template = CustomMetadataTableTemplate(name="Custom Template", creator=self.user)

        supported_schemas = custom_template.get_supported_schemas()

        # Test that custom schemas were added
        self.assertIn("proteomics_dda", supported_schemas)
        self.assertIn("proteomics_dia", supported_schemas)
        self.assertIn("metabolomics", supported_schemas)

        # Test that base schemas are still included
        base_schemas = ["default", "human", "vertebrates", "plants", "minimum"]
        for schema in base_schemas:
            self.assertIn(schema, supported_schemas)

    def test_template_inheritance(self):
        """Test that custom template inherits properly."""
        custom_template = CustomMetadataTableTemplate(name="Test Template", creator=self.user)

        # Test inheritance
        self.assertIsInstance(custom_template, BaseMetadataTableTemplate)

        # Test base functionality still works
        self.assertEqual(str(custom_template), "Test Template")

        # Test custom methods are available
        self.assertTrue(hasattr(custom_template, "get_template_validators"))
        self.assertTrue(hasattr(custom_template, "get_supported_schemas"))

    def test_base_template_defaults(self):
        """Test default implementations in BaseMetadataTableTemplate."""
        base_template = BaseMetadataTableTemplate(name="Base Template", creator=self.user)

        # Test defaults
        self.assertEqual(base_template.get_template_validators(), [])

        supported_schemas = base_template.get_supported_schemas()
        expected_base_schemas = ["default", "human", "vertebrates", "plants", "nonvertebrates", "cell_lines", "minimum"]
        for schema in expected_base_schemas:
            self.assertIn(schema, supported_schemas)


class ExtensibilityIntegrationTest(TestCase):
    """Integration tests for extensibility features."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory")

    def test_multiple_custom_implementations(self):
        """Test that multiple custom implementations can coexist."""

        class ProteomicsTable(BaseMetadataTable):
            def get_custom_fields(self):
                return {"instrument": {"type": "CharField"}}

            class Meta:
                app_label = "tests"

        class MetabolomicsTable(BaseMetadataTable):
            def get_custom_fields(self):
                return {"platform": {"type": "CharField"}}

            class Meta:
                app_label = "tests"

        # Create instances
        proteomics_table = ProteomicsTable(name="Proteomics Study", creator=self.user)

        metabolomics_table = MetabolomicsTable(name="Metabolomics Study", creator=self.user)

        # Test that each has its own custom fields
        proteomics_fields = proteomics_table.get_custom_fields()
        metabolomics_fields = metabolomics_table.get_custom_fields()

        self.assertIn("instrument", proteomics_fields)
        self.assertNotIn("platform", proteomics_fields)

        self.assertIn("platform", metabolomics_fields)
        self.assertNotIn("instrument", metabolomics_fields)

    def test_extensibility_with_real_sdrf_patterns(self):
        """Test extensibility using real SDRF data patterns."""

        class SDRFAwareTable(BaseMetadataTable):
            def get_custom_fields(self):
                # Based on common SDRF fields from fixtures
                return {
                    "proteome_exchange_accession": {
                        "type": "CharField",
                        "max_length": 20,
                        "pattern": r"PXD\d+",
                        "required": True,
                    },
                    "technology_type": {
                        "type": "CharField",
                        "max_length": 100,
                        "choices": ["proteomic profiling by mass spectrometry"],
                        "required": True,
                    },
                    "cleavage_agents": {"type": "JSONField", "default": list, "required": False},
                }

            def get_custom_validators(self):
                return [
                    {
                        "field": "proteome_exchange_accession",
                        "validator": lambda x: x.startswith("PXD") and x[3:].isdigit(),
                        "message": "ProteomeXchange accession must follow PXD format",
                    }
                ]

            class Meta:
                app_label = "tests"

        # Create table with SDRF-aware fields
        sdrf_table = SDRFAwareTable(name="SDRF Compliant Study", creator=self.user, sample_count=10)

        # Test custom fields match SDRF patterns
        custom_fields = sdrf_table.get_custom_fields()

        self.assertIn("proteome_exchange_accession", custom_fields)
        self.assertIn("technology_type", custom_fields)
        self.assertIn("cleavage_agents", custom_fields)

        # Test ProteomeXchange validation
        validators = sdrf_table.get_custom_validators()
        px_validator = validators[0]["validator"]

        self.assertTrue(px_validator("PXD002137"))  # From fixture
        self.assertTrue(px_validator("PXD019185"))  # From fixture
        self.assertFalse(px_validator("INVALID123"))
        self.assertFalse(px_validator("PXD"))

    def test_validation_integration(self):
        """Test integration between custom validators and Django validation."""
        # Test validation using mixin directly
        mixin = CustomMetadataTableMixin()

        # Get custom validators
        validators = mixin.get_custom_validators()
        sample_validator = validators[0]

        # Test validation failure with low sample count
        sample_count_low = 1  # Below custom minimum
        is_valid = sample_validator["validator"](sample_count_low)
        self.assertFalse(is_valid)

        # Test error message
        error_message = sample_validator["message"]
        self.assertIn("statistical significance", error_message)

        # Test that validation passes with correct value
        sample_count_high = 5
        is_valid = sample_validator["validator"](sample_count_high)
        self.assertTrue(is_valid)
