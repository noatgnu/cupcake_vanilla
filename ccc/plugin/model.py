from django.db import models


class Plugin(models.Model):
    """A registered plugin/addon container that extends CUPCAKE functionality."""

    name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    manifest_cache = models.JSONField(default=dict)
    base_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccc"
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.display_name} v{self.version} (id={self.id})"
