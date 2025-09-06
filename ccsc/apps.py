"""
CUPCAKE Salted Caramel (CCSC) Django App Configuration.

Financial management and billing system for CUPCAKE.
Theme: "Sweet deals with a business edge"
"""

from django.apps import AppConfig


class CcscConfig(AppConfig):
    """
    Django app configuration for CUPCAKE Salted Caramel.

    CUPCAKE Salted Caramel provides comprehensive billing, invoicing, and
    financial management functionality for laboratory services with
    flexible pricing models and cost center tracking.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "ccsc"
    verbose_name = "CUPCAKE Salted Caramel (Billing & Finance)"

    def ready(self):
        """Import signal handlers when the app is ready."""
        try:
            import ccsc.signals  # noqa F401
        except ImportError:
            pass
