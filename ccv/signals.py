"""
Django signals for CUPCAKE Vanilla metadata models.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import MetadataColumn, MetadataTableTemplate, SamplePool


@receiver(post_save, sender=MetadataTableTemplate)
def ensure_single_default_template(sender, instance, **kwargs):
    """Ensure only one template can be marked as default."""
    if instance.is_default:
        # Unmark other templates as default
        MetadataTableTemplate.objects.filter(is_default=True).exclude(id=instance.id).update(is_default=False)


@receiver(post_save, sender=MetadataColumn)
def sync_hidden_property_to_pool_columns(sender, instance, **kwargs):
    """
    When a metadata column's hidden property is updated, sync it to corresponding pool columns.
    """
    # Only sync if this is an update and the hidden field has potentially changed
    if not kwargs.get("created", False):
        # Find all sample pools in the same metadata table
        sample_pools = SamplePool.objects.filter(metadata_table=instance.metadata_table)

        for pool in sample_pools:
            # Find the corresponding pool column by position
            try:
                pool_columns = pool.metadata_columns.filter(column_position=instance.column_position)
                if pool_columns.exists():
                    pool_columns.update(hidden=instance.hidden)
            except Exception:
                # Silently continue if there's an issue finding corresponding columns
                continue


@receiver(post_save, sender=SamplePool)
def update_pooled_sample_columns_on_pool_save(sender, instance, **kwargs):
    """
    When a sample pool is saved (samples added/removed), update the pooled sample column values.
    """
    from .utils import update_pooled_sample_column_for_table

    try:
        update_pooled_sample_column_for_table(instance.metadata_table)
    except Exception:
        # Silently continue if there's an issue updating pooled columns
        pass
