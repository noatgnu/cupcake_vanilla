from django.db import models
from django.utils.crypto import get_random_string, salted_hmac


class Plugin(models.Model):
    """A registered plugin/addon container that extends CUPCAKE functionality."""

    LIFECYCLE_UNKNOWN = "unknown"
    LIFECYCLE_INSTALLING = "installing"
    LIFECYCLE_STARTING = "starting"
    LIFECYCLE_RUNNING = "running"
    LIFECYCLE_STOPPED = "stopped"
    LIFECYCLE_ERROR = "error"

    LIFECYCLE_CHOICES = [
        (LIFECYCLE_UNKNOWN, "Unknown"),
        (LIFECYCLE_INSTALLING, "Installing"),
        (LIFECYCLE_STARTING, "Starting"),
        (LIFECYCLE_RUNNING, "Running"),
        (LIFECYCLE_STOPPED, "Stopped"),
        (LIFECYCLE_ERROR, "Error"),
    ]

    name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    manifest_cache = models.JSONField(default=dict)
    base_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=64, unique=True, db_index=True, default="")
    lifecycle_status = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default=LIFECYCLE_UNKNOWN)
    progress_message = models.CharField(max_length=500, blank=True)
    progress_data = models.JSONField(default=dict)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccc"
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.display_name} v{self.version} (id={self.id})"

    @staticmethod
    def hash_token(plain: str) -> str:
        """Return the HMAC-SHA256 hex digest of a plain token, keyed with SECRET_KEY."""
        return salted_hmac("ccc.plugin.token", plain, algorithm="sha256").hexdigest()

    def save(self, *args, **kwargs):
        if not self.token:
            plain = get_random_string(64)
            self._plain_token = plain
            self.token = self.hash_token(plain)
        super().save(*args, **kwargs)
