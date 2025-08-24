"""
Management command to sync builtin schemas from sdrf-pipelines with the database.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from ccv.models import Schema


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

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting schema synchronization..."))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        try:
            # Get available schemas from sdrf-pipelines
            from ccv.utils import get_all_default_schema_names

            builtin_schema_names = get_all_default_schema_names()

            self.stdout.write(f'Found {len(builtin_schema_names)} builtin schemas: {", ".join(builtin_schema_names)}')

            if options["dry_run"]:
                # Show what would be created/updated
                existing_schemas = set(Schema.objects.filter(is_builtin=True).values_list("name", flat=True))

                new_schemas = [name for name in builtin_schema_names if name not in existing_schemas]
                existing_to_update = [name for name in builtin_schema_names if name in existing_schemas]

                if new_schemas:
                    self.stdout.write(f'Would CREATE: {", ".join(new_schemas)}')
                if existing_to_update:
                    self.stdout.write(f'Would UPDATE: {", ".join(existing_to_update)}')

                self.stdout.write(self.style.SUCCESS("Dry run completed. Use --force to apply changes."))
                return

            # Perform the actual sync
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

                # Show final stats
                total_schemas = Schema.objects.filter(is_builtin=True, is_active=True).count()
                self.stdout.write(self.style.SUCCESS(f"Total active builtin schemas in database: {total_schemas}"))

                # Show usage stats
                schemas_with_usage = Schema.objects.filter(is_builtin=True, usage_count__gt=0).order_by("-usage_count")

                if schemas_with_usage.exists():
                    self.stdout.write("\nSchema usage statistics:")
                    for schema in schemas_with_usage[:5]:  # Top 5 most used
                        self.stdout.write(f"  {schema.display_name}: {schema.usage_count} uses")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during schema synchronization: {str(e)}"))
            raise

        self.stdout.write(self.style.SUCCESS("Schema synchronization completed successfully!"))
