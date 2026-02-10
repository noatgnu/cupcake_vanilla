"""
Management command to sync builtin schemas from sdrf-pipelines with the database.

Handles migration from legacy schema names to new naming convention:
- minimum -> base
- default -> ms-proteomics
- cell_lines -> cell-lines
- nonvertebrates -> invertebrates
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from ccv.models import Schema

LEGACY_NAME_MAPPING = {
    "minimum": "base",
    "default": "ms-proteomics",
    "cell_lines": "cell-lines",
    "nonvertebrates": "invertebrates",
}


class Command(BaseCommand):
    help = "Synchronize builtin schemas from sdrf-pipelines package with the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update of existing schemas",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--delete-orphans",
            action="store_true",
            help="Delete builtin schemas that no longer exist in sdrf-pipelines",
        )
        parser.add_argument(
            "--migrate-names",
            action="store_true",
            help="Migrate legacy schema names to new naming convention",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting schema synchronization..."))

        dry_run = options["dry_run"]
        migrate_names = options.get("migrate_names", False)
        delete_orphans = options.get("delete_orphans", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        try:
            from sdrf_pipelines.sdrf.schemas import SchemaRegistry

            from ccv.utils import get_all_default_schema_names

            registry = SchemaRegistry()
            builtin_schema_names = get_all_default_schema_names()
            manifest = registry.manifest or {}
            templates_info = manifest.get("templates", {})

            self.stdout.write(f"Found {len(builtin_schema_names)} schemas in sdrf-pipelines:")
            for name in sorted(builtin_schema_names):
                meta = templates_info.get(name, {})
                layer = meta.get("layer", "-")
                usable = meta.get("usable_alone", True)
                status = meta.get("status", "stable")
                self.stdout.write(f"  - {name} (layer={layer}, usable_alone={usable}, status={status})")

            if migrate_names:
                self.stdout.write("\nMigrating legacy schema names...")
                self._migrate_legacy_names(dry_run)

            if dry_run:
                existing_schemas = set(Schema.objects.filter(is_builtin=True).values_list("name", flat=True))

                new_schemas = [name for name in builtin_schema_names if name not in existing_schemas]
                existing_to_update = [name for name in builtin_schema_names if name in existing_schemas]

                if new_schemas:
                    self.stdout.write(f'Would CREATE: {", ".join(new_schemas)}')
                if existing_to_update:
                    self.stdout.write(f'Would UPDATE: {", ".join(existing_to_update)}')

                if delete_orphans:
                    orphans = existing_schemas - set(builtin_schema_names)
                    if orphans:
                        self.stdout.write(f'Would DELETE orphans: {", ".join(orphans)}')

                self.stdout.write(self.style.SUCCESS("Dry run completed."))
                return

            with transaction.atomic():
                result = Schema.sync_builtin_schemas()

                if "error" in result:
                    self.stdout.write(self.style.ERROR(f'Error during sync: {result["error"]}'))
                    return

                created_count = result.get("created", 0)
                updated_count = result.get("updated", 0)

                if created_count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Created {created_count} new schemas"))

                if updated_count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Updated {updated_count} existing schemas"))

                if created_count == 0 and updated_count == 0:
                    self.stdout.write(self.style.SUCCESS("All schemas are already up to date"))

                if delete_orphans:
                    existing_schemas = set(Schema.objects.filter(is_builtin=True).values_list("name", flat=True))
                    orphans = existing_schemas - set(builtin_schema_names)
                    if orphans:
                        deleted_count, _ = Schema.objects.filter(name__in=orphans, is_builtin=True).delete()
                        self.stdout.write(
                            self.style.WARNING(f"Deleted {deleted_count} orphan schema(s): {', '.join(orphans)}")
                        )

                total_schemas = Schema.objects.filter(is_builtin=True, is_active=True).count()
                self.stdout.write(self.style.SUCCESS(f"Total active builtin schemas in database: {total_schemas}"))

                schemas_with_usage = Schema.objects.filter(is_builtin=True, usage_count__gt=0).order_by("-usage_count")

                if schemas_with_usage.exists():
                    self.stdout.write("\nSchema usage statistics:")
                    for schema in schemas_with_usage[:5]:
                        self.stdout.write(f"  {schema.display_name}: {schema.usage_count} uses")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during schema synchronization: {str(e)}"))
            raise

        self.stdout.write(self.style.SUCCESS("Schema synchronization completed successfully!"))

    def _migrate_legacy_names(self, dry_run=False):
        """Migrate legacy schema names to new naming convention."""
        for old_name, new_name in LEGACY_NAME_MAPPING.items():
            schema = Schema.objects.filter(name=old_name, is_builtin=True).first()
            if schema:
                if dry_run:
                    self.stdout.write(f"  Would rename '{old_name}' -> '{new_name}'")
                else:
                    if Schema.objects.filter(name=new_name).exists():
                        Schema.objects.filter(name=new_name).delete()
                    schema.name = new_name
                    schema.display_name = new_name.replace("-", " ").replace("_", " ").title()
                    schema.save()
                    self.stdout.write(self.style.SUCCESS(f"  Renamed '{old_name}' -> '{new_name}'"))
