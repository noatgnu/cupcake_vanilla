"""
Django signals for CCRV real-time WebSocket notifications.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import TimeKeeper, TimeKeeperEvent
from .websocket_utils import format_duration, send_timekeeper_started, send_timekeeper_stopped, send_timekeeper_updated

logger = logging.getLogger(__name__)


@receiver(post_save, sender=TimeKeeper)
def timekeeper_updated_signal(sender, instance, created, **kwargs):
    """
    Signal handler for TimeKeeper save events.

    Sends WebSocket notifications when:
    - TimeKeeper is started (started changes from False to True)
    - TimeKeeper is stopped (started changes from True to False)
    - TimeKeeper is updated
    """
    if created:
        return

    try:
        old_instance = None
        if hasattr(instance, "_pre_save_instance"):
            old_instance = instance._pre_save_instance

        timekeeper_data = {
            "timekeeper_id": str(instance.id),
            "name": instance.name,
            "session_id": str(instance.session.id) if instance.session else None,
            "step_id": str(instance.step.id) if instance.step else None,
            "timestamp": timezone.now().isoformat(),
        }

        if old_instance:
            if not old_instance.started and instance.started:
                TimeKeeperEvent.objects.create(
                    time_keeper=instance,
                    event_type="started",
                    duration_at_event=instance.current_duration,
                )
                timekeeper_data["start_time"] = instance.start_time.isoformat()
                send_timekeeper_started(instance.user.id, timekeeper_data)
                logger.info(f"TimeKeeper {instance.id} started for user {instance.user.id}")

            elif old_instance.started and not instance.started:
                TimeKeeperEvent.objects.create(
                    time_keeper=instance,
                    event_type="stopped",
                    duration_at_event=instance.current_duration,
                )
                timekeeper_data["duration"] = instance.current_duration
                timekeeper_data["duration_formatted"] = format_duration(instance.current_duration)
                send_timekeeper_stopped(instance.user.id, timekeeper_data)
                logger.info(f"TimeKeeper {instance.id} stopped for user {instance.user.id}")

            else:
                timekeeper_data["started"] = instance.started
                timekeeper_data["duration"] = instance.current_duration
                send_timekeeper_updated(instance.user.id, timekeeper_data)
                logger.debug(f"TimeKeeper {instance.id} updated for user {instance.user.id}")

        else:
            if instance.started:
                timekeeper_data["start_time"] = instance.start_time.isoformat()
                send_timekeeper_started(instance.user.id, timekeeper_data)
            else:
                timekeeper_data["duration"] = instance.current_duration
                timekeeper_data["duration_formatted"] = format_duration(instance.current_duration)
                send_timekeeper_stopped(instance.user.id, timekeeper_data)

    except Exception as e:
        logger.error(f"Error in timekeeper_updated_signal: {e}")
