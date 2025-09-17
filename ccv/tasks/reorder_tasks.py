"""
Async tasks for CUPCAKE Vanilla metadata table and template column reordering operations.
"""
from typing import Any, Dict

from django.contrib.auth.models import User

from django_rq import job

from ccv.models import MetadataTableTemplate
from ccv.notification_service import NotificationService
from ccv.task_models import AsyncTaskStatus

from .base_task import task_with_tracking
from .task_utils import create_success_result, get_user_and_table, mark_task_success


def reorder_metadata_table_columns_sync(
    metadata_table_id: int,
    user_id: int,
    schema_ids: list[int] = None,
) -> Dict[str, Any]:
    """
    Synchronous version of metadata table column reordering.

    Args:
        metadata_table_id: ID of the metadata table to reorder
        user_id: ID of the user performing the operation
        schema_ids: List of schema IDs to use for reordering (optional)

    Returns:
        Dictionary containing success status and results
    """
    try:
        # Get user and metadata table
        user, metadata_table = get_user_and_table(user_id, metadata_table_id)

        # Check permissions
        if not metadata_table.can_edit(user):
            return {
                "success": False,
                "error": "Permission denied: cannot edit this metadata table",
            }

        # Perform reordering
        if schema_ids:
            metadata_table.reorder_columns_by_schema(schema_ids=schema_ids)
        else:
            # Use basic reordering if no schema IDs provided
            if hasattr(metadata_table, "basic_column_reordering"):
                metadata_table.basic_column_reordering()
            else:
                metadata_table.normalize_column_positions()

        # Apply same reordering to sample pools
        for pool in metadata_table.sample_pools.all():
            if pool.metadata_columns.exists():
                if schema_ids:
                    try:
                        pool.reorder_pool_columns_by_schema(schema_ids=schema_ids)
                    except Exception:
                        pool.basic_pool_column_reordering()
                else:
                    pool.basic_pool_column_reordering()

        # Save and complete
        metadata_table.save()

        result_data = {
            "metadata_table_id": metadata_table_id,
            "reordered_columns": metadata_table.columns.count(),
            "reordered_pools": metadata_table.sample_pools.count(),
            "schema_ids_used": schema_ids or [],
        }

        return {
            "success": True,
            "result": result_data,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Column reordering failed: {str(e)}",
            "exception_type": type(e).__name__,
            "exception_args": e.args,
        }


def reorder_metadata_table_template_columns_sync(
    template_id: int,
    user_id: int,
    schema_ids: list[int] = None,
) -> Dict[str, Any]:
    """
    Synchronous version of metadata table template column reordering.

    Args:
        template_id: ID of the metadata table template to reorder
        user_id: ID of the user performing the operation
        schema_ids: List of schema IDs to use for reordering (optional)

    Returns:
        Dictionary containing success status and results
    """
    try:
        # Get user and template
        user = User.objects.get(id=user_id)
        template = MetadataTableTemplate.objects.get(id=template_id)

        # Check permissions
        if not template.can_edit(user):
            return {
                "success": False,
                "error": "Permission denied: cannot edit this template",
            }

        # Perform reordering
        if schema_ids:
            template.reorder_columns_by_schema(schema_ids=schema_ids)
        else:
            # Use basic reordering if no schema IDs provided
            template.normalize_column_positions()

        # Save and complete
        template.save()

        result_data = {
            "template_id": template_id,
            "reordered_columns": template.template_columns.count(),
            "schema_ids_used": schema_ids or [],
        }

        return {
            "success": True,
            "result": result_data,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Template column reordering failed: {str(e)}",
            "exception_type": type(e).__name__,
            "exception_args": e.args,
        }


@job("default", timeout=1800)
@task_with_tracking
def reorder_metadata_table_columns_task(
    metadata_table_id: int,
    user_id: int,
    schema_ids: list[int] = None,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for reordering metadata table columns by schema.

    Args:
        metadata_table_id: ID of the metadata table to reorder
        user_id: ID of the user performing the operation
        schema_ids: List of schema IDs to use for reordering (optional)
        task_id: Task identifier for progress tracking

    Returns:
        Dictionary containing success status and results
    """
    try:
        # Update progress
        if task_id:
            task = AsyncTaskStatus.objects.get(id=task_id)
            task.update_progress(10, description="Starting column reordering")

        # Update progress
        if task_id:
            task.update_progress(50, description="Performing column reordering")

        # Use sync function for core logic
        result = reorder_metadata_table_columns_sync(
            metadata_table_id=metadata_table_id,
            user_id=user_id,
            schema_ids=schema_ids,
        )

        if not result["success"]:
            return {
                "success": False,
                "error": result["error"],
                "task_id": task_id,
            }

        # Update progress
        if task_id:
            task.update_progress(95, description="Finalizing reordering")

        # Get user for notification
        user = User.objects.get(id=user_id)
        from ccv.models import MetadataTable

        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        # Send notification
        notification_service = NotificationService()
        notification_service.notify_user(
            user_id=user.id,
            notification_type="success",
            message=f"Successfully reordered columns for '{metadata_table.name}'",
            title="Column Reordering Complete",
        )

        # Mark task as successful
        mark_task_success(task_id, result["result"])

        return create_success_result(result["result"], task_id)

    except Exception as e:
        error_msg = f"Column reordering failed: {str(e)}"

        # Send error notification
        try:
            notification_service = NotificationService()
            notification_service.notify_user(
                user_id=user_id,
                notification_type="error",
                message=error_msg,
                title="Column Reordering Failed",
            )
        except Exception:
            pass

        return {
            "success": False,
            "error": error_msg,
            "exception_type": type(e).__name__,
            "exception_args": e.args,
            "task_id": task_id,
        }


@job("default", timeout=1800)
@task_with_tracking
def reorder_metadata_table_template_columns_task(
    template_id: int,
    user_id: int,
    schema_ids: list[int] = None,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for reordering metadata table template columns by schema.

    Args:
        template_id: ID of the metadata table template to reorder
        user_id: ID of the user performing the operation
        schema_ids: List of schema IDs to use for reordering (optional)
        task_id: Task identifier for progress tracking

    Returns:
        Dictionary containing success status and results
    """
    try:
        # Update progress
        if task_id:
            task = AsyncTaskStatus.objects.get(id=task_id)
            task.update_progress(10, description="Starting template column reordering")

        # Update progress
        if task_id:
            task.update_progress(50, description="Performing template column reordering")

        # Use sync function for core logic
        result = reorder_metadata_table_template_columns_sync(
            template_id=template_id,
            user_id=user_id,
            schema_ids=schema_ids,
        )

        if not result["success"]:
            return {
                "success": False,
                "error": result["error"],
                "task_id": task_id,
            }

        # Update progress
        if task_id:
            task.update_progress(95, description="Finalizing template reordering")

        # Get user and template for notification
        user = User.objects.get(id=user_id)
        template = MetadataTableTemplate.objects.get(id=template_id)

        # Send notification
        notification_service = NotificationService()
        notification_service.notify_user(
            user_id=user.id,
            notification_type="success",
            message=f"Successfully reordered columns for template '{template.name}'",
            title="Template Column Reordering Complete",
        )

        # Mark task as successful
        mark_task_success(task_id, result["result"])

        return create_success_result(result["result"], task_id)

    except Exception as e:
        error_msg = f"Template column reordering failed: {str(e)}"

        # Send error notification
        try:
            notification_service = NotificationService()
            notification_service.notify_user(
                user_id=user_id,
                notification_type="error",
                message=error_msg,
                title="Template Column Reordering Failed",
            )
        except Exception:
            pass

        return {
            "success": False,
            "error": error_msg,
            "exception_type": type(e).__name__,
            "exception_args": e.args,
            "task_id": task_id,
        }
