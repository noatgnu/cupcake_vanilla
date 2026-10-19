"""Reading image dimensions from file headers."""

from __future__ import annotations

import struct

JPEG_SIZE_MARKERS = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


def image_dimensions(content: bytes) -> tuple[int, int] | None:
    """
    Return the width and height of a PNG, GIF or JPEG image.

    Args:
        content: Image file content.

    Returns:
        ``(width, height)`` in pixels, or ``None`` when the format is not recognised.
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        return struct.unpack(">II", content[16:24])
    if content[:6] in (b"GIF87a", b"GIF89a") and len(content) >= 10:
        return struct.unpack("<HH", content[6:10])
    if content.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(content)
    return None


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    position = 2
    while position + 4 <= len(content):
        if content[position] != 0xFF:
            return None
        marker = content[position + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        length = struct.unpack(">H", content[position + 2 : position + 4])[0]
        if marker in JPEG_SIZE_MARKERS and position + 9 <= len(content):
            height, width = struct.unpack(">HH", content[position + 5 : position + 9])
            return width, height
        position += 2 + length
    return None
