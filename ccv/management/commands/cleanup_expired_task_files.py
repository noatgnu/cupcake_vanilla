"""
Management command to clean up expired task result files.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from ccc.models import TaskResult


class Command(BaseCommand):
    help = "Clean up expired task result files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting anything",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force cleanup without confirmation",
        )

    def handle(self, *args, **options):
        # Find expired files
        expired_results = TaskResult.objects.filter(expires_at__lt=timezone.now(), file__isnull=False).select_related(
            "task", "task__user"
        )

        expired_count = expired_results.count()

        if expired_count == 0:
            self.stdout.write(self.style.SUCCESS("No expired task result files found."))
            return

        self.stdout.write(f"Found {expired_count} expired task result files.")

        if options["dry_run"]:
            self.stdout.write("\nDry run - showing files that would be deleted:")
            for result in expired_results:
                self.stdout.write(f"  - {result.file_name} (Task: {result.task.id}, User: {result.task.user.username})")
            return

        if not options["force"]:
            confirm = input(f"Are you sure you want to delete {expired_count} expired files? [y/N]: ")
            if confirm.lower() not in ["y", "yes"]:
                self.stdout.write("Cleanup cancelled.")
                return

        cleaned_count = 0
        error_count = 0

        for result in expired_results:
            try:
                file_name = result.file_name
                task_id = result.task.id
                result.cleanup_expired()
                cleaned_count += 1
                self.stdout.write(f"✓ Cleaned up: {file_name} (Task: {task_id})")
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"✗ Error cleaning up {result.file_name}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(f"\nCleanup completed: {cleaned_count} files cleaned, {error_count} errors")
        )
