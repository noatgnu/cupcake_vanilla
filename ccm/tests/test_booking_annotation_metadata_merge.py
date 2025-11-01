from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import Annotation, LabGroup
from ccm.models import Instrument, InstrumentJob, InstrumentJobAnnotation
from ccv.models import MetadataColumn, MetadataTable

User = get_user_model()


class BookingAnnotationMetadataMergeTest(TestCase):
    """
    Test suite for booking annotation metadata merge functionality.

    When a booking annotation is created for an instrument job, the system should:
    1. Merge instrument metadata into job metadata
    2. Replace empty/blank/N/A job columns with instrument values
    3. Add new columns from instrument that don't exist in job
    """

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.staff_user = User.objects.create_user(username="staffuser", password="testpass", is_staff=True)

        self.lab_group = LabGroup.objects.create(
            name="Test Lab",
            description="Test lab for metadata merge tests",
            creator=self.user,
        )
        self.lab_group.members.add(self.user)

        self.instrument = Instrument.objects.create(
            instrument_name="Test LCMS",
            user=self.user,
        )

        self.instrument_metadata_table = self.instrument.metadata_table

        self.job_metadata_table = MetadataTable.objects.create(
            name="Test Job Metadata",
            description="Metadata for test job",
            sample_count=1,
            owner=self.user,
            lab_group=self.lab_group,
            is_published=False,
            is_locked=False,
            source_app="ccm",
        )

        self.instrument_job = InstrumentJob.objects.create(
            user=self.user,
            instrument=self.instrument,
            lab_group=self.lab_group,
            job_type="analysis",
            job_name="Test Analysis Job",
            status="submitted",
            metadata_table=self.job_metadata_table,
        )

    def test_merge_replaces_empty_job_column_with_instrument_value(self):
        """Test that empty job columns are replaced with instrument values."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column1",
            type="characteristics",
            value="Instrument Value",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column1",
            type="characteristics",
            value="",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column1",
        )
        self.assertEqual(job_col.value, "Instrument Value")

    def test_merge_replaces_blank_job_column_with_instrument_value(self):
        """Test that blank job columns (whitespace only) are replaced."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column2",
            type="characteristics",
            value="Instrument Value 2",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column2",
            type="characteristics",
            value="   ",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column2",
        )
        self.assertEqual(job_col.value, "Instrument Value 2")

    def test_merge_replaces_not_applicable_job_column(self):
        """Test that not_applicable job columns are replaced."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column3",
            type="characteristics",
            value="Instrument Value 3",
            not_applicable=False,
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column3",
            type="characteristics",
            value="Old Value",
            not_applicable=True,
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column3",
        )
        self.assertEqual(job_col.value, "Instrument Value 3")
        self.assertFalse(job_col.not_applicable)

    def test_merge_replaces_not_available_job_column(self):
        """Test that not_available job columns are replaced."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column4",
            type="characteristics",
            value="Instrument Value 4",
            not_available=False,
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column4",
            type="characteristics",
            value="Old Value",
            not_available=True,
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column4",
        )
        self.assertEqual(job_col.value, "Instrument Value 4")
        self.assertFalse(job_col.not_available)

    def test_merge_does_not_replace_existing_job_values(self):
        """Test that existing non-empty job values are NOT replaced."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column5",
            type="characteristics",
            value="Instrument Value 5",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column5",
            type="characteristics",
            value="Existing Job Value",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column5",
        )
        self.assertEqual(job_col.value, "Existing Job Value")

    def test_merge_adds_missing_columns_from_instrument(self):
        """Test that columns from instrument that don't exist in job are added."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="new_column",
            type="factor value",
            value="New Instrument Value",
            column_position=10,
            mandatory=True,
            staff_only=False,
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        self.assertTrue(
            MetadataColumn.objects.filter(
                metadata_table=self.job_metadata_table,
                name="new_column",
                type="factor value",
            ).exists()
        )

        new_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="new_column",
        )
        self.assertEqual(new_col.value, "New Instrument Value")
        self.assertEqual(new_col.column_position, 10)
        self.assertTrue(new_col.mandatory)
        self.assertFalse(new_col.staff_only)

    def test_merge_handles_multiple_columns(self):
        """Test merging multiple columns in a single operation."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="col_a",
            type="characteristics",
            value="Value A",
        )
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="col_b",
            type="characteristics",
            value="Value B",
        )
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="col_c",
            type="characteristics",
            value="Value C",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="col_a",
            type="characteristics",
            value="",
        )
        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="col_b",
            type="characteristics",
            value="Existing Value B",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        col_a = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="col_a",
        )
        self.assertEqual(col_a.value, "Value A")

        col_b = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="col_b",
        )
        self.assertEqual(col_b.value, "Existing Value B")

        col_c = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="col_c",
        )
        self.assertEqual(col_c.value, "Value C")

    def test_merge_only_triggers_for_booking_annotations(self):
        """Test that merge only happens for booking annotation type."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column6",
            type="characteristics",
            value="Instrument Value 6",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column6",
            type="characteristics",
            value="",
        )

        text_annotation = Annotation.objects.create(
            annotation="Regular text annotation",
            annotation_type="text",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=text_annotation,
        )

        job_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="column6",
        )
        self.assertEqual(job_col.value, "")

    def test_merge_handles_no_instrument_metadata(self):
        """Test graceful handling when instrument has no metadata table."""
        instrument_no_metadata = Instrument.objects.create(
            instrument_name="Instrument Without Metadata",
            user=self.user,
        )
        instrument_no_metadata.metadata_table.delete()
        instrument_no_metadata.metadata_table = None
        instrument_no_metadata.save()

        job_no_inst_metadata = InstrumentJob.objects.create(
            user=self.user,
            instrument=instrument_no_metadata,
            lab_group=self.lab_group,
            job_type="analysis",
            job_name="Job with no instrument metadata",
            status="submitted",
            metadata_table=self.job_metadata_table,
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=job_no_inst_metadata,
            annotation=annotation,
        )

    def test_merge_handles_no_job_metadata(self):
        """Test graceful handling when job has no metadata table."""
        job_no_metadata = InstrumentJob.objects.create(
            user=self.user,
            instrument=self.instrument,
            lab_group=self.lab_group,
            job_type="analysis",
            job_name="Job with no metadata",
            status="submitted",
            metadata_table=None,
        )

        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column7",
            type="characteristics",
            value="Instrument Value 7",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=job_no_metadata,
            annotation=annotation,
        )

    def test_merge_respects_name_and_type_uniqueness(self):
        """Test that columns are matched by both name AND type."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="temperature",
            type="characteristics",
            value="25C",
        )
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="temperature",
            type="factor value",
            value="37C",
        )

        MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="temperature",
            type="characteristics",
            value="",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        char_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="temperature",
            type="characteristics",
        )
        self.assertEqual(char_col.value, "25C")

        factor_col = MetadataColumn.objects.get(
            metadata_table=self.job_metadata_table,
            name="temperature",
            type="factor value",
        )
        self.assertEqual(factor_col.value, "37C")

    def test_merge_does_not_trigger_on_update(self):
        """Test that merge only happens on creation, not on update."""
        MetadataColumn.objects.create(
            metadata_table=self.instrument_metadata_table,
            name="column8",
            type="characteristics",
            value="Original Instrument Value",
        )

        job_col = MetadataColumn.objects.create(
            metadata_table=self.job_metadata_table,
            name="column8",
            type="characteristics",
            value="",
        )

        annotation = Annotation.objects.create(
            annotation="Booking annotation",
            annotation_type="booking",
            owner=self.user,
        )

        job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.instrument_job,
            annotation=annotation,
        )

        job_col.refresh_from_db()
        self.assertEqual(job_col.value, "Original Instrument Value")

        inst_col = MetadataColumn.objects.get(
            metadata_table=self.instrument_metadata_table,
            name="column8",
        )
        inst_col.value = "Updated Instrument Value"
        inst_col.save()

        job_annotation.order = 999
        job_annotation.save()

        job_col.refresh_from_db()
        self.assertEqual(job_col.value, "Original Instrument Value")
