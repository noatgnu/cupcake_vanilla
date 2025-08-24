"""
CUPCAKE Core (CCC) Django App Configuration.
"""

from django.apps import AppConfig


class CccConfig(AppConfig):
    """
    Django app configuration for CUPCAKE Core.

    CUPCAKE Core provides user management, lab group collaboration,
    and site administration functionality for Django projects.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "ccc"
    verbose_name = "CUPCAKE Core"

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        try:
            import ccc.signals  # noqa F401
        except ImportError:
            pass
