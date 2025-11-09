"""
RQ tasks for WebRTC session cleanup operations.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from django_rq import job

logger = logging.getLogger(__name__)


@job("default", timeout=300)
def cleanup_stale_peers(timeout_minutes: int = 5):
    """
    Clean up stale WebRTC peers that haven't sent heartbeat.

    Marks peers as disconnected if their last_seen_at is older than timeout_minutes
    and broadcasts peer.left events to notify active peers.
    This handles cases where WebSocket disconnect wasn't properly called (crashes, network issues).

    Args:
        timeout_minutes: Minutes of inactivity before considering a peer stale
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from ccmc.models import WebRTCPeer

    timeout_threshold = timezone.now() - timedelta(minutes=timeout_minutes)

    stale_peers = WebRTCPeer.objects.filter(
        connection_state__in=["connecting", "connected"], last_seen_at__lt=timeout_threshold
    ).select_related("user", "session")

    count = 0
    channel_layer = get_channel_layer()

    for peer in stale_peers:
        session_group = f"webrtc_session_{peer.session.id}"

        async_to_sync(channel_layer.group_send)(
            session_group,
            {
                "type": "peer.left",
                "peer_id": str(peer.id),
                "user_id": peer.user.id,
                "username": peer.user.username,
            },
        )

        peer.connection_state = "disconnected"
        peer.save(update_fields=["connection_state"])
        count += 1

    if count > 0:
        logger.info(f"Marked {count} stale peers as disconnected and broadcasted peer.left events")

    return {"stale_peers_cleaned": count, "timeout_minutes": timeout_minutes}


@job("default", timeout=300)
def cleanup_disconnected_peers(hours: int = 1):
    """
    Delete disconnected peers that have been inactive for the specified hours.

    Permanently removes peer records to prevent database bloat while keeping
    recent disconnected peers for potential reconnection.

    Args:
        hours: Number of hours to keep disconnected peers for reconnection
    """
    from ccmc.models import WebRTCPeer

    cutoff_time = timezone.now() - timedelta(hours=hours)

    old_disconnected_peers = WebRTCPeer.objects.filter(connection_state="disconnected", last_seen_at__lt=cutoff_time)

    count = old_disconnected_peers.count()

    if count > 0:
        old_disconnected_peers.delete()
        logger.info(f"Deleted {count} old disconnected peers")

    return {"peers_deleted": count, "retention_hours": hours}


@job("default", timeout=300)
def cleanup_old_webrtc_sessions(days: int = 7):
    """
    Clean up old ended WebRTC sessions and their peers.

    Deletes sessions that ended more than specified days ago.

    Args:
        days: Number of days to keep ended sessions
    """
    from ccmc.models import WebRTCSession

    cutoff_date = timezone.now() - timedelta(days=days)

    old_sessions = WebRTCSession.objects.filter(session_status="ended", ended_at__lt=cutoff_date)

    count = old_sessions.count()

    if count > 0:
        old_sessions.delete()
        logger.info(f"Deleted {count} old WebRTC sessions")

    return {"sessions_deleted": count, "retention_days": days}
