"""Test cases for the export_mobile_snapshot management command."""

import gzip
import json
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from ccv.models import MetadataColumnTemplate, Schema, Species


class ExportMobileSnapshotTest(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Species.objects.create(
            code="HUMAN",
            taxon=9606,
            official_name="Homo sapiens",
            common_name="Human",
            synonym="",
        )
        MetadataColumnTemplate.objects.create(
            name="Organism",
            column_name="organism",
            column_type="characteristics",
            is_system_template=True,
        )
        MetadataColumnTemplate.objects.create(
            name="Private template",
            column_name="custom",
            column_type="characteristics",
            is_system_template=False,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("export_mobile_snapshot", *args, "--output-dir", self.tmpdir, stdout=out)
        return out.getvalue()

    def _read_manifest(self):
        return json.loads((Path(self.tmpdir) / "manifest.json").read_text())

    def _read_sqlite_table(self, filename, table_name):
        sqlite_path = Path(self.tmpdir) / "tmp.sqlite"
        with gzip.open(Path(self.tmpdir) / filename, "rb") as f_in, open(sqlite_path, "wb") as f_out:
            f_out.write(f_in.read())
        conn = sqlite3.connect(sqlite_path)
        try:
            return conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
        finally:
            conn.close()
            sqlite_path.unlink()

    def test_ontology_table_export(self):
        self._run("--dataset", "ontology", "--table", "species")
        manifest = self._read_manifest()
        entry = manifest["tables"][0]
        self.assertEqual(entry["dataset"], "ontology")
        self.assertEqual(entry["name"], "species")
        self.assertEqual(entry["row_count"], 1)
        self.assertTrue((Path(self.tmpdir) / entry["file"]).exists())

        rows = self._read_sqlite_table(entry["file"], "species")
        self.assertEqual(len(rows), 1)

    def test_ontology_unknown_table_raises(self):
        with self.assertRaises(Exception):
            self._run("--dataset", "ontology", "--table", "not-a-real-table")

    def test_table_flag_requires_ontology_dataset(self):
        with self.assertRaises(Exception):
            self._run("--dataset", "schema", "--table", "species")

    def test_column_template_export_excludes_private_templates(self):
        self._run("--dataset", "column-template")
        manifest = self._read_manifest()
        entry = manifest["tables"][0]
        self.assertEqual(entry["dataset"], "column-template")
        self.assertEqual(entry["row_count"], 1)

        rows = self._read_sqlite_table(entry["file"], "column_template")
        self.assertEqual(len(rows), 1)

    def test_schema_export_includes_builtin_column_definitions(self):
        Schema.sync_builtin_schemas()
        self.assertTrue(Schema.objects.filter(is_builtin=True).exists())

        self._run("--dataset", "schema")
        manifest = self._read_manifest()
        entry = manifest["tables"][0]
        self.assertEqual(entry["dataset"], "schema")
        self.assertEqual(entry["row_count"], Schema.objects.filter(is_builtin=True, is_active=True).count())

        rows = self._read_sqlite_table(entry["file"], "schema")
        self.assertGreater(len(rows), 0)
        columns_json_index = 10
        for row in rows:
            parsed = json.loads(row[columns_json_index])
            self.assertIn("columns", parsed)
            self.assertGreater(len(parsed["columns"]), 0)
            self.assertIn("name", parsed["columns"][0])

    def test_all_dataset_produces_manifest_for_every_table(self):
        self._run("--dataset", "all")
        manifest = self._read_manifest()
        self.assertEqual(manifest["format_version"], 1)
        names = {entry["name"] for entry in manifest["tables"]}
        self.assertIn("species", names)
        self.assertIn("sdrf", names)
        self.assertIn("system", names)
        self.assertEqual(len(manifest["tables"]), 14 + 2)
