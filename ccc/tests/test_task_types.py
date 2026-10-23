from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc import task_types
from ccc.models import AsyncTaskStatus
from ccc.task_types import register_task_type, task_type_choices


@mock.patch.dict(task_types._registered, clear=True)
class TaskTypeRegistryTest(TestCase):
    def test_registered_types_follow_the_built_in_ones(self):
        """Registered types follow the built-in ones."""
        register_task_type("EXPORT_ELSEWHERE", "Export elsewhere")
        choices = task_type_choices()
        self.assertEqual(choices[: len(task_types.BUILTIN_TASK_TYPES)], task_types.BUILTIN_TASK_TYPES)
        self.assertEqual(choices[-1], ("EXPORT_ELSEWHERE", "Export elsewhere"))

    def test_registering_again_with_the_same_label_is_allowed(self):
        """Registering again with the same label is allowed."""
        register_task_type("EXPORT_ELSEWHERE", "Export elsewhere")
        register_task_type("EXPORT_ELSEWHERE", "Export elsewhere")
        self.assertEqual([code for code, _ in task_type_choices()].count("EXPORT_ELSEWHERE"), 1)

    def test_conflicting_or_invalid_types_are_rejected(self):
        """Conflicting, built-in or too long types are rejected."""
        register_task_type("EXPORT_ELSEWHERE", "Export elsewhere")
        with self.assertRaises(ValueError):
            register_task_type("EXPORT_ELSEWHERE", "Something else")
        with self.assertRaises(ValueError):
            register_task_type("EXPORT_SDRF", "Export SDRF File")
        with self.assertRaises(ValueError):
            register_task_type("X" * 26, "Too long")

    def test_task_status_shows_the_label_of_a_registered_type(self):
        """Task status shows the label of a registered type."""
        register_task_type("EXPORT_ELSEWHERE", "Export elsewhere")
        user = get_user_model().objects.create_user("task-owner", password="x")
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_ELSEWHERE", user=user)
        self.assertEqual(task.get_task_type_display(), "Export elsewhere")
