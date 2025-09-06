"""
CUPCAKE Macaron (CCM) Django App Configuration.
"""

from django.apps import AppConfig


class CcmConfig(AppConfig):
    """
    Django app configuration for CUPCAKE Macaron.

    CUPCAKE Macaron provides precision instrument management and inventory
    control for complex laboratory operations.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "ccm"
    verbose_name = "CUPCAKE Macaron"

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        try:
            import ccm.signals  # noqa F401
        except ImportError:
            pass
