from typing import List

from django.core.files.base import ContentFile

from drf_chunked_upload.serializers import ChunkedUploadSerializer
from drf_chunked_upload.views import ChunkedUploadView
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .chunked_upload import BaseChunkedUpload
from .models import Annotation, AnnotationFolder


class AnnotationFileUpload(BaseChunkedUpload):
    class Meta:
        app_label = "ccc"

    def get_allowed_extensions(self) -> List[str]:
        return [
            # Images
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".tiff",
            ".tif",
            ".webp",
            ".svg",
            # Videos
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".mkv",
            ".m4v",
            # Audio
            ".mp3",
            ".wav",
            ".flac",
            ".aac",
            ".ogg",
            ".wma",
            ".m4a",
            # Documents
            ".pdf",
            ".doc",
            ".docx",
            ".txt",
            ".rtf",
            ".odt",
            # Spreadsheets
            ".xls",
            ".xlsx",
            ".csv",
            ".ods",
            # Presentations
            ".ppt",
            ".pptx",
            ".odp",
            # Data/Code
            ".json",
            ".xml",
            ".csv",
            ".tsv",
            ".yml",
            ".yaml",
            # Archives
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            # Other common file types
            ".log",
            ".md",
            ".py",
            ".r",
        ]

    def get_allowed_mime_types(self) -> List[str]:
        """Get list of allowed MIME types for annotation files."""
        return [
            # Images
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/bmp",
            "image/tiff",
            "image/webp",
            "image/svg+xml",
            # Videos
            "video/mp4",
            "video/avi",
            "video/quicktime",
            "video/x-ms-wmv",
            "video/x-flv",
            "video/webm",
            "video/x-matroska",
            # Audio
            "audio/mpeg",
            "audio/wav",
            "audio/flac",
            "audio/aac",
            "audio/ogg",
            "audio/x-ms-wma",
            # Documents
            "application/pdf",
            "application/msword",
            ("application/vnd.openxmlformats-officedocument" ".wordprocessingml.document"),
            "text/plain",
            "text/rtf",
            "application/vnd.oasis.opendocument.text",
            # Spreadsheets
            "application/vnd.ms-excel",
            ("application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet"),
            "text/csv",
            "application/vnd.oasis.opendocument.spreadsheet",
            # Presentations
            "application/vnd.ms-powerpoint",
            ("application/vnd.openxmlformats-officedocument" ".presentationml.presentation"),
            "application/vnd.oasis.opendocument.presentation",
            # Data/Code
            "application/json",
            "application/xml",
            "text/tab-separated-values",
            "text/yaml",
            "application/x-yaml",
            # Archives
            "application/zip",
            "application/x-rar-compressed",
            "application/x-7z-compressed",
            "application/x-tar",
            "application/gzip",
            # Other
            "text/x-log",
            "text/markdown",
            "text/x-python",
            "text/x-r-source",
        ]

    def get_max_file_size(self) -> int:
        """Get maximum file size in bytes (500MB)."""
        return 500 * 1024 * 1024  # 500MB


class AnnotationFileUploadSerializer(ChunkedUploadSerializer):
    """Serializer for annotation file uploads."""

    class Meta:
        model = AnnotationFileUpload
        fields = (
            "id",
            "file",
            "filename",
            "offset",
            "created_at",
            "status",
            "completed_at",
        )
        read_only_fields = ("id", "created_at", "status", "completed_at")


class AnnotationChunkedUploadView(ChunkedUploadView):
    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """Handle completion of file upload and create annotation."""
        try:
            # Get annotation parameters from request
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )
            folder_id = request.data.get("folder_id")

            # Get folder if specified
            folder = None
            if folder_id:
                try:
                    folder = AnnotationFolder.objects.get(id=folder_id, user=request.user)
                except AnnotationFolder.DoesNotExist:
                    pass  # Continue without folder

            # Create annotation from completed upload
            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                folder,
                request.user,
            )

            result = {
                "annotation_id": annotation.id,
                "message": "Annotation created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            # Log error but don't fail the upload completion
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create annotation: {str(e)}")
            result = {"warning": (f"File uploaded but annotation creation failed: {str(e)}")}
            return Response(result, status=status.HTTP_200_OK)

    def _detect_annotation_type(self, filename: str) -> str:
        """Detect annotation type based on file extension."""
        if not filename:
            return "file"

        ext = filename.lower().split(".")[-1] if "." in filename else ""

        # Map file extensions to annotation types
        image_exts = [
            "jpg",
            "jpeg",
            "png",
            "gif",
            "bmp",
            "tiff",
            "svg",
            "webp",
        ]
        video_exts = ["mp4", "avi", "mov", "wmv", "flv", "webm", "mkv"]
        audio_exts = ["mp3", "wav", "flac", "aac", "ogg", "wma"]
        doc_exts = ["pdf", "doc", "docx", "txt", "rtf", "odt"]

        if ext in image_exts:
            return "image"
        elif ext in video_exts:
            return "video"
        elif ext in audio_exts:
            return "audio"
        elif ext in doc_exts:
            return "document"
        else:
            return "file"

    def _create_annotation_from_upload(self, upload, annotation_text, annotation_type, folder, user):
        """Create annotation record from completed upload."""
        # Create annotation record
        annotation = Annotation.objects.create(
            owner=user,
            annotation_type=annotation_type,
            annotation=annotation_text or f"Uploaded file: {upload.filename}",
            folder=folder,
            resource_type="file",
        )

        # Attach the uploaded file to the annotation
        if upload.file:
            # Copy the uploaded file to annotation
            with open(upload.file.path, "rb") as f:
                file_content = f.read()
                annotation.file.save(
                    upload.filename or f"upload_{annotation.id}",
                    ContentFile(file_content),
                    save=True,
                )

        return annotation
