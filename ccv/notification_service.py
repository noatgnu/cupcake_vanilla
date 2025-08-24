"""
Notification service for sending real-time notifications via WebSockets.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending real-time notifications via WebSockets."""

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

    def notify_lab_group(self, lab_group_id: int, notification_type: str, message: str, **kwargs):
        """Send notification to all members of a lab group."""
        data = {
            "lab_group_id": lab_group_id,
            "action": notification_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self._send_to_group(f"lab_group_{lab_group_id}", "lab_group_update", data)

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

    # Specific notification methods for common actions

    def metadata_table_created(self, table_id: int, table_name: str, owner_id: int, lab_group_id: Optional[int] = None):
        """Notify about metadata table creation."""
        message = f"New metadata table '{table_name}' created"

        # Notify table owner
        self.notify_user(owner_id, "metadata_table.created", message, table_id=table_id, table_name=table_name)

        # Notify lab group if applicable
        if lab_group_id:
            self.notify_lab_group(lab_group_id, "table_created", message, table_id=table_id, table_name=table_name)

    def metadata_table_updated(
        self, table_id: int, table_name: str, owner_id: int, lab_group_id: Optional[int] = None, action: str = "updated"
    ):
        """Notify about metadata table updates."""
        message = f"Metadata table '{table_name}' {action}"

        # Send to table-specific channel for real-time updates
        data = {
            "table_id": table_id,
            "action": action,
            "message": message,
            "user": owner_id,
            "timestamp": datetime.now().isoformat(),
        }
        self._send_to_group(f"metadata_table_{table_id}", "metadata_table_update", data)

        # Notify owner
        self.notify_user(
            owner_id, "metadata_table.updated", message, table_id=table_id, table_name=table_name, action=action
        )

        # Notify lab group if applicable
        if lab_group_id:
            self.notify_lab_group(
                lab_group_id, "table_updated", message, table_id=table_id, table_name=table_name, action=action
            )

    def metadata_table_deleted(self, table_name: str, owner_id: int, lab_group_id: Optional[int] = None):
        """Notify about metadata table deletion."""
        message = f"Metadata table '{table_name}' deleted"

        # Notify owner
        self.notify_user(owner_id, "metadata_table.deleted", message, table_name=table_name)

        # Notify lab group if applicable
        if lab_group_id:
            self.notify_lab_group(lab_group_id, "table_deleted", message, table_name=table_name)

    def lab_group_member_added(self, lab_group_id: int, lab_group_name: str, new_member_id: int, added_by_id: int):
        """Notify about new lab group member."""
        message = f"New member added to lab group '{lab_group_name}'"

        # Notify the new member
        self.notify_user(
            new_member_id,
            "lab_group.member_added",
            f"You've been added to lab group '{lab_group_name}'",
            lab_group_id=lab_group_id,
            lab_group_name=lab_group_name,
        )

        # Notify existing lab group members
        self.notify_lab_group(
            lab_group_id, "member_added", message, new_member_id=new_member_id, added_by_id=added_by_id
        )

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


# Global instance
notification_service = NotificationService()
