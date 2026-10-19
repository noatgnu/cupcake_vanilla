import struct
import zlib

from choux.images import image_dimensions


def png(width, height):
    """Return a minimal PNG of the given size."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = (b"\x00" + b"\x00\x00\x00" * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg_header(width, height):
    """Return the start of a JPEG with an APP0 segment followed by a baseline frame header."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + frame


def test_png_dimensions():
    """Png dimensions."""
    assert image_dimensions(png(120, 45)) == (120, 45)


def test_gif_dimensions():
    """Gif dimensions."""
    assert image_dimensions(b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 6) == (640, 480)


def test_jpeg_dimensions_skip_leading_segments():
    """Jpeg dimensions skip leading segments."""
    assert image_dimensions(jpeg_header(1024, 768)) == (1024, 768)


def test_unknown_or_truncated_content():
    """Unknown or truncated content."""
    assert image_dimensions(b"not an image") is None
    assert image_dimensions(b"\x89PNG\r\n\x1a\n") is None
    assert image_dimensions(b"\xff\xd8\xff") is None
