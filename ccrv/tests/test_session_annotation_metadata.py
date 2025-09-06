"""
Tests for SessionAnnotation metadata table functionality.

Tests that SessionAnnotation can create and manage metadata tables with columns,
similar to how Instrument and StoredReagent manage metadata.
"""

import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ccc.models import Annotation
from ccrv.models import ProtocolModel, Session, SessionAnnotation
from ccv.models import MetadataColumn, MetadataTable
from tests.factories import UserFactory


class SessionAnnotationMetadataTestCase(TestCase):
    """Test basic metadata table functionality for session annotations."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.other_user = UserFactory.create_user()

        # Create protocol and session
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Experimental Protocol",
            protocol_description="Protocol for metadata testing",
            owner=self.user,
        )

        self.session = Session.objects.create(
            unique_id=uuid.uuid4(), name="Metadata Test Session", owner=self.user, visibility="private"
        )
        self.session.protocols.add(self.protocol)

        # Create annotation and session annotation
        self.annotation = Annotation.objects.create(
            annotation="Experimental results and data", annotation_type="text", owner=self.user
        )

        self.session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=self.annotation)

    def test_create_metadata_table(self):
        """Test creating a metadata table for session annotation."""
        # Initially no metadata table
        self.assertIsNone(self.session_annotation.metadata_table)

        # Create metadata table
        metadata_table = self.session_annotation.create_metadata_table()

        # Verify table was created and linked
        self.assertIsNotNone(metadata_table)
        self.assertIsInstance(metadata_table, MetadataTable)
        self.assertEqual(self.session_annotation.metadata_table, metadata_table)

        # Verify table properties
        expected_name = f"SessionAnnotation-{self.session.name}-{self.annotation.id}"
        self.assertEqual(metadata_table.name, expected_name)
        self.assertEqual(metadata_table.description, f"Metadata table for session annotation: {self.session.name}")
        self.assertEqual(metadata_table.owner, self.user)
        self.assertEqual(metadata_table.visibility, "private")
        self.assertEqual(metadata_table.source_app, "ccrv")

    def test_create_metadata_table_idempotent(self):
        """Test that creating metadata table multiple times doesn't create duplicates."""
        # Create metadata table twice
        table1 = self.session_annotation.create_metadata_table()
        table2 = self.session_annotation.create_metadata_table()

        # Should be the same table
        self.assertEqual(table1, table2)
        self.assertEqual(table1.id, table2.id)

    def test_add_metadata_column_basic(self):
        """Test adding a basic metadata column."""
        column_data = {"name": "Sample Type", "type": "characteristics", "value": "blood plasma"}

        column = self.session_annotation.add_metadata_column(column_data)

        # Verify column was created
        self.assertIsInstance(column, MetadataColumn)
        self.assertEqual(column.name, "Sample Type")
        self.assertEqual(column.type, "characteristics")
        self.assertEqual(column.value, "blood plasma")
        self.assertEqual(column.column_position, 0)  # First column
        self.assertFalse(column.mandatory)

        # Verify metadata table was created automatically
        self.assertIsNotNone(self.session_annotation.metadata_table)
        self.assertEqual(column.metadata_table, self.session_annotation.metadata_table)

    def test_add_metadata_column_advanced_options(self):
        """Test adding metadata column with advanced options."""
        column_data = {
            "name": "Patient ID",
            "type": "factor value",
            "value": "P001",
            "mandatory": True,
            "hidden": True,
            "readonly": True,
            "position": 0,
        }

        column = self.session_annotation.add_metadata_column(column_data)

        # Verify advanced options
        self.assertEqual(column.name, "Patient ID")
        self.assertEqual(column.type, "factor value")
        self.assertEqual(column.value, "P001")
        self.assertTrue(column.mandatory)
        self.assertTrue(column.hidden)
        self.assertTrue(column.readonly)
        self.assertEqual(column.column_position, 0)

    def test_add_multiple_columns_positioning(self):
        """Test that multiple columns get correct positions."""
        # Add first column
        column1 = self.session_annotation.add_metadata_column({"name": "Sample ID", "value": "S001"})

        # Add second column
        column2 = self.session_annotation.add_metadata_column({"name": "Concentration", "value": "100 mg/ml"})

        # Add third column with explicit position
        column3 = self.session_annotation.add_metadata_column({"name": "Volume", "value": "50 μL", "position": 1})

        # Verify positions
        self.assertEqual(column1.column_position, 0)
        self.assertEqual(column2.column_position, 1)  # Auto-assigned
        self.assertEqual(column3.column_position, 1)  # Explicitly set

    def test_add_column_missing_name(self):
        """Test that adding column without name raises error."""
        with self.assertRaises(ValueError) as context:
            self.session_annotation.add_metadata_column({"type": "characteristics", "value": "test"})

        self.assertIn("Column name is required", str(context.exception))

    def test_remove_metadata_column(self):
        """Test removing a metadata column."""
        # Add a column first
        column = self.session_annotation.add_metadata_column({"name": "Test Column", "value": "test value"})

        # Verify column exists
        self.assertEqual(self.session_annotation.get_metadata_columns().count(), 1)

        # Remove the column
        result = self.session_annotation.remove_metadata_column(column.id)

        # Verify removal
        self.assertTrue(result)
        self.assertEqual(self.session_annotation.get_metadata_columns().count(), 0)

        # Verify column was deleted from database
        with self.assertRaises(MetadataColumn.DoesNotExist):
            MetadataColumn.objects.get(id=column.id)

    def test_remove_column_no_metadata_table(self):
        """Test removing column when no metadata table exists."""
        with self.assertRaises(ValueError) as context:
            self.session_annotation.remove_metadata_column(999)

        self.assertIn("No metadata table found", str(context.exception))

    def test_remove_nonexistent_column(self):
        """Test removing column that doesn't exist."""
        # Create metadata table but no columns
        self.session_annotation.create_metadata_table()

        with self.assertRaises(ValueError) as context:
            self.session_annotation.remove_metadata_column(999)

        self.assertIn("Column with ID 999 not found", str(context.exception))

    def test_get_metadata_columns_no_table(self):
        """Test getting columns when no metadata table exists."""
        columns = self.session_annotation.get_metadata_columns()

        # Should return empty queryset
        self.assertEqual(columns.count(), 0)
        self.assertEqual(list(columns), [])

    def test_get_metadata_columns_with_ordering(self):
        """Test getting metadata columns returns them in correct order."""
        # Add columns in mixed order
        self.session_annotation.add_metadata_column({"name": "Column B", "position": 2})
        self.session_annotation.add_metadata_column({"name": "Column A", "position": 0})
        self.session_annotation.add_metadata_column({"name": "Column C", "position": 1})

        # Get columns
        columns = list(self.session_annotation.get_metadata_columns())

        # Should be ordered by position
        self.assertEqual(len(columns), 3)
        self.assertEqual(columns[0].name, "Column A")  # position 0
        self.assertEqual(columns[1].name, "Column C")  # position 1
        self.assertEqual(columns[2].name, "Column B")  # position 2

    def test_update_metadata_column_value(self):
        """Test updating metadata column values."""
        # Add a column
        column = self.session_annotation.add_metadata_column({"name": "Status", "value": "pending"})

        # Update the value
        result = self.session_annotation.update_metadata_column_value(column.id, "completed")

        # Verify update
        self.assertTrue(result)

        # Refresh from database
        column.refresh_from_db()
        self.assertEqual(column.value, "completed")

    def test_update_column_value_no_table(self):
        """Test updating column value when no metadata table exists."""
        with self.assertRaises(ValueError) as context:
            self.session_annotation.update_metadata_column_value(999, "new value")

        self.assertIn("No metadata table found", str(context.exception))

    def test_update_nonexistent_column_value(self):
        """Test updating value of nonexistent column."""
        self.session_annotation.create_metadata_table()

        with self.assertRaises(ValueError) as context:
            self.session_annotation.update_metadata_column_value(999, "new value")

        self.assertIn("Column with ID 999 not found", str(context.exception))


class SessionAnnotationMetadataWorkflowTestCase(TestCase):
    """Test complete metadata workflows with session annotations."""

    def setUp(self):
        self.researcher = UserFactory.create_user()
        self.collaborator = UserFactory.create_user()

        # Create experimental session
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(), name="Proteomics Experiment #1", owner=self.researcher, visibility="protected"
        )

        # Create experimental data annotation with file
        data_file = SimpleUploadedFile(
            "experimental_data.csv",
            b"sample_id,protein_concentration,absorbance\nS001,2.5,0.65\nS002,1.8,0.48",
            content_type="text/csv",
        )

        self.annotation = Annotation.objects.create(
            annotation="Protein concentration measurements from BCA assay",
            annotation_type="file",
            file=data_file,
            owner=self.researcher,
        )

        self.session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=self.annotation)

    def test_complete_experimental_metadata_workflow(self):
        """Test complete workflow of building experimental metadata."""
        # 1. Create experimental metadata structure

        # Sample information columns
        self.session_annotation.add_metadata_column(
            {"name": "Sample ID", "type": "factor value", "value": "S001", "mandatory": True}
        )

        self.session_annotation.add_metadata_column(
            {"name": "Organism Part", "type": "characteristics", "value": "liver"}
        )

        # Experimental parameters
        self.session_annotation.add_metadata_column(
            {"name": "Protocol", "type": "parameter value", "value": "BCA Protein Assay"}
        )

        concentration_col = self.session_annotation.add_metadata_column(
            {"name": "Protein Concentration", "type": "factor value", "value": "2.5 mg/ml"}
        )

        # 2. Verify metadata table structure
        metadata_table = self.session_annotation.metadata_table
        self.assertIsNotNone(metadata_table)
        self.assertEqual(metadata_table.get_column_count(), 4)

        # 3. Verify columns are properly ordered and configured
        columns = list(self.session_annotation.get_metadata_columns())
        self.assertEqual(len(columns), 4)

        # Check mandatory column
        sample_col = next(col for col in columns if col.name == "Sample ID")
        self.assertTrue(sample_col.mandatory)
        self.assertEqual(sample_col.type, "factor value")

        # 4. Update experimental values
        self.session_annotation.update_metadata_column_value(concentration_col.id, "3.2 mg/ml")

        # Verify update
        concentration_col.refresh_from_db()
        self.assertEqual(concentration_col.value, "3.2 mg/ml")

        # 5. Add quality control column
        self.session_annotation.add_metadata_column(
            {
                "name": "Quality Control",
                "type": "parameter value",
                "value": "passed",
                "position": 0,  # Insert at beginning
            }
        )

        # Verify final structure
        final_columns = list(self.session_annotation.get_metadata_columns())
        self.assertEqual(len(final_columns), 5)
        self.assertEqual(final_columns[0].name, "Quality Control")

    def test_metadata_table_permissions_inherit_from_session(self):
        """Test that metadata table permissions follow session permissions."""
        # Create metadata table
        metadata_table = self.session_annotation.create_metadata_table()

        # Metadata table should inherit session properties
        self.assertEqual(metadata_table.owner, self.researcher)
        self.assertEqual(metadata_table.visibility, self.session.visibility)

        # Add collaborator to session
        self.session.editors.add(self.collaborator)

        # The metadata table should be accessible through the session annotation
        # which inherits session permissions
        self.assertTrue(self.session_annotation.can_view(self.researcher))
        self.assertTrue(self.session_annotation.can_edit(self.researcher))

    def test_multiple_session_annotations_separate_metadata(self):
        """Test that different session annotations have separate metadata tables."""
        # Create second annotation and session annotation
        annotation2 = Annotation.objects.create(
            annotation="Additional experimental notes", annotation_type="text", owner=self.researcher
        )

        session_annotation2 = SessionAnnotation.objects.create(session=self.session, annotation=annotation2)

        # Add columns to first session annotation
        self.session_annotation.add_metadata_column({"name": "Sample Type", "value": "plasma"})

        # Add different columns to second session annotation
        session_annotation2.add_metadata_column({"name": "Instrument", "value": "HPLC-MS"})

        # Verify they have separate metadata tables
        self.assertNotEqual(self.session_annotation.metadata_table, session_annotation2.metadata_table)

        # Verify different column sets
        columns1 = list(self.session_annotation.get_metadata_columns())
        columns2 = list(session_annotation2.get_metadata_columns())

        self.assertEqual(len(columns1), 1)
        self.assertEqual(len(columns2), 1)
        self.assertEqual(columns1[0].name, "Sample Type")
        self.assertEqual(columns2[0].name, "Instrument")

    def test_session_annotation_with_instrument_usage_metadata(self):
        """Test session annotation metadata in context of instrument usage."""
        from ccm.models import Instrument, InstrumentUsage

        # Create instrument and usage
        instrument = Instrument.objects.create(instrument_name="LC-MS System", user=self.researcher)

        usage = InstrumentUsage.objects.create(
            instrument=instrument, user=self.researcher, description="Protein analysis run"
        )

        # Link session annotation to instrument usage
        from ccrv.models import InstrumentUsageSessionAnnotation

        usage_link = InstrumentUsageSessionAnnotation.objects.create(
            session_annotation=self.session_annotation, instrument_usage=usage
        )

        # Add instrument-specific metadata to session annotation
        self.session_annotation.add_metadata_column(
            {"name": "Instrument Method", "type": "parameter value", "value": "Protein_Analysis_v2.1"}
        )

        self.session_annotation.add_metadata_column(
            {"name": "Run Time", "type": "parameter value", "value": "45 minutes"}
        )

        # Verify metadata structure
        columns = list(self.session_annotation.get_metadata_columns())
        self.assertEqual(len(columns), 2)

        method_col = next(col for col in columns if col.name == "Instrument Method")
        runtime_col = next(col for col in columns if col.name == "Run Time")

        self.assertEqual(method_col.value, "Protein_Analysis_v2.1")
        self.assertEqual(runtime_col.value, "45 minutes")

        # The linked usage should be accessible
        self.assertEqual(usage_link.session_annotation, self.session_annotation)
        self.assertEqual(usage_link.instrument_usage, usage)
