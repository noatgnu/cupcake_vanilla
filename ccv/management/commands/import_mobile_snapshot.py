"""
Management command to import ontology tables and system column templates from a
cupcake-webgui GitHub Release's mobile snapshot artifacts.

Counterpart to export_mobile_snapshot: fetches the release's manifest-*.json plus the
requested <name>.sqlite.gz assets and bulk-loads them, replacing whatever rows already
exist for that model. This is meant as a fast, version-pinned alternative to load_ontologies
et al for populating a fresh instance's reference tables from a known-good pre-baked snapshot
(large ontologies like NCBI taxonomy can OOM a live scrape-and-parse in a memory-constrained
container; importing a pre-built SQLite dump is a plain bulk insert instead).

Only scalar fields are exported/imported (see export_mobile_snapshot's SCALAR_INTERNAL_TYPES),
so relational fields (e.g. CellOntology.parent_terms) are not populated by this path — use
load_ontologies if full hierarchical relationships are required.

SDRF schema import (--dataset schema) is intentionally not implemented: Schema.schema_file
stores a pickled sdrf-pipelines SchemaDefinition object, and reconstructing one from the
exported columns_json would require pinning to that package's exact internal class shape.
sync_schemas is already fast and local, so there's no OOM-avoidance reason to route schema
loading through this command anyway.
"""

import gzip
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

import requests

from ccv.management.commands.export_mobile_snapshot import _scalar_fields
from ccv.models import MetadataColumnTemplate
from ccv.ontology_registry import registry

GITHUB_RELEASES_API = "https://api.github.com/repos/noatgnu/cupcake-webgui/releases"


def _deserialize(field, value):
    if value is None:
        return None
    internal = field.get_internal_type()
    if internal == "BooleanField":
        return bool(value)
    if internal == "JSONField":
        return json.loads(value)
    if internal == "DateTimeField":
        return parse_datetime(value)
    return value


class Command(BaseCommand):
    help = "Import ontology tables and system column templates from a cupcake-webgui GitHub Release snapshot"

    def add_arguments(self, parser):
        parser.add_argument("--dataset", choices=["ontology", "column-template", "all"], default="all")
        parser.add_argument("--table", help="Restrict --dataset ontology to a single type_key")
        parser.add_argument("--release-tag", default=None, help="GitHub release tag to pull from (default: latest)")

    def handle(self, *args, **options):
        dataset = options["dataset"]
        table = options.get("table")
        release_tag = options.get("release_tag")

        if table and dataset not in ("ontology", "all"):
            raise CommandError("--table is only valid with --dataset ontology (or all)")

        release = self._fetch_release(release_tag)
        manifest = self._fetch_manifest(release)

        entries = [e for e in manifest["tables"] if e["dataset"] in ("ontology", "column-template")]
        if dataset != "all":
            entries = [e for e in entries if e["dataset"] == dataset]
        if table:
            entries = [e for e in entries if e["name"] == table]
        if not entries:
            raise CommandError("No matching entries in manifest for the requested dataset/table")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for entry in entries:
                sqlite_path = self._download(release, entry["file"], tmp_path)
                row_count = self._import_entry(entry, sqlite_path)
                self.stdout.write(self.style.SUCCESS(f"{entry['dataset']}/{entry['name']}: imported {row_count} rows"))

    def _fetch_release(self, release_tag):
        url = f"{GITHUB_RELEASES_API}/tags/{release_tag}" if release_tag else f"{GITHUB_RELEASES_API}/latest"
        response = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github+json"})
        if response.status_code != 200:
            raise CommandError(f"Failed to fetch release metadata from {url}: HTTP {response.status_code}")
        return response.json()

    def _fetch_manifest(self, release):
        candidates = [
            a for a in release.get("assets", []) if a["name"].startswith("manifest") and a["name"].endswith(".json")
        ]
        if not candidates:
            raise CommandError(f"No manifest*.json asset found in release {release.get('tag_name')}")
        response = requests.get(candidates[0]["browser_download_url"], timeout=30)
        response.raise_for_status()
        return response.json()

    def _download(self, release, filename, tmp_path):
        asset = next((a for a in release.get("assets", []) if a["name"] == filename), None)
        if asset is None:
            raise CommandError(f"Asset {filename} not found in release {release.get('tag_name')}")
        gz_path = tmp_path / filename
        response = requests.get(asset["browser_download_url"], timeout=180, stream=True)
        response.raise_for_status()
        with open(gz_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        sqlite_path = gz_path.with_suffix("")
        with gzip.open(gz_path, "rb") as f_in, open(sqlite_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        return sqlite_path

    def _import_entry(self, entry, sqlite_path):
        if entry["dataset"] == "ontology":
            model = registry.get_model(entry["name"])
            if model is None:
                raise CommandError(f"Unknown ontology type_key: {entry['name']}")
            return self._import_scalar_table(model, entry["name"], sqlite_path)
        if entry["dataset"] == "column-template":
            return self._import_scalar_table(MetadataColumnTemplate, "column_template", sqlite_path)
        raise CommandError(f"Unsupported dataset for import: {entry['dataset']}")

    def _import_scalar_table(self, model, sqlite_table, sqlite_path, batch_size=2000):
        """Stream rows from the sqlite table in batches rather than materializing the whole
        table as model instances at once -- ncbi_taxonomy alone is ~2.9M rows, so building
        every instance in memory before a single bulk_create would risk the exact kind of OOM
        this command exists to avoid.
        """
        # Drop only auto-generated surrogate PKs; natural PKs (e.g. NCBITaxonomy.tax_id) must be kept.
        fields = [
            f
            for f in _scalar_fields(model)
            if not (f.primary_key and f.get_internal_type() in ("AutoField", "BigAutoField"))
        ]

        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(f'SELECT * FROM "{sqlite_table}"')
            usable_fields = None
            total = 0

            with transaction.atomic():
                model.objects.all().delete()

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    if usable_fields is None:
                        exported_columns = set(rows[0].keys())
                        usable_fields = [f for f in fields if f.column in exported_columns]
                    batch = [
                        model(**{f.attname: _deserialize(f, row[f.column]) for f in usable_fields}) for row in rows
                    ]
                    model.objects.bulk_create(batch, batch_size=batch_size)
                    total += len(batch)
        finally:
            conn.close()

        return total
