"""Test cases for the import_mobile_snapshot management command."""

import gzip
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from ccv.models import MetadataColumnTemplate, Species

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

    def test_table_requires_ontology_dataset(self):
        with self.assertRaises(CommandError):
            call_command("import_mobile_snapshot", "--dataset", "column-template", "--table", "species")

    def test_unknown_type_key_raises(self):
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
                call_command("import_mobile_snapshot", "--dataset", "ontology")

    def test_release_fetch_failure_raises(self):
        def _get(url, timeout=None, headers=None, stream=None):
            response = MagicMock()
            response.status_code = 404
            return response

        with patch("ccv.management.commands.import_mobile_snapshot.requests.get", side_effect=_get):
            with self.assertRaises(CommandError):
                call_command("import_mobile_snapshot", "--dataset", "ontology")
