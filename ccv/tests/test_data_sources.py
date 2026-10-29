"""
Tests for recording the upstream release of loaded reference data and exporting it in the
mobile snapshot manifest.
"""

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase

from ccv.data_sources import (
    last_modified_release,
    obo_release,
    ols_release,
    record_source,
    sdrf_pipelines_version,
    source_entry,
    uniprot_release,
)
from ccv.models import DataSourceVersion


class OboReleaseTests(TestCase):
    def test_dated_release_path(self):
        header = "format-version: 1.2\ndata-version: releases/2026-10-06\n\n[Term]\nid: MONDO:0000001\n"
        self.assertEqual(obo_release(header), ("2026-10-06", date(2026, 10, 6)))

    def test_release_path_with_file_name_and_date_header(self):
        header = "format-version: 1.2\ndata-version: releases/2026-09-30/doid.obo\ndate: 30:09:2026 11:23\n"
        self.assertEqual(obo_release(header), ("2026-09-30", date(2026, 9, 30)))

    def test_dated_release_wins_over_earlier_edit_date(self):
        header = "format-version: 1.2\ndata-version: releases/2021-10-26\ndate: 23:10:2021 16:56\n"
        self.assertEqual(obo_release(header), ("2021-10-26", date(2021, 10, 26)))

    def test_numbered_release_keeps_number_and_uses_date_header(self):
        header = "format-version: 1.2\ndata-version: 256\ndate: 06:10:2026 11:26\n"
        self.assertEqual(obo_release(header), ("256", date(2026, 10, 6)))

    def test_semantic_version(self):
        header = b"format-version: 1.2\ndata-version: 4.2.12\ndate: 26:10:2026 12:00\n"
        self.assertEqual(obo_release(header), ("4.2.12", date(2026, 10, 26)))

    def test_date_only_header_becomes_the_version(self):
        header = "format-version: 1.4\ndate: 17:02:2026 11:36\n"
        self.assertEqual(obo_release(header), ("2026-02-17", date(2026, 2, 17)))

    def test_header_ends_at_first_stanza(self):
        content = "format-version: 1.2\n\n[Term]\nid: X:1\ndata-version: 9.9\n"
        self.assertEqual(obo_release(content), ("", None))


class OtherReleaseFormatTests(TestCase):
    def test_uniprot_release_line(self):
        content = "-----\nRelease:     2026_03 of 02-Sep-2026\n-----\n"
        self.assertEqual(uniprot_release(content), ("2026_03", date(2026, 9, 2)))

    def test_uniprot_without_release_line(self):
        self.assertEqual(uniprot_release("no header here"), ("", None))

    def test_last_modified_header(self):
        response = MagicMock(headers={"Last-Modified": "Thu, 29 Oct 2026 12:29:23 GMT"})
        self.assertEqual(last_modified_release(response), ("2026-10-29", date(2026, 10, 29)))

    def test_missing_last_modified_header(self):
        self.assertEqual(last_modified_release(MagicMock(headers={})), ("", None))

    @patch("ccv.data_sources.requests.get")
    def test_ols_release_prefers_declared_version(self, mock_get):
        mock_get.return_value.json.return_value = {
            "config": {"version": "3.95.0", "versionIri": "http://www.ebi.ac.uk/efo/releases/v3.95.0/efo.owl"}
        }
        self.assertEqual(ols_release("efo"), ("3.95.0", None))

    @patch("ccv.data_sources.requests.get")
    def test_ols_release_from_dated_version_iri(self, mock_get):
        mock_get.return_value.json.return_value = {
            "config": {
                "version": None,
                "versionIri": "http://purl.obolibrary.org/obo/pride/releases/2026-10-26/pride.owl",
            }
        }
        self.assertEqual(ols_release("pride"), ("2026-10-26", date(2026, 10, 26)))

    @patch("ccv.data_sources.requests.get")
    def test_ols_release_from_numbered_version_iri(self, mock_get):
        mock_get.return_value.json.return_value = {
            "config": {"version": None, "versionIri": "http://purl.obolibrary.org/obo/ms/4.2.12/ms.owl"}
        }
        self.assertEqual(ols_release("ms"), ("4.2.12", None))

    def test_sdrf_pipelines_version_is_installed_version(self):
        self.assertRegex(sdrf_pipelines_version(), r"^\d+\.\d+")


class RecordSourceTests(TestCase):
    def test_record_replaces_earlier_release(self):
        record_source("ontology:mondo", "http://example.org/mondo.obo", "2026-01-01", date(2026, 1, 1))
        record_source("ontology:mondo", "http://example.org/mondo.obo", "2026-10-06", date(2026, 10, 6))

        self.assertEqual(DataSourceVersion.objects.filter(key="ontology:mondo").count(), 1)
        entry = source_entry("ontology:mondo")
        self.assertEqual(entry["version"], "2026-10-06")
        self.assertEqual(entry["released"], "2026-10-06")
        self.assertEqual(entry["url"], "http://example.org/mondo.obo")
        self.assertTrue(entry["retrieved_at"])

    def test_unrecorded_source(self):
        self.assertIsNone(source_entry("ontology:unknown"))


class LoaderRecordsSourceTests(TestCase):
    def test_species_loader_records_release_of_local_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("Release:     2026_03 of 02-Sep-2026\n")
            path = handle.name
        self.addCleanup(Path(path).unlink)

        call_command("load_species", path, stdout=MagicMock())

        record = DataSourceVersion.objects.get(key="ontology:species")
        self.assertEqual(record.version, "2026_03")
        self.assertEqual(record.released, date(2026, 9, 2))
        self.assertEqual(record.source_url, path)


class ManifestSourceTests(TestCase):
    def test_manifest_lists_source_release_and_sdrf_pipelines_version(self):
        record_source("ontology:mondo", "http://purl.obolibrary.org/obo/mondo.obo", "2026-10-06", date(2026, 10, 6))

        with tempfile.TemporaryDirectory() as output_dir:
            call_command(
                "export_mobile_snapshot",
                dataset="ontology",
                table="mondo",
                output_dir=output_dir,
                stdout=MagicMock(),
            )
            call_command(
                "export_mobile_snapshot", dataset="schema", output_dir=output_dir + "/schema", stdout=MagicMock()
            )
            manifest = json.loads((Path(output_dir) / "manifest.json").read_text())
            schema_manifest = json.loads((Path(output_dir) / "schema" / "manifest.json").read_text())

        self.assertEqual(manifest["sdrf_pipelines_version"], sdrf_pipelines_version())
        mondo = manifest["tables"][0]
        self.assertEqual(mondo["source"]["version"], "2026-10-06")
        self.assertEqual(mondo["source"]["released"], "2026-10-06")
        self.assertIsNone(schema_manifest["tables"][0]["source"])
