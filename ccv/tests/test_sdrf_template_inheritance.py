"""
Tests for SDRF import template inheritance functionality.

This module tests that SDRF imports properly inherit ontology and other properties
from column templates, which was the original issue being fixed.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from ccv.models import LabGroup, MetadataColumnTemplate, MetadataTable, MetadataTableTemplate


class SDRFTemplateInheritanceTest(TestCase):
    """Test that SDRF imports properly inherit properties from templates."""

    def setUp(self):
        """Set up test data with templates."""
        # Step 1: Sync builtin schemas (from sync_schemas command line 57)
        from ccv.models import Schema

        Schema.sync_builtin_schemas()

        # Step 2: Create admin user for templates (from load_column_templates)
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = User.objects.create_superuser("admin", "admin@test.com", "password")

        # Step 3: Get schema object (from load_column_templates lines 100-114)
        schema_obj = Schema.objects.get(name="minimum", is_builtin=True)

        # Step 4: Load schema definition (from load_column_templates line 150)
        from ccv.utils import get_specific_default_schema

        schema = get_specific_default_schema("minimum")

        # Step 5: Create column templates (from load_column_templates lines 192-240)
        for column in schema.columns:
            column_type = ""
            column_name = column.name
            display_name = column.name

            # Parse column type from name (lines 198-210)
            if column.name.startswith("characteristics"):
                column_type = "characteristics"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name.startswith("comment"):
                column_type = "comment"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name.startswith("factor value"):
                column_type = "factor value"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name == "source name":
                column_type = "source_name"
            else:
                column_type = "special"

            # Create template (lines 213-225)
            template = MetadataColumnTemplate.objects.create(
                name=display_name,
                description=column.description or f"Template for {display_name}",
                column_name=column_name,
                column_type=column_type,
                base_column=True,
                is_system_template=True,
                owner=admin_user,
                category="Minimum Schema",
                source_schema="minimum",
                schema=schema_obj,
                visibility="public",
            )

            # Configure ontology options (from load_column_templates lines 242-302)
            if "organism part" in template.column_name.lower():
                template.ontology_options = ["tissue", "uberon"]
                template.ontology_type = "tissue"

            for validator in column.validators:
                if validator.validator_name == "ontology":
                    custom_filter = {}
                    template.enable_typeahead = True
                    template.ontology_options = []
                    template.possible_default_values = validator.params.get("examples", [])
                    for ontology in validator.params.get("ontologies", []):
                        if ontology == "ncbitaxon":
                            template.ontology_options.extend(["ncbi_taxonomy", "species"])
                            template.ontology_type = "species"
                        elif ontology == "cl":
                            template.ontology_options.append("cell_ontology")
                            template.ontology_type = "cell_ontology"
                        elif ontology == "pride":
                            template.ontology_options.append("ms_unique_vocabularies")
                            custom_filter["ms_unique_vocabularies"] = {"term_type": "sample attribute"}
                            template.ontology_type = "ms_unique_vocabularies"
                        elif ontology == "unimod":
                            template.ontology_options.append("unimod")
                            template.ontology_type = "unimod"
                        elif ontology == "ms":
                            template.ontology_options.append("ms_unique_vocabularies")
                            # Set specific filters based on column name
                            if "instrument" in template.column_name.lower():
                                custom_filter["ms_unique_vocabularies"] = {"term_type": "instrument"}
                            elif "analyzer" in template.column_name.lower():
                                custom_filter["ms_unique_vocabularies"] = {"term_type": "ms analyzer type"}
                            elif "cleavage" in template.column_name.lower():
                                custom_filter["ms_unique_vocabularies"] = {"term_type": "cleavage agent"}
                            template.ontology_type = "ms_unique_vocabularies"
                        elif ontology == "mondo":
                            template.ontology_options.extend(["human_disease", "mondo"])
                            template.ontology_type = "human_disease"
                        elif ontology == "clo":
                            template.ontology_options.append("ms_unique_vocabularies")
                            custom_filter["ms_unique_vocabularies"] = {"term_type": "cell line"}
                            template.ontology_type = "ms_unique_vocabularies"

                    # Handle special column-specific configurations
                    if "ancestry category" in template.column_name.lower():
                        template.ontology_options.append("ms_unique_vocabularies")
                        custom_filter["ms_unique_vocabularies"] = {"term_type": "ancestral category"}
                        template.ontology_type = "ms_unique_vocabularies"
                    elif "sex" in template.column_name.lower():
                        template.ontology_options.append("ms_unique_vocabularies")
                        custom_filter["ms_unique_vocabularies"] = {"term_type": "sex"}
                        template.ontology_type = "ms_unique_vocabularies"
                    elif "developmental stage" in template.column_name.lower():
                        template.ontology_options.append("ms_unique_vocabularies")
                        custom_filter["ms_unique_vocabularies"] = {"term_type": "developmental stage"}
                        template.ontology_type = "ms_unique_vocabularies"

                    # Set custom filters if any were configured
                    if custom_filter:
                        template.custom_ontology_filters = custom_filter

            template.save()

        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
        # Add user to the lab group as a member
        self.lab_group.members.add(self.user)

        # Get the loaded column templates
        self.organism_template = MetadataColumnTemplate.objects.filter(column_name="characteristics[organism]").first()
        self.organism_part_template = MetadataColumnTemplate.objects.filter(
            column_name="characteristics[organism part]"
        ).first()
        self.disease_template = MetadataColumnTemplate.objects.filter(column_name="characteristics[disease]").first()

        # Create a table template from schema using the proper method
        self.table_template = MetadataTableTemplate.create_from_schemas(
            name="SDRF Test Template", schema_ids=[schema_obj.id], creator=self.user, lab_group=self.lab_group
        )

    def test_sdrf_import_with_template_inheritance(self):
        """Test that SDRF import into a table created from template preserves template properties."""

        # STEP 1: Create table from the template we already have
        created_table = self.table_template.create_table_from_template(
            table_name="SDRF Template Test Table",
            creator=self.user,
            lab_group=self.lab_group,
            sample_count=3,
            description="Table for testing SDRF template inheritance",
        )

        # Verify it has columns with template properties
        organism_col_before = created_table.columns.filter(name="characteristics[organism]").first()
        self.assertIsNotNone(organism_col_before)
        self.assertEqual(organism_col_before.ontology_type, "species")
        # Verify template properties are set on creation
        self.assertIsNotNone(organism_col_before.ontology_options)
        self.assertIsNotNone(organism_col_before.template)

        # STEP 2: Import SDRF into the templated table using the real API
        sdrf_content = (
            "source name\tcharacteristics[organism]\t"
            "characteristics[organism part]\tcharacteristics[disease]\t"
            "assay name\n"
            "Sample1\thomo sapiens\tliver\tcancer\trun1\n"
            "Sample2\tmus musculus\tbrain\tdiabetes\trun2\n"
            "Sample3\thomo sapiens\theart\tcancer\trun3\n"
        )

        # Import using the exact same workflow as the real API
        from ccv.tasks.import_utils import import_sdrf_data

        result = import_sdrf_data(
            file_content=sdrf_content,
            metadata_table=created_table,
            user=self.user,
            replace_existing=False,
            validate_ontologies=True,
            create_pools=True,
        )

        # Verify the import was successful
        self.assertTrue(result["success"])

        # STEP 3: Verify template properties are preserved after import
        organism_col_after = created_table.columns.filter(name="characteristics[organism]").first()
        self.assertIsNotNone(organism_col_after, "Organism column should exist after import")
        self.assertEqual(organism_col_after.ontology_type, "species", "Ontology type should be preserved")
        self.assertIsNotNone(organism_col_after.template, "Template reference should be preserved")
        self.assertIsNotNone(organism_col_after.ontology_options, "Ontology options should be preserved")
        # Verify ontology_options contains the expected ontology sources
        self.assertIn("ncbi_taxonomy", organism_col_after.ontology_options)
        self.assertIn("species", organism_col_after.ontology_options)

        organism_part_col = created_table.columns.filter(name="characteristics[organism part]").first()
        self.assertIsNotNone(organism_part_col, "Organism part column should exist after import")
        self.assertEqual(organism_part_col.ontology_type, "tissue", "Ontology type should be preserved")
        self.assertIsNotNone(organism_part_col.template, "Template reference should be preserved")
        self.assertIsNotNone(organism_part_col.ontology_options, "Ontology options should be preserved")
        # Verify ontology_options contains the expected ontology sources
        self.assertIn("tissue", organism_part_col.ontology_options)
        self.assertIn("uberon", organism_part_col.ontology_options)

        disease_col = created_table.columns.filter(name="characteristics[disease]").first()
        self.assertIsNotNone(disease_col, "Disease column should exist after import")
        self.assertEqual(disease_col.ontology_type, "human_disease", "Ontology type should be preserved")
        self.assertIsNotNone(disease_col.template, "Template reference should be preserved")
        self.assertIsNotNone(disease_col.ontology_options, "Ontology options should be preserved")
        # Verify ontology_options contains the expected ontology sources
        self.assertIn("human_disease", disease_col.ontology_options)
        self.assertIn("mondo", disease_col.ontology_options)

    def test_sdrf_import_without_template(self):
        """Test that SDRF import without template creates basic columns."""
        metadata_table = MetadataTable.objects.create(
            name="Basic SDRF Test Table", owner=self.user, lab_group=self.lab_group
        )

        sdrf_content = "source name\tcharacteristics[unknown field]\tassay name\n" "Sample1\tsome value\trun1\n"

        # Import without table template
        # Import without any templates available
        from ccv.tasks.import_utils import import_sdrf_data

        result = import_sdrf_data(
            file_content=sdrf_content,
            metadata_table=metadata_table,
            user=self.user,
            replace_existing=False,
            validate_ontologies=True,
            create_pools=True,
        )

        self.assertTrue(result["success"])

        # Check that column was created without template properties
        unknown_col = metadata_table.columns.filter(name="characteristics[unknown field]").first()
        self.assertIsNotNone(unknown_col)
        self.assertIsNone(unknown_col.ontology_type)
        self.assertIsNone(unknown_col.template)
        self.assertTrue(unknown_col.ontology_options in [None, []])

    def test_sdrf_import_case_insensitive_template_matching(self):
        """Test that template matching is case insensitive when table has template."""
        # Create table from template so it has template properties
        created_table = self.table_template.create_table_from_template(
            table_name="Case Insensitive Test Table",
            creator=self.user,
            lab_group=self.lab_group,
            sample_count=1,
            description="Table for testing case insensitive matching",
        )

        sdrf_content = "source name\tCHARACTERISTICS[ORGANISM]\tassay name\n" "Sample1\thomo sapiens\trun1\n"

        from ccv.tasks.import_utils import import_sdrf_data

        result = import_sdrf_data(
            file_content=sdrf_content,
            metadata_table=created_table,
            user=self.user,
            replace_existing=False,
            validate_ontologies=True,
            create_pools=True,
        )

        self.assertTrue(result["success"])

        # Check that uppercase column name was normalized and matched template
        # SDRF import converts all column names to lowercase for consistency
        organism_col = created_table.columns.filter(name="characteristics[organism]").first()
        self.assertIsNotNone(organism_col, "Column should be created with normalized lowercase name")
        self.assertEqual(organism_col.ontology_type, "species")
        self.assertIsNotNone(organism_col.template, "Template should be preserved")
