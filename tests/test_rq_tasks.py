"""
Tests for RQ (Redis Queue) async task functionality.
"""
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from rest_framework import status
from rest_framework.test import APIClient

from ccv.models import LabGroup, MetadataColumn, MetadataTable
from ccv.task_models import AsyncTaskStatus, TaskResult


class RQTaskTestCase(TestCase):
    """Base test case for RQ task tests."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test table with columns
        self.table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

        self.column1 = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[organism]",
            type="characteristics",
            column_position=0,
            value="homo sapiens",
        )

        self.column2 = MetadataColumn.objects.create(
            metadata_table=self.table,
            name="characteristics[organism part]",
            type="characteristics",
            column_position=1,
            value="liver",
        )


@override_settings(ENABLE_RQ_TASKS=True)
class AsyncExportTestCase(RQTaskTestCase):
    """Test cases for async export functionality."""

    @patch("ccv.async_views.get_queue")
    def test_async_excel_export_queues_task(self, mock_get_queue):
        """Test that async Excel export queues a task correctly."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        url = "/api/v1/async-export/excel_template/"
        data = {"metadata_table_id": self.table.id, "include_pools": True}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)
        self.assertIn("message", response.data)

        # Check that task was created
        task_id = response.data["task_id"]
        task = AsyncTaskStatus.objects.get(id=task_id)
        self.assertEqual(task.task_type, "EXPORT_EXCEL")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.status, "QUEUED")
        self.assertEqual(task.rq_job_id, "test-job-id")

        # Verify queue.enqueue was called
        mock_queue.enqueue.assert_called_once()
        args, kwargs = mock_queue.enqueue.call_args
        self.assertEqual(args[0], "ccv.tasks.export_excel_template_task")

    @patch("ccv.async_views.get_queue")
    def test_async_sdrf_export_queues_task(self, mock_get_queue):
        """Test that async SDRF export queues a task correctly."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id-sdrf"
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        url = "/api/v1/async-export/sdrf_file/"
        data = {"metadata_table_id": self.table.id, "include_pools": False}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)

        # Check that task was created
        task_id = response.data["task_id"]
        task = AsyncTaskStatus.objects.get(id=task_id)
        self.assertEqual(task.task_type, "EXPORT_SDRF")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.status, "QUEUED")

    def test_async_export_permission_denied(self):
        """Test that async export respects permissions."""
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        url = "/api/v1/async-export/excel_template/"
        data = {"metadata_table_id": self.table.id}

        response = other_client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(ENABLE_RQ_TASKS=False)
    def test_async_export_disabled_returns_503(self):
        """Test that async export returns 503 when RQ is disabled."""
        url = "/api/v1/async-export/excel_template/"
        data = {"metadata_table_id": self.table.id}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("Async task queuing is not enabled", response.data["error"])


@override_settings(ENABLE_RQ_TASKS=True)
class AsyncImportTestCase(RQTaskTestCase):
    """Test cases for async import functionality."""

    @patch("ccv.async_views.get_queue")
    def test_async_sdrf_import_queues_task(self, mock_get_queue):
        """Test that async SDRF import queues a task correctly."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-import-job-id"
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        # Create test SDRF content
        sdrf_content = (
            "characteristics[organism]\tcharacteristics[organism part]\n"
            "homo sapiens\tliver\n"
            "homo sapiens\theart\n"
        )

        # Create a temporary file-like object
        from io import BytesIO

        file_obj = BytesIO(sdrf_content.encode("utf-8"))
        file_obj.name = "test.sdrf.tsv"

        url = "/api/v1/async-import/sdrf_file/"
        data = {
            "metadata_table_id": self.table.id,
            "file": file_obj,
            "replace_existing": False,
            "validate_ontologies": True,
        }

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)

        # Check that task was created
        task_id = response.data["task_id"]
        task = AsyncTaskStatus.objects.get(id=task_id)
        self.assertEqual(task.task_type, "IMPORT_SDRF")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.status, "QUEUED")
        self.assertEqual(task.rq_job_id, "test-import-job-id")

        # Verify queue.enqueue was called
        mock_queue.enqueue.assert_called_once()
        args, kwargs = mock_queue.enqueue.call_args
        self.assertEqual(args[0], "ccv.tasks.import_sdrf_task")

    def test_async_import_permission_denied(self):
        """Test that async import respects edit permissions."""
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        from io import BytesIO

        file_obj = BytesIO(b"test content")
        file_obj.name = "test.sdrf.tsv"

        url = "/api/v1/async-import/sdrf_file/"
        data = {"metadata_table_id": self.table.id, "file": file_obj}

        response = other_client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AsyncTaskStatusTestCase(RQTaskTestCase):
    """Test cases for async task status tracking."""

    def test_task_status_list(self):
        """Test listing user's async tasks."""
        # Create some test tasks
        AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table, status="SUCCESS"
        )

        AsyncTaskStatus.objects.create(
            task_type="IMPORT_SDRF",
            user=self.user,
            metadata_table=self.table,
            status="FAILURE",
            error_message="Test error",
        )

        # Create task for different user (should not appear)
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        AsyncTaskStatus.objects.create(
            task_type="EXPORT_SDRF", user=other_user, metadata_table=self.table, status="SUCCESS"
        )

        url = "/api/v1/async-tasks/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # Check task data structure
        task_data = response.data[0]  # Should be most recent (task2)
        self.assertIn("id", task_data)
        self.assertIn("task_type", task_data)
        self.assertIn("status", task_data)
        self.assertIn("progress_percentage", task_data)
        self.assertIn("created_at", task_data)

    def test_task_status_detail(self):
        """Test retrieving specific task details."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL",
            user=self.user,
            metadata_table=self.table,
            status="SUCCESS",
            result={"filename": "test.xlsx", "file_size": 1024},
        )

        url = f"/api/v1/async-tasks/{task.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(task.id))
        self.assertEqual(response.data["task_type"], "EXPORT_EXCEL")
        self.assertEqual(response.data["status"], "SUCCESS")
        self.assertEqual(response.data["result"]["filename"], "test.xlsx")

    def test_task_cancel(self):
        """Test cancelling a queued task."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL",
            user=self.user,
            metadata_table=self.table,
            status="QUEUED",
            rq_job_id="test-job-id",
        )

        url = f"/api/v1/async-tasks/{task.id}/cancel/"

        with patch("ccv.async_views.get_queue") as mock_get_queue:
            mock_queue = MagicMock()
            mock_job = MagicMock()
            mock_queue.job_class.fetch.return_value = mock_job
            mock_get_queue.return_value = mock_queue

            response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("cancelled successfully", response.data["message"])

        # Check task was marked as cancelled
        task.refresh_from_db()
        self.assertEqual(task.status, "CANCELLED")

    def test_task_download_success(self):
        """Test downloading completed task result."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_SDRF",
            user=self.user,
            metadata_table=self.table,
            status="SUCCESS",
            result={
                "file_content": "test\tcontent\nrow1\trow2",
                "filename": "test.sdrf.tsv",
                "content_type": "text/tab-separated-values",
            },
        )

        url = f"/api/v1/async-tasks/{task.id}/download/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/tab-separated-values")
        self.assertIn('attachment; filename="test.sdrf.tsv"', response["Content-Disposition"])
        self.assertEqual(response.content.decode(), "test\tcontent\nrow1\trow2")

    def test_task_download_not_completed(self):
        """Test downloading from incomplete task returns error."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table, status="QUEUED"
        )

        url = f"/api/v1/async-tasks/{task.id}/download/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not completed successfully", response.data["error"])


class SyncToAsyncIntegrationTestCase(RQTaskTestCase):
    """Test integration between sync and async endpoints."""

    @override_settings(ENABLE_RQ_TASKS=True)
    @patch("ccv.views.AsyncExportViewSet")
    def test_sync_excel_export_with_async_param(self, mock_async_viewset):
        """Test that sync export endpoint can route to async when requested."""
        mock_async_view = MagicMock()
        mock_async_viewset.return_value = mock_async_view
        mock_async_view.excel_template.return_value = MagicMock(
            status_code=202, data={"task_id": str(uuid.uuid4()), "message": "Task queued"}
        )

        url = f"/api/v1/metadata-tables/{self.table.id}/export_excel_template/"
        data = {"metadata_table_id": self.table.id, "async_processing": True}

        self.client.post(url, data)

        # Should have called async viewset
        mock_async_viewset.assert_called_once()
        mock_async_view.excel_template.assert_called_once()

    @override_settings(ENABLE_RQ_TASKS=False)
    def test_sync_export_with_async_param_disabled(self):
        """Test that sync export returns error when async is requested but disabled."""
        url = f"/api/v1/metadata-tables/{self.table.id}/export_excel_template/"
        data = {"metadata_table_id": self.table.id, "async_processing": True}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("Async task queuing is not enabled", response.data["error"])


class TaskModelTestCase(TestCase):
    """Test cases for AsyncTaskStatus and TaskResult models."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", owner=self.user)
        self.table = MetadataTable.objects.create(
            name="Test Table", owner=self.user, lab_group=self.lab_group, sample_count=5
        )

    def test_task_status_creation(self):
        """Test creating AsyncTaskStatus instance."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table, parameters={"test": "value"}
        )

        self.assertEqual(task.status, "QUEUED")  # Default status
        self.assertEqual(task.task_type, "EXPORT_EXCEL")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.progress_percentage, 0)
        self.assertIsNotNone(task.id)  # UUID should be generated

    def test_task_status_progress_tracking(self):
        """Test task progress tracking methods."""
        task = AsyncTaskStatus.objects.create(task_type="IMPORT_SDRF", user=self.user, metadata_table=self.table)

        # Test mark_started
        task.mark_started()
        self.assertEqual(task.status, "STARTED")
        self.assertIsNotNone(task.started_at)

        # Test update_progress
        task.update_progress(current=50, total=100, description="Processing rows")
        self.assertEqual(task.progress_current, 50)
        self.assertEqual(task.progress_total, 100)
        self.assertEqual(task.progress_percentage, 50.0)
        self.assertEqual(task.progress_description, "Processing rows")

        # Test mark_success
        result_data = {"rows_processed": 100, "columns_created": 5}
        task.mark_success(result_data)
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(task.progress_current, 100)  # Should be set to total
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.result, result_data)

    def test_task_status_failure_tracking(self):
        """Test task failure tracking."""
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table)

        task.mark_failure("Test error message", "Test traceback")
        self.assertEqual(task.status, "FAILURE")
        self.assertEqual(task.error_message, "Test error message")
        self.assertEqual(task.traceback, "Test traceback")
        self.assertIsNotNone(task.completed_at)

    def test_task_result_model(self):
        """Test TaskResult model for storing large results."""
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table)

        result = TaskResult.objects.create(
            task=task,
            file_name="test.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size=2048,
            file_content=b"fake excel content",
        )

        self.assertEqual(result.task, task)
        self.assertEqual(result.file_name, "test.xlsx")
        self.assertEqual(result.file_size, 2048)
        self.assertEqual(result.file_content, b"fake excel content")

        # Test relationship
        self.assertEqual(task.large_result, result)
