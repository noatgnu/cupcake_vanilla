"""
Tests for RQ (Redis Queue) async task functionality.
"""
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
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
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


class AsyncExportTestCase(RQTaskTestCase):
    """Test cases for async export functionality."""

    @patch("ccv.tasks.export_excel_template_task.delay")
    def test_async_excel_export_queues_task(self, mock_delay):
        """Test that async Excel export queues a task correctly."""
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_delay.return_value = mock_job

        url = "/api/v1/async-export/excel_template/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id, self.column2.id],
            "sample_number": self.table.sample_count,
            "include_pools": True,
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        if response.status_code != status.HTTP_202_ACCEPTED:
            print(f"DEBUG: POST failed with {response.status_code}: {response.content}")
            print(f"DEBUG: Data sent: {data}")
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

        # Verify task.delay was called
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(kwargs["metadata_table_id"], self.table.id)
        self.assertEqual(kwargs["user_id"], self.user.id)

    @patch("ccv.tasks.export_sdrf_task.delay")
    def test_async_sdrf_export_queues_task(self, mock_delay):
        """Test that async SDRF export queues a task correctly."""
        mock_job = MagicMock()
        mock_job.id = "test-job-id-sdrf"
        mock_delay.return_value = mock_job

        url = "/api/v1/async-export/sdrf_file/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id, self.column2.id],
            "sample_number": self.table.sample_count,
            "include_pools": False,
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)

        # Check that task was created
        task_id = response.data["task_id"]
        task = AsyncTaskStatus.objects.get(id=task_id)
        self.assertEqual(task.task_type, "EXPORT_SDRF")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.status, "QUEUED")
        self.assertEqual(task.rq_job_id, "test-job-id-sdrf")

        # Verify task.delay was called
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(kwargs["metadata_table_id"], self.table.id)
        self.assertEqual(kwargs["user_id"], self.user.id)

    def test_async_export_permission_denied(self):
        """Test that async export respects permissions."""
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        url = "/api/v1/async-export/excel_template/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id, self.column2.id],
            "sample_number": self.table.sample_count,
        }

        import json

        response = other_client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_async_export_always_enabled(self):
        """Test that async export is always available."""
        url = "/api/v1/async-export/excel_template/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id, self.column2.id],
            "sample_number": self.table.sample_count,
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)


class AsyncImportTestCase(RQTaskTestCase):
    """Test cases for async import functionality."""

    @patch("ccv.tasks.import_sdrf_task.delay")
    def test_async_sdrf_import_queues_task(self, mock_delay):
        """Test that async SDRF import queues a task correctly."""
        mock_job = MagicMock()
        mock_job.id = "test-import-job-id"
        mock_delay.return_value = mock_job

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

        # Verify task.delay was called
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(kwargs["metadata_table_id"], self.table.id)
        self.assertEqual(kwargs["user_id"], self.user.id)

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
        # Clear any existing tasks for this user from previous test runs
        AsyncTaskStatus.objects.filter(user=self.user).delete()

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

        # Response is paginated, so check results array
        tasks = response.data["results"]
        self.assertEqual(len(tasks), 2)

        # Check task data structure
        task_data = tasks[0]  # Should be most recent (task2)
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

    @override_settings(DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage")
    def test_task_download_success(self):
        """Test downloading completed task result."""
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(MEDIA_ROOT=temp_dir):
                task = AsyncTaskStatus.objects.create(
                    task_type="EXPORT_SDRF",
                    user=self.user,
                    metadata_table=self.table,
                    status="SUCCESS",
                )

                # Create a TaskResult with an actual file
                file_content = "test\tcontent\nrow1\trow2"
                task_result = TaskResult.objects.create(
                    task=task,
                    file_name="test.sdrf.tsv",
                    content_type="text/tab-separated-values",
                    file_size=len(file_content.encode()),
                )
                task_result.file.save("test.sdrf.tsv", ContentFile(file_content.encode()))

                # Generate signed token for download
                signed_token, _ = task_result.generate_download_url(expire_minutes=10)

                url = f"/api/v1/async-tasks/{task.id}/download/?token={signed_token}"
                response = self.client.get(url)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response["Content-Type"], "text/tab-separated-values")
                self.assertIn('attachment; filename="test.sdrf.tsv"', response["Content-Disposition"])

    def test_task_download_not_completed(self):
        """Test downloading from incomplete task returns error."""
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table, status="QUEUED"
        )

        url = f"/api/v1/async-tasks/{task.id}/download_url/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # download_url endpoint returns JSON
        self.assertIn("not completed successfully", response.data["error"])


class SyncToAsyncIntegrationTestCase(RQTaskTestCase):
    """Test integration between sync and async endpoints."""

    def test_sync_excel_export_with_async_param(self):
        """Test that sync export endpoint can route to async when requested."""
        url = "/api/v1/metadata-management/export_excel_template/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id],
            "sample_number": 5,
            "async_processing": True,
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")

        # Should return 202 status (async task queued) rather than sync processing
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)
        self.assertIn("message", response.data)

    def test_sync_export_with_async_param_enabled(self):
        """Test that sync export redirects to async when async is requested."""
        url = "/api/v1/metadata-management/export_excel_template/"
        data = {
            "metadata_table_id": self.table.id,
            "metadata_column_ids": [self.column1.id],
            "sample_number": 5,
            "async_processing": True,
        }

        import json

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)


class TaskModelTestCase(TestCase):
    """Test cases for AsyncTaskStatus and TaskResult models."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)
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
        )

        self.assertEqual(result.task, task)
        self.assertEqual(result.file_name, "test.xlsx")
        self.assertEqual(result.file_size, 2048)

        # Test relationship
        self.assertEqual(task.file_result, result)


class AsyncValidationViewTestCase(RQTaskTestCase):
    """Test async validation view functionality."""

    @patch("ccv.tasks.validation_tasks.validate_metadata_table_task.delay")
    def test_async_validation_queues_task(self, mock_task_delay):
        """Test that async validation queues a task correctly."""
        mock_job = MagicMock()
        mock_job.id = "test-validation-job-id"
        mock_task_delay.return_value = mock_job

        url = "/api/v1/async-validation/metadata_table/"
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": True}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)
        self.assertIn("message", response.data)

        # Check that task was created
        task_id = response.data["task_id"]
        task = AsyncTaskStatus.objects.get(id=task_id)
        self.assertEqual(task.task_type, "VALIDATE_TABLE")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.metadata_table, self.table)
        self.assertEqual(task.status, "QUEUED")
        self.assertEqual(task.rq_job_id, "test-validation-job-id")

        # Verify task was queued with correct parameters
        mock_task_delay.assert_called_once()
        args, kwargs = mock_task_delay.call_args
        self.assertEqual(kwargs["metadata_table_id"], self.table.id)
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["task_id"], str(task.id))

    def test_async_validation_permission_denied(self):
        """Test that async validation respects edit permissions."""
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        url = "/api/v1/async-validation/metadata_table/"
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": True}

        response = other_client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_async_validation_invalid_table(self):
        """Test validation with invalid table ID."""
        url = "/api/v1/async-validation/metadata_table/"
        data = {"metadata_table_id": 99999, "validate_sdrf_format": True}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Metadata table not found", str(response.data["metadata_table_id"][0]))

    def test_async_validation_missing_table_id(self):
        """Test validation with missing table ID."""
        url = "/api/v1/async-validation/metadata_table/"
        data = {"validate_sdrf_format": True}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_async_validation_invalid_data_types(self):
        """Test validation with invalid data types."""
        url = "/api/v1/async-validation/metadata_table/"
        data = {
            "metadata_table_id": "invalid",  # Should be integer
            "validate_sdrf_format": "not_boolean",  # Should be boolean
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_async_validation_rq_disabled(self):
        """Test validation when RQ is disabled (should still work via sync fallback)."""
        url = "/api/v1/async-validation/metadata_table/"
        data = {"metadata_table_id": self.table.id, "validate_sdrf_format": True}

        # This should work even with RQ disabled since validation can run synchronously
        with patch("ccv.tasks.validation_utils.validate_metadata_table") as mock_validate:
            mock_validate.return_value = {
                "success": True,
                "metadata_table_id": self.table.id,
                "metadata_table_name": self.table.name,
                "errors": [],
                "warnings": [],
            }

            response = self.client.post(url, data)
            # Should either queue successfully or return sync result
            self.assertIn(response.status_code, [status.HTTP_202_ACCEPTED, status.HTTP_200_OK])

    def test_validation_task_type_in_list(self):
        """Test that VALIDATE_TABLE appears in task list."""
        # Clear any existing tasks for this user
        AsyncTaskStatus.objects.filter(user=self.user).delete()

        # Create validation task
        AsyncTaskStatus.objects.create(
            task_type="VALIDATE_TABLE", user=self.user, metadata_table=self.table, status="SUCCESS"
        )

        url = "/api/v1/async-tasks/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tasks = response.data["results"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_type"], "VALIDATE_TABLE")

    def test_validation_task_filter_by_type(self):
        """Test filtering tasks by validation type."""
        # Clear any existing tasks for this user
        AsyncTaskStatus.objects.filter(user=self.user).delete()

        # Create different types of tasks
        AsyncTaskStatus.objects.create(
            task_type="EXPORT_EXCEL", user=self.user, metadata_table=self.table, status="SUCCESS"
        )

        AsyncTaskStatus.objects.create(
            task_type="VALIDATE_TABLE", user=self.user, metadata_table=self.table, status="SUCCESS"
        )

        # Filter for validation tasks only
        url = "/api/v1/async-tasks/?task_type=VALIDATE_TABLE"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tasks = response.data["results"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_type"], "VALIDATE_TABLE")
