"""
Django signals for CUPCAKE Vanilla metadata models.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import MetadataTableTemplate


@receiver(post_save, sender=MetadataTableTemplate)
def ensure_single_default_template(sender, instance, **kwargs):
    """Ensure only one template can be marked as default."""
    if instance.is_default:
        # Unmark other templates as default
        MetadataTableTemplate.objects.filter(is_default=True).exclude(id=instance.id).update(is_default=False)
