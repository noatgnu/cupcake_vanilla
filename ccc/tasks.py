"""
RQ tasks for CUPCAKE Core (CCC).
"""

import logging

from django_rq import job

from ccc.models import SiteConfig

logger = logging.getLogger(__name__)


@job("transcribe", timeout="5m")
def refresh_available_whisper_models():
    """
    Scan for available Whisper.cpp models and update cache.

    This job should be queued on the transcribe worker which has
    access to the model files.

    Returns:
        dict: Information about scanned models
    """
    try:
        models = SiteConfig.scan_available_whisper_models()

        site_config = SiteConfig.objects.first()
        if not site_config:
            site_config = SiteConfig.objects.create()

        site_config.cached_available_models = models
        site_config.save(update_fields=["cached_available_models"])

        logger.info(f"Successfully cached {len(models)} Whisper.cpp models")

        return {"status": "success", "models_count": len(models), "models": models}

    except Exception as e:
        logger.exception("Failed to refresh available Whisper.cpp models")
        return {"status": "error", "error": str(e)}
