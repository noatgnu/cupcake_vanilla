"""
RQ tasks for async export and import operations.
"""
import io
import traceback
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction

from django_rq import job

from ccv.models import MetadataTable
from ccv.task_models import AsyncTaskStatus, TaskResult
from ccv.utils import export_excel_template, sort_metadata
from ccv.views import MetadataTableViewSet


@job("default", timeout=3600)
def export_excel_template_task(
    metadata_table_id: int,
    user_id: int,
    metadata_column_ids: Optional[List[int]] = None,
    include_pools: bool = True,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for exporting Excel template.

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

        # Check permissions
        if not metadata_table.can_view(user):
            return {"success": False, "error": "Permission denied: cannot view this metadata table", "task_id": task_id}

        # Get metadata columns
        if metadata_column_ids:
            metadata_columns = metadata_table.columns.filter(id__in=metadata_column_ids)
        else:
            metadata_columns = metadata_table.columns.all()

        # Separate main and hidden metadata
        main_metadata = [m for m in metadata_columns if not m.hidden]
        hidden_metadata = [m for m in metadata_columns if m.hidden]

        # Sort metadata and get structured output
        result_main, id_map_main = sort_metadata(main_metadata, metadata_table.sample_count, metadata_table)
        result_hidden = []
        id_map_hidden = {}
        if hidden_metadata:
            result_hidden, id_map_hidden = sort_metadata(hidden_metadata, metadata_table.sample_count, metadata_table)

        # Get pools
        pools = list(metadata_table.sample_pools.all()) if include_pools else []

        # Get favourites for each metadata column
        favourites = {}
        for column in metadata_columns:
            if hasattr(column, "favourite_options") and column.favourite_options.exists():
                favourites[column.name] = list(column.favourite_options.values_list("value", flat=True))

        # Create Excel workbook
        wb = export_excel_template(
            metadata_columns=list(metadata_columns),
            sample_number=metadata_table.sample_count,
            pools=pools,
            favourites=favourites,
        )

        # Save to BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        # Get file data and create filename
        file_data = output.getvalue()
        filename = f"{metadata_table.name}_template.xlsx"
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task, file_name=filename, content_type=content_type, file_size=len(file_data)
                )

                # Save file content
                django_file = ContentFile(file_data, name=filename)
                task_result.file.save(filename, django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": filename,
                        "file_size": len(file_data),
                        "content_type": content_type,
                        "metadata_table_name": metadata_table.name,
                        "column_count": metadata_columns.count(),
                        "pool_count": len(pools),
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass  # Task not found, continue without saving

        return {
            "success": True,
            "filename": filename,
            "file_size": len(file_data),
            "content_type": content_type,
            "metadata_table_name": metadata_table.name,
            "column_count": metadata_columns.count(),
            "pool_count": len(pools),
            "task_id": task_id,
        }

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
    metadata_table_id: int, user_id: int, include_pools: bool = True, task_id: str = None
) -> Dict[str, Any]:
    """
    Async task for exporting SDRF file.

    Args:
        metadata_table_id: ID of the metadata table
        user_id: ID of the user performing export
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

        # Check permissions
        if not metadata_table.can_view(user):
            return {"success": False, "error": "Permission denied: cannot view this metadata table", "task_id": task_id}

        # Get all columns ordered by position
        columns = metadata_table.columns.order_by("column_position")

        # Build headers
        headers = [col.name for col in columns]

        # Build data rows
        rows = []
        for sample_idx in range(1, metadata_table.sample_count + 1):
            row = []
            for col in columns:
                # Get value for this sample
                value = col.value or ""

                # Apply modifiers if they exist
                if col.modifiers:
                    for modifier in col.modifiers:
                        if "samples" in modifier and str(sample_idx) in modifier.get("samples", []):
                            value = modifier.get("value", value)
                            break

                row.append(value)
            rows.append(row)

        # Add pool rows if requested
        if include_pools:
            pools = metadata_table.sample_pools.all()
            for pool in pools:
                pool_columns = pool.metadata_columns.order_by("column_position")
                if pool_columns.exists():
                    pool_row = []
                    for col in columns:
                        # Find matching pool column
                        pool_col = pool_columns.filter(column_position=col.column_position).first()
                        if pool_col:
                            pool_row.append(pool_col.value or "")
                        else:
                            pool_row.append("")
                    rows.append(pool_row)

        # Create TSV content
        content_lines = ["\t".join(headers)]
        for row in rows:
            content_lines.append("\t".join(str(cell) for cell in row))

        sdrf_content = "\n".join(content_lines)
        filename = f"{metadata_table.name}.sdrf.tsv"
        content_type = "text/tab-separated-values"
        file_data = sdrf_content.encode("utf-8")

        # Get task and create file result
        if task_id:
            try:
                task = AsyncTaskStatus.objects.get(id=task_id)
                task_result = TaskResult.objects.create(
                    task=task, file_name=filename, content_type=content_type, file_size=len(file_data)
                )

                # Save file content
                django_file = ContentFile(file_data, name=filename)
                task_result.file.save(filename, django_file)

                # Mark task as successful
                task.mark_success(
                    {
                        "filename": filename,
                        "file_size": len(file_data),
                        "content_type": content_type,
                        "metadata_table_name": metadata_table.name,
                        "column_count": columns.count(),
                        "sample_count": metadata_table.sample_count,
                        "pool_count": metadata_table.sample_pools.count() if include_pools else 0,
                    }
                )

            except AsyncTaskStatus.DoesNotExist:
                pass

        return {
            "success": True,
            "filename": filename,
            "file_size": len(file_data),
            "content_type": content_type,
            "metadata_table_name": metadata_table.name,
            "column_count": columns.count(),
            "sample_count": metadata_table.sample_count,
            "pool_count": metadata_table.sample_pools.count() if include_pools else 0,
            "task_id": task_id,
        }

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
def import_sdrf_task(
    metadata_table_id: int,
    user_id: int,
    file_content: str,
    replace_existing: bool = False,
    validate_ontologies: bool = True,
    task_id: str = None,
) -> Dict[str, Any]:
    """
    Async task for importing SDRF file.

    Args:
        metadata_table_id: ID of the metadata table
        user_id: ID of the user performing import
        file_content: Content of the SDRF file
        replace_existing: Whether to replace existing data
        validate_ontologies: Whether to validate ontology terms
        task_id: Optional task identifier for tracking

    Returns:
        Dict with import results
    """
    try:
        # Get user and metadata table
        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        # Check permissions
        if not metadata_table.can_edit(user):
            return {"success": False, "error": "Permission denied: cannot edit this metadata table", "task_id": task_id}

        with transaction.atomic():
            # Use the existing import logic from the viewset
            viewset = MetadataTableViewSet()

            # Parse the file content
            lines = file_content.strip().split("\n")
            if not lines:
                return {"success": False, "error": "Empty file content", "task_id": task_id}

            # Parse headers and data
            headers = lines[0].split("\t")
            data_rows = [line.split("\t") for line in lines[1:]]

            # Process the import using the existing logic
            result = viewset._process_sdrf_import(
                headers=headers,
                data_rows=data_rows,
                metadata_table=metadata_table,
                replace_existing=replace_existing,
                user=user,
                validate_ontologies=validate_ontologies,
            )

            return {
                "success": True,
                "metadata_table_name": metadata_table.name,
                "columns_created": result.get("columns_created", 0),
                "columns_updated": result.get("columns_updated", 0),
                "pools_created": result.get("pools_created", 0),
                "pools_updated": result.get("pools_updated", 0),
                "warnings": result.get("warnings", []),
                "task_id": task_id,
            }

    except Exception as e:
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
    Async task for importing Excel file.

    Args:
        metadata_table_id: ID of the metadata table
        user_id: ID of the user performing import
        file_data: Binary data of the Excel file
        replace_existing: Whether to replace existing data
        validate_ontologies: Whether to validate ontology terms
        task_id: Optional task identifier for tracking

    Returns:
        Dict with import results
    """
    try:
        # Get user and metadata table
        user = User.objects.get(id=user_id)
        metadata_table = MetadataTable.objects.get(id=metadata_table_id)

        # Check permissions
        if not metadata_table.can_edit(user):
            return {"success": False, "error": "Permission denied: cannot edit this metadata table", "task_id": task_id}

        with transaction.atomic():
            # Use the existing import logic from the viewset
            viewset = MetadataTableViewSet()

            # Create a file-like object from bytes
            file_obj = io.BytesIO(file_data)

            # Process the import using the existing logic
            result = viewset._process_excel_import(
                file_obj=file_obj,
                metadata_table=metadata_table,
                replace_existing=replace_existing,
                user=user,
                validate_ontologies=validate_ontologies,
            )

            return {
                "success": True,
                "metadata_table_name": metadata_table.name,
                "columns_created": result.get("columns_created", 0),
                "columns_updated": result.get("columns_updated", 0),
                "pools_created": result.get("pools_created", 0),
                "pools_updated": result.get("pools_updated", 0),
                "warnings": result.get("warnings", []),
                "task_id": task_id,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc(), "task_id": task_id}
