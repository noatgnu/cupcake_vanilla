"""
Comprehensive test cases for CUPCAKE models with realistic SDRF data.

Tests all model functionality using realistic data patterns from SDRF fixtures
and scientific metadata conventions.
"""

import random

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ccv.models import MetadataColumn, SamplePool, Species
from tests.factories import (
    FavouriteMetadataOptionFactory,
    LabGroupFactory,
    MetadataColumnFactory,
    MetadataTableFactory,
    OntologyFactory,
    QuickTestDataMixin,
    SamplePoolFactory,
    SDRFDataPatterns,
    SDRFTestDataBuilder,
    UserFactory,
)

User = get_user_model()


class MetadataTableComprehensiveTest(TestCase, QuickTestDataMixin):
    """Comprehensive tests for MetadataTable model with realistic data."""

    def setUp(self):
        self.user = UserFactory.create_user(username="researcher1")
        self.lab_group = LabGroupFactory.create_lab_group(name="Proteomics Lab")
        self.other_user = UserFactory.create_user(username="researcher2")

    def test_create_table_with_realistic_sdrf_data(self):
        """Test creating metadata tables with realistic SDRF-based data."""
        # Test proteomics study
        proteomics_table = MetadataTableFactory.create_proteomics_table(
            user=self.user,
            lab_group=self.lab_group,
            name="Human Liver Proteomics PXD012345",
            description="Quantitative proteomics analysis of human liver tissue",
            sample_count=24,
        )

        self.assertEqual(proteomics_table.name, "Human Liver Proteomics PXD012345")
        self.assertEqual(proteomics_table.sample_count, 24)
        self.assertEqual(proteomics_table.owner, self.user)
        self.assertEqual(proteomics_table.lab_group, self.lab_group)
        self.assertFalse(proteomics_table.is_locked)
        self.assertFalse(proteomics_table.is_published)

        # Test that timestamps are set
        self.assertIsNotNone(proteomics_table.created_at)
        self.assertIsNotNone(proteomics_table.updated_at)

        # Test string representation
        self.assertEqual(str(proteomics_table), "Human Liver Proteomics PXD012345")

    def test_table_with_many_samples(self):
        """Test handling of tables with large sample counts."""
        large_study = MetadataTableFactory.create_basic_table(
            user=self.user,
            name="Large Scale Study",
            sample_count=1000,
            description="Large-scale proteomics study with 1000 samples",
        )

        self.assertEqual(large_study.sample_count, 1000)
        self.assertEqual(large_study.get_column_count(), 0)  # No columns yet

    def test_table_locking_functionality(self):
        """Test table locking and unlocking."""
        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Initially unlocked
        self.assertFalse(table.is_locked)

        # Lock the table
        table.is_locked = True
        table.save()
        table.refresh_from_db()

        self.assertTrue(table.is_locked)

        # Test that locked_at timestamp is updated
        self.assertIsNotNone(table.updated_at)

    def test_table_publishing_workflow(self):
        """Test table publishing functionality."""
        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Initially not published
        self.assertFalse(table.is_published)

        # Publish the table
        table.is_published = True
        table.save()
        table.refresh_from_db()

        self.assertTrue(table.is_published)

    def test_table_with_zero_samples(self):
        """Test edge case of table with zero samples."""
        empty_table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=0, name="Empty Study")

        self.assertEqual(empty_table.sample_count, 0)
        self.assertEqual(empty_table.get_column_count(), 0)

    def test_table_cascading_delete(self):
        """Test that deleting a table cascades to related objects."""
        table = MetadataTableFactory.create_with_columns(user=self.user, column_count=5, sample_count=10)

        # Create related objects
        SamplePoolFactory.create_pool(metadata_table=table)
        column_count = table.columns.count()
        pool_count = table.sample_pools.count()

        self.assertEqual(column_count, 5)
        self.assertEqual(pool_count, 1)

        # Delete table
        table_id = table.id
        table.delete()

        # Check that related objects are deleted
        self.assertEqual(MetadataColumn.objects.filter(metadata_table_id=table_id).count(), 0)
        self.assertEqual(SamplePool.objects.filter(metadata_table_id=table_id).count(), 0)

    def test_table_column_counting(self):
        """Test accurate column counting with various column types."""
        table = MetadataTableFactory.create_basic_table(user=self.user)

        # Add different types of columns
        columns_data = [
            ("source name", "", True),
            ("organism", "characteristics", True),
            ("disease", "characteristics", False),
            ("instrument", "comment", False),
            ("technical replicate", "comment", True),
        ]

        for i, (name, col_type, mandatory) in enumerate(columns_data):
            MetadataColumnFactory.create_column(
                metadata_table=table, name=name, type=col_type, column_position=i, mandatory=mandatory
            )

        self.assertEqual(table.get_column_count(), len(columns_data))

    def test_table_permissions_and_ownership(self):
        """Test table ownership and permission-related functionality."""
        # Create table owned by user1
        user1_table = MetadataTableFactory.create_basic_table(user=self.user)

        # Create table owned by user2
        user2_table = MetadataTableFactory.create_basic_table(user=self.other_user)

        # Test ownership
        self.assertEqual(user1_table.owner, self.user)
        self.assertEqual(user2_table.owner, self.other_user)

        # Test that different users can have tables with the same name
        user2_duplicate = MetadataTableFactory.create_basic_table(user=self.other_user, name=user1_table.name)

        self.assertEqual(user2_duplicate.name, user1_table.name)
        self.assertNotEqual(user2_duplicate.owner, user1_table.owner)

    def test_table_search_and_filtering_data(self):
        """Test creating tables with data suitable for search/filtering."""
        # Create tables with searchable names and descriptions
        studies = [
            ("Breast Cancer Proteomics", "breast", "cancer"),
            ("Liver Metabolomics", "liver", "metabolomics"),
            ("Brain Tissue Analysis", "brain", "tissue"),
            ("Heart Disease Study", "heart", "disease"),
        ]

        created_tables = []
        for name, keyword1, keyword2 in studies:
            table = MetadataTableFactory.create_basic_table(
                user=self.user, name=name, description=f"Study focusing on {keyword1} {keyword2} analysis"
            )
            created_tables.append(table)

        # Test that all tables were created with correct data
        self.assertEqual(len(created_tables), 4)

        # Test searchable content
        breast_table = created_tables[0]
        self.assertIn("breast", breast_table.name.lower())
        self.assertIn("breast", breast_table.description.lower())
        self.assertIn("cancer", breast_table.description.lower())


class MetadataColumnComprehensiveTest(TestCase, QuickTestDataMixin):
    """Comprehensive tests for MetadataColumn model with realistic SDRF data."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=15)

    def test_create_columns_with_sdrf_patterns(self):
        """Test creating columns that match real SDRF patterns."""
        sdrf_columns = [
            # Core SDRF columns
            {"name": "source name", "type": "", "value": "PDC000126-Sample-1", "mandatory": True},
            {"name": "characteristics", "type": "organism", "value": "homo sapiens", "mandatory": True},
            {"name": "characteristics", "type": "organism part", "value": "endometrium", "mandatory": True},
            {
                "name": "characteristics",
                "type": "disease",
                "value": "cervical endometrioid adenocarcinoma",
                "mandatory": True,
            },
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "mandatory": False,
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;MT=Variable;TA=M;AC=Unimod:35",
                "mandatory": False,
            },
        ]

        created_columns = []
        for i, col_data in enumerate(sdrf_columns):
            column = MetadataColumnFactory.create_column(metadata_table=self.table, column_position=i, **col_data)
            created_columns.append(column)

        # Test that all columns were created correctly
        self.assertEqual(len(created_columns), len(sdrf_columns))

        # Test specific column properties
        source_name_col = created_columns[0]
        self.assertEqual(source_name_col.name, "source name")
        self.assertEqual(source_name_col.type, "")
        self.assertTrue(source_name_col.mandatory)

        organism_col = created_columns[1]
        self.assertEqual(organism_col.name, "characteristics")
        self.assertEqual(organism_col.type, "organism")
        self.assertEqual(organism_col.value, "homo sapiens")

        instrument_col = created_columns[4]
        self.assertIn("Orbitrap Fusion Lumos", instrument_col.value)
        self.assertIn("MS:1002732", instrument_col.value)

        modification_col = created_columns[5]
        self.assertIn("Unimod:35", modification_col.value)
        self.assertIn("Variable", modification_col.value)

    def test_column_modifiers_functionality(self):
        """Test column modifiers for sample-specific values."""
        base_value = "homo sapiens"
        modifiers = {
            "samples": [
                {"samples": ["1", "2"], "value": "mus musculus"},
                {"samples": ["3"], "value": "rattus norvegicus"},
                {"samples": ["4", "5", "6"], "value": "danio rerio"},
            ]
        }

        column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism", value=base_value, modifiers=modifiers
        )

        # Test that modifiers were stored correctly
        self.assertEqual(column.value, base_value)
        self.assertIsNotNone(column.modifiers)
        self.assertIn("samples", column.modifiers)

        # Test modifier structure
        sample_modifiers = column.modifiers["samples"]
        self.assertEqual(len(sample_modifiers), 3)

        # Test specific modifier entries
        first_modifier = sample_modifiers[0]
        self.assertEqual(first_modifier["samples"], ["1", "2"])
        self.assertEqual(first_modifier["value"], "mus musculus")

    def test_column_positioning_and_ordering(self):
        """Test column positioning and ordering functionality."""
        column_positions = [0, 2, 1, 4, 3]  # Intentionally out of order
        columns = []

        for pos in column_positions:
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table, name=f"column_{pos}", column_position=pos
            )
            columns.append(column)

        # Test that columns can be retrieved in order
        ordered_columns = self.table.columns.all().order_by("column_position")
        ordered_positions = [col.column_position for col in ordered_columns]

        self.assertEqual(ordered_positions, [0, 1, 2, 3, 4])

    def test_column_types_validation(self):
        """Test various column types from SDRF specifications."""
        column_types = [
            ("characteristics", "organism"),
            ("characteristics", "organism part"),
            ("characteristics", "disease"),
            ("characteristics", "cell type"),
            ("characteristics", "cell line"),
            ("comment", "instrument"),
            ("comment", "cleavage agent details"),
            ("comment", "modification parameters"),
            ("comment", "technical replicate"),
            ("factor value", "phenotype"),
        ]

        for i, (name, col_type) in enumerate(column_types):
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table,
                name=name,
                type=col_type,
                column_position=i,
                value=MetadataColumnFactory.get_realistic_value(name, col_type),
            )

            # Test that column was created with correct types
            self.assertEqual(column.name, name)
            self.assertEqual(column.type, col_type)
            self.assertIsNotNone(column.value)

    def test_column_flags_and_properties(self):
        """Test column flags (mandatory, hidden, readonly, etc.)."""
        # Test mandatory column
        mandatory_col = MetadataColumnFactory.create_column(
            metadata_table=self.table,
            name="source name",
            mandatory=True,
            hidden=False,
            readonly=False,
            auto_generated=False,
        )

        self.assertTrue(mandatory_col.mandatory)
        self.assertFalse(mandatory_col.hidden)
        self.assertFalse(mandatory_col.readonly)
        self.assertFalse(mandatory_col.auto_generated)

        # Test auto-generated readonly column
        auto_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="assay name", value="run 1", auto_generated=True, readonly=True
        )

        self.assertTrue(auto_col.auto_generated)
        self.assertTrue(auto_col.readonly)

        # Test hidden column
        hidden_col = MetadataColumnFactory.create_column(metadata_table=self.table, name="internal_id", hidden=True)

        self.assertTrue(hidden_col.hidden)

    def test_column_validation_with_ontology_values(self):
        """Test columns with values that reference ontologies."""
        # Create ontology-aware columns
        ontology_columns = [
            {
                "name": "characteristics",
                "type": "organism",
                "value": "homo sapiens",
                "validation_pattern": r"^[a-z]+ [a-z]+$",
            },
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "validation_pattern": r"NT=.*?;AC=MS:\d+",
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
                "validation_pattern": r"NT=.*?;AC=UNIMOD:\d+",
            },
        ]

        for i, col_data in enumerate(ontology_columns):
            validation_pattern = col_data.pop("validation_pattern")

            column = MetadataColumnFactory.create_column(metadata_table=self.table, column_position=i, **col_data)

            # Test that value matches expected pattern (basic validation)
            import re

            self.assertTrue(
                re.match(validation_pattern, column.value),
                f"Value '{column.value}' doesn't match pattern '{validation_pattern}'",
            )

    def test_large_column_values(self):
        """Test columns with large text values."""
        large_description = "This is a very long description " * 50
        large_comment = "Technical details: " + "data " * 100

        desc_column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="description", value=large_description
        )

        comment_column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="technical details", value=large_comment
        )

        # Test that large values are stored correctly
        self.assertEqual(len(desc_column.value), len(large_description))
        self.assertEqual(len(comment_column.value), len(large_comment))

    def test_column_json_field_functionality(self):
        """Test JSON field functionality in modifiers."""
        complex_modifiers = {
            "samples": [
                {
                    "samples": ["1", "2", "3"],
                    "value": "TMT126",
                    "metadata": {"intensity": 1000000, "purity": 0.95, "batch": "B001"},
                },
                {
                    "samples": ["4", "5", "6"],
                    "value": "TMT127N",
                    "metadata": {"intensity": 950000, "purity": 0.97, "batch": "B001"},
                },
            ],
            "validation_rules": {
                "required": True,
                "pattern": r"TMT\d+[NC]?",
                "allowed_values": ["TMT126", "TMT127N", "TMT127C", "TMT128N"],
            },
        }

        column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="label", value="TMT126", modifiers=complex_modifiers
        )

        # Test JSON storage and retrieval
        self.assertIn("samples", column.modifiers)
        self.assertIn("validation_rules", column.modifiers)

        # Test nested data access
        first_sample_metadata = column.modifiers["samples"][0]["metadata"]
        self.assertEqual(first_sample_metadata["intensity"], 1000000)
        self.assertEqual(first_sample_metadata["purity"], 0.95)

        validation_rules = column.modifiers["validation_rules"]
        self.assertTrue(validation_rules["required"])
        self.assertIn("TMT126", validation_rules["allowed_values"])


class SamplePoolComprehensiveTest(TestCase, QuickTestDataMixin):
    """Comprehensive tests for SamplePool model with realistic pooling scenarios."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=20)

    def test_create_realistic_sample_pools(self):
        """Test creating sample pools based on real SDRF patterns."""
        # Test simple pooled samples
        simple_pool = SamplePoolFactory.create_pool(
            metadata_table=self.table,
            pool_name="Simple Pool A",
            pooled_only_samples=[1, 2, 3],
            pooled_and_independent_samples=[],
            is_reference=True,
        )

        self.assertEqual(simple_pool.pool_name, "Simple Pool A")
        self.assertEqual(simple_pool.pooled_only_samples, [1, 2, 3])
        self.assertEqual(simple_pool.get_total_samples(), 3)
        self.assertTrue(simple_pool.is_reference)

        # Test pool with both pooled-only and pooled-and-independent samples
        complex_pool = SamplePoolFactory.create_pool(
            metadata_table=self.table,
            pool_name="Complex Pool B",
            pooled_only_samples=[4, 5],
            pooled_and_independent_samples=[6, 7, 8],
            is_reference=False,
        )

        self.assertEqual(complex_pool.get_total_samples(), 5)
        self.assertFalse(complex_pool.is_reference)

    def test_sdrf_sn_pattern_pools(self):
        """Test pools created from SDRF SN= patterns."""
        sample_names = ["D-HEp3 #1", "D-HEp3 #2", "T-HEp3 #1"]

        sn_pool = SamplePoolFactory.create_from_sdrf_pattern(metadata_table=self.table, sample_names=sample_names)

        # Test SN= pattern in pool name
        self.assertTrue(sn_pool.pool_name.startswith("SN="))
        self.assertIn("D-HEp3 #1", sn_pool.pool_name)
        self.assertIn("D-HEp3 #2", sn_pool.pool_name)

        # Test pool description
        self.assertIn("Pool created from samples", sn_pool.pool_description)
        for sample_name in sample_names:
            self.assertIn(sample_name, sn_pool.pool_description)

        # Test that it's marked as reference
        self.assertTrue(sn_pool.is_reference)

    def test_pool_sdrf_value_generation(self):
        """Test dynamic SDRF value generation."""
        pool = SamplePoolFactory.create_pool(
            metadata_table=self.table,
            pool_name="Test Pool",
            pooled_only_samples=[1, 3, 5],
            pooled_and_independent_samples=[2, 4],
        )

        # Test that sdrf_value is generated dynamically
        sdrf_value = pool.sdrf_value
        self.assertTrue(sdrf_value.startswith("SN="))

        # Test that it contains sample information
        self.assertIn("sample", sdrf_value)  # Should contain sample names

    def test_pool_validation_edge_cases(self):
        """Test pool validation with edge cases."""
        # Test empty pool
        empty_pool = SamplePool(
            metadata_table=self.table,
            pool_name="Empty Pool",
            pooled_only_samples=[],
            pooled_and_independent_samples=[],
            created_by=self.user,
        )

        self.assertEqual(empty_pool.get_total_samples(), 0)

        # Test pool with maximum samples
        max_pool = SamplePoolFactory.create_pool(
            metadata_table=self.table,
            pool_name="Maximum Pool",
            pooled_only_samples=list(range(1, 21)),  # All 20 samples
        )

        self.assertEqual(max_pool.get_total_samples(), 20)
        self.assertEqual(max_pool.get_total_samples(), self.table.sample_count)

    def test_pool_relationships(self):
        """Test pool relationships with metadata table and user."""
        pool = SamplePoolFactory.create_pool(metadata_table=self.table, created_by=self.user)

        # Test relationships
        self.assertEqual(pool.metadata_table, self.table)
        self.assertEqual(pool.created_by, self.user)

        # Test reverse relationships
        self.assertIn(pool, self.table.sample_pools.all())

        # Test cascade delete
        pool_id = pool.id
        self.table.delete()

        self.assertFalse(SamplePool.objects.filter(id=pool_id).exists())

    def test_multiple_pools_per_table(self):
        """Test creating multiple pools for the same table."""
        pools_data = [
            ("Pool Alpha", [1, 2, 3], []),
            ("Pool Beta", [4, 5], [6, 7]),
            ("Pool Gamma", [], [8, 9, 10, 11]),
            ("Pool Delta", [12, 13, 14], [15, 16]),
        ]

        created_pools = []
        for pool_name, pooled_only, pooled_and_independent in pools_data:
            pool = SamplePoolFactory.create_pool(
                metadata_table=self.table,
                pool_name=pool_name,
                pooled_only_samples=pooled_only,
                pooled_and_independent_samples=pooled_and_independent,
            )
            created_pools.append(pool)

        # Test that all pools were created
        self.assertEqual(len(created_pools), 4)
        self.assertEqual(self.table.sample_pools.count(), 4)

        # Test pool names
        pool_names = [pool.pool_name for pool in created_pools]
        self.assertIn("Pool Alpha", pool_names)
        self.assertIn("Pool Delta", pool_names)

        # Test total sample distribution
        total_pooled_samples = sum(pool.get_total_samples() for pool in created_pools)
        # Note: Some samples might be counted in multiple pools
        self.assertGreater(total_pooled_samples, 0)

    def test_pool_timestamps(self):
        """Test pool creation and update timestamps."""
        pool = SamplePoolFactory.create_pool(metadata_table=self.table)

        # Test creation timestamp
        self.assertIsNotNone(pool.created_at)
        self.assertIsNotNone(pool.updated_at)

        # Test that timestamps are recent
        now = timezone.now()
        self.assertLess((now - pool.created_at).total_seconds(), 60)  # Created within last minute

        # Update pool and test timestamp change
        original_updated = pool.updated_at
        pool.pool_description = "Updated description"
        pool.save()

        pool.refresh_from_db()
        self.assertGreater(pool.updated_at, original_updated)


class OntologyModelsComprehensiveTest(TestCase, QuickTestDataMixin):
    """Comprehensive tests for ontology models with realistic scientific data."""

    def test_species_model_with_realistic_data(self):
        """Test Species model with real taxonomic data."""
        species_data = [
            {
                "code": "HUMAN",
                "taxon": 9606,
                "official_name": "Homo sapiens",
                "common_name": "Human",
                "synonym": "H. sapiens",
            },
            {
                "code": "MOUSE",
                "taxon": 10090,
                "official_name": "Mus musculus",
                "common_name": "House mouse",
                "synonym": "M. musculus",
            },
            {
                "code": "ECOLI",
                "taxon": 511145,
                "official_name": "Escherichia coli str. K-12 substr. MG1655",
                "common_name": "E. coli K12",
                "synonym": "E. coli MG1655",
            },
        ]

        created_species = []
        for species_info in species_data:
            species = OntologyFactory.create_species(**species_info)
            created_species.append(species)

        # Test species creation
        self.assertEqual(len(created_species), 3)

        # Test specific species properties
        human = created_species[0]
        self.assertEqual(human.code, "HUMAN")
        self.assertEqual(human.taxon, 9606)
        self.assertEqual(str(human), "Homo sapiens (HUMAN)")

        mouse = created_species[1]
        self.assertEqual(mouse.taxon, 10090)
        self.assertIn("musculus", mouse.official_name)

        # Test that duplicate codes are allowed (no uniqueness constraint on Species.code)
        duplicate_human = Species.objects.create(code="HUMAN", taxon=9999, official_name="Duplicate Human")
        self.assertEqual(duplicate_human.code, "HUMAN")
        self.assertEqual(duplicate_human.taxon, 9999)

    def test_tissue_model_with_uberon_ontology(self):
        """Test Tissue model with UBERON ontology identifiers."""
        tissue_data = [
            {
                "identifier": "UBERON_0002107",
                "accession": "liver",
                "synonyms": "hepatic tissue;hepar",
                "cross_references": "FMA:7197;MA:0000358",
            },
            {
                "identifier": "UBERON_0002048",
                "accession": "lung",
                "synonyms": "pulmonary tissue;pulmo",
                "cross_references": "FMA:7195;MA:0000415",
            },
            {
                "identifier": "UBERON_0000955",
                "accession": "brain",
                "synonyms": "neural tissue;cerebrum",
                "cross_references": "FMA:50801;MA:0000168",
            },
        ]

        tissues = [OntologyFactory.create_tissue(**data) for data in tissue_data]

        # Test tissue creation and properties
        liver = tissues[0]
        self.assertEqual(liver.identifier, "UBERON_0002107")
        self.assertEqual(liver.accession, "liver")
        self.assertIn("hepatic", liver.synonyms)
        self.assertIn("FMA:7197", liver.cross_references)
        self.assertEqual(str(liver), "liver (UBERON_0002107)")

        # Test search functionality
        lung = tissues[1]
        self.assertIn("pulmonary", lung.synonyms)
        self.assertIn("pulmo", lung.synonyms)

    def test_human_disease_model_with_mondo_ontology(self):
        """Test HumanDisease model with MONDO ontology."""
        disease_data = [
            {
                "identifier": "MONDO_0007254",
                "acronym": "BC",
                "accession": "breast carcinoma",
                "definition": "A carcinoma that arises from the breast.",
                "synonyms": "breast cancer;mammary carcinoma",
                "cross_references": "DOID:3459;ICD10:C50",
                "keywords": "cancer,oncology,breast,carcinoma",
            },
            {
                "identifier": "MONDO_0005233",
                "acronym": "LC",
                "accession": "lung carcinoma",
                "definition": "A carcinoma that arises from the lung.",
                "synonyms": "lung cancer;pulmonary carcinoma",
                "cross_references": "DOID:3905;ICD10:C78.0",
                "keywords": "cancer,oncology,lung,carcinoma",
            },
        ]

        diseases = [OntologyFactory.create_disease(**data) for data in disease_data]

        # Test disease properties
        breast_cancer = diseases[0]
        self.assertEqual(breast_cancer.identifier, "MONDO_0007254")
        self.assertEqual(breast_cancer.acronym, "BC")
        self.assertIn("breast", breast_cancer.accession)
        self.assertIn("carcinoma that arises", breast_cancer.definition)
        self.assertIn("DOID:3459", breast_cancer.cross_references)

        # Test keyword functionality
        self.assertIn("cancer", breast_cancer.keywords)
        self.assertIn("oncology", breast_cancer.keywords)

    def test_ms_vocabularies_model(self):
        """Test MSUniqueVocabularies model with real MS ontology terms."""
        ms_terms_data = [
            {
                "accession": "MS_1002732",
                "name": "Orbitrap Fusion Lumos",
                "definition": "Thermo Scientific Orbitrap Fusion Lumos mass spectrometer.",
                "term_type": "instrument",
            },
            {
                "accession": "MS_1001251",
                "name": "Trypsin",
                "definition": "Trypsin cleavage enzyme.",
                "term_type": "enzyme",
            },
            {
                "accession": "MS_1000422",
                "name": "HCD",
                "definition": "Higher-energy collisional dissociation.",
                "term_type": "dissociation",
            },
        ]

        ms_terms = [OntologyFactory.create_ms_term(**data) for data in ms_terms_data]

        # Test MS term properties
        orbitrap = ms_terms[0]
        self.assertEqual(orbitrap.accession, "MS_1002732")
        self.assertIn("Orbitrap", orbitrap.name)
        self.assertEqual(orbitrap.term_type, "instrument")

        trypsin = ms_terms[1]
        self.assertEqual(trypsin.term_type, "enzyme")
        self.assertIn("cleavage", trypsin.definition)

    def test_unimod_modification_model(self):
        """Test Unimod model with protein modification data."""
        unimod_data = [
            {
                "accession": "UNIMOD_1",
                "name": "Acetyl",
                "definition": "Acetylation of lysine residues.",
                "additional_data": {
                    "mass": 42.010565,
                    "formula": "C2H2O",
                    "targets": ["K", "N-term"],
                    "classification": "post-translational",
                },
            },
            {
                "accession": "UNIMOD_35",
                "name": "Oxidation",
                "definition": "Oxidation of methionine residues.",
                "additional_data": {"mass": 15.994915, "formula": "O", "targets": ["M"], "classification": "chemical"},
            },
        ]

        modifications = [OntologyFactory.create_unimod(**data) for data in unimod_data]

        # Test modification properties
        acetyl = modifications[0]
        self.assertEqual(acetyl.accession, "UNIMOD_1")
        self.assertEqual(acetyl.name, "Acetyl")
        self.assertIn("lysine", acetyl.definition)

        # Test additional_data JSON field
        acetyl_data = acetyl.additional_data
        self.assertAlmostEqual(acetyl_data["mass"], 42.010565, places=6)
        self.assertEqual(acetyl_data["formula"], "C2H2O")
        self.assertIn("K", acetyl_data["targets"])

        oxidation = modifications[1]
        oxidation_data = oxidation.additional_data
        self.assertAlmostEqual(oxidation_data["mass"], 15.994915, places=6)
        self.assertIn("M", oxidation_data["targets"])


class FavouriteMetadataOptionComprehensiveTest(TestCase, QuickTestDataMixin):
    """Comprehensive tests for favourite metadata options."""

    def setUp(self):
        self.user = UserFactory.create_user(username="researcher")
        self.lab_group = LabGroupFactory.create_lab_group(name="Research Lab")
        self.other_user = UserFactory.create_user(username="other_researcher")
        self.other_lab = LabGroupFactory.create_lab_group(name="Other Lab")

    def test_create_user_specific_favourites(self):
        """Test creating user-specific favourite metadata options."""
        user_favourites = [
            {"name": "organism", "type": "characteristics", "value": "homo sapiens", "display_value": "Human"},
            {
                "name": "disease",
                "type": "characteristics",
                "value": "breast carcinoma",
                "display_value": "Breast Cancer",
            },
            {
                "name": "instrument",
                "type": "comment",
                "value": "orbitrap fusion lumos",
                "display_value": "Orbitrap Fusion Lumos",
            },
        ]

        created_favourites = []
        for fav_data in user_favourites:
            favourite = FavouriteMetadataOptionFactory.create_favourite(
                user=self.user, lab_group=self.lab_group, **fav_data
            )
            created_favourites.append(favourite)

        # Test favourite creation
        self.assertEqual(len(created_favourites), 3)

        # Test user-specific properties
        for favourite in created_favourites:
            self.assertEqual(favourite.user, self.user)
            self.assertEqual(favourite.lab_group, self.lab_group)
            self.assertFalse(favourite.is_global)

        # Test specific favourite
        organism_fav = created_favourites[0]
        self.assertEqual(organism_fav.name, "organism")
        self.assertEqual(organism_fav.value, "homo sapiens")
        self.assertEqual(organism_fav.display_value, "Human")

    def test_create_global_favourites(self):
        """Test creating global favourite metadata options."""
        global_favourites = [
            {"name": "disease", "type": "characteristics", "value": "normal", "display_value": "Normal/Healthy"},
            {
                "name": "technology type",
                "type": "comment",
                "value": "proteomic profiling by mass spectrometry",
                "display_value": "Proteomics MS",
            },
        ]

        created_globals = []
        for fav_data in global_favourites:
            favourite = FavouriteMetadataOptionFactory.create_global_favourite(**fav_data)
            created_globals.append(favourite)

        # Test global properties
        for favourite in created_globals:
            self.assertTrue(favourite.is_global)
            self.assertIsNone(favourite.user)
            self.assertIsNone(favourite.lab_group)

        # Test specific global favourite
        normal_disease = created_globals[0]
        self.assertEqual(normal_disease.value, "normal")
        self.assertEqual(normal_disease.display_value, "Normal/Healthy")

    def test_favourite_scope_isolation(self):
        """Test that favourites are properly isolated by user/lab."""
        # Create favourites for different users
        user1_fav = FavouriteMetadataOptionFactory.create_favourite(
            user=self.user, lab_group=self.lab_group, name="organism", value="homo sapiens"
        )

        user2_fav = FavouriteMetadataOptionFactory.create_favourite(
            user=self.other_user, lab_group=self.other_lab, name="organism", value="mus musculus"
        )

        # Test that favourites have different values for same field
        self.assertEqual(user1_fav.value, "homo sapiens")
        self.assertEqual(user2_fav.value, "mus musculus")
        self.assertNotEqual(user1_fav.user, user2_fav.user)
        self.assertNotEqual(user1_fav.lab_group, user2_fav.lab_group)

    def test_favourite_with_realistic_scientific_values(self):
        """Test favourites with realistic scientific metadata values."""
        scientific_favourites = [
            # Organism values from SDRF patterns
            {
                "name": "organism",
                "type": "characteristics",
                "value": random.choice(SDRFDataPatterns.ORGANISMS),
                "display_value": None,  # Will be auto-generated
            },
            # Disease values
            {
                "name": "disease",
                "type": "characteristics",
                "value": random.choice(SDRFDataPatterns.DISEASES),
                "display_value": None,
            },
            # Instrument values
            {
                "name": "instrument",
                "type": "comment",
                "value": random.choice(SDRFDataPatterns.INSTRUMENTS),
                "display_value": None,
            },
            # Modification values
            {
                "name": "modification parameters",
                "type": "comment",
                "value": f"NT={random.choice(SDRFDataPatterns.MODIFICATION_PARAMETERS)};AC={random.choice(SDRFDataPatterns.MOD_PARAMS_AC)};MT=Variable",
                "display_value": None,
            },
        ]

        created_favourites = []
        for fav_data in scientific_favourites:
            # Auto-generate display_value if not provided
            if not fav_data["display_value"]:
                fav_data["display_value"] = fav_data["value"].title()

            favourite = FavouriteMetadataOptionFactory.create_favourite(
                user=self.user, lab_group=self.lab_group, **fav_data
            )
            created_favourites.append(favourite)

        # Test that all favourites were created with realistic values
        self.assertEqual(len(created_favourites), 4)

        # Test organism favourite
        organism_fav = created_favourites[0]
        self.assertIn(organism_fav.value, SDRFDataPatterns.ORGANISMS)

        # Test modification parameter format
        mod_fav = created_favourites[3]
        self.assertIn("NT=", mod_fav.value)
        self.assertIn("AC=", mod_fav.value)
        self.assertIn("MT=", mod_fav.value)

    def test_favourite_usage_statistics(self):
        """Test tracking favourite usage (if implemented)."""
        favourite = FavouriteMetadataOptionFactory.create_favourite(
            user=self.user, lab_group=self.lab_group, name="organism", value="homo sapiens"
        )

        # Test initial state
        self.assertIsNotNone(favourite.created_at)
        self.assertIsNotNone(favourite.updated_at)

        # Test that favourite can be updated
        original_updated = favourite.updated_at
        favourite.display_value = "Updated Human"
        favourite.save()

        favourite.refresh_from_db()
        self.assertGreater(favourite.updated_at, original_updated)
        self.assertEqual(favourite.display_value, "Updated Human")


class IntegrationTestWithFactories(TestCase, QuickTestDataMixin):
    """Integration tests using the comprehensive factory system."""

    def test_complete_study_creation(self):
        """Test creating a complete study using SDRFTestDataBuilder."""
        builder = SDRFTestDataBuilder()

        study_data = builder.create_complete_study(
            study_name="Comprehensive Integration Test Study",
            sample_count=15,
            include_pools=True,
            include_ontologies=True,
        )

        # Test study components
        table = study_data["table"]
        self.assertEqual(table.name, "Comprehensive Integration Test Study")
        self.assertEqual(table.sample_count, 15)

        # Test columns
        columns = study_data["columns"]
        self.assertGreaterEqual(len(columns), 10)

        # Test pools
        pools = study_data["pools"]
        self.assertGreater(len(pools), 0)

        # Test ontologies
        ontologies = study_data["ontologies"]
        self.assertIn("species", ontologies)
        self.assertIn("tissues", ontologies)
        self.assertIn("diseases", ontologies)

        # Test favourites
        favourites = study_data["favourites"]
        self.assertEqual(len(favourites), 2)  # One user, one global

        # Clean up
        builder.cleanup()

    def test_multi_study_dataset_creation(self):
        """Test creating multiple related studies."""
        builder = SDRFTestDataBuilder()

        studies = builder.create_multi_study_dataset(study_count=3)

        # Test that multiple studies were created
        self.assertEqual(len(studies), 3)

        # Test that each study has required components
        for i, study in enumerate(studies):
            table = study["table"]
            self.assertIn(f"Multi-Study {i+1}", table.name)
            self.assertGreater(table.sample_count, 5)
            self.assertGreater(len(study["columns"]), 5)

        # Test that ontologies are shared (only created once)
        first_study_ontologies = studies[0]["ontologies"]
        if first_study_ontologies:  # Only first study creates ontologies
            self.assertGreater(len(first_study_ontologies["species"]), 0)

        # Clean up
        builder.cleanup()

    def test_realistic_data_patterns(self):
        """Test that factories generate data matching real SDRF patterns."""
        # Create table with realistic columns
        user = self.create_test_user()
        table = MetadataTableFactory.create_with_columns(
            user=user, name="SDRF Pattern Test Study PXD123456", sample_count=12, column_count=10
        )

        # Test table name pattern
        self.assertIn("PXD", table.name)
        self.assertIn("Study", table.name)

        # Test column patterns
        columns = table.columns.all()

        # Check for standard SDRF columns
        column_names = [col.name for col in columns]
        self.assertIn("source name", column_names)
        self.assertIn("organism", column_names)
        self.assertIn("assay name", column_names)

        # Test column values match SDRF patterns
        for column in columns:
            if column.name == "organism" and column.type == "characteristics":
                self.assertIn(column.value, SDRFDataPatterns.ORGANISMS)
            elif column.name == "disease" and column.type == "characteristics":
                self.assertIn(column.value, SDRFDataPatterns.DISEASES)

    def test_factory_performance_and_cleanup(self):
        """Test factory performance with larger datasets and proper cleanup."""
        import time

        start_time = time.time()

        # Create multiple studies quickly
        users = [UserFactory.create_user() for _ in range(5)]
        tables = []

        for user in users:
            table = MetadataTableFactory.create_with_columns(user=user, sample_count=20, column_count=12)
            tables.append(table)

        creation_time = time.time() - start_time

        # Test performance (should create 5 studies quickly)
        self.assertLess(creation_time, 10.0)  # Should complete in under 10 seconds

        # Test data integrity
        self.assertEqual(len(tables), 5)
        for table in tables:
            self.assertEqual(table.columns.count(), 12)
            self.assertEqual(table.sample_count, 20)

        # Test cleanup
        total_columns_before = MetadataColumn.objects.count()
        self.assertGreater(total_columns_before, 50)  # Should have many columns

        # Delete tables (should cascade to columns)
        for table in tables:
            table.delete()

        total_columns_after = MetadataColumn.objects.count()
        self.assertLess(total_columns_after, total_columns_before)
