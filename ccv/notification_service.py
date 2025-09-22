"""
CCV-specific notification service extending the base notification infrastructure.
"""

from datetime import datetime
from typing import Optional

from ccc.notification_service import BaseNotificationService


class NotificationService(BaseNotificationService):
    """CCV-specific notification service extending base functionality."""

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

    # CCV-specific notification methods

    def metadata_table_created(self, table_id: int, table_name: str, owner_id: int, lab_group_id: Optional[int] = None):
        """Notify about metadata table creation."""
        # Use base service generic method
        self.entity_created("metadata_table", table_id, table_name, owner_id, table_id=table_id)

        # Notify lab group if applicable
        if lab_group_id:
            message = f"New metadata table '{table_name}' created"
            self.notify_lab_group(lab_group_id, "table_created", message, table_id=table_id, table_name=table_name)

    def metadata_table_updated(
        self, table_id: int, table_name: str, owner_id: int, lab_group_id: Optional[int] = None, action: str = "updated"
    ):
        """Notify about metadata table updates."""
        # Send to table-specific channel for real-time updates
        self.send_to_entity_channel(
            "metadata_table",
            table_id,
            action,
            f"Metadata table '{table_name}' {action}",
            owner_id,
            table_id=table_id,
            table_name=table_name,
        )

        # Use base service generic method
        self.entity_updated("metadata_table", table_id, table_name, owner_id, action, table_id=table_id)

        # Notify lab group if applicable
        if lab_group_id:
            message = f"Metadata table '{table_name}' {action}"
            self.notify_lab_group(
                lab_group_id, "table_updated", message, table_id=table_id, table_name=table_name, action=action
            )

    def metadata_table_deleted(self, table_name: str, owner_id: int, lab_group_id: Optional[int] = None):
        """Notify about metadata table deletion."""
        # Use base service generic method
        self.entity_deleted("metadata_table", table_name, owner_id)

        # Notify lab group if applicable
        if lab_group_id:
            message = f"Metadata table '{table_name}' deleted"
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


# Global instance
notification_service = NotificationService()
