"""
Metadata table validation utilities for SDRF compliance using sdrf_pipelines.
"""
import io
from typing import Any, Dict

from django.contrib.auth.models import User

from sdrf_pipelines.sdrf.schemas import SchemaRegistry, SchemaValidator
from sdrf_pipelines.sdrf.sdrf import SDRFDataFrame, read_sdrf

from ccv.models import MetadataTable
from ccv.tasks.export_utils import export_sdrf_data


def validate_metadata_table(
    metadata_table: MetadataTable, user: User, validation_options: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Validate a metadata table using sdrf_pipelines SchemaValidator.

    Args:
        metadata_table: MetadataTable instance to validate
        user: User performing the validation
        validation_options: Optional validation configuration

    Returns:
        Dict containing validation results

    Raises:
        PermissionError: If user doesn't have edit permissions on the metadata table
    """
    # Check permissions - user must be able to edit the table to validate it
    if not metadata_table.can_edit(user):
        raise PermissionError(
            f"User {user.username} does not have permission to validate metadata table {metadata_table.id}"
        )

    if validation_options is None:
        validation_options = {}

    include_pools = validation_options.get("include_pools", True)
    template = validation_options.get("template", "default")
    use_ols_cache_only = validation_options.get("use_ols_cache_only", False)

    validation_results = {
        "success": True,
        "metadata_table_id": metadata_table.id,
        "metadata_table_name": metadata_table.name,
        "validation_timestamp": None,
        "errors": [],
        "warnings": [],
    }

    try:
        from django.utils import timezone

        validation_results["validation_timestamp"] = timezone.now().isoformat()

        export_result = export_sdrf_data(
            metadata_table=metadata_table,
            user=user,
            metadata_column_ids=None,
            include_pools=include_pools,
            validate_sdrf=False,
        )

        if not export_result.get("success", False):
            validation_results["success"] = False
            validation_results["errors"].append(export_result.get("error", "Failed to export SDRF data"))
            return validation_results

        # Get the SDRF content
        sdrf_content = export_result.get("sdrf_content", "")
        if not sdrf_content:
            validation_results["success"] = False
            validation_results["errors"].append("No SDRF content generated")
            return validation_results

        # Create StringIO and read SDRF
        sdrf_io = io.StringIO(sdrf_content)
        df = read_sdrf(sdrf_io)

        # Create SchemaValidator and validate using template
        registry = SchemaRegistry()
        validator = SchemaValidator(registry)
        sdrf_df = SDRFDataFrame(df)

        # Perform validation
        errors = validator.validate(sdrf_df, template, use_ols_cache_only)

        if errors:
            validation_results["success"] = False
            for error in errors:
                error_str = str(error)
                if "warning" in error_str.lower():
                    validation_results["warnings"].append(error_str)
                else:
                    validation_results["errors"].append(error_str)
        else:
            validation_results["success"] = True

        return validation_results

    except Exception as e:
        validation_results["success"] = False
        validation_results["errors"].append(f"Validation failed: {str(e)}")
        return validation_results
