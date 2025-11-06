"""
CCRV notification service for sending real-time notifications via WebSockets.

This module extends the base notification service for CCRV-specific features
like transcription updates.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


class CCRVNotificationService:
    """Service for sending CCRV-specific notifications via WebSockets."""

    def __init__(self):
        """Initialize the CCRV notification service with the channel layer."""
        self.channel_layer = get_channel_layer()

    def _send_to_group(self, group_name: str, message_type: str, data: Dict[str, Any]):
        """Send message to a channel group."""
        if not self.channel_layer:
            logger.warning("Channel layer not configured - cannot send WebSocket notification")
            return

        try:
            async_to_sync(self.channel_layer.group_send)(group_name, {"type": message_type, **data})
            logger.debug(f"CCRV notification sent to group {group_name}: {message_type}")
        except Exception as e:
            logger.error(f"Failed to send CCRV notification to group {group_name}: {e}")

    def notify_user(self, user_id: int, notification_type: str, message: str, **kwargs):
        """Send notification to a specific user via core WebSocket."""
        data = {
            "message": {
                "type": notification_type,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                **kwargs,
            }
        }
        self._send_to_group(f"user_{user_id}", "notification_message", data)

    def transcription_completed(
        self, user_id: int, annotation_id: int, language: str = None, has_translation: bool = False, **kwargs
    ):
        """Notify user that transcription has completed."""
        message = "Transcription completed"
        if language:
            message = f"Transcription completed (detected language: {language})"

        extra = {"annotation_id": annotation_id}
        if language:
            extra["language"] = language
        if has_translation:
            extra["has_translation"] = has_translation

        self.notify_user(user_id, "transcription.completed", message, **extra)

    def transcription_failed(self, user_id: int, annotation_id: int, error: str, **kwargs):
        """Notify user that transcription has failed."""
        message = f"Transcription failed: {error}"
        self.notify_user(user_id, "transcription.failed", message, annotation_id=annotation_id, error=error)

    def transcription_started(self, user_id: int, annotation_id: int, **kwargs):
        """Notify user that transcription has started."""
        message = "Transcription started"
        self.notify_user(user_id, "transcription.started", message, annotation_id=annotation_id)


ccrv_notification_service = CCRVNotificationService()
