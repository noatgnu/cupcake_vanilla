"""
Management command to clean up expired Excel launch codes.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from ccv.models import ExcelLaunchCode


class Command(BaseCommand):
    help = "Clean up expired Excel launch codes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting anything",
        )

    def handle(self, *args, **options):
        expired_codes = ExcelLaunchCode.objects.filter(expires_at__lt=timezone.now())
        expired_count = expired_codes.count()

        if expired_count == 0:
            self.stdout.write(self.style.SUCCESS("No expired launch codes found."))
            return

        if options["dry_run"]:
            self.stdout.write(f"\nDry run - would delete {expired_count} expired launch codes:")
            for code in expired_codes[:10]:
                status = "claimed" if code.claimed_at else "unclaimed"
                self.stdout.write(f"  - {code.code} for table '{code.table.name}' ({status})")
            if expired_count > 10:
                self.stdout.write(f"  ... and {expired_count - 10} more")
            return

        deleted_count, _ = expired_codes.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} expired launch codes."))
