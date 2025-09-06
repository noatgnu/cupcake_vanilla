"""
RQ tasks for async validation operations.
"""
import traceback
from typing import Any, Dict

from django.contrib.auth.models import User

from django_rq import job

from ccv.models import MetadataTable
from ccv.task_models import AsyncTaskStatus

from .validation_utils import validate_metadata_table


@job("default", timeout=1800)
def validate_metadata_table_task(
    metadata_table_id: int,
    user_id: int,
    validation_options: Dict[str, Any] = None,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for validating metadata table.

    Args:
        metadata_table_id: ID of the metadata table to validate
        user_id: ID of the user performing validation
        validation_options: Optional validation configuration
        task_id: Optional task identifier for tracking

    Returns:
        Dict with validation results
    """
    try:
        # Mark task as started
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        user = User.objects.get(id=user_id)

        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        result = validate_metadata_table(
            metadata_table=metadata_table, user=user, validation_options=validation_options or {}
        )

        # Mark task as successful
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_success(result)
            except Exception as e:
                print(f"Error marking validation task as successful: {e}")
                print(f"Full traceback:\n{traceback.format_exc()}")
                raise

        result["task_id"] = task_id
        return result

    except Exception as e:
        # Print full error details to console for debugging
        print(f"Validation task error: {str(e)}")
        print(f"Full traceback:\n{traceback.format_exc()}")

        # Mark task as failed if task_id is provided
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}
