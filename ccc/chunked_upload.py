"""
CUPCAKE Core (CCC) - Base Chunked Upload Infrastructure.

Provides reusable chunked upload functionality that can be extended by any
CUPCAKE application. Built on top of drf-chunked-upload with additional
features for security, integrity checking, and file management.
"""

import hashlib
import mimetypes
import os
from typing import List, Optional, Tuple

from django.conf import settings
from django.db import models
from django.utils import timezone

from drf_chunked_upload.models import AbstractChunkedUpload
from drf_chunked_upload.serializers import ChunkedUploadSerializer
from drf_chunked_upload.views import ChunkedUploadView
from rest_framework.permissions import IsAuthenticated


class BaseChunkedUpload(AbstractChunkedUpload):
    """
    Base chunked upload model with enhanced security and integrity features.

    Provides:
    - SHA-256 integrity checking
    - Enhanced filename generation
    - User-based organization
    - Extensible validation hooks

    Applications should inherit from this class and add their specific fields
    and validation logic.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(class)s",
        editable=False,
        on_delete=models.CASCADE,
    )
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Original filename as provided by client",
    )
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Detected MIME type of the uploaded file",
    )
    file_size = models.BigIntegerField(
        blank=True,
        null=True,
        help_text="Total size of the uploaded file in bytes",
    )
    upload_session_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Session ID for tracking related uploads",
    )

    class Meta:
        app_label = "ccc"
        abstract = True

    def save(self, *args, **kwargs):
        """Override save to set metadata and filename."""
        # Store original filename if not already set
        if not self.original_filename and self.filename:
            self.original_filename = self.filename

        # Detect MIME type
        if self.filename and not self.mime_type:
            self.mime_type, _ = mimetypes.guess_type(self.filename)

        # Set file size if file is complete
        if self.status == self.COMPLETE and self.file and not self.file_size:
            try:
                self.file_size = self.file.size
            except (OSError, ValueError):
                pass

        super().save(*args, **kwargs)

    def generate_filename(self):
        """Generate secure filename using SHA-256 hash and timestamp."""
        if self.file and self.user:
            # Calculate hash for uniqueness
            sha256_hash = hashlib.sha256()
            self.file.seek(0)
            for chunk in iter(lambda: self.file.read(4096), b""):
                sha256_hash.update(chunk)
            self.file.seek(0)

            # Create filename components
            hash_prefix = sha256_hash.hexdigest()[:16]
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            user_id = self.user.id

            # Preserve original extension if available
            original_ext = ""
            if self.original_filename or self.filename:
                source_name = self.original_filename or self.filename
                original_ext = os.path.splitext(source_name)[1].lower()

            return f"upload_{user_id}_{hash_prefix}_{timestamp}{original_ext}"

        # Use the default filename if no custom logic applies
        import uuid

        return f"upload_{uuid.uuid4().hex[:8]}_" f"{timezone.now().strftime('%Y%m%d_%H%M%S')}"

    def verify_integrity(self, expected_checksum: str = None) -> bool:
        """
        Verify file integrity using checksum.

        Args:
            expected_checksum: Optional expected checksum to compare against

        Returns:
            True if integrity check passes, False otherwise
        """
        if not self.file or not os.path.exists(self.file.path):
            return False

        calculated_checksum = self.checksum
        if not calculated_checksum:
            return False

        # Compare with expected checksum if provided
        if expected_checksum:
            return calculated_checksum == expected_checksum

        return True

    def get_allowed_extensions(self) -> List[str]:
        """
        Get list of allowed file extensions.
        Override in subclasses to define specific file type restrictions.
        """
        return []  # No restrictions by default

    def get_allowed_mime_types(self) -> List[str]:
        """
        Get list of allowed MIME types.
        Override in subclasses to define specific MIME type restrictions.
        """
        return []  # No restrictions by default

    def validate_file_type(self) -> Tuple[bool, str]:
        """
        Validate uploaded file type against allowed extensions and MIME types.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.filename:
            return True, ""  # No validation if no filename

        allowed_extensions = self.get_allowed_extensions()
        allowed_mime_types = self.get_allowed_mime_types()

        # Skip validation if no restrictions defined
        if not allowed_extensions and not allowed_mime_types:
            return True, ""

        # Check file extension
        file_ext = os.path.splitext(self.filename.lower())[1]
        if allowed_extensions and file_ext not in allowed_extensions:
            return (
                False,
                f"Unsupported file extension: {file_ext}. " f"Allowed: {', '.join(allowed_extensions)}",
            )

        # Check MIME type if available
        if allowed_mime_types and self.mime_type and self.mime_type not in allowed_mime_types:
            return (
                False,
                f"Unsupported MIME type: {self.mime_type}. " f"Allowed: {', '.join(allowed_mime_types)}",
            )

        return True, ""

    def get_max_file_size(self) -> Optional[int]:
        """
        Get maximum allowed file size in bytes.
        Override in subclasses to define specific size limits.
        """
        return getattr(settings, "DRF_CHUNKED_UPLOAD_MAX_BYTES", None)

    def validate_file_size(self) -> Tuple[bool, str]:
        """
        Validate file size against maximum allowed size.

        Returns:
            Tuple of (is_valid, error_message)
        """
        max_size = self.get_max_file_size()
        if not max_size or not self.file_size:
            return True, ""

        if self.file_size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            return (
                False,
                (
                    f"File size ({self.file_size / (1024 * 1024):.1f} MB) "
                    f"exceeds maximum allowed size ({max_size_mb:.1f} MB)"
                ),
            )

        return True, ""

    def validate_upload(self) -> Tuple[bool, str]:
        """
        Comprehensive upload validation.
        Override in subclasses to add custom validation logic.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate file type
        is_valid, error_msg = self.validate_file_type()
        if not is_valid:
            return is_valid, error_msg

        # Validate file size
        is_valid, error_msg = self.validate_file_size()
        if not is_valid:
            return is_valid, error_msg

        return True, ""


class BaseChunkedUploadSerializer(ChunkedUploadSerializer):
    """Base serializer for chunked uploads with additional metadata fields."""

    class Meta:
        model = BaseChunkedUpload
        fields = (
            "id",
            "file",
            "filename",
            "offset",
            "created_at",
            "status",
            "completed_at",
            "original_filename",
            "mime_type",
            "file_size",
            "upload_session_id",
        )
        read_only_fields = (
            "id",
            "created_at",
            "status",
            "completed_at",
            "mime_type",
            "file_size",
        )


class BaseChunkedUploadView(ChunkedUploadView):
    serializer_class = BaseChunkedUploadSerializer
    permission_classes = [IsAuthenticated]
