"""
WebSocket consumers for CCMC (Mint Chocolate) real-time notifications and messaging.
"""

import json
import logging

from django.contrib.auth.models import AnonymousUser

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class CommunicationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for CCMC notifications and messages.

    Handles:
    - Real-time notification delivery
    - Message thread updates
    - Direct message notifications
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]

        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            logger.warning("CCMC WebSocket connection rejected - user not authenticated")
            await self.close(code=4001)
            return

        self.user_group_name = f"ccmc_user_{self.user.id}"
        self.message_threads = []

        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "ccmc.connection.established",
                    "message": "CCMC WebSocket connection established",
                    "user_id": self.user.id,
                    "username": self.user.username,
                }
            )
        )

        logger.info(f"CCMC WebSocket connected for user {self.user.username} (ID: {self.user.id})")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user") and self.user.is_authenticated:
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

            for thread_id in self.message_threads:
                thread_group_name = f"ccmc_thread_{thread_id}"
                await self.channel_layer.group_discard(thread_group_name, self.channel_name)

            logger.info(f"CCMC WebSocket disconnected for user {self.user.username} (code: {close_code})")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type", "unknown")

            if message_type == "subscribe_thread":
                await self.handle_thread_subscription(data)
            elif message_type == "unsubscribe_thread":
                await self.handle_thread_unsubscription(data)
            elif message_type == "mark_notification_read":
                await self.handle_mark_notification_read(data)
            elif message_type == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
            else:
                logger.warning(f"Unknown message type received: {message_type}")

        except json.JSONDecodeError:
            logger.error("Invalid JSON received in CCMC WebSocket message")
        except Exception as e:
            logger.error(f"Error processing CCMC WebSocket message: {e}")

    async def handle_thread_subscription(self, data):
        """Handle subscription to a message thread."""
        thread_id = data.get("thread_id")
        if thread_id:
            can_access = await self.check_thread_access(thread_id)
            if can_access:
                thread_group_name = f"ccmc_thread_{thread_id}"
                await self.channel_layer.group_add(thread_group_name, self.channel_name)
                self.message_threads.append(thread_id)
                await self.send(text_data=json.dumps({"type": "thread.subscription.confirmed", "thread_id": thread_id}))
                logger.info(f"User {self.user.username} subscribed to thread {thread_id}")
            else:
                await self.send(
                    text_data=json.dumps(
                        {"type": "thread.subscription.denied", "thread_id": thread_id, "error": "Access denied"}
                    )
                )

    async def handle_thread_unsubscription(self, data):
        """Handle unsubscription from a message thread."""
        thread_id = data.get("thread_id")
        if thread_id and thread_id in self.message_threads:
            thread_group_name = f"ccmc_thread_{thread_id}"
            await self.channel_layer.group_discard(thread_group_name, self.channel_name)
            self.message_threads.remove(thread_id)
            await self.send(text_data=json.dumps({"type": "thread.unsubscription.confirmed", "thread_id": thread_id}))
            logger.info(f"User {self.user.username} unsubscribed from thread {thread_id}")

    async def handle_mark_notification_read(self, data):
        """Handle marking a notification as read."""
        notification_id = data.get("notification_id")
        if notification_id:
            success = await self.mark_notification_read(notification_id)
            if success:
                await self.send(
                    text_data=json.dumps({"type": "notification.marked_read", "notification_id": notification_id})
                )

    @database_sync_to_async
    def check_thread_access(self, thread_id):
        """Check if user has access to a message thread."""
        try:
            from .models import MessageThread

            thread = MessageThread.objects.get(id=thread_id)
            return self.user in thread.participants.all()
        except Exception as e:
            logger.error(f"Error checking thread access: {e}")
            return False

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Mark a notification as read."""
        try:
            from .models import Notification

            notification = Notification.objects.get(id=notification_id, recipient=self.user)
            notification.mark_as_read()
            return True
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            return False

    async def new_notification(self, event):
        """Handle new notification events."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification.new",
                    "notification_id": event["notification_id"],
                    "title": event["title"],
                    "message": event["message"],
                    "notification_type": event["notification_type"],
                    "priority": event["priority"],
                    "data": event.get("data", {}),
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def new_message(self, event):
        """Handle new message events in subscribed threads."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "message.new",
                    "thread_id": event["thread_id"],
                    "message_id": event["message_id"],
                    "sender_id": event["sender_id"],
                    "sender_username": event["sender_username"],
                    "content": event["content"],
                    "message_type": event["message_type"],
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def thread_update(self, event):
        """Handle thread update events."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "thread.update",
                    "thread_id": event["thread_id"],
                    "action": event["action"],
                    "message": event.get("message", ""),
                    "timestamp": event.get("timestamp"),
                }
            )
        )

    async def notification_update(self, event):
        """Handle notification status update events."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification.update",
                    "notification_id": event["notification_id"],
                    "status": event["status"],
                    "timestamp": event.get("timestamp"),
                }
            )
        )
