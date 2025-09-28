"""
Async task management views for handling export/import operations via RQ.
"""
from django.http import HttpResponse
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from django_rq import get_queue
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ccv.models import MetadataTable
from ccv.serializers import (
    AsyncTaskListSerializer,
    AsyncTaskStatusSerializer,
    BulkExcelExportSerializer,
    BulkExportSerializer,
    MetadataExportSerializer,
    MetadataImportSerializer,
    MetadataValidationSerializer,
)
from ccv.task_models import AsyncTaskStatus, TaskResult
from ccv.tasks import (
    export_excel_template_task,
    export_multiple_excel_template_task,
    export_multiple_sdrf_task,
    export_sdrf_task,
    import_excel_task,
    import_sdrf_task,
    validate_metadata_table_task,
)


class AsyncTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing async tasks (export/import operations).

    Provides read-only access to user's async tasks with filtering and search capabilities.
    Users can list, retrieve, cancel, and download results from their tasks.
    """

    queryset = AsyncTaskStatus.objects.all()
    serializer_class = AsyncTaskListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["task_type", "status", "metadata_table"]
    search_fields = ["metadata_table__name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        """Filter queryset to user's tasks only."""
        return AsyncTaskStatus.objects.filter(user=self.request.user).order_by("-created_at")

    def get_serializer_class(self):
        """Return appropriate serializer class based on action."""
        if self.action == "retrieve":
            return AsyncTaskStatusSerializer
        return AsyncTaskListSerializer

    def retrieve(self, request, pk=None):
        """Get specific task details."""
        try:
            task = self.get_queryset().get(id=pk)
        except AsyncTaskStatus.DoesNotExist:
            return Response({"error": "Task not found"}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "id": str(task.id),
            "task_type": task.task_type,
            "status": task.status,
            "metadata_table_id": task.metadata_table.id if task.metadata_table else None,
            "metadata_table_name": task.metadata_table.name if task.metadata_table else None,
            "parameters": task.parameters,
            "result": task.result,
            "progress_percentage": task.progress_percentage,
            "progress_description": task.progress_description,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "duration": task.duration,
            "error_message": task.error_message,
            "traceback": task.traceback if task.status == "FAILURE" else None,
        }

        return Response(data)

    @action(detail=True, methods=["delete"])
    def cancel(self, request, pk=None):
        """Cancel a queued/running task or delete a completed task."""
        try:
            task = self.get_queryset().get(id=pk)
        except AsyncTaskStatus.DoesNotExist:
            return Response({"error": "Task not found"}, status=status.HTTP_404_NOT_FOUND)

        # If task is completed, delete it
        if task.status in ["SUCCESS", "FAILURE", "CANCELLED"]:
            # Clean up associated file if exists
            if hasattr(task, "file_result") and task.file_result.file:
                try:
                    task.file_result.cleanup_expired()
                except Exception:
                    pass

            # Delete the task
            task.delete()
            return Response({"message": "Task deleted successfully"})

        # If task is still running, cancel it
        if task.status in ["QUEUED", "STARTED"]:
            # Try to cancel RQ job
            if task.rq_job_id:
                try:
                    queue = get_queue(task.queue_name)
                    job = queue.job_class.fetch(task.rq_job_id, connection=queue.connection)
                    if job:
                        job.cancel()
                except Exception:
                    # If RQ job cannot be cancelled (e.g., already finished), continue with task cancellation
                    pass

            task.cancel()
            return Response({"message": "Task cancelled successfully"})

        return Response({"error": "Invalid task status"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["delete"])
    def cleanup_completed(self, request):
        """Delete all completed, failed, and cancelled tasks for the user."""
        user_tasks = self.get_queryset()

        # Filter tasks that can be deleted
        deletable_tasks = user_tasks.filter(status__in=["SUCCESS", "FAILURE", "CANCELLED"])

        if not deletable_tasks.exists():
            return Response({"message": "No completed tasks to delete"})

        # Clean up associated files
        for task in deletable_tasks:
            if hasattr(task, "file_result") and task.file_result.file:
                try:
                    task.file_result.cleanup_expired()
                except Exception:
                    pass

        # Count and delete
        deleted_count = deletable_tasks.count()
        deletable_tasks.delete()

        return Response({"message": f"Deleted {deleted_count} completed tasks"})

    @action(detail=True, methods=["get"])
    def download_url(self, request, pk=None):
        """Generate a signed download URL for task result file."""
        try:
            task = self.get_object()
        except AsyncTaskStatus.DoesNotExist:
            return Response({"error": "Task not found"}, status=status.HTTP_404_NOT_FOUND)

        if task.status != "SUCCESS":
            return Response({"error": "Task not completed successfully"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if task has file result
        if not hasattr(task, "file_result") or not task.file_result.file:
            return Response({"error": "No file available for download"}, status=status.HTTP_404_NOT_FOUND)

        file_result = task.file_result

        # Check if file has expired
        if file_result.is_expired():
            return Response({"error": "File has expired"}, status=status.HTTP_410_GONE)

        # Generate signed download token with 10 minute expiry
        signed_token, nginx_internal_path = file_result.generate_download_url(expire_minutes=10)

        # Return download URL info
        download_url = f"{request.build_absolute_uri(f'/api/v1/async-tasks/{task.id}/download/')}?token={signed_token}"

        return Response(
            {
                "download_url": download_url,
                "filename": file_result.file_name,
                "content_type": file_result.content_type,
                "file_size": file_result.file_size,
                "expires_at": file_result.expires_at,
                "expires_in_hours": max(0, int((file_result.expires_at - timezone.now()).total_seconds() / 3600)),
            }
        )

    @action(detail=True, methods=["get"], permission_classes=[])
    def download(self, request, pk=None):
        """Direct download endpoint with signed token verification.

        No authentication required - token contains all necessary validation.
        """
        signed_token = request.query_params.get("token")

        if not signed_token:
            return HttpResponse("Missing token", status=400)

        # Verify the signed token (no user authentication required)
        task_result = TaskResult.verify_download_token(signed_token)

        if not task_result:
            return HttpResponse("Invalid or expired token", status=403)

        # Check if file exists
        if not task_result.file or not task_result.get_file_path():
            return HttpResponse("File not found", status=404)

        # Record download
        task_result.record_download()

        # Check if running in Electron environment (no nginx)
        from django.conf import settings

        is_electron = getattr(settings, "IS_ELECTRON_ENVIRONMENT", False)

        if is_electron:
            # Direct file serving for Electron environment - return file as blob
            import os

            file_path = task_result.get_file_path()
            if not os.path.exists(file_path):
                return HttpResponse("File not found", status=404)

            # Read file into memory and return as blob
            with open(file_path, "rb") as f:
                file_content = f.read()

            response = HttpResponse(
                file_content,
                content_type=task_result.content_type or "application/octet-stream",
            )
            response["Content-Disposition"] = f'attachment; filename="{task_result.file_name}"'
            # Add cache headers (short cache since files are temporary)
            response["Cache-Control"] = "private, max-age=300"  # 5 minutes
            # Add security headers
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Download-Options"] = "noopen"
        else:
            # Use nginx X-Accel-Redirect for production with nginx
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"/internal/media/{task_result.file.name}"
            response["Content-Type"] = task_result.content_type or "application/octet-stream"
            response["Content-Disposition"] = f'attachment; filename="{task_result.file_name}"'
            response["Content-Length"] = task_result.file_size
            # Add cache headers (short cache since files are temporary)
            response["Cache-Control"] = "private, max-age=300"  # 5 minutes
            # Add security headers
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Download-Options"] = "noopen"

        return response


class AsyncExportViewSet(viewsets.GenericViewSet):
    """
    ViewSet for async export operations.

    Provides endpoints to queue async export tasks for Excel and SDRF formats.
    Tasks are processed in the background via RQ workers.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def excel_template(self, request):
        """Queue Excel template export task."""
        serializer = MetadataExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            metadata_table = MetadataTable.objects.get(id=data["metadata_table_id"])
        except MetadataTable.DoesNotExist:
            return Response(
                {"error": "metadata_table_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check permissions
        if not metadata_table.can_view(request.user):
            return Response(
                {"error": "Permission denied: cannot view this metadata table"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Create task record
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL",
            user=request.user,
            metadata_table=metadata_table,
            parameters={
                "metadata_column_ids": data.get("metadata_column_ids"),
                "include_pools": data.get("include_pools", True),
            },
        )

        # Queue the task
        job = export_excel_template_task.delay(
            metadata_table_id=metadata_table.id,
            user_id=request.user.id,
            metadata_column_ids=data.get("metadata_column_ids"),
            include_pools=data.get("include_pools", True),
            lab_group_ids=data.get("lab_group_ids"),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "Excel export task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def sdrf_file(self, request):
        """Queue SDRF file export task."""
        serializer = MetadataExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            metadata_table = MetadataTable.objects.get(id=data["metadata_table_id"])
        except MetadataTable.DoesNotExist:
            return Response(
                {"error": "metadata_table_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check permissions
        if not metadata_table.can_view(request.user):
            return Response(
                {"error": "Permission denied: cannot view this metadata table"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Create task record
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_SDRF",
            user=request.user,
            metadata_table=metadata_table,
            parameters={
                "include_pools": data.get("include_pools", True),
            },
        )

        # Queue the task
        job = export_sdrf_task.delay(
            metadata_table_id=metadata_table.id,
            user_id=request.user.id,
            metadata_column_ids=data.get("metadata_column_ids"),
            include_pools=data.get("include_pools", True),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "SDRF export task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def multiple_sdrf_files(self, request):
        """Queue bulk SDRF files export task."""
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        metadata_table_ids = data["metadata_table_ids"]

        # Check that all tables exist and user has permission
        metadata_tables = []
        try:
            for table_id in metadata_table_ids:
                table = MetadataTable.objects.get(id=table_id)
                if not table.can_view(request.user):
                    return Response(
                        {"error": f"Permission denied: cannot view metadata table {table_id}"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                metadata_tables.append(table)
        except MetadataTable.DoesNotExist:
            return Response(
                {"error": f"Metadata table {table_id} not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create task record - use first table as primary reference
        primary_table = metadata_tables[0] if metadata_tables else None
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_MULTIPLE_SDRF",
            user=request.user,
            metadata_table=primary_table,
            parameters={
                "metadata_table_ids": metadata_table_ids,
                "include_pools": data.get("include_pools", True),
                "validate_sdrf": data.get("validate_sdrf", False),
            },
        )

        # Queue the task with 2-hour timeout for bulk operations
        job = export_multiple_sdrf_task.delay(
            metadata_table_ids=metadata_table_ids,
            user_id=request.user.id,
            include_pools=data.get("include_pools", True),
            validate_sdrf=data.get("validate_sdrf", False),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "Bulk SDRF export task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def multiple_excel_templates(self, request):
        """Queue bulk Excel templates export task."""
        serializer = BulkExcelExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        metadata_table_ids = data["metadata_table_ids"]

        # Check that all tables exist and user has permission
        metadata_tables = []
        try:
            for table_id in metadata_table_ids:
                table = MetadataTable.objects.get(id=table_id)
                if not table.can_view(request.user):
                    return Response(
                        {"error": f"Permission denied: cannot view metadata table {table_id}"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                metadata_tables.append(table)
        except MetadataTable.DoesNotExist:
            return Response(
                {"error": f"Metadata table {table_id} not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create task record - use first table as primary reference
        primary_table = metadata_tables[0] if metadata_tables else None
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_MULTIPLE_EXCEL",
            user=request.user,
            metadata_table=primary_table,
            parameters={
                "metadata_table_ids": metadata_table_ids,
                "metadata_column_ids": data.get("metadata_column_ids"),
                "include_pools": data.get("include_pools", True),
                "lab_group_ids": data.get("lab_group_ids"),
            },
        )

        # Queue the task with 2-hour timeout for bulk operations
        job = export_multiple_excel_template_task.delay(
            metadata_table_ids=metadata_table_ids,
            user_id=request.user.id,
            metadata_column_ids=data.get("metadata_column_ids"),
            include_pools=data.get("include_pools", True),
            lab_group_ids=data.get("lab_group_ids"),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "Bulk Excel templates export task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )


class AsyncImportViewSet(viewsets.GenericViewSet):
    """
    ViewSet for async import operations.

    Provides endpoints to queue async import tasks for SDRF and Excel files.
    Tasks are processed in the background via RQ workers.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def sdrf_file(self, request):
        """Queue SDRF file import task."""
        serializer = MetadataImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            metadata_table = MetadataTable.objects.get(id=data["metadata_table_id"])
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

        # Read file content
        file_content = data["file"].read().decode("utf-8")

        # Create task record
        task = AsyncTaskStatus.objects.create(
            task_type="IMPORT_SDRF",
            user=request.user,
            metadata_table=metadata_table,
            parameters={
                "replace_existing": data.get("replace_existing", False),
                "validate_ontologies": data.get("validate_ontologies", True),
                "file_name": data["file"].name,
            },
        )

        # Queue the task
        job = import_sdrf_task.delay(
            metadata_table_id=metadata_table.id,
            user_id=request.user.id,
            file_content=file_content,
            replace_existing=data.get("replace_existing", False),
            validate_ontologies=data.get("validate_ontologies", True),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "SDRF import task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def excel_file(self, request):
        """Queue Excel file import task."""
        serializer = MetadataImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            metadata_table = MetadataTable.objects.get(id=data["metadata_table_id"])
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

        # Read file data
        file_data = data["file"].read()

        # Create task record
        task = AsyncTaskStatus.objects.create(
            task_type="IMPORT_EXCEL",
            user=request.user,
            metadata_table=metadata_table,
            parameters={
                "replace_existing": data.get("replace_existing", False),
                "validate_ontologies": data.get("validate_ontologies", True),
                "file_name": data["file"].name,
            },
        )

        # Queue the task
        job = import_excel_task.delay(
            metadata_table_id=metadata_table.id,
            user_id=request.user.id,
            file_data=file_data,
            replace_existing=data.get("replace_existing", False),
            validate_ontologies=data.get("validate_ontologies", True),
            task_id=str(task.id),
        )

        # Update task with job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "Excel import task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )


class AsyncValidationViewSet(viewsets.GenericViewSet):
    """
    ViewSet for async validation operations.
    """

    serializer_class = MetadataValidationSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def metadata_table(self, request):
        """Queue metadata table validation task."""
        serializer = MetadataValidationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Get metadata table and check permissions
        try:
            metadata_table = MetadataTable.objects.get(id=data["metadata_table_id"])
        except MetadataTable.DoesNotExist:
            return Response({"error": "Metadata table not found"}, status=status.HTTP_404_NOT_FOUND)

        if not metadata_table.can_edit(request.user):
            return Response(
                {"error": "Permission denied: cannot validate this metadata table"}, status=status.HTTP_403_FORBIDDEN
            )

        # Create task record
        task = AsyncTaskStatus.objects.create(
            task_type="VALIDATE_TABLE",
            user=request.user,
            metadata_table=metadata_table,
            # description=f"Validating metadata table: {metadata_table.name}",
        )

        # Prepare validation options
        validation_options = {
            "validate_sdrf_format": data.get("validate_sdrf_format", True),
            "include_pools": data.get("include_pools", True),
        }

        # Queue validation task
        job = validate_metadata_table_task.delay(
            metadata_table_id=data["metadata_table_id"],
            user_id=request.user.id,
            validation_options=validation_options,
            task_id=str(task.id),
        )

        # Store RQ job ID
        task.rq_job_id = job.id
        task.save(update_fields=["rq_job_id"])

        return Response(
            {"task_id": str(task.id), "message": "Metadata table validation task queued successfully"},
            status=status.HTTP_202_ACCEPTED,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cleanup_expired_files(request):
    """
    Management endpoint to clean up expired task result files.

    This should typically be called by a cron job or similar scheduled task.
    """
    if not request.user.is_staff:
        return Response({"error": "Admin privileges required"}, status=status.HTTP_403_FORBIDDEN)

    # Find expired files
    expired_results = TaskResult.objects.filter(expires_at__lt=timezone.now(), file__isnull=False)

    cleaned_count = 0
    error_count = 0

    for result in expired_results:
        try:
            result.cleanup_expired()
            cleaned_count += 1
        except Exception as e:
            error_count += 1
            # Log error in production
            print(f"Error cleaning up file for task {result.task.id}: {e}")

    return Response({"message": "Cleanup completed", "files_cleaned": cleaned_count, "errors": error_count})
