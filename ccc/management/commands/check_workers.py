from django.core.management.base import BaseCommand

import django_rq
from rq.worker import Worker


class Command(BaseCommand):
    help = "Check status of all RQ workers and queues"

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            type=str,
            help="Check specific queue only (default: all)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed worker information",
        )

    def handle(self, *args, **options):
        queue_filter = options.get("queue")
        verbose = options.get("verbose", False)

        queue_names = ["default", "high", "low", "transcribe"]
        if queue_filter:
            queue_names = [queue_filter]

        self.stdout.write(self.style.SUCCESS("\n=== RQ Worker Status ===\n"))

        try:
            queue = django_rq.get_queue("default")
            workers = Worker.all(connection=queue.connection)

            if not workers:
                self.stdout.write(self.style.WARNING("No workers found!"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Found {len(workers)} worker(s):\n"))

                for worker in workers:
                    state = worker.get_state()
                    queues = [q.name for q in worker.queues]

                    if state == "busy":
                        style = self.style.WARNING
                    elif state == "idle":
                        style = self.style.SUCCESS
                    else:
                        style = self.style.NOTICE

                    self.stdout.write(style(f"\n  Worker: {worker.name}"))
                    self.stdout.write(f"    State: {state}")
                    self.stdout.write(f"    Queues: {', '.join(queues)}")
                    self.stdout.write(f"    PID: {worker.pid}")

                    current_job = worker.get_current_job()
                    if current_job:
                        self.stdout.write(f"    Current Job: {current_job.id}")
                        self.stdout.write(f"      Function: {current_job.func_name}")
                        if verbose:
                            self.stdout.write(f"      Created: {current_job.created_at}")
                            self.stdout.write(f"      Started: {current_job.started_at}")

                    if verbose:
                        self.stdout.write(f"    Birth: {worker.birth_date}")
                        if hasattr(worker, "last_heartbeat"):
                            self.stdout.write(f"    Last Heartbeat: {worker.last_heartbeat}")
                        self.stdout.write(f"    Successful Jobs: {worker.successful_job_count}")
                        self.stdout.write(f"    Failed Jobs: {worker.failed_job_count}")
                        self.stdout.write(f"    Total Working Time: {worker.total_working_time}s")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting workers: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("\n\n=== Queue Statistics ===\n"))

        for queue_name in queue_names:
            try:
                queue = django_rq.get_queue(queue_name)
                queued = len(queue)
                failed = queue.failed_job_registry.count
                scheduled = queue.scheduled_job_registry.count
                started = queue.started_job_registry.count

                self.stdout.write(f"\n  Queue: {queue_name}")
                self.stdout.write(f"    Queued: {queued}")
                self.stdout.write(f"    Started: {started}")
                self.stdout.write(f"    Scheduled: {scheduled}")
                self.stdout.write(f"    Failed: {failed}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\n  Queue: {queue_name}"))
                self.stdout.write(self.style.ERROR(f"    Error: {str(e)}"))

        self.stdout.write("\n")
