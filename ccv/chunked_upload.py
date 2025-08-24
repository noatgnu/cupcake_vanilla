"""
Chunked upload implementation for CUPCAKE Vanilla metadata files.
"""

import hashlib
import mimetypes
import os
from typing import Any, Dict, List

from django.utils import timezone

from drf_chunked_upload.models import ChunkedUpload
from drf_chunked_upload.serializers import ChunkedUploadSerializer
from drf_chunked_upload.views import ChunkedUploadView
from openpyxl import load_workbook
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import MetadataColumn, MetadataTable, SamplePool
from .utils import convert_sdrf_to_metadata, detect_pooled_samples


class MetadataFileUpload(ChunkedUpload):
    """Custom chunked upload model for metadata files with SHA-256 hashing."""

    def save(self, *args, **kwargs):
        """Override save to set filename from user if not provided."""
        if not self.filename and hasattr(self, "user") and self.user:
            # Generate filename based on user and timestamp
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            self.filename = f"metadata_upload_{self.user.id}_{timestamp}"
        super().save(*args, **kwargs)

    def generate_filename(self):
        """Generate filename using SHA-256 hash."""
        if self.file:
            # Calculate SHA-256 hash of the file content
            sha256_hash = hashlib.sha256()
            self.file.seek(0)
            for chunk in iter(lambda: self.file.read(4096), b""):
                sha256_hash.update(chunk)
            self.file.seek(0)

            # Use first 16 characters of hash + timestamp for uniqueness
            hash_prefix = sha256_hash.hexdigest()[:16]
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")

            # Preserve original extension if available
            original_ext = ""
            if self.filename:
                original_ext = os.path.splitext(self.filename)[1]

            return f"metadata_{hash_prefix}_{timestamp}{original_ext}"

        return super().generate_filename()

    def verify_file_integrity(self, expected_checksum: str = None) -> bool:
        """Verify file integrity using SHA-256 checksum."""
        if not self.file or not os.path.exists(self.file.path):
            return False

        # Calculate SHA-256 checksum of the complete file
        sha256_hash = hashlib.sha256()
        with open(self.file.path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)

        calculated_checksum = sha256_hash.hexdigest()

        # If expected checksum is provided, compare it
        if expected_checksum:
            return calculated_checksum == expected_checksum

        # Store calculated checksum for future reference
        if hasattr(self, "checksum"):
            self.checksum = calculated_checksum
            self.save(update_fields=["checksum"])

        return True


class MetadataFileUploadSerializer(ChunkedUploadSerializer):
    """Custom serializer for metadata file uploads."""

    class Meta:
        model = MetadataFileUpload
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


class MetadataChunkedUploadView(ChunkedUploadView):
    """
    Chunked upload view for metadata files (SDRF, Excel, TSV).
    Supports large file uploads with progress tracking.
    """

    model = MetadataFileUpload
    serializer_class = MetadataFileUploadSerializer
    permission_classes = [IsAuthenticated]

    def check_permissions(self, request):
        """Check upload permissions."""
        super().check_permissions(request)

        # Additional custom permission checks can go here
        if not request.user.is_authenticated:
            self.permission_denied(request, message="Authentication required for file upload")

    def validate_file(self, file):
        """Validate uploaded file type and content."""
        if not file:
            return False, "No file provided"

        # Get file extension and MIME type
        filename = getattr(file, "name", "")
        mime_type, _ = mimetypes.guess_type(filename)

        # Allowed file types
        allowed_extensions = {".xlsx", ".xls", ".tsv", ".txt", ".sdrf"}
        allowed_mime_types = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            "application/vnd.ms-excel",  # .xls
            "text/tab-separated-values",  # .tsv
            "text/plain",  # .txt
            "application/octet-stream",  # Generic binary (fallback)
        }

        # Check file extension
        file_ext = os.path.splitext(filename.lower())[1]
        if file_ext not in allowed_extensions:
            return (
                False,
                f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}",
            )

        # Check MIME type if available
        if mime_type and mime_type not in allowed_mime_types:
            # Allow if extension is valid (MIME type detection can be unreliable)
            if file_ext not in allowed_extensions:
                return False, f"Unsupported MIME type: {mime_type}"

        return True, "File validation passed"

    def create(self, request, *args, **kwargs):
        """Create a new chunked upload instance."""
        # Validate file before creating upload
        file = request.FILES.get("file")
        if file:
            is_valid, message = self.validate_file(file)
            if not is_valid:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

    def on_completion(self, uploaded_file, request):
        """
        Called when the file upload is completed.
        Verify file integrity and process the uploaded file.
        """
        try:
            # Verify file integrity using SHA-256
            expected_checksum = request.data.get("checksum")  # Optional client-provided checksum
            if not uploaded_file.verify_file_integrity(expected_checksum):
                return Response(
                    {"error": "File integrity verification failed"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get processing parameters from request
            metadata_table_id = request.data.get("metadata_table_id")
            create_pools = request.data.get("create_pools", True)
            replace_existing = request.data.get("replace_existing", False)

            if not metadata_table_id:
                return Response(
                    {"error": "metadata_table_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get target metadata table
            try:
                metadata_table = MetadataTable.objects.get(id=metadata_table_id)
            except MetadataTable.DoesNotExist:
                return Response(
                    {"error": "Invalid metadata_table_id"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check permissions
            if not metadata_table.can_edit(request.user):
                return Response(
                    {"error": "Permission denied: cannot edit this metadata table"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Process file based on type
            file_path = uploaded_file.file.path
            filename = uploaded_file.filename or uploaded_file.file.name
            file_ext = os.path.splitext(filename.lower())[1]

            if file_ext in [".xlsx", ".xls"]:
                result = self._process_excel_file(
                    file_path,
                    metadata_table,
                    create_pools,
                    replace_existing,
                    request.user,
                )
            elif file_ext in [".tsv", ".txt", ".sdrf"]:
                result = self._process_text_file(
                    file_path,
                    metadata_table,
                    create_pools,
                    replace_existing,
                    request.user,
                )
            else:
                return Response(
                    {"error": f"Unsupported file type: {file_ext}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Clean up uploaded file
            uploaded_file.delete()

            return Response(result)

        except Exception as e:
            return Response(
                {"error": f"File processing failed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _process_excel_file(
        self,
        file_path: str,
        metadata_table: MetadataTable,
        create_pools: bool,
        replace_existing: bool,
        user: Any,
    ) -> Dict[str, Any]:
        """Process Excel file and extract metadata."""

        # Load Excel workbook
        wb = load_workbook(file_path, data_only=True)

        # Process main worksheet
        main_ws = wb["main"] if "main" in wb.sheetnames else wb.active

        # Convert to list of lists
        data = []
        for row in main_ws.iter_rows(values_only=True):
            if row and any(cell is not None for cell in row):  # Skip empty rows
                data.append([str(cell) if cell is not None else "" for cell in row])

        if not data:
            return {"error": "No data found in Excel file"}

        headers = data[0]
        data_rows = data[1:]

        return self._create_metadata_from_data(headers, data_rows, metadata_table, create_pools, replace_existing, user)

    def _process_text_file(
        self,
        file_path: str,
        metadata_table: MetadataTable,
        create_pools: bool,
        replace_existing: bool,
        user: Any,
    ) -> Dict[str, Any]:
        """Process text/TSV/SDRF file and extract metadata."""

        # Read file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return {"error": "Empty file"}

        # Split into lines and parse
        lines = content.split("\n")

        # Detect delimiter (tab is preferred for SDRF)
        first_line = lines[0]
        delimiter = "\t" if "\t" in first_line else "," if "," in first_line else "\t"

        # Parse data
        headers = lines[0].split(delimiter)
        data_rows = [line.split(delimiter) for line in lines[1:] if line.strip()]

        return self._create_metadata_from_data(headers, data_rows, metadata_table, create_pools, replace_existing, user)

    def _create_metadata_from_data(
        self,
        headers: List[str],
        data_rows: List[List[str]],
        metadata_table: MetadataTable,
        create_pools: bool,
        replace_existing: bool,
        user: Any,
    ) -> Dict[str, Any]:
        """Create metadata columns and pools from parsed data."""

        created_columns = []
        created_pools = []

        # Clear existing columns if replace_existing is True
        if replace_existing:
            metadata_table.columns.all().delete()
            metadata_table.sample_pools.all().delete()

        # Update sample count based on data
        if data_rows:
            metadata_table.sample_count = len(data_rows)
            metadata_table.save(update_fields=["sample_count"])

        # Create metadata columns
        for i, header in enumerate(headers):
            # Parse header format: name[type] or just name
            if "[" in header and "]" in header:
                name = header.split("[")[0].strip()
                metadata_type = header.split("[")[1].rstrip("]").strip()
            else:
                name = header.strip()
                metadata_type = "characteristics"  # Default type

            if not name:  # Skip empty headers
                continue

            # Determine default value from first few non-empty rows
            default_value = ""
            for row in data_rows[:5]:  # Check first 5 rows
                if i < len(row) and row[i].strip():
                    default_value = row[i].strip()
                    break

            # Convert value using SDRF conventions
            if default_value:
                default_value = convert_sdrf_to_metadata(name, default_value)

            # Create metadata column
            metadata_column = MetadataColumn.objects.create(
                metadata_table=metadata_table,
                name=name,
                type=metadata_type,
                column_position=i,
                value=default_value,
            )
            created_columns.append(metadata_column)

        # Detect and create pools if requested
        if create_pools:
            pooled_column_index, sn_rows, pooled_rows = detect_pooled_samples(data_rows, headers)

            if pooled_column_index is not None:
                # Create pools from detected data
                import_pools_data = []

                # Process SN= rows (reference pools)
                for sn_row_idx in sn_rows:
                    if sn_row_idx < len(data_rows):
                        row = data_rows[sn_row_idx]
                        if pooled_column_index < len(row):
                            sdrf_value = row[pooled_column_index].strip()

                            if sdrf_value.startswith("SN="):
                                source_names = sdrf_value[3:].split(",")
                                source_names = [name.strip() for name in source_names]

                                # Find source name column
                                source_name_column_index = None
                                for j, h in enumerate(headers):
                                    if "source name" in h.lower():
                                        source_name_column_index = j
                                        break

                                pool_name = (
                                    row[source_name_column_index]
                                    if source_name_column_index and source_name_column_index < len(row)
                                    else f"Pool {len(import_pools_data) + 1}"
                                )

                                # Find matching samples
                                pooled_only_samples = []
                                for sample_idx, sample_row in enumerate(data_rows):
                                    if (
                                        source_name_column_index
                                        and source_name_column_index < len(sample_row)
                                        and sample_row[source_name_column_index].strip() in source_names
                                    ):
                                        pooled_only_samples.append(sample_idx + 1)

                                import_pools_data.append(
                                    {
                                        "pool_name": pool_name,
                                        "pooled_only_samples": pooled_only_samples,
                                        "pooled_and_independent_samples": [],
                                        "is_reference": True,
                                        "sdrf_value": sdrf_value,
                                    }
                                )

                # Create SamplePool objects
                for pool_data in import_pools_data:
                    sample_pool = SamplePool.objects.create(
                        metadata_table=metadata_table,
                        pool_name=pool_data["pool_name"],
                        pooled_only_samples=pool_data["pooled_only_samples"],
                        pooled_and_independent_samples=pool_data["pooled_and_independent_samples"],
                        is_reference=pool_data["is_reference"],
                        created_by=metadata_table.creator,
                    )
                    created_pools.append(sample_pool)

        return {
            "message": "File processed successfully",
            "created_columns": len(created_columns),
            "created_pools": len(created_pools),
            "sample_rows": len(data_rows),
            "metadata_columns": [
                {
                    "id": col.id,
                    "name": col.name,
                    "type": col.type,
                    "position": col.column_position,
                }
                for col in created_columns
            ],
            "sample_pools": [
                {
                    "id": pool.id,
                    "name": pool.pool_name,
                    "total_samples": pool.get_total_samples(),
                    "is_reference": pool.is_reference,
                }
                for pool in created_pools
            ],
        }
