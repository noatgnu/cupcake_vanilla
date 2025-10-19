from django.apps import AppConfig


class CcrvConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ccrv"
    verbose_name = "CUPCAKE Red Velvet"

    def ready(self):
        """Import signals when app is ready."""
        import ccrv.signals  # noqa: F401
