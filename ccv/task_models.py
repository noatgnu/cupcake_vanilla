"""
Models for tracking async task status and results.
"""
import os
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner
from django.db import models
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from ccv.models import MetadataTable


class AsyncTaskStatus(models.Model):
    """
    Track status and results of async tasks.
    """

    TASK_STATUS_CHOICES = [
        ("QUEUED", "Queued"),
        ("STARTED", "Started"),
        ("SUCCESS", "Success"),
        ("FAILURE", "Failure"),
        ("CANCELLED", "Cancelled"),
    ]

    TASK_TYPE_CHOICES = [
        ("EXPORT_EXCEL", "Export Excel Template"),
        ("EXPORT_SDRF", "Export SDRF File"),
        ("IMPORT_SDRF", "Import SDRF File"),
        ("IMPORT_EXCEL", "Import Excel File"),
        ("EXPORT_MULTIPLE_SDRF", "Export Multiple SDRF Files"),
        ("EXPORT_MULTIPLE_EXCEL", "Export Multiple Excel Templates"),
        ("VALIDATE_TABLE", "Validate Metadata Table"),
        ("REORDER_TABLE_COLUMNS", "Reorder Table Columns"),
        ("REORDER_TEMPLATE_COLUMNS", "Reorder Template Columns"),
        ("TRANSCRIBE_AUDIO", "Transcribe Audio"),
        ("TRANSCRIBE_VIDEO", "Transcribe Video"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_type = models.CharField(max_length=25, choices=TASK_TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=TASK_STATUS_CHOICES, default="QUEUED")

    # Task context
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="async_tasks")
    metadata_table = models.ForeignKey(
        MetadataTable, on_delete=models.CASCADE, related_name="async_tasks", null=True, blank=True
    )

    # Task parameters (stored as JSON)
    parameters = models.JSONField(default=dict, blank=True)

    # Task results (stored as JSON)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # RQ job information
    rq_job_id = models.CharField(max_length=100, blank=True)
    queue_name = models.CharField(max_length=50, default="default")

    # Progress tracking
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=100)
    progress_description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["task_type", "-created_at"]),
            models.Index(fields=["rq_job_id"]),
        ]

    def __str__(self):
        return f"{self.get_task_type_display()} - {self.get_status_display()}"

    @property
    def duration(self):
        """Return task duration in seconds if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (timezone.now() - self.started_at).total_seconds()
        return None

    @property
    def progress_percentage(self):
        """Return progress as percentage."""
        if self.progress_total == 0:
            return 0
        return min(100, (self.progress_current / self.progress_total) * 100)

    def mark_started(self):
        """Mark task as started."""
        self.status = "STARTED"
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])
        self.send_websocket_update()

    def mark_success(self, result_data=None):
        """Mark task as successful."""
        self.status = "SUCCESS"
        self.completed_at = timezone.now()
        self.progress_current = self.progress_total
        if result_data:
            self.result = result_data
        self.save(update_fields=["status", "completed_at", "progress_current", "result"])
        self.send_websocket_update()

    def mark_failure(self, error_message, traceback_str=None):
        """Mark task as failed."""
        self.status = "FAILURE"
        self.completed_at = timezone.now()
        self.error_message = error_message
        if traceback_str:
            self.traceback = traceback_str
        self.save(update_fields=["status", "completed_at", "error_message", "traceback"])
        self.send_websocket_update()

    def update_progress(self, current, total=None, description=None):
        """Update task progress."""
        self.progress_current = current
        if total is not None:
            self.progress_total = total
        if description is not None:
            self.progress_description = description
        self.save(update_fields=["progress_current", "progress_total", "progress_description"])
        self.send_websocket_update()

    def cancel(self):
        """Mark task as cancelled."""
        self.status = "CANCELLED"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])
        self.send_websocket_update()

    def send_websocket_update(self):
        """Send task status update via WebSocket."""
        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            # Prepare download URL if task is successful and has file result
            download_url = None
            if self.status == "SUCCESS" and hasattr(self, "file_result") and self.file_result.file:
                try:
                    signed_token, _ = self.file_result.generate_download_url(expire_minutes=10)
                    download_url = f"/api/v1/async-tasks/{self.id}/download/?token={signed_token}"
                except Exception:
                    pass

            # Send update to user's WebSocket group
            user_group_name = f"async_tasks_user_{self.user.id}"
            async_to_sync(channel_layer.group_send)(
                user_group_name,
                {
                    "type": "async_task_update",
                    "task_id": str(self.id),
                    "status": self.status,
                    "progress_percentage": self.progress_percentage,
                    "progress_description": self.progress_description,
                    "error_message": self.error_message,
                    "result": self.result,
                    "download_url": download_url,
                    "timestamp": timezone.now().isoformat(),
                },
            )
        except Exception as e:
            # Log error but don't fail the task update
            print(f"Error sending WebSocket update for task {self.id}: {e}")


def task_result_upload_path(instance, filename):
    """Generate upload path for task result files."""
    return f"temp/task_results/{instance.task.user.id}/{instance.task.id}/{filename}"


class TaskResult(models.Model):
    """
    Store large task results as temporary media files with secure access.
    """

    task = models.OneToOneField(AsyncTaskStatus, on_delete=models.CASCADE, related_name="file_result")

    # File storage
    file = models.FileField(upload_to=task_result_upload_path, null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveIntegerField(default=0)

    # File metadata
    expires_at = models.DateTimeField(help_text="When this file expires and should be cleaned up")
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["task", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Result for {self.task} - {self.file_name}"

    def save(self, *args, **kwargs):
        """Set expiration date on save."""
        if not self.expires_at:
            # Files expire after 7 days by default
            expire_days = getattr(settings, "TASK_RESULT_EXPIRE_DAYS", 7)
            self.expires_at = timezone.now() + timezone.timedelta(days=expire_days)

        if self.file and not self.file_size:
            self.file_size = self.file.size

        super().save(*args, **kwargs)

    def generate_download_url(self, expire_minutes=10):
        """
        Generate a signed download URL that expires after the specified minutes.

        Args:
            expire_minutes: Minutes until the signed URL expires

        Returns:
            Tuple of (signed_token, nginx_internal_path)
        """
        signer = TimestampSigner()

        # Create payload with task ID, user ID, and file path
        payload = f"{self.task.id}:{self.task.user.id}:{self.file.name}"
        signed_token = signer.sign(payload)

        # nginx internal path for X-Accel-Redirect
        nginx_internal_path = f"/internal/media/{self.file.name}"

        return signed_token, nginx_internal_path

    @classmethod
    def verify_download_token(cls, signed_token):
        """
        Verify a signed download token and return the TaskResult if valid.

        The token contains all necessary authentication information - no additional
        user verification needed since the token generation already validated permissions.

        Args:
            signed_token: The signed token to verify

        Returns:
            TaskResult instance if valid, None otherwise
        """
        signer = TimestampSigner()

        try:
            # Verify signature and check age (default 10 minutes)
            max_age = getattr(settings, "TASK_DOWNLOAD_TOKEN_MAX_AGE", 600)  # 10 minutes
            payload = signer.unsign(signed_token, max_age=max_age)

            # Parse payload
            task_id, user_id, file_path = payload.split(":", 2)

            # Get task result using the user_id from the token
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.get(id=user_id)

            # Get task result
            task_result = cls.objects.select_related("task").get(task__id=task_id, task__user=user, file=file_path)

            # Check if file has expired
            if task_result.expires_at < timezone.now():
                return None

            return task_result

        except Exception:
            return None

    def record_download(self):
        """Record a download attempt."""
        self.download_count += 1
        self.last_downloaded_at = timezone.now()
        self.save(update_fields=["download_count", "last_downloaded_at"])

    def is_expired(self):
        """Check if the file has expired."""
        return self.expires_at < timezone.now()

    def get_file_path(self):
        """Get the full file system path."""
        if self.file:
            return self.file.path
        return None

    def cleanup_expired(self):
        """Clean up expired file."""
        if self.is_expired() and self.file:
            # Delete the actual file
            try:
                if os.path.exists(self.file.path):
                    os.remove(self.file.path)
            except Exception:
                pass
            # Clear the file field
            self.file = None
            self.save(update_fields=["file"])
