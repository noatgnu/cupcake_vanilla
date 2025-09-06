"""
RQ tasks for async import operations.
"""
import traceback
from typing import Any, Dict

from django.contrib.auth.models import User

from django_rq import job

from ccv.models import MetadataTable
from ccv.task_models import AsyncTaskStatus

from .import_utils import import_excel_data, import_sdrf_data


@job("default", timeout=3600)
def import_sdrf_task(
    metadata_table_id: int,
    user_id: int,
    file_content: str,
    replace_existing: bool = False,
    validate_ontologies: bool = True,
    task_id: str = None,
) -> Dict[str, Any]:
    r"""
    Async task for importing SDRF file with proper validation and pool creation.

    Example:
        >>> sdrf_content = "source name\tcharacteristics[organism]\tcharacteristics[pooled sample]\n" + \
        ...                "D-HEp3 #1\thomo sapiens\tpooled\n" + \
        ...                "T-HEp3 #1\thomo sapiens\tnot pooled"
        >>> result = import_sdrf_task(
        ...     metadata_table_id=1,
        ...     user_id=2,
        ...     file_content=sdrf_content,
        ...     replace_existing=True,
        ...     validate_ontologies=True,
        ...     task_id="abc123"
        ... )
        >>> print(result['success'])
        True

    Args:
        metadata_table_id: ID of the metadata table to import into
        user_id: ID of the user performing the import operation
        file_content: Tab-separated SDRF file content as string
        replace_existing: Whether to replace existing data or skip duplicates
        validate_ontologies: Whether to validate ontology terms against vocabularies
        task_id: Optional UUID string for async task tracking

    Returns:
        Dict containing success status, import statistics, and any errors
    """
    try:
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        result = import_sdrf_data(
            file_content=file_content,
            metadata_table=metadata_table,
            user=user,
            replace_existing=replace_existing,
            validate_ontologies=validate_ontologies,
            create_pools=True,
        )

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_success(result)
            except Exception as e:
                print(f"Error marking task as successful: {e}")
                print(f"Full traceback:\n{traceback.format_exc()}")
                raise

        result["task_id"] = task_id
        return result

    except Exception as e:
        print(f"Import task error: {str(e)}")
        print(f"Full traceback:\n{traceback.format_exc()}")

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}


@job("default", timeout=3600)
def import_excel_task(
    metadata_table_id: int,
    user_id: int,
    file_data: bytes,
    replace_existing: bool = False,
    validate_ontologies: bool = True,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for importing Excel file with multi-sheet pool data processing.

    Example:
        >>> # Excel file contains proteomics data with ontology terms
        >>> # main sheet: organism=homo sapiens, cell_type=NT=HEp-3 cell;AC=BTO:0005139
        >>> # pool_object_map sheet: ["D-HEp3 Pool", [1,2], [], true]
        >>> with open('proteomics_metadata.xlsx', 'rb') as f:
        ...     file_data = f.read()
        >>> result = import_excel_task(
        ...     metadata_table_id=1,
        ...     user_id=2,
        ...     file_data=file_data,
        ...     replace_existing=False,
        ...     validate_ontologies=True,
        ...     task_id="def456"
        ... )
        >>> print(result['pools_created'])
        2

    Args:
        metadata_table_id: ID of the metadata table to import into
        user_id: ID of the user performing the import operation
        file_data: Binary Excel file data (.xlsx format)
        replace_existing: Whether to replace existing data or skip duplicates
        validate_ontologies: Whether to validate ontology terms against vocabularies
        task_id: Optional UUID string for async task tracking

    Returns:
        Dict containing success status, import statistics including pools created
    """
    try:
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_started()
            except AsyncTaskStatus.DoesNotExist:
                pass

        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        result = import_excel_data(
            file_data=file_data,
            metadata_table=metadata_table,
            user=user,
            replace_existing=replace_existing,
            validate_ontologies=validate_ontologies,
            create_pools=True,
        )

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                print(f"DEBUG: Marking Excel task {task_id} as successful with result: {result}")
                task.mark_success(result)
                print(f"DEBUG: Excel task {task_id} marked as successful, status: {task.status}")
            except Exception as e:
                print(f"Error marking task as successful: {e}")
                print(f"Full traceback:\n{traceback.format_exc()}")
                raise

        result["task_id"] = task_id
        return result

    except Exception as e:
        print(f"Import task error: {str(e)}")
        print(f"Full traceback:\n{traceback.format_exc()}")

        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task.mark_failure(str(e), traceback.format_exc())
            except AsyncTaskStatus.DoesNotExist:
                pass

        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}
