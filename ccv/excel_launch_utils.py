"""
Signing utilities for Excel launch codes.

Uses Django's TimestampSigner for stateless, cryptographically signed codes
that carry user ID, table ID, and an expiry timestamp with no database storage.
"""

import base64
import json
import secrets

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

EXCEL_LAUNCH_MAX_AGE = 300
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_nonce(length: int = 4) -> str:
    """Generate a random alphanumeric nonce."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _encode_for_display(signed_value: str) -> str:
    """Encode a signed value to a URL-safe base64 string for copy-paste display."""
    encoded = base64.urlsafe_b64encode(signed_value.encode()).decode()
    return encoded.rstrip("=")


def _decode_from_display(code: str) -> str:
    """Decode a display code back to the signed value."""
    code = code.strip().replace(" ", "")
    padding = 4 - (len(code) % 4)
    if padding != 4:
        code += "=" * padding
    return base64.urlsafe_b64decode(code).decode()


def create_launch_code(user_id: int, table_id: int) -> str:
    """
    Create a signed launch code containing user and table information.

    The code is a base64-encoded signed JSON payload that includes:
    - user_id: The authenticated user's ID
    - table_id: The table to open
    - nonce: Random value to make each code unique

    Args:
        user_id: The authenticated user's ID.
        table_id: The ID of the table to open.

    Returns:
        An uppercase base64-encoded signed string.
    """
    signer = TimestampSigner(salt="excel-launch")
    payload = {"u": user_id, "t": table_id, "n": _generate_nonce(4)}
    json_payload = json.dumps(payload, separators=(",", ":"))
    signed_value = signer.sign(json_payload)
    return _encode_for_display(signed_value)


def verify_launch_code(code: str) -> dict:
    """
    Verify a launch code and extract the payload.

    Args:
        code: The user-entered launch code string.

    Returns:
        dict with 'user_id' and 'table_id' if valid.

    Raises:
        SignatureExpired: Code has exceeded EXCEL_LAUNCH_MAX_AGE seconds.
        BadSignature: Code is invalid or tampered.
    """
    signer = TimestampSigner(salt="excel-launch")
    try:
        signed_value = _decode_from_display(code)
        json_payload = signer.unsign(signed_value, max_age=EXCEL_LAUNCH_MAX_AGE)
        payload = json.loads(json_payload)
        return {"user_id": payload["u"], "table_id": payload["t"]}
    except SignatureExpired:
        raise
    except (BadSignature, json.JSONDecodeError, KeyError, Exception) as e:
        raise BadSignature(f"Invalid launch code: {e}")
