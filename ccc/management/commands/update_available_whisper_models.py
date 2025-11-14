"""
Management command to scan and cache available Whisper.cpp models.

This command should be run by the transcribe worker on startup to report
which models are available in its filesystem.
"""

import logging

from django.core.management.base import BaseCommand

from ccc.models import SiteConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Scan for available Whisper.cpp models and cache them in SiteConfig."""

    help = "Scan for available Whisper.cpp models and update SiteConfig cache"

    def handle(self, *args, **options):
        """Execute the command."""
        try:
            models = SiteConfig.scan_available_whisper_models()

            site_config = SiteConfig.objects.first()
            if not site_config:
                site_config = SiteConfig.objects.create()

            site_config.cached_available_models = models
            site_config.save(update_fields=["cached_available_models"])

            self.stdout.write(self.style.SUCCESS(f"Successfully cached {len(models)} Whisper.cpp models:"))
            for model in models:
                self.stdout.write(f"  - {model['name']} ({model['size']}) - {model['description']}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to scan models: {str(e)}"))
            logger.exception("Failed to scan Whisper.cpp models")
            raise
