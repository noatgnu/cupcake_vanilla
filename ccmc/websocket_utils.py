"""
Utility functions for sending WebSocket messages through CCMC.
"""

import logging

from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def send_notification_to_user(user_id, notification_data):
    """
    Send a real-time notification to a specific user via WebSocket.

    Args:
        user_id: The ID of the user to send the notification to
        notification_data: Dictionary containing notification details
            - notification_id: UUID of the notification
            - title: Notification title
            - message: Notification message
            - notification_type: Type of notification
            - priority: Priority level
            - data: Additional data dictionary
            - timestamp: ISO format timestamp

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        user_group_name = f"ccmc_user_{user_id}"

        message = {"type": "new_notification", **notification_data}

        async_to_sync(channel_layer.group_send)(user_group_name, message)
        logger.debug(f"WebSocket notification sent to user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WebSocket notification to user {user_id}: {e}")
        return False


def send_message_to_thread(thread_id, message_data):
    """
    Send a real-time message notification to all thread participants via WebSocket.

    Args:
        thread_id: The UUID of the message thread
        message_data: Dictionary containing message details
            - message_id: UUID of the message
            - sender_id: User ID of the sender
            - sender_username: Username of the sender
            - content: Message content
            - message_type: Type of message
            - timestamp: ISO format timestamp

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        thread_group_name = f"ccmc_thread_{thread_id}"

        message = {"type": "new_message", "thread_id": str(thread_id), **message_data}

        async_to_sync(channel_layer.group_send)(thread_group_name, message)
        logger.debug(f"WebSocket message sent to thread {thread_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WebSocket message to thread {thread_id}: {e}")
        return False


def send_thread_update(thread_id, action, message=""):
    """
    Send a thread update notification to all participants.

    Args:
        thread_id: The UUID of the message thread
        action: The action that occurred (e.g., 'participant_added', 'thread_archived')
        message: Optional descriptive message

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        thread_group_name = f"ccmc_thread_{thread_id}"

        update_message = {
            "type": "thread_update",
            "thread_id": str(thread_id),
            "action": action,
            "message": message,
            "timestamp": timezone.now().isoformat(),
        }

        async_to_sync(channel_layer.group_send)(thread_group_name, update_message)
        logger.debug(f"Thread update sent to thread {thread_id}: {action}")
        return True

    except Exception as e:
        logger.error(f"Error sending thread update to {thread_id}: {e}")
        return False


def send_notification_update(user_id, notification_id, status):
    """
    Send a notification status update to a user.

    Args:
        user_id: The ID of the user
        notification_id: The UUID of the notification
        status: The new status (e.g., 'read', 'delivered')

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        user_group_name = f"ccmc_user_{user_id}"

        update_message = {
            "type": "notification_update",
            "notification_id": str(notification_id),
            "status": status,
            "timestamp": timezone.now().isoformat(),
        }

        async_to_sync(channel_layer.group_send)(user_group_name, update_message)
        logger.debug(f"Notification update sent to user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending notification update to user {user_id}: {e}")
        return False
