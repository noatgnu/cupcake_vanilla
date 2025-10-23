"""
Base notification service for sending real-time notifications via WebSockets.

This module provides the core notification infrastructure that can be extended
by specific applications for their domain-specific needs.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from django.contrib.auth import get_user_model

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

User = get_user_model()
logger = logging.getLogger(__name__)


class BaseNotificationService:
    """Base service for sending real-time notifications via WebSockets."""

    def __init__(self):
        """
        Initialize the notification service with the channel layer.
        """
        self.channel_layer = get_channel_layer()

    def _send_to_group(self, group_name: str, message_type: str, data: Dict[str, Any]):
        """Send message to a channel group."""
        if not self.channel_layer:
            logger.warning("Channel layer not configured - cannot send WebSocket notification")
            return

        try:
            async_to_sync(self.channel_layer.group_send)(group_name, {"type": message_type, **data})
            logger.debug(f"Notification sent to group {group_name}: {message_type}")
        except Exception as e:
            logger.error(f"Failed to send notification to group {group_name}: {e}")

    def notify_user(self, user_id: int, notification_type: str, message: str, **kwargs):
        """Send notification to a specific user."""
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

    def notify_users(self, user_ids: List[int], notification_type: str, message: str, **kwargs):
        """Send notification to multiple users."""
        for user_id in user_ids:
            self.notify_user(user_id, notification_type, message, **kwargs)

    def notify_group(self, group_name: str, notification_type: str, message: str, **kwargs):
        """Send notification to a named group."""
        data = {
            "action": notification_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self._send_to_group(group_name, "group_notification", data)

    def notify_global(self, level: str, title: str, message: str, **kwargs):
        """Send system-wide notification to all connected users."""
        data = {
            "level": level,  # info, warning, error, success
            "title": title,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self._send_to_group("global_notifications", "system_notification", data)

    def notify_admins(self, message: str, level: str = "info", **kwargs):
        """Send notification to admin users only."""
        data = {"message": message, "level": level, "timestamp": datetime.now().isoformat(), **kwargs}
        self._send_to_group("admin_notifications", "admin_notification", data)

    # Generic notification methods for common actions

    def file_upload_completed(self, user_id: int, filename: str, file_size: int = None):
        """Notify about successful file upload."""
        message = f"File '{filename}' uploaded successfully"
        extra = {"filename": filename}
        if file_size:
            extra["file_size"] = file_size

        self.notify_user(user_id, "file.upload.completed", message, **extra)

    def file_upload_failed(self, user_id: int, filename: str, error: str):
        """Notify about failed file upload."""
        message = f"File '{filename}' upload failed: {error}"
        self.notify_user(user_id, "file.upload.failed", message, filename=filename, error=error)

    def data_processing_completed(self, user_id: int, job_id: str, job_type: str):
        """Notify about completed data processing job."""
        message = f"Data processing job ({job_type}) completed"
        self.notify_user(user_id, "data.processing.completed", message, job_id=job_id, job_type=job_type)

    def data_processing_failed(self, user_id: int, job_id: str, job_type: str, error: str):
        """Notify about failed data processing job."""
        message = f"Data processing job ({job_type}) failed: {error}"
        self.notify_user(user_id, "data.processing.failed", message, job_id=job_id, job_type=job_type, error=error)

    def maintenance_notification(self, title: str, message: str, level: str = "warning"):
        """Send maintenance notification to all users."""
        self.notify_global(level, title, message, category="maintenance")

    def entity_created(self, entity_type: str, entity_id: int, entity_name: str, owner_id: int, **kwargs):
        """Generic notification for entity creation."""
        message = f"New {entity_type} '{entity_name}' created"
        self.notify_user(
            owner_id, f"{entity_type}.created", message, entity_id=entity_id, entity_name=entity_name, **kwargs
        )

    def entity_updated(
        self, entity_type: str, entity_id: int, entity_name: str, owner_id: int, action: str = "updated", **kwargs
    ):
        """Generic notification for entity updates."""
        message = f"{entity_type.title()} '{entity_name}' {action}"
        self.notify_user(
            owner_id,
            f"{entity_type}.updated",
            message,
            entity_id=entity_id,
            entity_name=entity_name,
            action=action,
            **kwargs,
        )

    def entity_deleted(self, entity_type: str, entity_name: str, owner_id: int, **kwargs):
        """Generic notification for entity deletion."""
        message = f"{entity_type.title()} '{entity_name}' deleted"
        self.notify_user(owner_id, f"{entity_type}.deleted", message, entity_name=entity_name, **kwargs)

    def send_to_entity_channel(
        self, entity_type: str, entity_id: int, action: str, message: str, user_id: int, **kwargs
    ):
        """Send notification to entity-specific channel for real-time updates."""
        data = {
            "entity_id": entity_id,
            "action": action,
            "message": message,
            "user": user_id,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self._send_to_group(f"{entity_type}_{entity_id}", f"{entity_type}_update", data)

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


# Global base instance
base_notification_service = BaseNotificationService()
