"""
Management command to clean up old temporary export files.

Usage:
    python manage.py cleanup_export_temps [--max-age HOURS]
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Clean up old temporary export files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age",
            type=int,
            default=24,
            help="Maximum age of temporary files in hours (default: 24)",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        max_age_hours = options["max_age"]
        dry_run = options["dry_run"]

        media_root = Path(settings.MEDIA_ROOT)
        temp_exports_dir = media_root / "temp" / "exports"

        if not temp_exports_dir.exists():
            self.stdout.write(self.style.SUCCESS("No temporary exports directory found. Nothing to clean up."))
            return

        cutoff_time = time.time() - (max_age_hours * 3600)
        deleted_count = 0
        total_size = 0

        self.stdout.write(f"Scanning for files older than {max_age_hours} hours...")

        for file_path in temp_exports_dir.glob("*.html"):
            file_stat = file_path.stat()
            file_age_hours = (time.time() - file_stat.st_mtime) / 3600

            if file_stat.st_mtime < cutoff_time:
                file_size = file_stat.st_size
                total_size += file_size

                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would delete: {file_path.name} "
                        f"(age: {file_age_hours:.1f}h, size: {file_size / 1024:.1f}KB)"
                    )
                else:
                    try:
                        file_path.unlink()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Deleted: {file_path.name} "
                                f"(age: {file_age_hours:.1f}h, size: {file_size / 1024:.1f}KB)"
                            )
                        )
                        deleted_count += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Failed to delete {file_path.name}: {e}"))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY RUN] Would delete {deleted_count} files, " f"freeing {total_size / 1024 / 1024:.2f}MB"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCleaned up {deleted_count} temporary export files, " f"freed {total_size / 1024 / 1024:.2f}MB"
                )
            )
