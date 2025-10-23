"""
WebSocket consumer for CCM real-time events.
"""

import json
import logging

from django.contrib.auth.models import AnonymousUser

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for CCM notifications.

    Handles:
    - Transcription start/complete/fail events for instrument/maintenance annotations
    - Other CCM-specific notifications
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]

        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.user_group_name = f"ccm_user_{self.user.id}"

        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.established",
                    "message": "CCM notifications WebSocket connection established",
                    "userId": self.user.id,
                    "username": self.user.username,
                }
            )
        )

        logger.info(f"CCM notifications WebSocket connected for user {self.user.id}")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)
            logger.info(f"CCM notifications WebSocket disconnected for user {self.user.id}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages from client."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type")

            if message_type == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))

        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    async def notification_message(self, event):
        """Handle notification messages sent to groups."""
        await self.send(text_data=json.dumps(event["message"]))
