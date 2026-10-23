"""
CUPCAKE Vanilla (CCV) Django App Configuration.
"""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


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
        Import signal handlers and the ``external_vocabularies`` module of every installed app.
        """
        try:
            import ccv.signals  # noqa F401
        except ImportError:
            pass
        autodiscover_modules("external_vocabularies")
