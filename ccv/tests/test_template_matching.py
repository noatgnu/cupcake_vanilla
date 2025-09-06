"""
Tests for exact template matching logic in column creation.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from ccv.models import LabGroup, MetadataColumn, MetadataColumnTemplate, MetadataTable, MetadataTableTemplate
from ccv.viewsets import MetadataManagementViewSet


class TemplateMatchingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)

        # Create global column templates with exact names and ontology types
        self.organism_part_template = MetadataColumnTemplate.objects.create(
            column_name="characteristics[organism part]",
            column_type="characteristics",
            ontology_type="tissue",
            is_active=True,
            owner=self.user,
            lab_group=self.lab_group,
        )

        self.organism_template = MetadataColumnTemplate.objects.create(
            column_name="characteristics[organism]",
            column_type="characteristics",
            ontology_type="species",
            is_active=True,
            owner=self.user,
            lab_group=self.lab_group,
        )

        self.disease_template = MetadataColumnTemplate.objects.create(
            column_name="characteristics[disease]",
            column_type="characteristics",
            ontology_type="human_disease",
            is_active=True,
            owner=self.user,
            lab_group=self.lab_group,
        )

    def test_exact_template_matching_organism_part(self):
        """Test that 'characteristics[organism part]' matches exactly with tissue ontology."""
        table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        # Create a table template with the organism_part_template
        table_template = MetadataTableTemplate.objects.create(
            name="Test Template", owner=self.user, lab_group=self.lab_group
        )

        # Create a MetadataColumn in the template that references our MetadataColumnTemplate
        template_column = MetadataColumn.objects.create(
            metadata_table=table,  # Use the actual table
            name="characteristics[organism part]",
            type="characteristics",
            ontology_type="tissue",
            template=self.organism_part_template,
            column_position=0,
        )
        table_template.user_columns.add(template_column)

        viewset = MetadataManagementViewSet()

        # Test exact matching
        column = viewset._find_or_create_matching_column(
            clean_name="characteristics[organism part]",
            metadata_type="characteristics",
            metadata_table=table,
            table_template=table_template,
            column_position=0,
            occurrence_number=1,
        )

        self.assertEqual(column.name, "characteristics[organism part]")
        self.assertEqual(column.type, "characteristics")
        self.assertEqual(column.ontology_type, "tissue")
        self.assertEqual(column.template, self.organism_part_template)

    def test_exact_template_matching_organism(self):
        """Test that 'characteristics[organism]' matches exactly with species ontology."""
        table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        # Create a table template with the organism_template
        table_template = MetadataTableTemplate.objects.create(
            name="Test Template", owner=self.user, lab_group=self.lab_group
        )

        # Create a MetadataColumn in the template that references our MetadataColumnTemplate
        template_column = MetadataColumn.objects.create(
            metadata_table=table,  # Use the actual table
            name="characteristics[organism]",
            type="characteristics",
            ontology_type="species",
            template=self.organism_template,
            column_position=0,
        )
        table_template.user_columns.add(template_column)

        viewset = MetadataManagementViewSet()

        column = viewset._find_or_create_matching_column(
            clean_name="characteristics[organism]",
            metadata_type="characteristics",
            metadata_table=table,
            table_template=table_template,
            column_position=0,
            occurrence_number=1,
        )

        self.assertEqual(column.name, "characteristics[organism]")
        self.assertEqual(column.type, "characteristics")
        self.assertEqual(column.ontology_type, "species")
        self.assertEqual(column.template, self.organism_template)

    def test_no_partial_matching(self):
        """Test that partial matches don't occur - only exact matches."""
        table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        viewset = MetadataManagementViewSet()

        # Test that a column name that doesn't exist exactly falls back to basic
        column = viewset._find_or_create_matching_column(
            clean_name="characteristics[some unknown field]",
            metadata_type="characteristics",
            metadata_table=table,
            table_template=None,
            column_position=0,
            occurrence_number=1,
        )

        self.assertEqual(column.name, "characteristics[some unknown field]")
        self.assertEqual(column.type, "characteristics")
        self.assertIsNone(column.ontology_type)  # Should be None for basic columns
        self.assertIsNone(column.template)

    def test_case_insensitive_exact_matching(self):
        """Test that matching is case insensitive but still exact."""
        table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        # Create a table template with a MetadataColumn that has the organism_part_template
        table_template = MetadataTableTemplate.objects.create(
            name="Test Template", owner=self.user, lab_group=self.lab_group
        )

        # Create a MetadataColumn in the template that references our MetadataColumnTemplate
        template_column = MetadataColumn.objects.create(
            name="characteristics[organism part]",
            type="characteristics",
            ontology_type="tissue",
            template=self.organism_part_template,
            column_position=0,
        )
        table_template.user_columns.add(template_column)

        viewset = MetadataManagementViewSet()

        # Test case insensitive matching
        column = viewset._find_or_create_matching_column(
            clean_name="CHARACTERISTICS[ORGANISM PART]",
            metadata_type="characteristics",
            metadata_table=table,
            table_template=table_template,
            column_position=0,
            occurrence_number=1,
        )

        self.assertEqual(column.name, "CHARACTERISTICS[ORGANISM PART]")
        self.assertEqual(column.ontology_type, "tissue")
        self.assertEqual(column.template, self.organism_part_template)

    def test_table_template_priority_over_global(self):
        """Test that table template matches take priority over global templates."""
        # Create a table template with different ontology type
        table_template = MetadataTableTemplate.objects.create(
            name="Test Template", owner=self.user, lab_group=self.lab_group
        )

        table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        # Create a template column in the table template with different ontology
        from ccv.models import MetadataColumn

        template_column = MetadataColumn.objects.create(
            metadata_table=table,  # Use MetadataTable, not MetadataTableTemplate
            name="characteristics[organism part]",
            type="characteristics",
            ontology_type="uberon",  # Different from global template
            column_position=0,
        )
        table_template.user_columns.add(template_column)

        viewset = MetadataManagementViewSet()

        column = viewset._find_or_create_matching_column(
            clean_name="characteristics[organism part]",
            metadata_type="characteristics",
            metadata_table=table,
            table_template=table_template,
            column_position=0,
            occurrence_number=1,
        )

        # Should use table template, not global template
        self.assertEqual(column.ontology_type, "uberon")
