"""Test cases for the import_mobile_snapshot management command."""

import gzip
import json
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from ccv.models import MetadataColumnTemplate, NCBITaxonomy, Species

RELEASE_JSON = {
    "tag_name": "v0.0.3",
    "assets": [
        {"name": "manifest-v0.0.3.json", "browser_download_url": "https://example.test/manifest-v0.0.3.json"},
        {
            "name": "ontology-species.sqlite.gz",
            "browser_download_url": "https://example.test/ontology-species.sqlite.gz",
        },
        {
            "name": "column-template-system.sqlite.gz",
            "browser_download_url": "https://example.test/column-template-system.sqlite.gz",
        },
        {
            "name": "ontology-ncbi_taxonomy.sqlite.gz",
            "browser_download_url": "https://example.test/ontology-ncbi_taxonomy.sqlite.gz",
        },
    ],
}


def _build_sqlite_gz(table_name, columns, rows):
    tmp_dir = Path(tempfile.mkdtemp())
    sqlite_path = tmp_dir / "table.sqlite"
    conn = sqlite3.connect(sqlite_path)
    try:
        columns_sql = ", ".join(f'"{c}" TEXT' for c in columns)
        conn.execute(f'CREATE TABLE "{table_name}" ({columns_sql})')
        conn.executemany(f'INSERT INTO "{table_name}" VALUES ({", ".join("?" for _ in columns)})', rows)
        conn.commit()
    finally:
        conn.close()
    gz_path = tmp_dir / "table.sqlite.gz"
    with open(sqlite_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        f_out.write(f_in.read())
    return gz_path.read_bytes()


def _mock_requests_get(manifest, asset_bytes_by_url):
    def _get(url, timeout=None, headers=None, stream=None):
        response = MagicMock()
        response.status_code = 200
        if url.endswith("/releases/latest") or "/releases/tags/" in url:
            response.json.return_value = RELEASE_JSON
            return response
        if url == "https://example.test/manifest-v0.0.3.json":
            response.json.return_value = manifest
            response.raise_for_status = MagicMock()
            return response
        if url in asset_bytes_by_url:
            data = asset_bytes_by_url[url]
            response.raise_for_status = MagicMock()
            response.iter_content = MagicMock(return_value=iter([data]))
            return response
        raise AssertionError(f"Unexpected URL requested: {url}")

    return _get


class ImportMobileSnapshotTest(TestCase):
    def setUp(self):
        Species.objects.create(code="STALE", taxon=1, official_name="Stale species", common_name="", synonym="")

    def _run(self, *args):
        out = StringIO()
        call_command("import_mobile_snapshot", *args, stdout=out)
        return out.getvalue()

    def test_ontology_table_import_replaces_existing_rows(self):
        species_gz = _build_sqlite_gz(
            "species",
            ["code", "taxon", "official_name", "common_name", "synonym"],
            [("HUMAN", 9606, "Homo sapiens", "Human", "")],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {"dataset": "ontology", "name": "species", "file": "ontology-species.sqlite.gz", "row_count": 1},
            ],
        }
        mock_get = _mock_requests_get(manifest, {"https://example.test/ontology-species.sqlite.gz": species_gz})

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=mock_get):
            output = self._run("--dataset", "ontology", "--table", "species")

        self.assertIn("imported 1 rows", output)
        self.assertEqual(Species.objects.count(), 1)
        self.assertFalse(Species.objects.filter(code="STALE").exists())
        self.assertTrue(Species.objects.filter(code="HUMAN", taxon=9606).exists())

    def test_column_template_import(self):
        template_gz = _build_sqlite_gz(
            "column_template",
            ["name", "column_name", "column_type", "is_system_template"],
            [("Organism", "organism", "characteristics", 1)],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {
                    "dataset": "column-template",
                    "name": "system",
                    "file": "column-template-system.sqlite.gz",
                    "row_count": 1,
                },
            ],
        }
        mock_get = _mock_requests_get(manifest, {"https://example.test/column-template-system.sqlite.gz": template_gz})

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=mock_get):
            self._run("--dataset", "column-template")

        self.assertTrue(MetadataColumnTemplate.objects.filter(name="Organism", is_system_template=True).exists())

    def test_ontology_table_with_natural_primary_key(self):
        taxonomy_gz = _build_sqlite_gz(
            "ncbi_taxonomy",
            ["tax_id", "scientific_name", "rank"],
            [("9606", "Homo sapiens", "species")],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {
                    "dataset": "ontology",
                    "name": "ncbi_taxonomy",
                    "file": "ontology-ncbi_taxonomy.sqlite.gz",
                    "row_count": 1,
                },
            ],
        }
        mock_get = _mock_requests_get(manifest, {"https://example.test/ontology-ncbi_taxonomy.sqlite.gz": taxonomy_gz})

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=mock_get):
            self._run("--dataset", "ontology", "--table", "ncbi_taxonomy")

        self.assertTrue(NCBITaxonomy.objects.filter(tax_id=9606, scientific_name="Homo sapiens").exists())

    def test_table_requires_ontology_dataset(self):
        with self.assertRaises(CommandError):
            call_command("import_mobile_snapshot", "--dataset", "column-template", "--table", "species")

    def test_an_unknown_type_key_asked_for_by_name_raises(self):
        species_gz = _build_sqlite_gz("species", ["code"], [("HUMAN",)])
        manifest = {
            "format_version": 1,
            "tables": [
                {"dataset": "ontology", "name": "not-a-real-key", "file": "ontology-species.sqlite.gz", "row_count": 1}
            ],
        }
        mock_get = _mock_requests_get(manifest, {"https://example.test/ontology-species.sqlite.gz": species_gz})

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=mock_get):
            with self.assertRaises(CommandError):
                call_command("import_mobile_snapshot", "--dataset", "ontology", "--table", "not-a-real-key")

    def test_tables_a_newer_snapshot_adds_are_skipped_and_the_rest_imported(self):
        species_gz = _build_sqlite_gz(
            "species",
            ["code", "taxon", "official_name", "common_name", "synonym"],
            [("HUMAN", 9606, "Homo sapiens", "Human", "")],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {"dataset": "ontology", "name": "a_newer_ontology", "file": "ontology-newer.sqlite.gz", "row_count": 9},
                {"dataset": "ontology", "name": "species", "file": "ontology-species.sqlite.gz", "row_count": 1},
                {"dataset": "a-newer-dataset", "name": "things", "file": "things.sqlite.gz", "row_count": 3},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "manifest-v0.0.3.json").write_text(json.dumps(manifest))
            Path(folder, "ontology-species.sqlite.gz").write_bytes(species_gz)
            output = self._run("--dataset", "all", "--source-dir", folder)

        self.assertIn("ontology/a_newer_ontology: skipped; this backend does not know this table", output)
        self.assertIn("ontology/species: imported 1 rows", output)
        self.assertTrue(Species.objects.filter(code="HUMAN", taxon=9606).exists())

    def test_release_fetch_failure_raises(self):
        def _get(url, timeout=None, headers=None, stream=None):
            response = MagicMock()
            response.status_code = 404
            return response

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=_get):
            with self.assertRaises(CommandError):
                call_command("import_mobile_snapshot", "--dataset", "ontology")

    def test_import_from_a_local_snapshot_folder(self):
        species_gz = _build_sqlite_gz(
            "species",
            ["code", "taxon", "official_name", "common_name", "synonym"],
            [("HUMAN", 9606, "Homo sapiens", "Human", "")],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {"dataset": "ontology", "name": "species", "file": "ontology-species.sqlite.gz", "row_count": 1},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "manifest-v0.0.3.json").write_text(json.dumps(manifest))
            Path(folder, "ontology-species.sqlite.gz").write_bytes(species_gz)
            with patch("ccv.management.commands.import_mobile_snapshot.requests.get") as mock_get:
                output = self._run("--dataset", "ontology", "--source-dir", folder)
            mock_get.assert_not_called()

        self.assertIn("imported 1 rows", output)
        self.assertFalse(Species.objects.filter(code="STALE").exists())
        self.assertTrue(Species.objects.filter(code="HUMAN", taxon=9606).exists())

    def test_local_snapshot_folder_without_manifest_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CommandError):
                call_command("import_mobile_snapshot", "--source-dir", folder)

    def test_local_snapshot_file_outside_the_folder_is_refused(self):
        manifest = {
            "format_version": 1,
            "tables": [{"dataset": "ontology", "name": "species", "file": "../species.sqlite.gz", "row_count": 1}],
        }
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(CommandError):
                call_command("import_mobile_snapshot", "--source-dir", folder)

    def test_source_dir_and_release_tag_together_raise(self):
        with self.assertRaises(CommandError):
            call_command("import_mobile_snapshot", "--source-dir", "/tmp", "--release-tag", "v0.0.3")


class GentleImportTest(TestCase):
    def test_batches_and_pauses_can_be_set_for_a_small_server(self):
        species_gz = _build_sqlite_gz(
            "species",
            ["code", "taxon", "official_name", "common_name", "synonym"],
            [(f"S{i}", i, f"Species {i}", "", "") for i in range(5)],
        )
        manifest = {
            "format_version": 1,
            "tables": [
                {"dataset": "ontology", "name": "species", "file": "ontology-species.sqlite.gz", "row_count": 5}
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "manifest-v0.0.3.json").write_text(json.dumps(manifest))
            Path(folder, "ontology-species.sqlite.gz").write_bytes(species_gz)
            with patch("ccv.management.commands.import_mobile_snapshot.time.sleep") as sleep:
                out = StringIO()
                call_command(
                    "import_mobile_snapshot", "--source-dir", folder, "--batch-size", "2", "--pause", "0.2", stdout=out
                )
        self.assertIn("ontology/species: imported 5 rows", out.getvalue())
        self.assertEqual(Species.objects.count(), 5)
        self.assertEqual(sleep.call_args_list, [call(0.2)] * 3)
