"""
CUPCAKE Vanilla (CCV) Django App Configuration.
"""

from django.apps import AppConfig


class CcvConfig(AppConfig):
    """
    Django app configuration for CUPCAKE Vanilla.

    CUPCAKE Vanilla provides scientific metadata management, SDRF compliance,
    ontology integration, and template systems for Django projects.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "ccv"
    verbose_name = "CUPCAKE Vanilla"

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        try:
            import ccv.signals  # noqa F401
        except ImportError:
            pass
