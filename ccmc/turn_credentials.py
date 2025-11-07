"""
TURN server credential generation utility for CCMC WebRTC.

Generates time-limited credentials for TURN server access using HMAC-SHA1.
Based on RFC 5389 (TURN) and coturn REST API authentication.
"""

import hashlib
import hmac
import time
from typing import Dict, List

from django.conf import settings


def generate_turn_credentials(username: str, ttl: int = None) -> Dict[str, any]:
    """
    Generate time-limited TURN server credentials.

    Uses HMAC-SHA1 to generate credentials compatible with coturn's
    REST API authentication mechanism.

    Args:
        username: Username to generate credentials for
        ttl: Time-to-live in seconds (default: from settings.COTURN_TTL)

    Returns:
        Dictionary containing TURN server configuration:
        {
            'urls': ['turn:host:port', 'turns:host:port'],
            'username': 'timestamp:username',
            'credential': 'hmac-sha1-signature',
            'credentialType': 'password'
        }
    """
    if ttl is None:
        ttl = getattr(settings, "COTURN_TTL", 86400)

    timestamp = int(time.time()) + ttl
    turn_username = f"{timestamp}:{username}"

    secret = getattr(settings, "COTURN_SECRET", "")
    secret_bytes = secret.encode("utf-8")
    username_bytes = turn_username.encode("utf-8")

    credential = hmac.new(secret_bytes, username_bytes, hashlib.sha1).digest()
    credential_b64 = credential.hex()

    coturn_host = getattr(settings, "COTURN_HOST", "localhost")
    coturn_port = getattr(settings, "COTURN_PORT", 3478)
    coturn_tls_port = getattr(settings, "COTURN_TLS_PORT", 5349)

    return {
        "urls": [
            f"turn:{coturn_host}:{coturn_port}",
            f"turn:{coturn_host}:{coturn_port}?transport=tcp",
            f"turns:{coturn_host}:{coturn_tls_port}?transport=tcp",
        ],
        "username": turn_username,
        "credential": credential_b64,
        "credentialType": "password",
    }


def get_ice_servers(username: str, include_stun: bool = True) -> List[Dict[str, any]]:
    """
    Get complete ICE server configuration including STUN and TURN.

    Args:
        username: Username for TURN authentication
        include_stun: Include public STUN servers (default: True)

    Returns:
        List of ICE server configurations for WebRTC
    """
    ice_servers = []

    if include_stun:
        ice_servers.extend(
            [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
            ]
        )

    turn_config = generate_turn_credentials(username)
    ice_servers.append(turn_config)

    return ice_servers
