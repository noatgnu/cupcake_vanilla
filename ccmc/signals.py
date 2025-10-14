"""
Signal handlers for CCMC real-time notifications.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Message, Notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """
    Send WebSocket notification when a new notification is created.
    """
    if not created:
        return

    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured - WebSocket notification not sent")
            return

        user_group_name = f"ccmc_user_{instance.recipient.id}"

        notification_data = {
            "type": "new_notification",
            "notification_id": str(instance.id),
            "title": instance.title,
            "message": instance.message,
            "notification_type": instance.notification_type,
            "priority": instance.priority,
            "data": instance.data,
            "timestamp": instance.created_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(user_group_name, notification_data)

        instance.delivery_status = "sent"
        instance.sent_at = timezone.now()
        instance.save(update_fields=["delivery_status", "sent_at"])

        logger.info(f"WebSocket notification sent to user {instance.recipient.username}: {instance.title}")

    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")


@receiver(post_save, sender=Message)
def message_created(sender, instance, created, **kwargs):
    """
    Send WebSocket notification when a new message is created in a thread.
    """
    if not created:
        return

    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured - WebSocket message notification not sent")
            return

        thread_group_name = f"ccmc_thread_{instance.thread.id}"

        message_data = {
            "type": "new_message",
            "thread_id": str(instance.thread.id),
            "message_id": str(instance.id),
            "sender_id": instance.sender.id,
            "sender_username": instance.sender.username,
            "content": instance.content,
            "message_type": instance.message_type,
            "timestamp": instance.created_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(thread_group_name, message_data)

        instance.thread.last_message_at = timezone.now()
        instance.thread.save(update_fields=["last_message_at"])

        logger.info(f"WebSocket message sent to thread {instance.thread.id} from {instance.sender.username}")

    except Exception as e:
        logger.error(f"Error sending WebSocket message notification: {e}")
