from datetime import datetime, timezone

from django.core.management.base import BaseCommand

import django_rq
from rq.worker import Worker


class Command(BaseCommand):
    help = "Clean up dead RQ workers that haven't sent heartbeats"

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=300,
            help="Consider workers dead after N seconds without heartbeat (default: 300)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without actually removing",
        )

    def handle(self, *args, **options):
        timeout = options.get("timeout", 300)
        dry_run = options.get("dry_run", False)

        self.stdout.write(self.style.SUCCESS("\n=== Cleaning Up Dead RQ Workers ===\n"))

        queue = django_rq.get_queue("default")
        workers = Worker.all(connection=queue.connection)

        if not workers:
            self.stdout.write(self.style.WARNING("No workers found!"))
            return

        now = datetime.now(timezone.utc)
        dead_workers = []
        alive_workers = []

        for worker in workers:
            try:
                last_heartbeat = worker.last_heartbeat

                if last_heartbeat:
                    if isinstance(last_heartbeat, str):
                        last_heartbeat = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
                    elif not last_heartbeat.tzinfo:
                        last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)

                    time_since_heartbeat = (now - last_heartbeat).total_seconds()

                    if time_since_heartbeat > timeout:
                        dead_workers.append((worker, time_since_heartbeat))
                    else:
                        alive_workers.append(worker)
                else:
                    self.stdout.write(self.style.WARNING(f"Worker {worker.name} has no heartbeat timestamp"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error checking worker {worker.name}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"Found {len(alive_workers)} alive worker(s)"))

        if dead_workers:
            self.stdout.write(self.style.WARNING(f"\nFound {len(dead_workers)} dead worker(s):\n"))

            for worker, time_since in dead_workers:
                self.stdout.write(f"  - {worker.name} (PID: {worker.pid})")
                self.stdout.write(f"    Last heartbeat: {int(time_since)}s ago")
                self.stdout.write(f"    Queues: {', '.join([q.name for q in worker.queues])}")

                if not dry_run:
                    try:
                        worker.register_death()
                        self.stdout.write(self.style.SUCCESS(f"    ✓ Cleaned up {worker.name}"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"    ✗ Failed to clean up: {str(e)}"))
                else:
                    self.stdout.write(self.style.NOTICE(f"    [DRY RUN] Would clean up {worker.name}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo dead workers found!"))

        if dry_run and dead_workers:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY RUN] Run without --dry-run to actually remove {len(dead_workers)} worker(s)"
                )
            )

        self.stdout.write("\n")
