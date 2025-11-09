"""
WebSocket consumers for CCMC (Mint Chocolate) real-time notifications and messaging.
"""

import json
import logging

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from ccmc.turn_credentials import get_ice_servers

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


class WebRTCSignalConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for WebRTC signalling.

    Handles peer-to-peer signalling for video calls, audio calls,
    and screen sharing in CCMC communication sessions.

    Message types:
    - check: Discover available peers
    - offer: Send WebRTC offer (SDP)
    - answer: Send WebRTC answer (SDP)
    - ice_candidate: Exchange ICE candidates
    - peer_state: Update peer connection state
    """

    async def connect(self):
        """Handle WebSocket connection for WebRTC signalling."""
        self.user = self.scope["user"]

        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            logger.warning("WebRTC signalling connection rejected - user not authenticated")
            await self.close(code=4001)
            return

        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]

        session_exists = await self.check_session_exists(self.session_id)
        if not session_exists:
            logger.warning(f"WebRTC session {self.session_id} not found")
            await self.close(code=4004)
            return

        has_access = await self.check_session_access(self.session_id, self.user)
        if not has_access:
            logger.warning(f"User {self.user.username} denied access to session {self.session_id}")
            await self.close(code=4003)
            return

        query_string = self.scope.get("query_string", b"").decode()
        query_params = dict(param.split("=") for param in query_string.split("&") if "=" in param)
        client_peer_id = query_params.get("client_peer_id")

        self.peer = await self.get_or_create_peer(self.session_id, self.user, client_peer_id=client_peer_id)
        self.peer_id = str(self.peer.id)
        self.channel_id = f"webrtc_{self.peer_id}"

        self.session_group = f"webrtc_session_{self.session_id}"

        await self.channel_layer.group_add(self.session_group, self.channel_name)
        await self.channel_layer.group_add(self.channel_id, self.channel_name)

        await self.accept()

        ice_servers = await self.get_ice_servers_for_user(self.user.username)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.established",
                    "message": "WebRTC signalling connection established",
                    "peer_id": self.peer_id,
                    "client_peer_id": self.peer.client_peer_id,
                    "session_id": str(self.session_id),
                    "user_id": self.user.id,
                    "username": self.user.username,
                    "ice_servers": ice_servers,
                    "is_reconnection": client_peer_id is not None and self.peer.client_peer_id == client_peer_id,
                }
            )
        )

        await self.channel_layer.group_send(
            self.session_group,
            {
                "type": "peer.joined",
                "peer_id": self.peer_id,
                "user_id": self.user.id,
                "username": self.user.username,
            },
        )

        logger.info(f"User {self.user.username} connected to WebRTC session {self.session_id}")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "session_group"):
            await self.channel_layer.group_send(
                self.session_group,
                {
                    "type": "peer.left",
                    "peer_id": self.peer_id,
                    "user_id": self.user.id,
                    "username": self.user.username,
                },
            )
            await self.channel_layer.group_discard(self.session_group, self.channel_name)

        if hasattr(self, "channel_id"):
            await self.channel_layer.group_discard(self.channel_id, self.channel_name)

        if hasattr(self, "peer"):
            await self.update_peer_state(self.peer.id, "disconnected")

        logger.info(f"User {self.user.username} disconnected from WebRTC session {self.session_id}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type")

            if not message_type:
                await self.send_error("Missing message type")
                return

            handler_map = {
                "check": self.handle_check,
                "offer": self.handle_offer,
                "answer": self.handle_answer,
                "ice_candidate": self.handle_ice_candidate,
                "peer_state": self.handle_peer_state,
                "heartbeat": self.handle_heartbeat,
            }

            handler = handler_map.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f"Unknown message type: {message_type}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            await self.send_error("Invalid JSON")
        except Exception as e:
            logger.error(f"Error handling WebRTC message: {e}", exc_info=True)
            await self.send_error(f"Internal error: {str(e)}")

    async def handle_check(self, data):
        """
        Handle peer discovery check.

        Broadcasts presence to all other peers in the session.
        """
        peer_role = data.get("peer_role", "participant")

        await self.update_peer_role(self.peer.id, peer_role)

        peers = await self.get_session_peers(self.session_id, exclude_peer_id=self.peer_id)

        for peer_info in peers:
            await self.channel_layer.group_send(
                f"webrtc_{peer_info['id']}",
                {
                    "type": "peer.check",
                    "from_peer_id": self.peer_id,
                    "from_user_id": self.user.id,
                    "from_username": self.user.username,
                    "peer_role": peer_role,
                },
            )

        await self.send(
            text_data=json.dumps(
                {
                    "type": "check.response",
                    "peers": peers,
                }
            )
        )

    async def handle_offer(self, data):
        """
        Handle WebRTC offer.

        Relays SDP offer to target peer.
        """
        to_peer_id = data.get("to_peer_id")
        sdp = data.get("sdp")

        if not to_peer_id or not sdp:
            await self.send_error("Missing to_peer_id or sdp")
            return

        await self.store_signal(self.session_id, self.peer_id, to_peer_id, "offer", sdp)

        await self.channel_layer.group_send(
            f"webrtc_{to_peer_id}",
            {
                "type": "webrtc.offer",
                "from_peer_id": self.peer_id,
                "from_user_id": self.user.id,
                "from_username": self.user.username,
                "sdp": sdp,
            },
        )

        logger.info(f"Relayed offer from {self.peer_id} to {to_peer_id}")

    async def handle_answer(self, data):
        """
        Handle WebRTC answer.

        Relays SDP answer to target peer.
        """
        to_peer_id = data.get("to_peer_id")
        sdp = data.get("sdp")

        if not to_peer_id or not sdp:
            await self.send_error("Missing to_peer_id or sdp")
            return

        await self.store_signal(self.session_id, self.peer_id, to_peer_id, "answer", sdp)

        await self.channel_layer.group_send(
            f"webrtc_{to_peer_id}",
            {
                "type": "webrtc.answer",
                "from_peer_id": self.peer_id,
                "from_user_id": self.user.id,
                "from_username": self.user.username,
                "sdp": sdp,
            },
        )

        logger.info(f"Relayed answer from {self.peer_id} to {to_peer_id}")

    async def handle_ice_candidate(self, data):
        """
        Handle ICE candidate.

        Relays ICE candidate to target peer.
        """
        to_peer_id = data.get("to_peer_id")
        candidate = data.get("candidate")

        if not to_peer_id or not candidate:
            await self.send_error("Missing to_peer_id or candidate")
            return

        await self.store_signal(self.session_id, self.peer_id, to_peer_id, "ice_candidate", candidate)

        await self.channel_layer.group_send(
            f"webrtc_{to_peer_id}",
            {
                "type": "webrtc.ice_candidate",
                "from_peer_id": self.peer_id,
                "from_user_id": self.user.id,
                "from_username": self.user.username,
                "candidate": candidate,
            },
        )

    async def handle_peer_state(self, data):
        """
        Handle peer state update.

        Updates connection state, media capabilities.
        """
        state = data.get("connection_state")
        has_video = data.get("has_video")
        has_audio = data.get("has_audio")
        has_screen_share = data.get("has_screen_share")

        if state:
            await self.update_peer_state(self.peer.id, state)

        if has_video is not None or has_audio is not None or has_screen_share is not None:
            await self.update_peer_media(
                self.peer.id,
                has_video=has_video,
                has_audio=has_audio,
                has_screen_share=has_screen_share,
            )

        await self.channel_layer.group_send(
            self.session_group,
            {
                "type": "peer.state_update",
                "peer_id": self.peer_id,
                "user_id": self.user.id,
                "username": self.user.username,
                "connection_state": state,
                "has_video": has_video,
                "has_audio": has_audio,
                "has_screen_share": has_screen_share,
            },
        )

    async def handle_heartbeat(self, data):
        """
        Handle heartbeat/ping from client.

        Updates last_seen_at to track active connections.
        """
        await self.update_peer_last_seen(self.peer.id)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "heartbeat.response",
                    "timestamp": timezone.now().isoformat(),
                }
            )
        )

    async def peer_check(self, event):
        """Handle incoming peer check."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "peer.check",
                    "from_peer_id": event["from_peer_id"],
                    "from_user_id": event["from_user_id"],
                    "from_username": event["from_username"],
                    "peer_role": event["peer_role"],
                }
            )
        )

    async def webrtc_offer(self, event):
        """Handle incoming WebRTC offer."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "offer",
                    "from_peer_id": event["from_peer_id"],
                    "from_user_id": event["from_user_id"],
                    "from_username": event["from_username"],
                    "sdp": event["sdp"],
                }
            )
        )

    async def webrtc_answer(self, event):
        """Handle incoming WebRTC answer."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "answer",
                    "from_peer_id": event["from_peer_id"],
                    "from_user_id": event["from_user_id"],
                    "from_username": event["from_username"],
                    "sdp": event["sdp"],
                }
            )
        )

    async def webrtc_ice_candidate(self, event):
        """Handle incoming ICE candidate."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "ice_candidate",
                    "from_peer_id": event["from_peer_id"],
                    "from_user_id": event["from_user_id"],
                    "from_username": event["from_username"],
                    "candidate": event["candidate"],
                }
            )
        )

    async def peer_state_update(self, event):
        """Handle peer state update broadcast."""
        if event["peer_id"] != self.peer_id:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "peer.state_update",
                        "peer_id": event["peer_id"],
                        "user_id": event["user_id"],
                        "username": event["username"],
                        "connection_state": event.get("connection_state"),
                        "has_video": event.get("has_video"),
                        "has_audio": event.get("has_audio"),
                        "has_screen_share": event.get("has_screen_share"),
                    }
                )
            )

    async def peer_joined(self, event):
        """Handle peer joined notification."""
        if event["peer_id"] != self.peer_id:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "peer.joined",
                        "peer_id": event["peer_id"],
                        "user_id": event["user_id"],
                        "username": event["username"],
                    }
                )
            )

    async def peer_left(self, event):
        """Handle peer left notification."""
        if event["peer_id"] != self.peer_id:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "peer.left",
                        "peer_id": event["peer_id"],
                        "user_id": event["user_id"],
                        "username": event["username"],
                    }
                )
            )

    async def send_error(self, message):
        """Send error message to client."""
        await self.send(text_data=json.dumps({"type": "error", "message": message}))

    @database_sync_to_async
    def check_session_exists(self, session_id):
        """Check if WebRTC session exists."""
        from .models import WebRTCSession

        return WebRTCSession.objects.filter(id=session_id).exists()

    @database_sync_to_async
    def check_session_access(self, session_id, user):
        """Check if user has access to the WebRTC session."""
        from .models import WebRTCSession

        try:
            session = WebRTCSession.objects.prefetch_related("ccrv_sessions").get(id=session_id)

            ccrv_sessions = session.ccrv_sessions.all()
            if not ccrv_sessions.exists():
                return session.initiated_by == user

            for ccrv_session in ccrv_sessions:
                if ccrv_session.can_view(user):
                    return True

            return False

        except WebRTCSession.DoesNotExist:
            return False

    @database_sync_to_async
    def get_or_create_peer(self, session_id, user, client_peer_id=None):
        """
        Get existing or create new WebRTCPeer for this connection.

        If client_peer_id is provided, attempts to reuse existing disconnected peer
        for reconnection. Otherwise creates a new peer with a generated client_peer_id.
        """
        import uuid

        from .models import WebRTCPeer, WebRTCSession

        session = WebRTCSession.objects.get(id=session_id)

        if client_peer_id:
            existing_peer = WebRTCPeer.objects.filter(
                session=session, user=user, client_peer_id=client_peer_id, connection_state="disconnected"
            ).first()

            if existing_peer:
                existing_peer.channel_id = f"webrtc_{uuid.uuid4()}"
                existing_peer.connection_state = "connecting"
                existing_peer.last_seen_at = timezone.now()
                existing_peer.save(update_fields=["channel_id", "connection_state", "last_seen_at"])
                return existing_peer

        if not client_peer_id:
            client_peer_id = str(uuid.uuid4())

        peer = WebRTCPeer.objects.create(
            session=session,
            user=user,
            client_peer_id=client_peer_id,
            channel_id=f"webrtc_{uuid.uuid4()}",
            connection_state="connecting",
        )

        return peer

    @database_sync_to_async
    def get_session_peers(self, session_id, exclude_peer_id=None, include_disconnected=False):
        """
        Get all peers in the session.

        Args:
            session_id: WebRTC session ID
            exclude_peer_id: Peer ID to exclude from results
            include_disconnected: If False, only returns connecting/connected peers
        """
        from .models import WebRTCPeer

        peers = WebRTCPeer.objects.filter(session_id=session_id).select_related("user")

        if not include_disconnected:
            peers = peers.filter(connection_state__in=["connecting", "connected"])

        if exclude_peer_id:
            peers = peers.exclude(id=exclude_peer_id)

        return [
            {
                "id": str(peer.id),
                "user_id": peer.user.id,
                "username": peer.user.username,
                "peer_role": peer.peer_role,
                "connection_state": peer.connection_state,
                "has_video": peer.has_video,
                "has_audio": peer.has_audio,
                "has_screen_share": peer.has_screen_share,
            }
            for peer in peers
        ]

    @database_sync_to_async
    def update_peer_state(self, peer_id, state):
        """Update peer connection state."""
        from .models import WebRTCPeer

        WebRTCPeer.objects.filter(id=peer_id).update(connection_state=state)

    @database_sync_to_async
    def update_peer_role(self, peer_id, role):
        """Update peer role."""
        from .models import WebRTCPeer

        WebRTCPeer.objects.filter(id=peer_id).update(peer_role=role)

    @database_sync_to_async
    def update_peer_media(self, peer_id, has_video=None, has_audio=None, has_screen_share=None):
        """Update peer media capabilities."""
        from .models import WebRTCPeer

        update_fields = {}
        if has_video is not None:
            update_fields["has_video"] = has_video
        if has_audio is not None:
            update_fields["has_audio"] = has_audio
        if has_screen_share is not None:
            update_fields["has_screen_share"] = has_screen_share

        if update_fields:
            WebRTCPeer.objects.filter(id=peer_id).update(**update_fields)

    @database_sync_to_async
    def update_peer_last_seen(self, peer_id):
        """Update peer last_seen_at timestamp."""
        from .models import WebRTCPeer

        WebRTCPeer.objects.filter(id=peer_id).update(last_seen_at=timezone.now())

    @database_sync_to_async
    def get_ice_servers_for_user(self, username):
        """Get ICE server configuration including TURN credentials."""
        return get_ice_servers(username, include_stun=True)

    @database_sync_to_async
    def store_signal(self, session_id, from_peer_id, to_peer_id, signal_type, signal_data):
        """Store signalling message in database."""
        from .models import WebRTCPeer, WebRTCSession, WebRTCSignal

        try:
            session = WebRTCSession.objects.get(id=session_id)
            from_peer = WebRTCPeer.objects.get(id=from_peer_id)
            to_peer = WebRTCPeer.objects.get(id=to_peer_id)

            WebRTCSignal.objects.create(
                session=session,
                from_peer=from_peer,
                to_peer=to_peer,
                signal_type=signal_type,
                signal_data=signal_data,
            )
        except Exception as e:
            logger.error(f"Error storing signal: {e}")
