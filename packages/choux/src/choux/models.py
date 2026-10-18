"""Value objects returned by the client."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadedFile:
    """
    A file stored in protocols.io file storage and ready to be referenced from content.

    Files are stored with public read access, so anyone holding ``source`` can download the file
    even when the protocol that uses it is private.

    Attributes:
        id: protocols.io file id.
        key: Storage key of the file.
        source: Public URL served by protocols.io.
        raw_source: Direct storage URL.
        original_name: File name shown to readers.
        mime_type: Content type the file was stored with.
        size: Size in bytes.
        file_type: protocols.io file type id.
        thumb_url: Icon protocols.io shows for this kind of file.
        width: Image width in pixels, when known.
        height: Image height in pixels, when known.
    """

    id: int
    key: str
    source: str
    raw_source: str
    original_name: str
    mime_type: str
    size: int
    file_type: int
    thumb_url: str
    width: float | None = None
    height: float | None = None

    @property
    def is_image(self) -> bool:
        """Whether the file was stored as an image."""
        return self.mime_type.startswith("image/")
