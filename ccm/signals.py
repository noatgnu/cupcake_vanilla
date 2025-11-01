"""
Signal handlers for CCM models to trigger CCMC notifications when available.

These signals provide automatic integration with the communication system
while maintaining optional functionality.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .communication import is_ccmc_available, send_maintenance_alert, send_notification
from .models import Instrument, InstrumentJobAnnotation, InstrumentUsage, MaintenanceLog, ReagentAction, StoredReagent

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
    """Automatically create a metadata table for new instruments to store specifications."""
    if created and not instance.metadata_table:
        from ccv.models import MetadataTable

        try:
            metadata_table = MetadataTable.objects.create(
                name=f"{instance.instrument_name} Specifications",
                description=f"Instrument specifications and settings for {instance.instrument_name}",
                sample_count=1,
                owner=instance.user,
                lab_group=getattr(instance.user, "default_lab_group", None) if instance.user else None,
                is_published=False,
                is_locked=False,
                source_app="ccm",
            )

            instance.metadata_table = metadata_table
            instance.save(update_fields=["metadata_table"])

            logger.info(f"Created metadata table {metadata_table.id} for instrument {instance.instrument_name}")

        except Exception as e:
            logger.error(f"Failed to create metadata table for instrument {instance.instrument_name}: {e}")


@receiver(post_save, sender=Instrument)
def create_instrument_default_folders(sender, instance, created, **kwargs):
    """Automatically create default annotation folders for new instruments."""
    if created and instance.user:
        try:
            instance.create_default_folders()
            logger.info(f"Created default annotation folders for instrument {instance.instrument_name}")
        except Exception as e:
            logger.error(f"Failed to create default folders for instrument {instance.instrument_name}: {e}")


@receiver(post_save, sender=StoredReagent)
def create_stored_reagent_metadata_table(sender, instance, created, **kwargs):
    """Automatically create a metadata table for new stored reagents to store specifications."""
    if created and not instance.metadata_table:
        from ccv.models import MetadataTable

        try:
            reagent_name = instance.reagent.name if instance.reagent else "Unknown Reagent"
            storage_name = instance.storage_object.object_name if instance.storage_object else "Unknown Storage"

            metadata_table = MetadataTable.objects.create(
                name=f"{reagent_name} ({storage_name}) Specifications",
                description=f"Reagent specifications and properties for {reagent_name} in {storage_name}",
                sample_count=1,
                owner=instance.user,
                lab_group=getattr(instance.user, "default_lab_group", None) if instance.user else None,
                is_published=False,
                is_locked=False,
                source_app="ccm",
            )

            instance.metadata_table = metadata_table
            instance.save(update_fields=["metadata_table"])

            logger.info(f"Created metadata table {metadata_table.id} for stored reagent {reagent_name}")

        except Exception as e:
            logger.error(f"Failed to create metadata table for stored reagent {reagent_name}: {e}")


@receiver(post_save, sender=StoredReagent)
def create_stored_reagent_default_folders(sender, instance, created, **kwargs):
    """Automatically create default annotation folders for new stored reagents."""
    if created and instance.user:
        try:
            instance.create_default_folders()
            reagent_name = instance.reagent.name if instance.reagent else "Unknown Reagent"
            logger.info(f"Created default annotation folders for stored reagent {reagent_name}")
        except Exception as e:
            reagent_name = instance.reagent.name if instance.reagent else "Unknown Reagent"
            logger.error(f"Failed to create default folders for stored reagent {reagent_name}: {e}")


@receiver(post_save, sender=InstrumentJobAnnotation)
def merge_instrument_metadata_on_booking(sender, instance, created, **kwargs):
    """
    Merge instrument metadata into job metadata when a booking annotation is created.

    When a booking annotation is created for an instrument job:
    1. Check if the instrument has metadata
    2. Check if the job has a metadata table
    3. For each instrument metadata column:
       - If job has a column with the same name and type:
         - If job column is empty/blank/N/A, replace with instrument value
       - If job doesn't have this column, add it
    """
    if not created:
        return

    if not instance.annotation or instance.annotation.annotation_type != "booking":
        return

    instrument_job = instance.instrument_job
    if not instrument_job or not instrument_job.instrument:
        return

    instrument = instrument_job.instrument
    if not instrument.metadata_table:
        logger.debug(f"Instrument {instrument.id} has no metadata table")
        return

    if not instrument_job.metadata_table:
        logger.debug(f"InstrumentJob {instrument_job.id} has no metadata table")
        return

    try:
        instrument_columns = instrument.metadata_table.columns.all()
        job_columns = instrument_job.metadata_table.columns.all()

        job_columns_dict = {(col.name, col.type): col for col in job_columns}

        columns_merged = 0
        columns_added = 0

        for inst_col in instrument_columns:
            key = (inst_col.name, inst_col.type)

            if key in job_columns_dict:
                job_col = job_columns_dict[key]

                should_replace = (
                    not job_col.value or job_col.value.strip() == "" or job_col.not_applicable or job_col.not_available
                )

                if should_replace and inst_col.value:
                    job_col.value = inst_col.value
                    job_col.not_applicable = inst_col.not_applicable
                    job_col.not_available = inst_col.not_available
                    job_col.save(update_fields=["value", "not_applicable", "not_available"])
                    columns_merged += 1
                    logger.info(f"Merged instrument metadata column '{inst_col.name}' " f"into job {instrument_job.id}")
            else:
                from ccv.models import MetadataColumn

                MetadataColumn.objects.create(
                    metadata_table=instrument_job.metadata_table,
                    name=inst_col.name,
                    type=inst_col.type,
                    value=inst_col.value,
                    not_applicable=inst_col.not_applicable,
                    not_available=inst_col.not_available,
                    column_position=inst_col.column_position,
                    template=inst_col.template,
                    mandatory=inst_col.mandatory,
                    hidden=inst_col.hidden,
                    readonly=inst_col.readonly,
                    staff_only=inst_col.staff_only,
                    ontology_type=inst_col.ontology_type,
                )
                columns_added += 1
                logger.info(f"Added instrument metadata column '{inst_col.name}' " f"to job {instrument_job.id}")

        if columns_merged > 0 or columns_added > 0:
            logger.info(
                f"Booking annotation created: merged {columns_merged} columns, "
                f"added {columns_added} columns from instrument {instrument.id} "
                f"to job {instrument_job.id}"
            )

    except Exception as e:
        logger.error(f"Failed to merge instrument metadata into job {instrument_job.id}: {e}", exc_info=True)
