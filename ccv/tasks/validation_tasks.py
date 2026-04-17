"""
RQ tasks for async validation operations.
"""
import traceback
from typing import Any, Dict

from django.contrib.auth.models import User

from django_rq import job

from ccc.models import AsyncTaskStatus
from ccv.models import MetadataTable

from .validation_utils import validate_metadata_table, validate_sdrf_file_content


def validate_metadata_table_sync(
    metadata_table_id: int,
    user_id: int,
    validation_options: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Synchronous version of metadata table validation.

    Args:
        metadata_table_id: ID of the metadata table to validate
        user_id: ID of the user performing validation
        validation_options: Optional validation configuration

    Returns:
        Dict with validation results
    """
    try:
        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        result = validate_metadata_table(
            metadata_table=metadata_table, user=user, validation_options=validation_options or {}
        )

        return {
            "success": True,
            "result": result,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "exception_type": type(e).__name__,
            "exception_args": e.args,
            "traceback": traceback.format_exc(),
        }


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

        # Use sync function for core logic
        result = validate_metadata_table_sync(
            metadata_table_id=metadata_table_id,
            user_id=user_id,
            validation_options=validation_options,
        )

        if not result["success"]:
            # Mark task as failed if task_id is provided
            if task_id:
                try:
                    task = AsyncTaskStatus.objects.get(id=task_id)
                    task.mark_failure(result["error"], result.get("traceback", ""))
                except AsyncTaskStatus.DoesNotExist:
                    pass
            return {
                "success": False,
                "error": result["error"],
                "traceback": result.get("traceback", ""),
                "task_id": task_id,
            }

        # Mark task as successful
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_success(result["result"])
            except Exception as e:
                print(f"Error marking validation task as successful: {e}")
                print(f"Full traceback:\n{traceback.format_exc()}")
                raise

        validation_result = result["result"].copy()
        validation_result["task_id"] = task_id
        return validation_result

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


@job("default", timeout=1800)
def validate_sdrf_file_task(
    file_content: str,
    user_id: int,
    validation_options: Dict[str, Any] = None,
    task_id: str = None,
    chunked_upload_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for validating an SDRF file without importing it.

    Args:
        file_content: Raw SDRF file content as a string
        user_id: ID of the user performing validation
        validation_options: Optional validation configuration
        task_id: Optional task identifier for tracking
        chunked_upload_id: Optional chunked upload ID to clean up after validation

    Returns:
        Dict with validation results
    """
    try:
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        result = validate_sdrf_file_content(
            file_content=file_content,
            validation_options=validation_options or {},
        )

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_success(result)
            except AsyncTaskStatus.DoesNotExist:
                pass

        if chunked_upload_id:
            try:
                from ccv.models import MetadataFileUpload

                MetadataFileUpload.objects.filter(id=chunked_upload_id).delete()
            except Exception:
                pass

        result["task_id"] = task_id
        return result

    except Exception as e:
        error_tb = traceback.format_exc()

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), error_tb)
            except AsyncTaskStatus.DoesNotExist:
                pass

        if chunked_upload_id:
            try:
                from ccv.models import MetadataFileUpload

                MetadataFileUpload.objects.filter(id=chunked_upload_id).delete()
            except Exception:
                pass

        return {"success": False, "error": str(e), "traceback": error_tb, "task_id": task_id}
