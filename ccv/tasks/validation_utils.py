"""
Metadata table validation utilities for SDRF compliance using sdrf_pipelines.
"""
import io
import logging
from typing import Any, Dict

from django.contrib.auth.models import User

from sdrf_pipelines.sdrf.schemas import SchemaRegistry, SchemaValidator
from sdrf_pipelines.sdrf.sdrf import read_sdrf

from ccv.models import MetadataTable
from ccv.tasks.export_utils import export_sdrf_data


def _validate_against_schema(
    validator: SchemaValidator,
    sdrf_df,
    schema_name: str,
    use_ols_cache_only: bool,
    skip_ontology: bool,
) -> Dict[str, Any]:
    """
    Validate SDRF data against a single schema.

    Args:
        validator: SchemaValidator instance
        sdrf_df: SDRFDataFrame to validate
        schema_name: Name of the schema to validate against
        use_ols_cache_only: Whether to use only cached OLS data
        skip_ontology: Whether to skip ontology validation

    Returns:
        Dict containing validation results for this schema
    """
    schema_result = {
        "schema_name": schema_name,
        "success": True,
        "errors": [],
        "warnings": [],
    }

    try:
        errors = validator.validate(
            sdrf_df,
            schema_name,
            use_ols_cache_only=use_ols_cache_only,
            skip_ontology=skip_ontology,
        )

        if errors:
            has_errors = False
            for error in errors:
                error_str = str(error)
                if error.error_type == logging.WARNING:
                    schema_result["warnings"].append(error_str)
                else:
                    schema_result["errors"].append(error_str)
                    has_errors = True
            schema_result["success"] = not has_errors
        else:
            schema_result["success"] = True

    except ValueError as e:
        schema_result["success"] = False
        schema_result["errors"].append(f"Schema '{schema_name}' not found: {str(e)}")
    except Exception as e:
        schema_result["success"] = False
        schema_result["errors"].append(f"Validation error: {str(e)}")

    return schema_result


def validate_metadata_table(
    metadata_table: MetadataTable, user: User, validation_options: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Validate a metadata table using sdrf_pipelines SchemaValidator.

    Supports validating against multiple schemas simultaneously.

    Args:
        metadata_table: MetadataTable instance to validate
        user: User performing the validation
        validation_options: Optional validation configuration containing:
            - include_pools: Whether to include sample pools (default: True)
            - schema_names: List of schema names to validate against (default: ["default"])
            - use_ols_cache_only: Whether to use only cached OLS data (default: False)
            - skip_ontology: Whether to skip ontology validation (default: False)

    Returns:
        Dict containing validation results with per-schema breakdown

    Raises:
        PermissionError: If user doesn't have edit permissions on the metadata table
    """
    if not metadata_table.can_edit(user):
        raise PermissionError(
            f"User {user.username} does not have permission to validate metadata table {metadata_table.id}"
        )

    if validation_options is None:
        validation_options = {}

    include_pools = validation_options.get("include_pools", True)
    schema_names = validation_options.get("schema_names", ["default"])
    use_ols_cache_only = validation_options.get("use_ols_cache_only", False)
    skip_ontology = validation_options.get("skip_ontology", False)

    if not schema_names:
        schema_names = ["default"]

    validation_results = {
        "success": True,
        "metadata_table_id": metadata_table.id,
        "metadata_table_name": metadata_table.name,
        "validation_timestamp": None,
        "schema_results": [],
        "errors": [],
        "warnings": [],
        "summary": {
            "total_schemas": len(schema_names),
            "passed_schemas": 0,
            "failed_schemas": 0,
        },
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

        sdrf_content = export_result.get("sdrf_content", "")
        if not sdrf_content:
            validation_results["success"] = False
            validation_results["errors"].append("No SDRF content generated")
            return validation_results

        sdrf_io = io.StringIO(sdrf_content)
        sdrf_df = read_sdrf(sdrf_io)

        registry = SchemaRegistry()
        validator = SchemaValidator(registry)

        all_errors = []
        all_warnings = []
        passed_count = 0

        for schema_name in schema_names:
            schema_result = _validate_against_schema(
                validator=validator,
                sdrf_df=sdrf_df,
                schema_name=schema_name,
                use_ols_cache_only=use_ols_cache_only,
                skip_ontology=skip_ontology,
            )
            validation_results["schema_results"].append(schema_result)

            if schema_result["success"]:
                passed_count += 1
            else:
                all_errors.extend([f"[{schema_name}] {e}" for e in schema_result["errors"]])

            all_warnings.extend([f"[{schema_name}] {w}" for w in schema_result["warnings"]])

        validation_results["summary"]["passed_schemas"] = passed_count
        validation_results["summary"]["failed_schemas"] = len(schema_names) - passed_count
        validation_results["errors"] = all_errors
        validation_results["warnings"] = all_warnings
        validation_results["success"] = passed_count == len(schema_names)

        return validation_results

    except Exception as e:
        validation_results["success"] = False
        validation_results["errors"].append(f"Validation failed: {str(e)}")
        return validation_results
