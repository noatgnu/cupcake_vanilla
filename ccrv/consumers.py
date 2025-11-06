"""
WebSocket consumers for CCRV real-time events.

Only contains module-specific consumers. General notifications use CCC's core consumer.
"""

import json
import logging

from django.contrib.auth.models import AnonymousUser

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class TimeKeeperConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for TimeKeeper real-time updates.

    Handles:
    - TimeKeeper start/stop events
    - Timer status updates
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]

        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.user_group_name = f"ccrv_user_{self.user.id}"

        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "ccrv.connection.established",
                    "message": "CCRV WebSocket connection established",
                    "userId": self.user.id,
                    "username": self.user.username,
                }
            )
        )

        logger.info(f"CCRV WebSocket connected for user {self.user.id}")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)
            logger.info(f"CCRV WebSocket disconnected for user {self.user.id}")

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

    async def timekeeper_started(self, event):
        """Handle timekeeper started event."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "timekeeper.started",
                    "timekeeperId": event["timekeeper_id"],
                    "name": event.get("name"),
                    "sessionId": event.get("session_id"),
                    "stepId": event.get("step_id"),
                    "startTime": event["start_time"],
                    "timestamp": event["timestamp"],
                }
            )
        )

    async def timekeeper_stopped(self, event):
        """Handle timekeeper stopped event."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "timekeeper.stopped",
                    "timekeeperId": event["timekeeper_id"],
                    "name": event.get("name"),
                    "sessionId": event.get("session_id"),
                    "stepId": event.get("step_id"),
                    "duration": event.get("duration"),
                    "durationFormatted": event.get("duration_formatted"),
                    "timestamp": event["timestamp"],
                }
            )
        )

    async def timekeeper_updated(self, event):
        """Handle timekeeper updated event."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "timekeeper.updated",
                    "timekeeperId": event["timekeeper_id"],
                    "name": event.get("name"),
                    "sessionId": event.get("session_id"),
                    "stepId": event.get("step_id"),
                    "started": event.get("started"),
                    "duration": event.get("duration"),
                    "timestamp": event["timestamp"],
                }
            )
        )
