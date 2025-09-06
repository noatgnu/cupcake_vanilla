"""
CUPCAKE Mint Chocolate (CCMC) Django App Configuration.

Communications and notifications system for CUPCAKE.
Theme: "Refreshing connections with rich conversations"
"""

from django.apps import AppConfig


class CcmcConfig(AppConfig):
    """
    Django app configuration for CUPCAKE Mint Chocolate.

    CUPCAKE Mint Chocolate provides messaging, notifications, and communication
    functionality for all CUPCAKE apps with optional integration.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "ccmc"
    verbose_name = "CUPCAKE Mint Chocolate (Communications)"

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        try:
            import ccmc.signals  # noqa F401
        except ImportError:
            pass
