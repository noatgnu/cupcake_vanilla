"""
Management command to export ontology tables, builtin SDRF schemas, and system
column templates as gzipped SQLite files for offline import by the mobile apps.

Each dataset is written as a standalone SQLite file (one table inside, named
after the dataset) plus a row in a shared manifest.json with row counts and
file sizes, so a client can decide what to download before fetching anything.
"""

import gzip
import json
import shutil
import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ccv.models import MetadataColumnTemplate, Schema
from ccv.ontology_registry import registry

SCALAR_INTERNAL_TYPES = {
    "AutoField": "INTEGER",
    "BigAutoField": "INTEGER",
    "IntegerField": "INTEGER",
    "PositiveIntegerField": "INTEGER",
    "PositiveSmallIntegerField": "INTEGER",
    "SmallIntegerField": "INTEGER",
    "BooleanField": "INTEGER",
    "FloatField": "REAL",
    "CharField": "TEXT",
    "TextField": "TEXT",
    "JSONField": "TEXT",
    "DateTimeField": "TEXT",
    "DateField": "TEXT",
}


def _scalar_fields(model):
    """Return the model's own fields that map to a plain SQLite column type."""
    return [f for f in model._meta.fields if f.get_internal_type() in SCALAR_INTERNAL_TYPES]


def _serialize(field, value):
    if value is None:
        return None
    internal = field.get_internal_type()
    if internal == "BooleanField":
        return 1 if value else 0
    if internal == "JSONField":
        return json.dumps(value)
    if internal in ("DateTimeField", "DateField"):
        return value.isoformat()
    return value


def _dump_queryset(queryset, table_name, sqlite_path):
    """Write every row of queryset's scalar fields into a fresh SQLite file."""
    model = queryset.model
    fields = _scalar_fields(model)

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_path.unlink(missing_ok=True)

    conn = sqlite3.connect(sqlite_path)
    try:
        columns_sql = ", ".join(f'"{f.column}" {SCALAR_INTERNAL_TYPES[f.get_internal_type()]}' for f in fields)
        conn.execute(f'CREATE TABLE "{table_name}" ({columns_sql})')
        insert_sql = f'INSERT INTO "{table_name}" VALUES ({", ".join("?" for _ in fields)})'

        row_count = 0
        batch = []
        for obj in queryset.iterator(chunk_size=2000):
            batch.append(tuple(_serialize(f, getattr(obj, f.attname)) for f in fields))
            row_count += 1
            if len(batch) >= 2000:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
        conn.commit()
    finally:
        conn.close()

    return row_count


def _dump_schemas(sqlite_path):
    """
    Dump builtin, active SDRF schemas as portable JSON.

    Schema.schema_file actually stores a pickled sdrf_pipelines
    SchemaDefinition (pydantic model), not YAML text despite the field's
    help_text - unpickle it (the backend's own trusted data) and re-serialize
    with model_dump_json() so the column definitions are plain JSON a mobile
    client can parse without any Python-specific deserialization.
    """
    import pickle

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_path.unlink(missing_ok=True)

    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            """
            CREATE TABLE "schema" (
                name TEXT, display_name TEXT, description TEXT, version TEXT,
                extends TEXT, usable_alone INTEGER, layer TEXT, requires TEXT,
                excludes TEXT, tags TEXT, columns_json TEXT
            )
            """
        )
        row_count = 0
        for schema in Schema.objects.filter(is_builtin=True, is_active=True).iterator():
            schema.schema_file.seek(0)
            schema_definition = pickle.loads(schema.schema_file.read())
            columns_json = schema_definition.model_dump_json()
            conn.execute(
                'INSERT INTO "schema" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    schema.name,
                    schema.display_name,
                    schema.description,
                    schema.version,
                    schema.extends,
                    1 if schema.usable_alone else 0,
                    schema.layer,
                    json.dumps(schema.requires),
                    json.dumps(schema.excludes),
                    json.dumps(schema.tags),
                    columns_json,
                ),
            )
            row_count += 1
        conn.commit()
    finally:
        conn.close()

    return row_count


def _gzip_file(sqlite_path):
    gz_path = sqlite_path.with_suffix(sqlite_path.suffix + ".gz")
    with open(sqlite_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    return gz_path


class Command(BaseCommand):
    help = "Export ontology tables, builtin SDRF schemas, and system column templates for mobile offline import"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            choices=["ontology", "schema", "column-template", "all"],
            default="all",
            help="Which dataset to export (default: all)",
        )
        parser.add_argument(
            "--table",
            help="Restrict --dataset ontology to a single ontology type_key (e.g. species)",
        )
        parser.add_argument(
            "--output-dir",
            default="mobile-snapshot",
            help="Directory to write <name>.sqlite.gz files and manifest.json into",
        )

    def handle(self, *args, **options):
        dataset = options["dataset"]
        table = options.get("table")
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        if table and dataset != "ontology":
            raise CommandError("--table is only valid with --dataset ontology")

        manifest = []

        if dataset in ("ontology", "all"):
            type_keys = [table] if table else [key for key, _ in registry.choices()]
            for type_key in type_keys:
                model = registry.get_model(type_key)
                if model is None:
                    raise CommandError(f"Unknown ontology type_key: {type_key}")
                sqlite_path = output_dir / f"ontology-{type_key}.sqlite"
                row_count = _dump_queryset(model.objects.all(), type_key, sqlite_path)
                manifest.append(self._manifest_entry("ontology", type_key, sqlite_path, row_count))

        if dataset in ("schema", "all"):
            sqlite_path = output_dir / "schema-sdrf.sqlite"
            row_count = _dump_schemas(sqlite_path)
            manifest.append(self._manifest_entry("schema", "sdrf", sqlite_path, row_count))

        if dataset in ("column-template", "all"):
            sqlite_path = output_dir / "column-template-system.sqlite"
            queryset = MetadataColumnTemplate.objects.filter(is_system_template=True)
            row_count = _dump_queryset(queryset, "column_template", sqlite_path)
            manifest.append(self._manifest_entry("column-template", "system", sqlite_path, row_count))

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps({"format_version": 1, "tables": manifest}, indent=2))

        self.stdout.write(self.style.SUCCESS(f"Exported {len(manifest)} table(s) to {output_dir}/"))
        for entry in manifest:
            self.stdout.write(
                f"  {entry['name']}: {entry['row_count']} rows, "
                f"{entry['uncompressed_bytes']} -> {entry['compressed_bytes']} bytes"
            )

    def _manifest_entry(self, dataset, name, sqlite_path, row_count):
        uncompressed_bytes = sqlite_path.stat().st_size
        gz_path = _gzip_file(sqlite_path)
        compressed_bytes = gz_path.stat().st_size
        sqlite_path.unlink()
        return {
            "dataset": dataset,
            "name": name,
            "file": gz_path.name,
            "row_count": row_count,
            "uncompressed_bytes": uncompressed_bytes,
            "compressed_bytes": compressed_bytes,
        }
