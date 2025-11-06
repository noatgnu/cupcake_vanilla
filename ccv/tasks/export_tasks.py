"""
RQ tasks for async export operations.
"""
import traceback
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from django_rq import job

from ccc.models import AsyncTaskStatus, TaskResult
from ccv.models import MetadataTable


@job("default", timeout=3600)
def export_excel_template_task(
    metadata_table_id: int,
    user_id: int,
    metadata_column_ids: Optional[List[int]] = None,
    include_pools: bool = True,
    lab_group_ids: Optional[List[int]] = None,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for exporting Excel template.

    Args:
        metadata_table_id: ID of the metadata table
        user_id: ID of the user performing export
        metadata_column_ids: Optional list of column IDs to export
        include_pools: Whether to include sample pools
        lab_group_ids: Optional list of lab group IDs for favourites
        task_id: Optional task identifier for tracking

    Returns:
        Dict with export results and file information
    """
    try:
        # Mark task as started
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        # Get user and metadata table
        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        # Use the shared export utility
        from .export_utils import export_excel_template_data

        result = export_excel_template_data(
            metadata_table=metadata_table,
            user=user,
            metadata_column_ids=metadata_column_ids,
            include_pools=include_pools,
            lab_group_ids=lab_group_ids,
        )

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task,
                    file_name=result["filename"],
                    content_type=result["content_type"],
                    file_size=result["file_size"],
                )

                # Save file content
                django_file = ContentFile(result["file_data"], name=result["filename"])
                task_result.file.save(result["filename"], django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": result["filename"],
                        "file_size": result["file_size"],
                        "content_type": result["content_type"],
                        "metadata_table_name": result["metadata_table_name"],
                        "column_count": result["column_count"],
                        "pool_count": result["pool_count"],
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass  # Task not found, continue without saving

        # Add task_id to result and return
        result["task_id"] = task_id
        return result

    except Exception as e:
        # Mark task as failed if task_id is provided
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}


@job("default", timeout=3600)
def export_sdrf_task(
    metadata_table_id: int,
    user_id: int,
    metadata_column_ids: Optional[List[int]] = None,
    include_pools: bool = True,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for exporting SDRF file.

    Args:
        metadata_table_id: ID of the metadata table
        user_id: ID of the user performing export
        metadata_column_ids: Optional list of column IDs to export
        include_pools: Whether to include sample pools
        task_id: Optional task identifier for tracking

    Returns:
        Dict with export results and file information
    """
    try:
        # Mark task as started
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        # Get user and metadata table
        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        # Use the shared export utility
        from .export_utils import export_sdrf_data

        result = export_sdrf_data(
            metadata_table=metadata_table,
            user=user,
            metadata_column_ids=metadata_column_ids,
            include_pools=include_pools,
            validate_sdrf=False,
        )

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task,
                    file_name=result["filename"],
                    content_type=result["content_type"],
                    file_size=result["file_size"],
                )

                # Save file content
                django_file = ContentFile(result["file_data"], name=result["filename"])
                task_result.file.save(result["filename"], django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": result["filename"],
                        "file_size": result["file_size"],
                        "content_type": result["content_type"],
                        "metadata_table_name": result["metadata_table_name"],
                        "column_count": result["column_count"],
                        "sample_count": result["sample_count"],
                        "pool_count": result["pool_count"],
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass

        # Add task_id to result and return
        result["task_id"] = task_id
        return result

    except Exception as e:
        # Mark task as failed if task_id is provided
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}


@job("default", timeout=7200)  # 2 hours for bulk operations
def export_multiple_sdrf_task(
    metadata_table_ids: List[int],
    user_id: int,
    include_pools: bool = True,
    validate_sdrf: bool = False,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for exporting multiple SDRF files as a ZIP archive.

    Args:
        metadata_table_ids: List of MetadataTable IDs to export
        user_id: ID of the user performing export
        include_pools: Whether to include sample pools
        validate_sdrf: Whether to validate SDRF format
        task_id: Optional task identifier for tracking

    Returns:
        Dict with export results and file information
    """
    try:
        # Mark task as started
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        # Get user
        user = User.objects.get(id=user_id)

        # Use the shared export utility
        from .export_utils import export_multiple_sdrf_data

        result = export_multiple_sdrf_data(
            metadata_table_ids=metadata_table_ids,
            user=user,
            include_pools=include_pools,
            validate_sdrf=validate_sdrf,
        )

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task,
                    file_name=result["filename"],
                    content_type=result["content_type"],
                    file_size=result["file_size"],
                )

                # Save file content
                django_file = ContentFile(result["file_data"], name=result["filename"])
                task_result.file.save(result["filename"], django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": result["filename"],
                        "file_size": result["file_size"],
                        "content_type": result["content_type"],
                        "exported_files": result["exported_files"],
                        "successful_exports": result["successful_exports"],
                        "failed_exports": result["failed_exports"],
                        "total_tables": result["total_tables"],
                        "total_columns": result["total_columns"],
                        "total_samples": result["total_samples"],
                        "total_pools": result["total_pools"],
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass

        # Add task_id to result and return
        result["task_id"] = task_id
        return result

    except Exception as e:
        # Mark task as failed if task_id is provided
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}


@job("default", timeout=7200)  # 2 hours for bulk operations
def export_multiple_excel_template_task(
    metadata_table_ids: List[int],
    user_id: int,
    metadata_column_ids: Optional[List[int]] = None,
    include_pools: bool = True,
    lab_group_ids: Optional[List[int]] = None,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for exporting multiple Excel templates as a ZIP archive.

    Args:
        metadata_table_ids: List of MetadataTable IDs to export
        user_id: ID of the user performing export
        metadata_column_ids: Optional list of column IDs to export
        include_pools: Whether to include sample pools
        lab_group_ids: Optional list of lab group IDs for favourites
        task_id: Optional task identifier for tracking

    Returns:
        Dict with export results and file information
    """
    try:
        # Mark task as started
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        # Get user
        user = User.objects.get(id=user_id)

        # Use the shared export utility
        from .export_utils import export_multiple_excel_template_data

        result = export_multiple_excel_template_data(
            metadata_table_ids=metadata_table_ids,
            user=user,
            metadata_column_ids=metadata_column_ids,
            include_pools=include_pools,
            lab_group_ids=lab_group_ids,
        )

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task,
                    file_name=result["filename"],
                    content_type=result["content_type"],
                    file_size=result["file_size"],
                )

                # Save file content
                django_file = ContentFile(result["file_data"], name=result["filename"])
                task_result.file.save(result["filename"], django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": result["filename"],
                        "file_size": result["file_size"],
                        "content_type": result["content_type"],
                        "exported_files": result["exported_files"],
                        "successful_exports": result["successful_exports"],
                        "failed_exports": result["failed_exports"],
                        "total_tables": result["total_tables"],
                        "total_columns": result["total_columns"],
                        "total_pools": result["total_pools"],
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass

        # Add task_id to result and return
        result["task_id"] = task_id
        return result

    except Exception as e:
        # Mark task as failed if task_id is provided
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}
