"""
Signal handlers for CCM models to trigger CCMC notifications when available.

These signals provide automatic integration with the communication system
while maintaining optional functionality.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .communication import is_ccmc_available, send_maintenance_alert, send_notification
from .models import Instrument, InstrumentUsage, MaintenanceLog, ReagentAction, StoredReagent

logger = logging.getLogger(__name__)


@receiver(post_save, sender=MaintenanceLog)
def maintenance_log_notification(sender, instance, created, **kwargs):
    """Send notification when maintenance is completed or updated."""
    if not is_ccmc_available() or not instance.instrument:
        return

    if created and instance.status == "completed":
        # Maintenance completed notification
        maintenance_info = {
            "maintenance_type": instance.get_maintenance_type_display(),
            "maintenance_date": instance.maintenance_date.isoformat() if instance.maintenance_date else None,
            "description": instance.maintenance_description,
        }

        send_maintenance_alert(
            instrument=instance.instrument, message_type="maintenance_completed", maintenance_info=maintenance_info
        )

    elif not created and instance.status == "requested":
        # Maintenance requested notification
        title = f"Maintenance Requested: {instance.instrument.instrument_name}"
        message = f"Maintenance has been requested for {instance.instrument.instrument_name}."

        if instance.instrument.user:
            send_notification(
                title=title,
                message=message,
                recipient=instance.instrument.user,
                notification_type="maintenance",
                priority="normal",
                related_object=instance.instrument,
                data={
                    "maintenance_type": instance.get_maintenance_type_display(),
                    "description": instance.maintenance_description,
                },
            )


@receiver(post_save, sender=ReagentAction)
def reagent_action_notification(sender, instance, created, **kwargs):
    """Trigger stock check notifications when reagent quantities change."""
    if not is_ccmc_available() or not created:
        return

    # Check if this action results in low stock
    if instance.action_type == "reserve" and instance.reagent:
        # Update the reagent quantity (assuming this happens elsewhere)
        # and check if we need to send low stock notifications
        instance.reagent.check_low_stock()


@receiver(post_save, sender=InstrumentUsage)
def instrument_usage_notification(sender, instance, created, **kwargs):
    """Send notification when instrument usage is approved or completed."""
    if not is_ccmc_available() or not instance.instrument or not instance.user:
        return

    if not created and instance.approved and hasattr(instance, "_approval_changed"):
        # Usage approved notification
        title = f"Instrument Usage Approved: {instance.instrument.instrument_name}"
        message = f"Your booking for {instance.instrument.instrument_name} has been approved."

        send_notification(
            title=title,
            message=message,
            recipient=instance.user,
            notification_type="system",
            priority="normal",
            related_object=instance.instrument,
            data={
                "usage_id": str(instance.id),
                "time_started": instance.time_started.isoformat() if instance.time_started else None,
                "time_ended": instance.time_ended.isoformat() if instance.time_ended else None,
            },
        )


@receiver(post_save, sender=Instrument)
def create_instrument_metadata_table(sender, instance, created, **kwargs):
    """Automatically create a blank metadata table for new instruments."""
    if created and not instance.metadata_table:
        from ccv.models import MetadataTable

        try:
            # Create blank metadata table with single row for SDRF tagging
            metadata_table = MetadataTable.objects.create(
                name=f"{instance.instrument_name} Metadata",
                description=f"SDRF metadata table for instrument {instance.instrument_name}",
                sample_count=1,  # Single row for the instrument
                owner=instance.user,
                lab_group=getattr(instance.user, "default_lab_group", None) if instance.user else None,
                is_published=False,
                is_locked=False,
                source_app="ccm",  # Mark as CCM-managed metadata table
            )

            # Link the metadata table to the instrument
            instance.metadata_table = metadata_table
            instance.save(update_fields=["metadata_table"])

            logger.info(f"Created metadata table {metadata_table.id} for instrument {instance.instrument_name}")

        except Exception as e:
            logger.error(f"Failed to create metadata table for instrument {instance.instrument_name}: {e}")


@receiver(post_save, sender=StoredReagent)
def create_stored_reagent_metadata_table(sender, instance, created, **kwargs):
    """Automatically create a blank metadata table for new stored reagents."""
    if created and not instance.metadata_table:
        from ccv.models import MetadataTable

        try:
            # Create blank metadata table with single row for SDRF tagging
            reagent_name = instance.reagent.name if instance.reagent else "Unknown Reagent"
            storage_name = instance.storage_object.object_name if instance.storage_object else "Unknown Storage"

            metadata_table = MetadataTable.objects.create(
                name=f"{reagent_name} ({storage_name}) Metadata",
                description=f"SDRF metadata table for stored reagent {reagent_name} in {storage_name}",
                sample_count=1,  # Single row for the reagent
                owner=instance.user,
                lab_group=getattr(instance.user, "default_lab_group", None) if instance.user else None,
                is_published=False,
                is_locked=False,
                source_app="ccm",  # Mark as CCM-managed metadata table
            )

            # Link the metadata table to the stored reagent
            instance.metadata_table = metadata_table
            instance.save(update_fields=["metadata_table"])

            logger.info(f"Created metadata table {metadata_table.id} for stored reagent {reagent_name}")

        except Exception as e:
            logger.error(f"Failed to create metadata table for stored reagent {reagent_name}: {e}")
