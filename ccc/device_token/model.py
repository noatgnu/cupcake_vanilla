from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string


class DeviceToken(models.Model):
    PERMISSION_READ = "read"
    PERMISSION_WRITE = "write"
    PERMISSION_CHOICES = [
        (PERMISSION_READ, "Read Only"),
        (PERMISSION_WRITE, "Read and Write"),
    ]

    token = models.CharField(max_length=128, unique=True, db_index=True)
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    permission = models.CharField(max_length=8, choices=PERMISSION_CHOICES, default=PERMISSION_READ)
    enabled = models.BooleanField(default=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "ccc"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} [{self.permission}]"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(128)
        super().save(*args, **kwargs)

    def is_expired(self):
        return self.expires_at is not None and self.expires_at < timezone.now()
