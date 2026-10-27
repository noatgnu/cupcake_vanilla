"""
Round-trip tests for Excel export and import of tables that hold several columns with the same
name, as SDRF files commonly do (e.g. repeated comment[modification parameters]).
"""

from django.contrib.auth.models import User
from django.test import TestCase

from ccc.models import LabGroup
from ccv.models import MetadataColumn, MetadataTable
from ccv.tasks.export_utils import export_excel_template_data
from ccv.tasks.import_utils import import_excel_data

MODIFICATION = "comment[modification parameters]"
MODIFICATION_VALUES = [
    "NT=Oxidation;MT=Variable;TA=M;AC=UNIMOD:35",
    "NT=Carbamidomethyl;MT=Fixed;TA=C;AC=UNIMOD:4",
    "NT=Acetyl;MT=Variable;PP=Protein N-term;AC=UNIMOD:1",
]


class ExcelDuplicateColumnRoundTripTest(TestCase):
    """An exported workbook imported back must leave a table with duplicate column names unchanged."""

    def setUp(self):
        self.user = User.objects.create_user(username="dupuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Dup Lab", creator=self.user)
        self.lab_group.members.add(self.user)
        self.table = MetadataTable.objects.create(
            name="Duplicate Columns",
            owner=self.user,
            lab_group=self.lab_group,
            sample_count=2,
        )
        MetadataColumn.objects.create(
            metadata_table=self.table,
            name="source name",
            type="source_name",
            column_position=0,
            value="sample",
        )
        for offset, value in enumerate(MODIFICATION_VALUES, start=1):
            MetadataColumn.objects.create(
                metadata_table=self.table,
                name=MODIFICATION,
                type="comment",
                column_position=offset,
                value=value,
            )

    def _modification_values(self):
        return list(
            self.table.columns.filter(name=MODIFICATION).order_by("column_position").values_list("value", flat=True)
        )

    def _round_trip(self):
        export_result = export_excel_template_data(self.table, self.user)
        self.assertTrue(export_result.get("success"), export_result.get("error"))
        import_result = import_excel_data(
            file_data=export_result["file_data"],
            metadata_table=self.table,
            user=self.user,
            validate_ontologies=False,
        )
        self.assertTrue(import_result.get("success"), import_result.get("error"))
        return import_result

    def test_round_trip_keeps_every_duplicate_column(self):
        column_ids = set(self.table.columns.values_list("id", flat=True))

        self._round_trip()

        self.assertEqual(self.table.columns.filter(name=MODIFICATION).count(), len(MODIFICATION_VALUES))
        self.assertEqual(set(self.table.columns.values_list("id", flat=True)), column_ids)

    def test_round_trip_keeps_each_duplicate_column_value(self):
        self._round_trip()

        self.assertEqual(self._modification_values(), MODIFICATION_VALUES)

    def test_round_trip_reports_updates_not_creations(self):
        result = self._round_trip()

        self.assertEqual(result.get("columns_created"), 0)
        self.assertEqual(result.get("columns_updated"), len(MODIFICATION_VALUES) + 1)

    def test_replacing_import_recreates_every_duplicate_column(self):
        export_result = export_excel_template_data(self.table, self.user)
        self.assertTrue(export_result.get("success"), export_result.get("error"))

        result = import_excel_data(
            file_data=export_result["file_data"],
            metadata_table=self.table,
            user=self.user,
            replace_existing=True,
            validate_ontologies=False,
        )

        self.assertTrue(result.get("success"), result.get("error"))
        self.assertEqual(self._modification_values(), MODIFICATION_VALUES)

    def test_import_into_another_table_recreates_every_duplicate_column(self):
        export_result = export_excel_template_data(self.table, self.user)
        self.assertTrue(export_result.get("success"), export_result.get("error"))
        target = MetadataTable.objects.create(name="Target", owner=self.user, lab_group=self.lab_group, sample_count=2)

        result = import_excel_data(
            file_data=export_result["file_data"],
            metadata_table=target,
            user=self.user,
            validate_ontologies=False,
        )

        self.assertTrue(result.get("success"), result.get("error"))
        values = list(
            target.columns.filter(name=MODIFICATION).order_by("column_position").values_list("value", flat=True)
        )
        self.assertEqual(values, MODIFICATION_VALUES)


class ExcelBlankColumnTypeRoundTripTest(TestCase):
    """A column with an empty type is exported as a blank cell and must still match on import."""

    def setUp(self):
        self.user = User.objects.create_user(username="blankuser", password="testpass")
        self.table = MetadataTable.objects.create(name="Blank Type", owner=self.user, sample_count=1)
        self.column = MetadataColumn.objects.create(
            metadata_table=self.table, name="assay name", type="", column_position=0, value="run 1"
        )

    def test_round_trip_updates_the_untyped_column(self):
        export_result = export_excel_template_data(self.table, self.user)
        self.assertTrue(export_result.get("success"), export_result.get("error"))

        result = import_excel_data(
            file_data=export_result["file_data"],
            metadata_table=self.table,
            user=self.user,
            validate_ontologies=False,
        )

        self.assertTrue(result.get("success"), result.get("error"))
        self.assertEqual(list(self.table.columns.values_list("id", flat=True)), [self.column.id])
        self.column.refresh_from_db()
        self.assertEqual(self.column.value, "run 1")
