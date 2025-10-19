"""
Utility functions for sending WebSocket messages through CCRV.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def send_timekeeper_started(user_id, timekeeper_data):
    """
    Send a real-time notification when a TimeKeeper is started.

    Args:
        user_id: The ID of the user who owns the TimeKeeper
        timekeeper_data: Dictionary containing TimeKeeper details
            - timekeeper_id: ID of the TimeKeeper
            - session_id: ID of the session (optional)
            - step_id: ID of the step (optional)
            - start_time: Start time in ISO format
            - timestamp: ISO format timestamp

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        user_group_name = f"ccrv_user_{user_id}"

        message = {"type": "timekeeper_started", **timekeeper_data}

        async_to_sync(channel_layer.group_send)(user_group_name, message)
        logger.debug(f"WebSocket timekeeper_started sent to user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WebSocket timekeeper_started to user {user_id}: {e}")
        return False


def send_timekeeper_stopped(user_id, timekeeper_data):
    """
    Send a real-time notification when a TimeKeeper is stopped.

    Args:
        user_id: The ID of the user who owns the TimeKeeper
        timekeeper_data: Dictionary containing TimeKeeper details
            - timekeeper_id: ID of the TimeKeeper
            - session_id: ID of the session (optional)
            - step_id: ID of the step (optional)
            - duration: Duration in seconds
            - duration_formatted: Human-readable duration
            - timestamp: ISO format timestamp

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        user_group_name = f"ccrv_user_{user_id}"

        message = {"type": "timekeeper_stopped", **timekeeper_data}

        async_to_sync(channel_layer.group_send)(user_group_name, message)
        logger.debug(f"WebSocket timekeeper_stopped sent to user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WebSocket timekeeper_stopped to user {user_id}: {e}")
        return False


def send_timekeeper_updated(user_id, timekeeper_data):
    """
    Send a real-time notification when a TimeKeeper is updated.

    Args:
        user_id: The ID of the user who owns the TimeKeeper
        timekeeper_data: Dictionary containing TimeKeeper details
            - timekeeper_id: ID of the TimeKeeper
            - session_id: ID of the session (optional)
            - step_id: ID of the step (optional)
            - started: Boolean indicating if started
            - duration: Duration in seconds
            - timestamp: ISO format timestamp

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured")
            return False

        user_group_name = f"ccrv_user_{user_id}"

        message = {"type": "timekeeper_updated", **timekeeper_data}

        async_to_sync(channel_layer.group_send)(user_group_name, message)
        logger.debug(f"WebSocket timekeeper_updated sent to user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WebSocket timekeeper_updated to user {user_id}: {e}")
        return False


def format_duration(seconds):
    """
    Format duration in seconds to human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        str: Formatted duration string
    """
    if not seconds:
        return "0s"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"
