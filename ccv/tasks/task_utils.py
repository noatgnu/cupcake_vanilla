"""
Utility functions for task management and execution.
"""
from typing import Any, Dict, Optional

from django.contrib.auth.models import User

from ccv.task_models import AsyncTaskStatus


def mark_task_started(task_id: Optional[str]) -> Optional[AsyncTaskStatus]:
    """
    Mark a task as started if task_id is provided.

    Args:
        task_id: Optional task identifier

    Returns:
        AsyncTaskStatus instance if found, None otherwise
    """
    if not task_id:
        return None

    try:
        task = AsyncTaskStatus.objects.get(id=task_id)
        task.mark_started()
        return task
    except AsyncTaskStatus.DoesNotExist:
        return None


def mark_task_success(task_id: Optional[str], result_data: Dict[str, Any]) -> bool:
    """
    Mark a task as successful with result data.

    Args:
        task_id: Optional task identifier
        result_data: Result data to store

    Returns:
        True if task was marked as successful, False otherwise
    """
    if not task_id:
        return False

    try:
        task = AsyncTaskStatus.objects.get(id=task_id)
        task.mark_success(result_data)
        return True
    except AsyncTaskStatus.DoesNotExist:
        return False


def mark_task_failure(task_id: Optional[str], error: str, traceback: str) -> bool:
    """
    Mark a task as failed with error information.

    Args:
        task_id: Optional task identifier
        error: Error message
        traceback: Error traceback

    Returns:
        True if task was marked as failed, False otherwise
    """
    if not task_id:
        return False

    try:
        task = AsyncTaskStatus.objects.get(id=task_id)
        task.mark_failure(error, traceback)
        return True
    except AsyncTaskStatus.DoesNotExist:
        return False


def get_user_and_table(user_id: int, table_id: int):
    """
    Get user and metadata table instances.

    Args:
        user_id: User ID
        table_id: Metadata table ID

    Returns:
        Tuple of (User, MetadataTable) instances

    Raises:
        User.DoesNotExist: If user not found
        MetadataTable.DoesNotExist: If table not found
    """
    from ccv.models import MetadataTable

    user = User.objects.get(id=user_id)
    metadata_table = MetadataTable.objects.get(id=table_id)

    return user, metadata_table


def create_error_result(error: Exception, task_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a standardized error result dictionary.

    Args:
        error: The exception that occurred
        task_id: Optional task identifier

    Returns:
        Standardized error result dictionary
    """
    import traceback

    return {"success": False, "error": str(error), "traceback": traceback.format_exc(), "task_id": task_id}


def create_success_result(result_data: Dict[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a standardized success result dictionary.

    Args:
        result_data: The result data
        task_id: Optional task identifier

    Returns:
        Standardized success result dictionary
    """
    return {"success": True, "task_id": task_id, **result_data}
