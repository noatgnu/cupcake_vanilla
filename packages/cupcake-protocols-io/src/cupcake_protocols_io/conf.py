"""Settings read by the protocols.io app, with their defaults."""

from django.conf import settings

DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def access_token() -> str:
    """Return ``PROTOCOLS_IO_ACCESS_TOKEN``, the server's own protocols.io token, or an empty string."""
    return getattr(settings, "PROTOCOLS_IO_ACCESS_TOKEN", "") or ""


def units_protocol() -> str:
    """Return ``PROTOCOLS_IO_UNITS_PROTOCOL``, the protocol whose unit list is loaded, or an empty string."""
    return getattr(settings, "PROTOCOLS_IO_UNITS_PROTOCOL", "") or ""


def max_upload_bytes() -> int:
    """Return ``PROTOCOLS_IO_MAX_UPLOAD_BYTES``, the largest annotation file uploaded to protocols.io."""
    return int(getattr(settings, "PROTOCOLS_IO_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
