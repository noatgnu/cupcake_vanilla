"""
WebSocket consumers for real-time notifications in CUPCAKE Vanilla.
"""

import json
import logging

from django.contrib.auth.models import AnonymousUser

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications.

    Handles user-specific notifications and system-wide broadcasts.
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]

        # Reject anonymous users
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            logger.warning("WebSocket connection rejected - user not authenticated")
            await self.close(code=4001)  # Custom code for authentication error
            return

        # Create user-specific group name
        self.user_group_name = f"user_{self.user.id}"
        self.lab_groups = []

        # Get user's lab groups for group notifications
        self.lab_groups = await self.get_user_lab_groups()

        # Join user-specific group
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        # Join lab group channels
        for lab_group_id in self.lab_groups:
            lab_group_name = f"lab_group_{lab_group_id}"
            await self.channel_layer.group_add(lab_group_name, self.channel_name)

        # Join global notifications group
        await self.channel_layer.group_add("global_notifications", self.channel_name)

        await self.accept()

        # Send welcome message
        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.established",
                    "message": "WebSocket connection established",
                    "user_id": self.user.id,
                    "username": self.user.username,
                    "lab_groups": self.lab_groups,
                }
            )
        )

        logger.info(f"WebSocket connected for user {self.user.username} (ID: {self.user.id})")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user") and self.user.is_authenticated:
            # Leave user-specific group
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

            # Leave lab group channels
            for lab_group_id in self.lab_groups:
                lab_group_name = f"lab_group_{lab_group_id}"
                await self.channel_layer.group_discard(lab_group_name, self.channel_name)

            # Leave global notifications group
            await self.channel_layer.group_discard("global_notifications", self.channel_name)

            logger.info(f"WebSocket disconnected for user {self.user.username} (code: {close_code})")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type", "unknown")

            if message_type == "subscribe":
                # Handle subscription to specific notification types
                await self.handle_subscription(data)
            else:
                logger.warning(f"Unknown message type received: {message_type}")

        except json.JSONDecodeError:
            logger.error("Invalid JSON received in WebSocket message")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    async def handle_subscription(self, data):
        """Handle subscription requests."""
        subscription_type = data.get("subscription_type")

        if subscription_type == "metadata_table_updates":
            table_id = data.get("table_id")
            if table_id:
                group_name = f"metadata_table_{table_id}"
                await self.channel_layer.group_add(group_name, self.channel_name)
                await self.send(
                    text_data=json.dumps(
                        {"type": "subscription.confirmed", "subscription_type": subscription_type, "table_id": table_id}
                    )
                )
        elif subscription_type == "async_task_updates":
            # Subscribe to user's async task updates
            task_group_name = f"async_tasks_user_{self.user.id}"
            await self.channel_layer.group_add(task_group_name, self.channel_name)
            await self.send(
                text_data=json.dumps({"type": "subscription.confirmed", "subscription_type": subscription_type})
            )

    # Group message handlers
    async def notification_message(self, event):
        """Handle notification messages sent to groups."""
        await self.send(text_data=json.dumps(event["message"]))

    async def metadata_table_update(self, event):
        """Handle metadata table update notifications."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "metadata_table.update",
                    "table_id": event["table_id"],
                    "action": event["action"],
                    "message": event["message"],
                    "user": event.get("user"),
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def lab_group_update(self, event):
        """Handle lab group update notifications."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "lab_group.update",
                    "lab_group_id": event["lab_group_id"],
                    "action": event["action"],
                    "message": event["message"],
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def system_notification(self, event):
        """Handle system-wide notifications."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "system.notification",
                    "level": event.get("level", "info"),
                    "title": event["title"],
                    "message": event["message"],
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def async_task_update(self, event):
        """Handle async task status updates."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "async_task.update",
                    "task_id": event["task_id"],
                    "status": event["status"],
                    "progress_percentage": event.get("progress_percentage"),
                    "progress_description": event.get("progress_description"),
                    "error_message": event.get("error_message"),
                    "result": event.get("result"),
                    "download_url": event.get("download_url"),
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    @database_sync_to_async
    def get_user_lab_groups(self):
        """Get user's lab group IDs."""
        try:
            # Import here to avoid circular imports
            from ccv.models import LabGroup

            # Get lab groups where user is member or admin
            lab_group_ids = list(LabGroup.objects.filter(members=self.user).values_list("id", flat=True))

            return lab_group_ids
        except Exception as e:
            logger.error(f"Error getting user lab groups: {e}")
            return []


class AdminNotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for admin-level notifications and monitoring.
    """

    async def connect(self):
        """Handle WebSocket connection for admin users only."""
        self.user = self.scope["user"]

        # Only allow authenticated admin users
        if (
            isinstance(self.user, AnonymousUser)
            or not self.user.is_authenticated
            or not (self.user.is_staff or self.user.is_superuser)
        ):
            logger.warning("Admin WebSocket connection rejected - insufficient permissions")
            await self.close(code=4003)  # Custom code for permission error
            return

        # Join admin notifications group
        await self.channel_layer.group_add("admin_notifications", self.channel_name)

        await self.accept()

        # Send admin welcome message
        await self.send(
            text_data=json.dumps(
                {
                    "type": "admin.connection.established",
                    "message": "Admin WebSocket connection established",
                    "user_id": self.user.id,
                    "username": self.user.username,
                    "permissions": {"is_staff": self.user.is_staff, "is_superuser": self.user.is_superuser},
                }
            )
        )

        logger.info(f"Admin WebSocket connected for user {self.user.username}")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user") and self.user.is_authenticated:
            await self.channel_layer.group_discard("admin_notifications", self.channel_name)
            logger.info(f"Admin WebSocket disconnected for user {self.user.username}")

    async def receive(self, text_data):
        """Handle incoming admin WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type", "unknown")

            if message_type == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
            elif message_type == "broadcast_system_message":
                # Allow admins to broadcast system messages
                await self.broadcast_system_message(data)

        except json.JSONDecodeError:
            logger.error("Invalid JSON received in admin WebSocket message")
        except Exception as e:
            logger.error(f"Error processing admin WebSocket message: {e}")

    async def broadcast_system_message(self, data):
        """Broadcast system message to all connected users."""
        if not (self.user.is_staff or self.user.is_superuser):
            return

        message = {
            "type": "system.notification",
            "level": data.get("level", "info"),
            "title": data.get("title", "System Notification"),
            "message": data.get("message", ""),
            "timestamp": data.get("timestamp"),
        }

        # Send to all users via global notifications group
        await self.channel_layer.group_send("global_notifications", {"type": "system_notification", **message})

    # Group message handlers
    async def admin_notification(self, event):
        """Handle admin-specific notifications."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "admin.notification",
                    "message": event["message"],
                    "level": event.get("level", "info"),
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def system_notification(self, event):
        """Handle system notifications for admins."""
        await self.send(text_data=json.dumps(event))
