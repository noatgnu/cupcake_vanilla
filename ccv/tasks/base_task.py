"""
Base task functionality and decorators.
"""
import functools
import traceback
from typing import Any, Callable, Dict, Optional

from django.core.files.base import ContentFile

from ccc.models import AsyncTaskStatus, TaskResult

from .task_utils import create_error_result, mark_task_failure, mark_task_started


def task_with_tracking(func: Callable) -> Callable:
    """
    Decorator for tasks that handles common task tracking functionality.

    This decorator:
    - Marks task as started
    - Handles exceptions and marks task as failed
    - Returns standardized error results
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        task_id = kwargs.get("task_id")

        try:
            # Mark task as started
            mark_task_started(task_id)

            # Execute the actual task function
            return func(*args, **kwargs)

        except Exception as e:
            # Mark task as failed
            mark_task_failure(task_id, str(e), traceback.format_exc())

            # Return standardized error result
            return create_error_result(e, task_id)

    return wrapper


def save_file_result(task_id: Optional[str], result: Dict[str, Any]) -> bool:
    """
    Save file result to TaskResult model.

    Args:
        task_id: Task identifier
        result: Result dictionary containing file data

    Returns:
        True if file was saved successfully, False otherwise
    """
    if not task_id or not result.get("file_data"):
        return False

    try:
        task = AsyncTaskStatus.objects.get(id=task_id)

        # Create TaskResult record
        task_result = TaskResult.objects.create(
            task=task, file_name=result["filename"], content_type=result["content_type"], file_size=result["file_size"]
        )

        # Save file content
        django_file = ContentFile(result["file_data"], name=result["filename"])
        task_result.file.save(result["filename"], django_file)

        return True

    except (AsyncTaskStatus.DoesNotExist, KeyError):
        return False


class BaseTaskExecutor:
    """
    Base class for task executors with common functionality.
    """

    def __init__(self, task_id: Optional[str] = None):
        """Initialize TaskTracker with optional task ID."""
        self.task_id = task_id
        self.task = None

    def start_task(self) -> bool:
        """Start the task and mark it as started."""
        if self.task_id:
            self.task = mark_task_started(self.task_id)
            return self.task is not None
        return True

    def complete_task(self, result_data: Dict[str, Any]) -> bool:
        """Mark task as completed with result data."""
        from .task_utils import mark_task_success

        return mark_task_success(self.task_id, result_data)

    def fail_task(self, error: str, traceback_str: str) -> bool:
        """Mark task as failed with error information."""
        return mark_task_failure(self.task_id, error, traceback_str)

    def save_file_result(self, result: Dict[str, Any]) -> bool:
        """Save file result to TaskResult model."""
        return save_file_result(self.task_id, result)

    def get_user_and_table(self, user_id: int, table_id: int):
        """Get user and metadata table instances."""
        from .task_utils import get_user_and_table

        return get_user_and_table(user_id, table_id)
