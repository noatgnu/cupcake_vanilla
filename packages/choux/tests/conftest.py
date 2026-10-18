import pytest
from choux.models import UploadedFile


@pytest.fixture
def uploaded_image():
    """An uploaded 640 by 480 PNG image."""
    return UploadedFile(
        id=1401860,
        key="bk3aebuzf7.png",
        source="https://content.protocols.io/bk3aebuzf7.png",
        raw_source="https://protocols-files.s3.amazonaws.com/bk3aebuzf7.png",
        original_name="gel.png",
        mime_type="image/png",
        size=120,
        file_type=31,
        thumb_url="https://www.protocols.io/img/extensions/png.png",
        width=640,
        height=480,
    )


@pytest.fixture
def uploaded_file():
    """An uploaded plain text file."""
    return UploadedFile(
        id=1401861,
        key="bk3afbuzf7.txt",
        source="https://content.protocols.io/bk3afbuzf7.txt",
        raw_source="https://protocols-files.s3.amazonaws.com/bk3afbuzf7.txt",
        original_name="plate-layout.txt",
        mime_type="text/plain",
        size=32,
        file_type=14,
        thumb_url="https://www.protocols.io/img/extensions/txt.png",
    )
