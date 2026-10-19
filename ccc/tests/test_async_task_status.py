"""Tests for async task status WebSocket updates."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import AsyncTaskStatus


class AsyncTaskStatusCreationTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("task-status-user", password="x")

    def test_creating_a_task_sends_one_update(self):
        """Creating a task sends one update."""
        with patch.object(AsyncTaskStatus, "send_websocket_update") as send:
            task = AsyncTaskStatus.objects.create(task_type="EXPORT_SDRF", user=self.user)
        send.assert_called_once_with()
        self.assertTrue(AsyncTaskStatus.objects.filter(id=task.id).exists())

    def test_saving_an_existing_task_sends_no_update(self):
        """Saving an existing task sends no update."""
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_SDRF", user=self.user)
        with patch.object(AsyncTaskStatus, "send_websocket_update") as send:
            task.progress_description = "Halfway"
            task.save()
            AsyncTaskStatus.objects.get(id=task.id).save()
        send.assert_not_called()

    def test_creating_through_save_sends_one_update(self):
        """Creating through save sends one update."""
        task = AsyncTaskStatus(task_type="EXPORT_SDRF", user=self.user)
        with patch.object(AsyncTaskStatus, "send_websocket_update") as send:
            task.save()
            task.save()
        send.assert_called_once_with()
