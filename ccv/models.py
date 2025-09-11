"""
CUPCAKE Vanilla - Core Metadata Models.

This module contains the core metadata management models extracted from the
main CUPCAKE project. It focuses on metadata columns, sample pools,
templates, and user preferences.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords

from ccc.models import AbstractResource, LabGroup, ResourceType


class BaseMetadataTable(AbstractResource):
    """
    Abstract base model for metadata tables.

    This model provides the core functionality for metadata tables and can be
    extended by other applications to create custom metadata table implementations.

    Key extension points:
    - Override get_custom_fields() to add app-specific fields
    - Override get_custom_validators() to add validation rules
    - Override get_export_formats() to support additional export formats
    - Use the generic foreign key to link to app-specific objects
    """

    name = models.CharField(max_length=255, help_text="Name of the metadata table")
    description = models.TextField(blank=True, null=True, help_text="Description of the metadata table")

    # Table configuration
    sample_count = models.PositiveIntegerField(default=0, help_text="Number of samples in this table")
    version = models.CharField(max_length=50, default="1.0", help_text="Version of the metadata table")

    # Table status
    is_published = models.BooleanField(default=False, help_text="Whether this table is published/finalized")

    # Source app tracking
    source_app = models.CharField(max_length=50, default="ccv", help_text="Django app that created this metadata table")

    # Generic foreign key for optional association with external objects
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta(AbstractResource.Meta):
        abstract = True
        ordering = ["-created_at", "name"]

    def get_custom_fields(self):
        """
        Override this method in subclasses to provide custom field definitions.

        Returns:
            dict: Dictionary of field definitions for custom fields

        Example:
            return {
                'project_code': {
                    'type': 'CharField',
                    'max_length': 50,
                    'required': True,
                    'help_text': 'Project identification code'
                }
            }
        """
        return {}

    def get_custom_validators(self):
        """
        Override this method in subclasses to provide custom validation rules.

        Returns:
            list: List of validator functions
        """
        return []

    def get_export_formats(self):
        """
        Override this method in subclasses to support additional export formats.

        Returns:
            dict: Dictionary of export format configurations

        Example:
            return {
                'custom_xml': {
                    'name': 'Custom XML Format',
                    'extension': '.xml',
                    'mime_type': 'application/xml',
                    'handler': self.export_custom_xml
                }
            }
        """
        return {
            "sdrf": {
                "name": "SDRF Format",
                "extension": ".sdrf.tsv",
                "mime_type": "text/tab-separated-values",
                "handler": self.export_sdrf,
            },
            "excel": {
                "name": "Excel Workbook",
                "extension": ".xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "handler": self.export_excel,
            },
        }

    def validate_custom_data(self, cleaned_data=None):
        """
        Override this method in subclasses to perform custom validation.

        Args:
            cleaned_data: Dictionary of cleaned data from forms/serializers

        Raises:
            ValidationError: If validation fails
        """
        for validator in self.get_custom_validators():
            validator(self, cleaned_data)

    def get_additional_context(self):
        """
        Override this method in subclasses to provide additional context for templates/exports.

        Returns:
            dict: Additional context data
        """
        return {}


class MetadataTable(BaseMetadataTable):
    """
    Concrete implementation of metadata table.

    This is the default implementation provided by CUPCAKE Vanilla.
    Applications can either use this directly or create their own
    implementations by extending BaseMetadataTable.
    """

    class Meta(BaseMetadataTable.Meta):
        app_label = "ccv"
        ordering = ["-created_at", "name"]
        indexes = [
            models.Index(fields=["is_published"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.resource_type:
            self.resource_type = ResourceType.METADATA_TABLE
        super().save(*args, **kwargs)

    def get_column_count(self):
        """Get the number of metadata columns in this table."""
        return self.columns.count()

    def get_sample_range(self):
        """Get the sample number range for this table."""
        if self.sample_count > 0:
            return f"1-{self.sample_count}"
        return "0"

    def change_sample_index(self, old_index: int, new_index: int):
        """
        Change a sample's row index number and update all associated data.

        This method updates:
        - All column modifiers that reference the old sample index
        - All sample pools that contain the old sample index

        Args:
            old_index: Current 1-based sample index to change
            new_index: New 1-based sample index to assign

        Returns:
            dict: Summary of changes made

        Raises:
            ValueError: If indices are invalid or new_index conflicts with existing data
        """
        # Validate inputs
        if old_index < 1 or new_index < 1:
            raise ValueError("Sample indices must be positive integers (1-based)")

        if old_index > self.sample_count:
            raise ValueError(f"Old index {old_index} exceeds sample count {self.sample_count}")

        if new_index > self.sample_count:
            raise ValueError(f"New index {new_index} exceeds sample count {self.sample_count}")

        if old_index == new_index:
            return {"changed": False, "message": "Indices are the same, no changes needed"}

        changes_summary = {
            "changed": True,
            "old_index": old_index,
            "new_index": new_index,
            "columns_updated": 0,
            "pools_updated": 0,
            "modifier_updates": [],
            "pool_updates": [],
        }

        # Update column modifiers
        for column in self.columns.all():
            if column.modifiers:
                updated_modifiers = []
                column_changed = False

                for modifier in column.modifiers:
                    if isinstance(modifier, dict) and "samples" in modifier:
                        # Parse and update sample indices in this modifier
                        updated_samples = self._update_sample_indices_in_range(
                            modifier["samples"], old_index, new_index
                        )

                        if updated_samples != modifier["samples"]:
                            column_changed = True
                            changes_summary["modifier_updates"].append(
                                {
                                    "column": column.name,
                                    "old_samples": modifier["samples"],
                                    "new_samples": updated_samples,
                                }
                            )

                        modifier["samples"] = updated_samples

                    updated_modifiers.append(modifier)

                if column_changed:
                    column.modifiers = updated_modifiers
                    column.save(update_fields=["modifiers"])
                    changes_summary["columns_updated"] += 1

        # Update sample pools
        for pool in self.sample_pools.all():
            pool_changed = False

            # Update pooled_only_samples
            if old_index in pool.pooled_only_samples:
                pool.pooled_only_samples.remove(old_index)
                pool.pooled_only_samples.append(new_index)
                pool.pooled_only_samples.sort()
                pool_changed = True
                changes_summary["pool_updates"].append(
                    {
                        "pool": pool.pool_name,
                        "type": "pooled_only_samples",
                        "change": f"moved {old_index} → {new_index}",
                    }
                )

            # Update pooled_and_independent_samples
            if old_index in pool.pooled_and_independent_samples:
                pool.pooled_and_independent_samples.remove(old_index)
                pool.pooled_and_independent_samples.append(new_index)
                pool.pooled_and_independent_samples.sort()
                pool_changed = True
                changes_summary["pool_updates"].append(
                    {
                        "pool": pool.pool_name,
                        "type": "pooled_and_independent_samples",
                        "change": f"moved {old_index} → {new_index}",
                    }
                )

            if pool_changed:
                pool.save(update_fields=["pooled_only_samples", "pooled_and_independent_samples"])
                changes_summary["pools_updated"] += 1

        return changes_summary

    def _update_sample_indices_in_range(self, sample_range_str: str, old_index: int, new_index: int) -> str:
        """
        Update sample indices within a range string (e.g., "1,2,3" or "1-3,5").

        Args:
            sample_range_str: String containing sample indices like "1,2,3" or "1-3,5"
            old_index: Sample index to replace
            new_index: New sample index

        Returns:
            Updated range string with indices changed
        """
        if not sample_range_str:
            return sample_range_str

        # Parse sample indices from the range string
        sample_indices = []
        for part in sample_range_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = map(int, part.split("-"))
                sample_indices.extend(range(start, end + 1))
            else:
                sample_indices.append(int(part))

        # Replace old index with new index if present
        if old_index in sample_indices:
            # Remove old index and add new index
            while old_index in sample_indices:
                idx = sample_indices.index(old_index)
                sample_indices[idx] = new_index

            # Remove duplicates and sort
            sample_indices = sorted(set(sample_indices))

            # Convert back to compressed range format
            return self._compress_sample_indices_to_string(sample_indices)

        return sample_range_str

    def _compress_sample_indices_to_string(self, indices: list[int]) -> str:
        """
        Convert a list of sample indices to a compressed string format.

        Args:
            indices: Sorted list of sample indices

        Returns:
            Compressed string like "1-3,5,7-9"
        """
        if not indices:
            return ""

        indices = sorted(set(indices))  # Ensure sorted and unique
        ranges = []
        start = indices[0]
        end = indices[0]

        for i in range(1, len(indices)):
            if indices[i] == end + 1:
                end = indices[i]
            else:
                # Add the current range
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = end = indices[i]

        # Add the final range
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")

        return ",".join(ranges)

    def batch_change_sample_indices(self, index_mappings: dict):
        """
        Change multiple sample indices in a single operation.

        Args:
            index_mappings: Dictionary mapping old_index -> new_index

        Returns:
            dict: Summary of all changes made

        Example:
            # Swap samples 1 and 3: {1: 3, 3: 1}
            # Reorder samples: {1: 2, 2: 3, 3: 1}
        """
        if not index_mappings:
            return {"changed": False, "message": "No mappings provided"}

        # Validate all mappings first
        for old_idx, new_idx in index_mappings.items():
            if old_idx < 1 or new_idx < 1:
                raise ValueError("Sample indices must be positive integers (1-based)")
            if old_idx > self.sample_count or new_idx > self.sample_count:
                raise ValueError(f"Sample indices must not exceed sample count {self.sample_count}")

        # Check for conflicts in new indices (unless it's a swap)
        new_indices = list(index_mappings.values())
        old_indices = list(index_mappings.keys())

        for new_idx in new_indices:
            if new_indices.count(new_idx) > 1:
                raise ValueError(f"Multiple samples cannot be mapped to the same index {new_idx}")
            # Allow mapping to an index that's also being moved (swap case)
            if new_idx not in old_indices and new_idx in [
                idx for idx in range(1, self.sample_count + 1) if idx not in old_indices
            ]:
                # This would overwrite an existing sample that's not being moved
                raise ValueError(f"Index {new_idx} is occupied by a sample that's not being moved")

        batch_summary = {
            "changed": True,
            "total_mappings": len(index_mappings),
            "columns_updated": 0,
            "pools_updated": 0,
            "individual_changes": [],
        }

        # Apply changes - need to be careful about order to avoid conflicts
        # For swaps and complex reorderings, use a temporary mapping approach
        temp_offset = self.sample_count + 1000  # Use high temporary indices

        # Step 1: Move all old indices to temporary positions
        temp_mappings = {}
        for old_idx, new_idx in index_mappings.items():
            temp_idx = temp_offset + old_idx
            temp_mappings[old_idx] = temp_idx
            change_result = self.change_sample_index(old_idx, temp_idx)
            batch_summary["individual_changes"].append(
                {"step": "temp_move", "old": old_idx, "temp": temp_idx, "result": change_result}
            )

        # Step 2: Move from temporary positions to final positions
        for old_idx, new_idx in index_mappings.items():
            temp_idx = temp_offset + old_idx
            change_result = self.change_sample_index(temp_idx, new_idx)
            batch_summary["individual_changes"].append(
                {
                    "step": "final_move",
                    "temp": temp_idx,
                    "new": new_idx,
                    "original_old": old_idx,
                    "result": change_result,
                }
            )

        # Summarize total changes
        batch_summary["columns_updated"] = sum(
            change["result"].get("columns_updated", 0) for change in batch_summary["individual_changes"]
        )
        batch_summary["pools_updated"] = sum(
            change["result"].get("pools_updated", 0) for change in batch_summary["individual_changes"]
        )

        return batch_summary

    def reorder_columns_by_schema(
        self, schema_names: list[str] = None, schema_ids: list[int] = None, schema_dir: str = None
    ):
        """
        Reorder columns in this metadata table based on SDRF schema definitions.

        Args:
            schema_names: List of schema names to use for column ordering
            schema_ids: List of schema IDs to use for column ordering
            schema_dir: Optional directory containing custom schemas

        Returns:
            bool: True if reordering was successful, False otherwise
        """
        from .utils import compile_sdrf_columns_from_schemas

        if not schema_names and not schema_ids:
            raise ValueError("Must specify at least one schema or schema_ids")
        if schema_names and schema_ids:
            raise ValueError("Cannot specify both schema_names and schema_ids")

        # Get all columns in this table
        current_columns = list(self.columns.all().order_by("column_position"))

        if not current_columns:
            return True  # Nothing to reorder

        # Get schema-based column ordering
        sections = compile_sdrf_columns_from_schemas(schema_names, schema_ids, schema_dir)
        section_order = ["source_name", "characteristics", "special", "comment", "factor_value"]

        column_map = {}
        for s in section_order:
            column_map[s] = {}

        for col in current_columns:
            col_name = col.name.lower()
            if col_name == "source name":
                if col_name not in column_map["source_name"]:
                    column_map["source_name"][col_name] = []
                column_map["source_name"][col_name].append(col)
            elif col_name.startswith("characteristics"):
                if col_name not in column_map["characteristics"]:
                    column_map["characteristics"][col_name] = []
                column_map["characteristics"][col_name].append(col)
            elif col_name.startswith("comment"):
                if col_name not in column_map["comment"]:
                    column_map["comment"][col_name] = []
                column_map["comment"][col_name].append(col)
            elif col_name.startswith("factor value"):
                if col_name not in column_map["factor_value"]:
                    column_map["factor_value"][col_name] = []
                column_map["factor_value"][col_name].append(col)
            else:
                if col_name not in column_map["special"]:
                    column_map["special"][col_name] = []
                column_map["special"][col_name].append(col)
        processed_columns = set()
        current_position = 0

        # Process columns by schema sections in defined order
        for section in section_order:
            schema_columns = sections.get(section, [])
            # First, process schema columns
            for schema_col_name in schema_columns:
                schema_col_lower = schema_col_name.lower()
                if schema_col_lower in column_map[section] and schema_col_lower not in processed_columns:
                    columns = column_map[section][schema_col_lower]
                    for column in columns:
                        print(f"Setting position {current_position} for column {column.name}")
                        column.column_position = current_position
                        column.save(update_fields=["column_position"])
                        current_position += 1
                    processed_columns.add(schema_col_lower)
            # Then, process remaining columns in this section not in schema
            for col_name, columns in column_map[section].items():
                if col_name not in processed_columns:
                    for column in columns:
                        print(f"Setting position {current_position} for column {column.name} (not in schema)")
                        column.column_position = current_position
                        column.save(update_fields=["column_position"])
                        current_position += 1

        for col in self.columns.all():
            print(f"Column: {col.name}, Position: {col.column_position}")
        # Removed unnecessary second loop and variables

        return True

    def add_column(self, column_data: dict, position: int = None):
        """
        Add a new column to this metadata table at the specified position.
        Also adds the column to all associated pools.

        Args:
            column_data: Dictionary containing column data
            position: Position to insert the column (None for end)

        Returns:
            MetadataColumn: The created column
        """
        if position is not None:
            # Shift existing columns to make room
            self.columns.filter(column_position__gte=position).update(column_position=models.F("column_position") + 1)
        else:
            # Add at the end
            position = self.columns.count()

        # Create the new column
        column_data["metadata_table"] = self
        column_data["column_position"] = position
        column = MetadataColumn.objects.create(**column_data)

        # Synchronize with pools: add column to all pools of this table
        self._sync_column_to_pools(column, action="add")

        return column

    def add_column_with_auto_reorder(self, column_data: dict, position: int = None, auto_reorder: bool = True):
        """
        Add a new column to this metadata table and automatically reorder columns.

        This convenience method combines adding a column with automatic schema-based
        reordering using the same patterns established throughout the codebase.

        Args:
            column_data: Dictionary containing column data
            position: Position to insert the column (None for end, ignored if auto_reorder=True)
            auto_reorder: Whether to automatically reorder columns after adding (default: True)

        Returns:
            dict: Result containing the created column and reordering status
                {
                    'column': MetadataColumn,
                    'reordered': bool,
                    'schema_ids_used': list[int],
                    'message': str
                }
        """
        # Add the column first (will be repositioned during reordering if enabled)
        column = self.add_column(column_data, position=position)

        result = {"column": column, "reordered": False, "schema_ids_used": [], "message": "Column added successfully"}

        if auto_reorder:
            try:
                # Collect schema IDs from existing columns using established pattern
                schema_ids = set()
                for col in self.columns.all():
                    if col.template and col.template.schema:
                        schema_ids.add(col.template.schema.id)

                schema_ids_list = list(schema_ids)
                result["schema_ids_used"] = schema_ids_list

                if schema_ids_list:
                    # Use existing schema-based reordering method
                    reorder_success = self.reorder_columns_by_schema(schema_ids=schema_ids_list)
                    if reorder_success:
                        result["reordered"] = True
                        result["message"] = f"Column added and reordered using {len(schema_ids_list)} schema(s)"
                    else:
                        result["message"] = "Column added successfully, but schema reordering failed"
                else:
                    # No schemas found, just normalize positions
                    self.normalize_column_positions()
                    result["reordered"] = True
                    result["message"] = "Column added and positions normalized (no schemas found)"

            except Exception as e:
                # If reordering fails, column is still added but not reordered
                result["message"] = f"Column added successfully, but reordering failed: {str(e)}"

        return result

    def remove_column(self, column_id: int):
        """
        Remove a column and adjust positions of remaining columns.
        Also removes the column from all associated pools.

        Args:
            column_id: ID of the column to remove

        Returns:
            bool: True if column was removed, False if not found
        """
        try:
            column = self.columns.get(id=column_id)
            removed_position = column.column_position

            # Synchronize with pools: remove column from all pools of this table
            self._sync_column_to_pools(column, action="remove")

            # Delete the column
            column.delete()

            # Shift remaining columns down
            self.columns.filter(column_position__gt=removed_position).update(
                column_position=models.F("column_position") - 1
            )

            return True
        except MetadataColumn.DoesNotExist:
            return False

    def _sync_column_to_pools(self, column, action="add"):
        """
        Synchronize a column operation with all pools belonging to this metadata table.

        Args:
            column: MetadataColumn instance to synchronize
            action: 'add' or 'remove'
        """
        for pool in self.sample_pools.all():
            if action == "add":
                # Create a new column for the pool based on the main table column
                pool_column_data = {
                    "name": column.name,
                    "type": column.type,
                    "value": column.value,
                    "modifiers": column.modifiers.copy() if column.modifiers else [],
                    "column_position": column.column_position,
                    "not_applicable": column.not_applicable,
                    "mandatory": column.mandatory,
                    "hidden": column.hidden,
                    "auto_generated": column.auto_generated,
                    "readonly": column.readonly,
                    "ontology_type": column.ontology_type,
                    "ontology_options": column.ontology_options.copy() if column.ontology_options else None,
                    "custom_ontology_filters": column.custom_ontology_filters.copy()
                    if column.custom_ontology_filters
                    else {},
                    "suggested_values": column.suggested_values.copy() if column.suggested_values else [],
                    "staff_only": column.staff_only,
                    "possible_default_values": column.possible_default_values.copy()
                    if column.possible_default_values
                    else [],
                    "template": column.template,
                }

                # Create a new MetadataColumn instance for the pool
                pool_column = MetadataColumn.objects.create(**pool_column_data)
                pool.metadata_columns.add(pool_column)

            elif action == "remove":
                # Remove columns from this pool that have the same name as the removed column
                pool_columns_to_remove = pool.metadata_columns.filter(name=column.name)
                for pool_column in pool_columns_to_remove:
                    pool.metadata_columns.remove(pool_column)
                    pool_column.delete()

    def reorder_column(self, column_id: int, new_position: int):
        """
        Move a column to a new position, adjusting other columns as needed.

        Args:
            column_id: ID of the column to move
            new_position: New position for the column

        Returns:
            bool: True if reordering was successful, False if column not found
        """
        try:
            column = self.columns.get(id=column_id)
            old_position = column.column_position

            if old_position == new_position:
                return True  # No change needed

            # Ensure new_position is within bounds
            max_position = self.columns.count() - 1
            new_position = max(0, min(new_position, max_position))

            if old_position < new_position:
                # Moving down: shift columns between old and new position up
                self.columns.filter(column_position__gt=old_position, column_position__lte=new_position).update(
                    column_position=models.F("column_position") - 1
                )
            else:
                # Moving up: shift columns between new and old position down
                self.columns.filter(column_position__gte=new_position, column_position__lt=old_position).update(
                    column_position=models.F("column_position") + 1
                )

            # Update the moved column's position
            column.column_position = new_position
            column.save(update_fields=["column_position"])

            return True
        except MetadataColumn.DoesNotExist:
            return False

    def normalize_column_positions(self):
        """
        Ensure column positions are sequential starting from 0 with no gaps.
        """
        columns = self.columns.all().order_by("column_position", "id")
        for index, column in enumerate(columns):
            if column.column_position != index:
                column.column_position = index
                column.save(update_fields=["column_position"])

    @classmethod
    def combine_tables_columnwise(
        cls,
        source_tables: list["MetadataTable"],
        target_name: str,
        description: str = None,
        user=None,
        apply_schema_reordering: bool = True,
    ) -> "MetadataTable":
        """
        Combine multiple metadata tables column-wise (side by side).

        This creates a new table with all columns from source tables combined,
        and the sample count set to the maximum sample count among source tables.

        Args:
            source_tables: List of MetadataTable objects to combine
            target_name: Name for the new combined table
            description: Optional description for the new table
            user: User creating the combined table
            apply_schema_reordering: Whether to apply schema-based column reordering

        Returns:
            MetadataTable: New combined metadata table

        Raises:
            ValueError: If no source tables provided or other validation errors
        """
        if not source_tables:
            raise ValueError("At least one source table is required")

        if not target_name:
            raise ValueError("Target table name is required")

        # Get the maximum sample count from all source tables
        max_sample_count = max(table.sample_count for table in source_tables)

        # Create the new combined metadata table
        combined_table = cls.objects.create(
            name=target_name,
            description=description or f"Combined table from {len(source_tables)} source tables",
            sample_count=max_sample_count,
            owner=user,
        )

        # Track column position counter and schema IDs
        column_position = 0
        schema_ids = set()

        try:
            # Combine columns from all source tables
            for table_index, source_table in enumerate(source_tables):
                table_prefix = f"T{table_index + 1}_" if len(source_tables) > 1 else ""

                for source_column in source_table.columns.order_by("column_position", "name"):
                    # Create new column with potentially prefixed name to avoid conflicts
                    new_column_name = f"{table_prefix}{source_column.name}"

                    # Check if a column with this name already exists
                    existing_column = combined_table.columns.filter(name=new_column_name).first()
                    if existing_column:
                        # Add numeric suffix to make it unique
                        counter = 1
                        while existing_column:
                            new_column_name = f"{table_prefix}{source_column.name}_{counter}"
                            existing_column = combined_table.columns.filter(name=new_column_name).first()
                            counter += 1

                    # Create the new column
                    new_column = MetadataColumn.objects.create(
                        metadata_table=combined_table,
                        name=new_column_name,
                        type=source_column.type,
                        value=source_column.value,
                        modifiers=source_column.modifiers.copy() if source_column.modifiers else [],
                        column_position=column_position,
                        mandatory=source_column.mandatory,
                        hidden=source_column.hidden,
                        field_mask=source_column.field_mask,
                        ontology_reference=source_column.ontology_reference,
                    )

                    # Copy templates relationship if it exists
                    if hasattr(source_column, "template") and source_column.template:
                        new_column.template = source_column.template
                        new_column.save()

                        # Collect schema IDs for reordering
                        if source_column.template.template and source_column.template.template.schema:
                            schema_ids.add(source_column.template.template.schema.id)

                    column_position += 1

            # Combine sample pools from all source tables
            for table_index, source_table in enumerate(source_tables):
                table_prefix = f"T{table_index + 1}_" if len(source_tables) > 1 else ""

                for source_pool in source_table.sample_pools.all():
                    # Create new pool with prefixed name
                    new_pool_name = f"{table_prefix}{source_pool.pool_name}"

                    # Ensure unique pool name
                    counter = 1
                    original_pool_name = new_pool_name
                    while combined_table.sample_pools.filter(pool_name=new_pool_name).exists():
                        new_pool_name = f"{original_pool_name}_{counter}"
                        counter += 1

                    new_pool = SamplePool.objects.create(
                        metadata_table=combined_table,
                        pool_name=new_pool_name,
                        pooled_only_samples=source_pool.pooled_only_samples.copy(),
                        pooled_and_independent_samples=source_pool.pooled_and_independent_samples.copy(),
                        is_reference=source_pool.is_reference,
                    )

                    # Copy pool metadata columns
                    for source_pool_column in source_pool.metadata_columns.all():
                        # Find corresponding column in the combined table
                        target_column_name = f"{table_prefix}{source_pool_column.name}"
                        target_column = combined_table.columns.filter(name=target_column_name).first()

                        if target_column:
                            # Create pool column copy
                            pool_column = MetadataColumn.objects.create(
                                name=source_pool_column.name,
                                type=source_pool_column.type,
                                value=source_pool_column.value,
                                modifiers=source_pool_column.modifiers.copy() if source_pool_column.modifiers else [],
                                column_position=source_pool_column.column_position,
                                mandatory=source_pool_column.mandatory,
                                hidden=source_pool_column.hidden,
                                field_mask=source_pool_column.field_mask,
                                ontology_reference=source_pool_column.ontology_reference,
                            )
                            new_pool.metadata_columns.add(pool_column)

            # Apply schema-based column reordering if requested and schemas are available
            if apply_schema_reordering and schema_ids:
                try:
                    combined_table.reorder_columns_by_schema(schema_ids=list(schema_ids))
                except Exception as e:
                    print(f"Warning: Failed to reorder columns by schema: {e}")
                    combined_table.normalize_column_positions()
            else:
                # Basic column position normalization
                combined_table.normalize_column_positions()

            return combined_table

        except Exception as e:
            # Clean up on error
            combined_table.delete()
            raise Exception(f"Failed to combine tables column-wise: {str(e)}")

    @classmethod
    def combine_tables_rowwise(
        cls,
        source_tables: list["MetadataTable"],
        target_name: str,
        description: str = None,
        user=None,
        apply_schema_reordering: bool = True,
        merge_strategy: str = "union",
    ) -> "MetadataTable":
        """
        Combine multiple metadata tables row-wise (stacked vertically).

        This creates a new table with rows from all source tables stacked,
        using either union (all unique columns) or intersection (only common columns).

        Args:
            source_tables: List of MetadataTable objects to combine
            target_name: Name for the new combined table
            description: Optional description for the new table
            user: User creating the combined table
            apply_schema_reordering: Whether to apply schema-based column reordering
            merge_strategy: "union" (all columns) or "intersection" (common columns only)

        Returns:
            MetadataTable: New combined metadata table

        Raises:
            ValueError: If no source tables provided or other validation errors
        """
        if not source_tables:
            raise ValueError("At least one source table is required")

        if not target_name:
            raise ValueError("Target table name is required")

        if merge_strategy not in ["union", "intersection"]:
            raise ValueError("Merge strategy must be 'union' or 'intersection'")

        # Analyze columns from all source tables
        all_column_info = {}  # column_name -> {type, properties, source_tables}
        schema_ids = set()

        for source_table in source_tables:
            for column in source_table.columns.all():
                if column.name not in all_column_info:
                    all_column_info[column.name] = {
                        "type": column.type,
                        "mandatory": column.mandatory,
                        "hidden": column.hidden,
                        "field_mask": column.field_mask,
                        "ontology_reference": column.ontology_reference,
                        "source_tables": [],
                    }
                all_column_info[column.name]["source_tables"].append(source_table)

                # Collect schema IDs
                if (
                    hasattr(column, "template")
                    and column.template
                    and column.template.template
                    and column.template.template.schema
                ):
                    schema_ids.add(column.template.template.schema.id)

        # Determine which columns to include based on merge strategy
        if merge_strategy == "intersection":
            # Only include columns present in ALL source tables
            columns_to_include = {
                name: info for name, info in all_column_info.items() if len(info["source_tables"]) == len(source_tables)
            }
        else:  # union
            # Include all columns from all source tables
            columns_to_include = all_column_info

        if not columns_to_include:
            raise ValueError(f"No common columns found for {merge_strategy} merge strategy")

        # Calculate total sample count
        total_sample_count = sum(table.sample_count for table in source_tables)

        # Create the new combined metadata table
        combined_table = cls.objects.create(
            name=target_name,
            description=description
            or f"Row-wise combined table from {len(source_tables)} source tables ({merge_strategy})",
            sample_count=total_sample_count,
            owner=user,
        )

        try:
            # Create columns in the combined table
            for column_position, (column_name, column_info) in enumerate(columns_to_include.items()):
                new_column = MetadataColumn.objects.create(
                    metadata_table=combined_table,
                    name=column_name,
                    type=column_info["type"],
                    column_position=column_position,
                    mandatory=column_info["mandatory"],
                    hidden=column_info["hidden"],
                    field_mask=column_info["field_mask"],
                    ontology_reference=column_info["ontology_reference"],
                )

                # Combine modifiers and values from all source tables
                combined_modifiers = []
                sample_offset = 1  # Start from sample 1

                for source_table in source_tables:
                    source_column = source_table.columns.filter(name=column_name).first()

                    if source_column:
                        # Use source column's value and modifiers
                        if not new_column.value:
                            new_column.value = source_column.value

                        # Adjust sample indices in modifiers
                        if source_column.modifiers:
                            for modifier in source_column.modifiers:
                                if isinstance(modifier, dict) and "samples" in modifier:
                                    # Parse and adjust sample ranges
                                    adjusted_modifier = modifier.copy()
                                    original_samples = modifier["samples"]
                                    adjusted_ranges = []

                                    for part in original_samples.split(","):
                                        part = part.strip()
                                        if "-" in part:
                                            start, end = map(int, part.split("-"))
                                            adjusted_ranges.append(
                                                f"{start + sample_offset - 1}-{end + sample_offset - 1}"
                                            )
                                        else:
                                            sample_idx = int(part)
                                            adjusted_ranges.append(str(sample_idx + sample_offset - 1))

                                    adjusted_modifier["samples"] = ",".join(adjusted_ranges)
                                    combined_modifiers.append(adjusted_modifier)
                    else:
                        # Column doesn't exist in this source table (union case)
                        # Add default value for this table's sample range
                        if merge_strategy == "union":
                            end_sample = sample_offset + source_table.sample_count - 1
                            if sample_offset == end_sample:
                                sample_range = str(sample_offset)
                            else:
                                sample_range = f"{sample_offset}-{end_sample}"

                            combined_modifiers.append(
                                {"samples": sample_range, "value": ""}  # Empty value for missing columns
                            )

                    sample_offset += source_table.sample_count

                new_column.modifiers = combined_modifiers
                new_column.save()

            # Combine sample pools with adjusted sample indices
            sample_offset = 1
            for table_index, source_table in enumerate(source_tables):
                table_prefix = f"T{table_index + 1}_" if len(source_tables) > 1 else ""

                for source_pool in source_table.sample_pools.all():
                    new_pool_name = f"{table_prefix}{source_pool.pool_name}"

                    # Ensure unique pool name
                    counter = 1
                    original_pool_name = new_pool_name
                    while combined_table.sample_pools.filter(pool_name=new_pool_name).exists():
                        new_pool_name = f"{original_pool_name}_{counter}"
                        counter += 1

                    # Adjust sample indices for the new table
                    adjusted_pooled_only = [idx + sample_offset - 1 for idx in source_pool.pooled_only_samples]
                    adjusted_pooled_independent = [
                        idx + sample_offset - 1 for idx in source_pool.pooled_and_independent_samples
                    ]

                    new_pool = SamplePool.objects.create(
                        metadata_table=combined_table,
                        pool_name=new_pool_name,
                        pooled_only_samples=adjusted_pooled_only,
                        pooled_and_independent_samples=adjusted_pooled_independent,
                        is_reference=source_pool.is_reference,
                    )

                    # Copy pool metadata columns for columns that exist in the combined table
                    for source_pool_column in source_pool.metadata_columns.all():
                        if source_pool_column.name in columns_to_include:
                            pool_column = MetadataColumn.objects.create(
                                name=source_pool_column.name,
                                type=source_pool_column.type,
                                value=source_pool_column.value,
                                modifiers=source_pool_column.modifiers.copy() if source_pool_column.modifiers else [],
                                column_position=source_pool_column.column_position,
                                mandatory=source_pool_column.mandatory,
                                hidden=source_pool_column.hidden,
                                field_mask=source_pool_column.field_mask,
                                ontology_reference=source_pool_column.ontology_reference,
                            )
                            new_pool.metadata_columns.add(pool_column)

                sample_offset += source_table.sample_count

            # Apply schema-based column reordering if requested and schemas are available
            if apply_schema_reordering and schema_ids:
                try:
                    combined_table.reorder_columns_by_schema(schema_ids=list(schema_ids))
                except Exception as e:
                    print(f"Warning: Failed to reorder columns by schema: {e}")
                    combined_table.normalize_column_positions()
            else:
                # Basic column position normalization
                combined_table.normalize_column_positions()

            # Update pooled sample columns if they exist
            from .utils import update_pooled_sample_column_for_table

            update_pooled_sample_column_for_table(combined_table)

            return combined_table

        except Exception as e:
            # Clean up on error
            combined_table.delete()
            raise Exception(f"Failed to combine tables row-wise: {str(e)}")


class MetadataColumn(models.Model):
    """
    Represents a metadata column with type, value, and configuration options.
    Core model for managing experimental metadata in SDRF-compliant format.
    """

    # Parent table relationship
    metadata_table = models.ForeignKey(
        MetadataTable,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Metadata table this column belongs to",
        blank=True,
        null=True,
    )

    # Column definition
    name = models.CharField(max_length=255, help_text="Name of the metadata column")
    type = models.CharField(max_length=255, help_text="Data type (e.g., 'factor value', 'characteristics')")
    column_position = models.IntegerField(blank=True, null=True, default=0, help_text="Position in column ordering")
    value = models.TextField(blank=True, null=True, help_text="Default or current value")
    not_applicable = models.BooleanField(default=False, help_text="Whether this column is marked as not applicable")

    # Template reference (optional - tracks which template this column was created from)
    template = models.ForeignKey(
        "MetadataColumnTemplate",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_columns",
        help_text="Template this column was created from",
    )

    # Column behavior configuration
    mandatory = models.BooleanField(default=False, help_text="Whether this column is required")
    hidden = models.BooleanField(default=False, help_text="Whether this column is hidden from main view")
    auto_generated = models.BooleanField(default=False, help_text="Whether this column is automatically generated")
    readonly = models.BooleanField(default=False, help_text="Whether this column is read-only")

    # Advanced features
    modifiers = models.JSONField(default=list, blank=True, help_text="Sample-specific value modifications")

    ontology_choices = [
        ("species", "Species"),
        ("tissue", "Tissue"),
        ("human_disease", "Human Disease"),
        ("subcellular_location", "Subcellular Location"),
        ("unimod", "Unimod Modifications"),
        ("ncbi_taxonomy", "NCBI Taxonomy"),
        ("mondo", "MONDO Disease"),
        ("uberon", "UBERON Anatomy"),
        ("subcellular_location", "Subcellular Location"),
        ("chebi", "ChEBI"),
        ("cell_ontology", "Cell Ontology"),
        ("ms_unique_vocabularies", "MS Unique Vocabularies"),
        ("psi_ms", "PSI-MS Controlled Vocabulary"),
    ]

    # Ontology configuration
    ontology_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=ontology_choices,
        help_text="Type of ontology to use for validation and suggestions",
    )

    ontology_options = models.JSONField(blank=True, null=True, help_text="Ontology options")

    custom_ontology_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom filters to apply when querying the ontology",
    )
    suggested_values = models.JSONField(default=list, blank=True, help_text="Cached suggested values from ontology")
    enable_typeahead = models.BooleanField(default=True, help_text="Enable typeahead suggestions in forms")
    staff_only = models.BooleanField(default=False, help_text="Whether only staff can edit this column")
    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()
    possible_default_values = models.JSONField(
        default=list,
        blank=True,
        help_text="List of possible default sdrf values for this column template",
    )

    class Meta:
        app_label = "ccv"
        ordering = ["metadata_table", "column_position", "name"]
        indexes = [
            models.Index(fields=["metadata_table", "column_position"]),
            models.Index(fields=["metadata_table", "name"]),
            models.Index(fields=["name", "type"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.type})"

    def clean(self):
        """Custom validation for metadata columns."""
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.type:
            self.type = self.type.strip()

    def get_ontology_model(self):
        """Get the associated ontology model class based on ontology_type."""
        if not self.ontology_type:
            return None

        ontology_mapping = {
            "species": Species,
            "tissue": Tissue,
            "human_disease": HumanDisease,
            "subcellular_location": SubcellularLocation,
            "ms_unique_vocabularies": MSUniqueVocabularies,
            "unimod": Unimod,
            "chebi": ChEBICompound,
            "ncbi_taxonomy": NCBITaxonomy,
            "mondo": MondoDisease,
            "uberon": UberonAnatomy,
            "cell_ontology": CellOntology,
            "psi_ms": PSIMSOntology,
        }
        return ontology_mapping.get(self.ontology_type)

    def get_ontology_suggestions(self, search_term: str = "", limit: int = 20, search_type: str = "icontains"):
        """
        Get ontology suggestions based on the column's ontology type with enhanced search capabilities.

        Args:
            search_term: Term to search for
            limit: Maximum number of results to return
            search_type: Type of search - 'icontains', 'istartswith', or 'exact'
        """
        model_class = self.get_ontology_model()
        if not model_class:
            return []
        queryset = model_class.objects.all()

        # Use the search_type directly (already case-insensitive for istartswith and icontains)
        case_insensitive_search_type = search_type

        # Apply custom ontology filters first
        if self.custom_ontology_filters:
            for field, filter_value in self.custom_ontology_filters.items():
                if field == self.ontology_type:
                    if isinstance(filter_value, dict):
                        # Handle complex filter values like {'icontains': 'value'} or {'exact': 'value'}
                        for lookup, value in filter_value.items():
                            filter_kwargs = {f"{lookup}__{case_insensitive_search_type}": value}
                            queryset = queryset.filter(**filter_kwargs)

        # Apply search filtering based on search_type and model type
        if search_term:
            search_queries = []

            # Build search queries based on ontology type and search type
            if self.ontology_type == "species":
                search_fields = ["official_name", "common_name", "code"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "tissue":
                search_fields = ["identifier", "accession", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "human_disease":
                search_fields = ["identifier", "acronym", "accession", "definition", "synonyms", "keywords"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "subcellular_location":
                search_fields = ["accession", "location_identifier", "definition", "synonyms", "content"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "ms_unique_vocabularies":
                search_fields = ["accession", "name", "definition"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "unimod":
                search_fields = ["accession", "name", "definition"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "chebi":
                search_fields = ["identifier", "name", "definition", "synonyms", "formula"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "ncbi_taxonomy":
                search_fields = ["scientific_name", "common_name", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "mondo":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "uberon":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "cell_ontology":
                search_fields = ["identifier", "name", "definition", "synonyms", "organism", "tissue_origin"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "psi_ms":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            # Combine all search queries with OR
            if search_queries:
                combined_query = search_queries[0]
                for query in search_queries[1:]:
                    combined_query |= query
                queryset = queryset.filter(combined_query)

        # Order by relevance - prioritize primary field matches first
        if search_term and search_type in ["icontains", "istartswith"]:
            from django.db.models import Case, IntegerField, When

            if self.ontology_type == "species" or self.ontology_type == "ncbi_taxonomy":
                # For species, prioritize scientific_name matches first
                if search_type == "istartswith":
                    primary_field_condition = models.Q(scientific_name__istartswith=search_term)
                else:  # icontains
                    primary_field_condition = models.Q(scientific_name__icontains=search_term)

                queryset = queryset.annotate(
                    primary_match=Case(
                        When(primary_field_condition, then=0),
                        default=1,
                        output_field=IntegerField(),
                    )
                ).order_by("primary_match", "scientific_name")

            elif self.ontology_type == "tissue":
                # For tissue, prioritize official_name matches
                if search_type == "istartswith":
                    primary_field_condition = models.Q(official_name__istartswith=search_term)
                else:  # icontains
                    primary_field_condition = models.Q(official_name__icontains=search_term)

                queryset = queryset.annotate(
                    primary_match=Case(
                        When(primary_field_condition, then=0),
                        default=1,
                        output_field=IntegerField(),
                    )
                ).order_by("primary_match", "official_name")

            elif hasattr(queryset.model, "name"):
                # For other ontologies with 'name' field
                if search_type == "istartswith":
                    primary_field_condition = models.Q(name__istartswith=search_term)
                else:  # icontains
                    primary_field_condition = models.Q(name__icontains=search_term)

                queryset = queryset.annotate(
                    primary_match=Case(
                        When(primary_field_condition, then=0),
                        default=1,
                        output_field=IntegerField(),
                    )
                ).order_by("primary_match", "name")

            elif hasattr(queryset.model, "identifier"):
                queryset = queryset.order_by("identifier")

        return list(queryset[:limit].values())

    def convert_sdrf_to_metadata(self, value: str) -> str | None:
        """
        Convert a value from SDRF format to the internal metadata format based on assigned ontology.
        :param value:
            The value to convert, typically from SDRF format.
        :return:
            The converted value suitable for storage in this metadata column.
        """
        value = value.strip()
        has_key_value = False
        if "=" in value:
            has_key_value = True
        value_splitted = value.split(";")
        value_dict = {}
        for field in value_splitted:
            field_split = field.split("=")
            if len(field_split) == 2:
                key = field_split[0].strip()
                val = field_split[1].strip()
                value_dict[key] = val
            else:
                value_dict[field.strip()] = ""
        if "AC" in value_dict:
            lookup_value = self.get_ontology_suggestions(value_dict["AC"], limit=1, search_type="exact")
        else:
            if "NT" in value_dict:
                lookup_value = self.get_ontology_suggestions(value_dict["NT"], limit=1, search_type="exact")
            else:
                lookup_value = self.get_ontology_suggestions(value, limit=1, search_type="exact")
        if lookup_value:
            lookup_value = lookup_value[0]
        else:
            return value
        row_value = []
        if self.ontology_type == "species":
            official_name = lookup_value.get("official_name", "").strip()
            # taxon_id = value_dict.get("taxon", "")
            return f"{official_name}"
        elif (
            "[label]" in self.name
            or "[instrument]" in self.name
            or "[cleavage agent details]" in self.name
            or "[dissociation method]" in self.name
        ):
            accession = lookup_value.get("accession", "").strip()
            if has_key_value:
                if "NT" in value_dict:
                    row_value.append(f"NT={value_dict['NT']}")
            else:
                row_value.append(f"NT={value}")
            row_value.append(f"AC={accession}")
            return ";".join(row_value)
        elif self.ontology_type == "unimod":
            accession = lookup_value.get("accession", "").strip()
            if has_key_value:
                value_dict["AC"] = accession
                return ";".join([f"{k}={v}" for k, v in value_dict.items()])
            else:
                return ";".join([f"AC={accession}", f"NT={value}"])
        elif self.ontology_type == "tissue" or self.ontology_type == "human_disease":
            if has_key_value:
                if "AC" in value_dict:
                    accession = value_dict["AC"].strip()
                    nt = lookup_value.get("identifier", "").strip()
                    row_value.append(f"AC={accession}")
                    row_value.append(f"NT={nt}")
                else:
                    nt = lookup_value.get("identifier", "").strip()
                    row_value.append(f"NT={nt}")
            else:
                nt = lookup_value.get("identifier", "").strip()
                row_value.append(f"NT={nt}")

            return ";".join(row_value)

        # Default case - return the original value if no specific ontology handling
        return value

    def validate_value_against_ontology(self, value: str) -> bool:
        """Validate if a value exists in the associated ontology."""
        model_class = self.get_ontology_model()
        if not model_class:
            return True  # No ontology validation required

        if not value or value.strip() == "":
            return True  # Empty values are allowed

        # Check if value exists in ontology based on model type
        if self.ontology_type == "species":
            return model_class.objects.filter(
                models.Q(official_name__iexact=value)
                | models.Q(common_name__iexact=value)
                | models.Q(code__iexact=value)
            ).exists()
        elif self.ontology_type in ["tissue", "disease", "subcellular_location"]:
            return model_class.objects.filter(
                models.Q(accession__iexact=value) | models.Q(synonyms__icontains=value)
            ).exists()
        elif self.ontology_type in ["ms_unique_vocabularies", "unimod"]:
            return model_class.objects.filter(models.Q(name__iexact=value) | models.Q(accession__iexact=value)).exists()

        return True

    def _format_sample_indices_to_string(self, indices: list[int]) -> str:
        """
        Format a list of 1-based sample indices into a compressed string format.

        Args:
            indices: List of 1-based sample indices (e.g., [1, 2, 3, 5, 6])

        Returns:
            Compressed string format (e.g., "1-3,5-6")
        """
        if not indices:
            return ""

        # Sort indices to ensure proper range detection
        sorted_indices = sorted(set(indices))
        ranges = []
        start = sorted_indices[0]
        end = sorted_indices[0]

        for i in range(1, len(sorted_indices)):
            if sorted_indices[i] == end + 1:
                # Continue the current range
                end = sorted_indices[i]
            else:
                # End current range and start new one
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = sorted_indices[i]
                end = sorted_indices[i]

        # Add the final range
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")

        return ",".join(ranges)

    def update_column_value_smart(self, value: str, sample_indices: list[int] = None, value_type: str = "default"):
        """
        Update column value with automatic modifier calculation.

        Args:
            value: New value to set
            sample_indices: List of 1-based sample indices for sample-specific updates (None for default)
            value_type: "default", "sample_specific", or "replace_all"

        Returns:
            dict: Summary of changes made
        """
        changes = {
            "old_default": self.value,
            "new_default": self.value,
            "old_modifiers": self.modifiers.copy() if self.modifiers else [],
            "new_modifiers": [],
            "updated_samples": [],
        }

        if value_type == "default":
            # Update default value only
            changes["new_default"] = value
            self.value = value

        elif value_type == "sample_specific" and sample_indices:
            # Update value for specific samples
            if not self.modifiers:
                self.modifiers = []

            # Find existing modifier that overlaps with these samples
            overlapping_modifier = None
            for i, modifier in enumerate(self.modifiers):
                if isinstance(modifier, dict) and "samples" in modifier:
                    existing_samples = self._parse_sample_indices_from_modifier_string(modifier["samples"])
                    if set(existing_samples) & set(
                        [idx - 1 for idx in sample_indices]
                    ):  # Convert to 0-based for comparison
                        overlapping_modifier = i
                        break

            if overlapping_modifier is not None:
                # Update existing modifier
                self.modifiers[overlapping_modifier]["value"] = value
                # Update sample range to include all requested samples
                existing_samples = self._parse_sample_indices_from_modifier_string(
                    self.modifiers[overlapping_modifier]["samples"]
                )
                combined_samples = sorted(set(existing_samples + [idx - 1 for idx in sample_indices]))
                self.modifiers[overlapping_modifier]["samples"] = self._format_sample_indices_to_string(
                    [idx + 1 for idx in combined_samples]  # Convert back to 1-based
                )
            else:
                # Create new modifier
                sample_range_string = self._format_sample_indices_to_string(sample_indices)
                new_modifier = {"samples": sample_range_string, "value": value}
                self.modifiers.append(new_modifier)

            changes["updated_samples"] = sample_indices

        elif value_type == "replace_all":
            # Replace default value and clear all modifiers
            changes["new_default"] = value
            self.value = value
            self.modifiers = []

        changes["new_modifiers"] = self.modifiers.copy() if self.modifiers else []
        return changes


class SamplePool(models.Model):
    """
    Represents a pool of samples for SDRF compliance and experiment organization.
    Matches original CUPCAKE's sophisticated pooling system with metadata support.
    """

    # Parent table relationship
    metadata_table = models.ForeignKey(
        MetadataTable,
        on_delete=models.CASCADE,
        related_name="sample_pools",
        help_text="Metadata table this pool belongs to",
    )

    pool_name = models.CharField(max_length=255, help_text="Name of the sample pool")
    pool_description = models.TextField(blank=True, null=True, help_text="Optional description of the pool")

    # Pool composition (matching original CUPCAKE structure)
    pooled_only_samples = models.JSONField(default=list, help_text="Sample indices that exist only in this pool")
    pooled_and_independent_samples = models.JSONField(
        default=list,
        help_text="Sample indices that exist both in pool and independently",
    )

    # Template sample support (from original CUPCAKE)
    template_sample = models.IntegerField(
        blank=True,
        null=True,
        help_text="Sample index to copy metadata from when creating this pool",
    )

    # Reference pool indicator for SDRF compliance
    is_reference = models.BooleanField(
        default=False,
        help_text="Whether this pool is a reference pool for channel normalization (appears in SDRF export with SN= format)",
    )

    # Metadata relationships (unified for ccv - no user/staff separation)
    metadata_columns = models.ManyToManyField("MetadataColumn", related_name="sample_pools", blank=True)

    # User who created this pool
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "ccv"
        unique_together = ["metadata_table", "pool_name"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["metadata_table", "pool_name"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.pool_name} - Table {self.metadata_table.id}"

    def clean(self):
        """Validate that no sample appears in both lists and indices are valid."""
        pooled_only_set = set(self.pooled_only_samples)
        pooled_and_independent_set = set(self.pooled_and_independent_samples)

        if pooled_only_set & pooled_and_independent_set:
            raise ValidationError("A sample cannot be both 'pooled only' and 'pooled and independent'")

        # Validate sample indices are within metadata table sample range
        if hasattr(self, "metadata_table") and self.metadata_table:
            max_sample = self.metadata_table.sample_count
            all_samples = pooled_only_set | pooled_and_independent_set

            invalid_samples = [s for s in all_samples if s < 1 or s > max_sample]
            if invalid_samples:
                raise ValidationError(
                    f"Sample indices {invalid_samples} are invalid. " f"Must be between 1 and {max_sample}"
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def all_pooled_samples(self):
        """Get all samples in this pool (both pooled-only and pooled+independent)."""
        return sorted(set(self.pooled_only_samples + self.pooled_and_independent_samples))

    @property
    def sdrf_value(self):
        """Generate SDRF-compliant value for this pool using source names."""
        all_samples = self.all_pooled_samples
        if not all_samples:
            return "not pooled"

        # Get source names from metadata
        source_names = self._get_source_names_for_samples()
        sample_names = []

        for i in all_samples:
            source_name = source_names.get(i, f"sample {i}")
            sample_names.append(source_name)

        return f"SN={','.join(sample_names)}"

    @property
    def total_samples_count(self):
        """Get total number of samples in this pool."""
        return len(self.all_pooled_samples)

    def get_sample_status(self, sample_index):
        """Get the status of a specific sample in this pool."""
        if sample_index in self.pooled_only_samples:
            return "pooled_only"
        elif sample_index in self.pooled_and_independent_samples:
            return "pooled_and_independent"
        else:
            return "not_in_pool"

    def add_sample(self, sample_index, status="pooled_only"):
        """Add a sample to the pool with specified status."""
        self.remove_sample(sample_index)  # Remove from any existing list first

        if status == "pooled_only":
            self.pooled_only_samples.append(sample_index)
            self.pooled_only_samples.sort()
        elif status == "pooled_and_independent":
            self.pooled_and_independent_samples.append(sample_index)
            self.pooled_and_independent_samples.sort()

    def remove_sample(self, sample_index):
        """Remove a sample from the pool."""
        if sample_index in self.pooled_only_samples:
            self.pooled_only_samples.remove(sample_index)
        if sample_index in self.pooled_and_independent_samples:
            self.pooled_and_independent_samples.remove(sample_index)

    def _get_source_names_for_samples(self):
        """Get source names for all samples from metadata."""
        import json

        # Get the Source name metadata column from unified metadata system
        source_name_column = None
        for metadata_column in self.metadata_table.columns.all():
            if metadata_column.name == "Source name":
                source_name_column = metadata_column
                break

        if not source_name_column:
            # No source name metadata found, return empty dict to use fallback
            return {}

        source_names = {}

        # Set default value for all samples
        if source_name_column.value:
            for i in range(1, self.metadata_table.sample_count + 1):
                source_names[i] = source_name_column.value

        # Override with modifier values if they exist
        if source_name_column.modifiers:
            try:
                modifiers = source_name_column.modifiers
                for modifier in modifiers:
                    samples_str = modifier.get("samples", "")
                    value = modifier.get("value", "")

                    # Parse sample indices from the modifier string
                    sample_indices = self._parse_sample_indices_from_modifier_string(samples_str)
                    for sample_index in sample_indices:
                        if 1 <= sample_index <= self.metadata_table.sample_count:
                            source_names[sample_index] = value
            except (json.JSONDecodeError, ValueError):
                pass

        return source_names

    def _parse_sample_indices_from_modifier_string(self, samples_str):
        """Parse sample indices from modifier string like '1,2,3' or '1-3,5'."""
        indices = []
        if not samples_str:
            return indices

        parts = samples_str.split(",")
        for part in parts:
            part = part.strip()
            if "-" in part:
                # Handle range like "1-3"
                try:
                    start, end = part.split("-", 1)
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())
                    indices.extend(range(start_idx, end_idx + 1))
                except ValueError:
                    pass
            else:
                # Handle single number
                try:
                    indices.append(int(part))
                except ValueError:
                    pass

        return indices

    def reorder_pool_columns_by_schema(
        self, schema_names: list[str] = None, schema_ids: list[int] = None, schema_dir: str = None
    ):
        """
        Reorder columns in this sample pool based on SDRF schema definitions.
        This follows the same logic as MetadataTable.reorder_columns_by_schema() but for pool columns.

        Args:
            schema_names: List of schema names to use for ordering
            schema_ids: List of schema IDs to use for ordering (preferred)
            schema_dir: Directory containing schema files (optional)

        Returns:
            bool: True if reordering was successful, False otherwise
        """
        from .utils import compile_sdrf_columns_from_schemas

        if not schema_names and not schema_ids:
            raise ValueError("Must specify at least one schema or schema_ids")

        # Get current pool columns
        current_columns = list(self.metadata_columns.all())

        if not current_columns:
            return True  # Nothing to reorder

        # Get schema-based column ordering
        sections = compile_sdrf_columns_from_schemas(schema_names, schema_ids, schema_dir)
        section_order = ["source_name", "characteristics", "special", "comment", "factor_value"]

        # Create mapping of column names to column objects
        column_map = {}
        for column in current_columns:
            column_name_lower = column.name.lower().replace("_", " ")
            column_map[column_name_lower] = column

        # Build new column order based on schema
        new_column_order = []
        used_columns = set()

        # Process each section in the defined order
        for section_name in section_order:
            if section_name in sections:
                section_columns = sections[section_name]
                for expected_column in section_columns:
                    expected_name = expected_column.lower().replace("_", " ")
                    if expected_name in column_map:
                        new_column_order.append(column_map[expected_name])
                        used_columns.add(expected_name)

        # Add any remaining columns that weren't in the schema
        for column_name, column in column_map.items():
            if column_name not in used_columns:
                new_column_order.append(column)

        # Update pool's metadata columns with new order
        self.metadata_columns.clear()
        self.metadata_columns.set(new_column_order)

        return True

    def basic_pool_column_reordering(self):
        """
        Basic column reordering by section when no schemas are available.
        Organizes pool columns by type: source_name, characteristics, comment, factor_value.
        """
        current_columns = list(self.metadata_columns.all())

        if not current_columns:
            return True

        sections = {
            "source_name": [],
            "characteristics": [],
            "special": [],
            "comment": [],
            "factor_value": [],
        }

        # Categorize columns by type
        for column in current_columns:
            column_type = column.type.lower() if column.type else "special"
            if column_type in sections:
                sections[column_type].append(column)
            else:
                sections["special"].append(column)

        # Build new order
        new_order = []
        for section_name in ["source_name", "characteristics", "special", "comment", "factor_value"]:
            new_order.extend(sections[section_name])

        # Update pool's metadata columns with new order
        self.metadata_columns.clear()
        self.metadata_columns.set(new_order)

        return True

    # Legacy methods for backward compatibility
    def get_total_samples(self):
        """Legacy method - use total_samples_count property instead."""
        return self.total_samples_count

    def get_all_sample_indices(self):
        """Legacy method - use all_pooled_samples property instead."""
        return self.all_pooled_samples


def schema_file_upload_path(instance, filename):
    """Generate upload path for schema files."""
    # Sanitize filename
    import os

    name = instance.name or "schema"
    ext = os.path.splitext(filename)[1]
    return f"schemas/{name}{ext}"


class Schema(models.Model):
    """
    Model for storing schema definitions used to create metadata table templates.
    Stores schema YAML files - both builtin (from sdrf-pipelines) and user-uploaded.
    """

    name = models.CharField(max_length=100, unique=True, help_text="Unique name for the schema")
    display_name = models.CharField(max_length=200, help_text="Human-readable display name")
    description = models.TextField(blank=True, help_text="Description of what this schema provides")

    # Schema file storage
    schema_file = models.FileField(upload_to=schema_file_upload_path, help_text="YAML schema file")

    # Schema source
    is_builtin = models.BooleanField(
        default=False, help_text="Whether this schema comes from sdrf-pipelines builtin resources"
    )

    # Schema metadata
    tags = models.JSONField(
        default=list, blank=True, help_text="Tags for categorizing schemas (e.g., 'proteomics', 'metabolomics')"
    )

    # File metadata
    file_size = models.PositiveIntegerField(default=0, help_text="Size of schema file in bytes")
    file_hash = models.CharField(
        max_length=64, blank=True, help_text="SHA256 hash of schema file for integrity checking"
    )

    # Usage tracking
    usage_count = models.PositiveIntegerField(default=0, help_text="Number of times this schema has been used")

    # Creator and permissions
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        help_text="User who uploaded this schema (null for builtin schemas)",
    )
    is_active = models.BooleanField(default=True, help_text="Whether this schema is active and available for use")
    is_public = models.BooleanField(default=False, help_text="Whether this schema is publicly available")

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["-is_builtin", "name"]  # Builtin schemas first, then alphabetical
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_builtin", "is_active"]),
            models.Index(fields=["creator", "is_public"]),
        ]

    def __str__(self):
        prefix = "[BUILTIN] " if self.is_builtin else "[CUSTOM] "
        return f"{prefix}{self.display_name}"

    def clean(self):
        """Custom validation for schemas."""
        super().clean()
        if self.name:
            self.name = self.name.strip().lower()
        if self.display_name:
            self.display_name = self.display_name.strip()

    def save(self, *args, **kwargs):
        """Override save to calculate file hash and size."""
        if self.schema_file:
            import hashlib

            # Calculate file size
            self.file_size = self.schema_file.size

            # Calculate SHA256 hash
            hash_sha256 = hashlib.sha256()
            for chunk in self.schema_file.chunks():
                hash_sha256.update(chunk)
            self.file_hash = hash_sha256.hexdigest()

            # Reset file position
            self.schema_file.seek(0)

        super().save(*args, **kwargs)

    def get_columns_from_schema(self):
        """
        Get column definitions for this schema by parsing the uploaded YAML file.
        """
        try:
            from .utils import compile_sdrf_columns_from_schemas

            if not self.schema_file:
                return {}

            # For builtin schemas, we can use the existing sdrf-pipelines functionality
            if self.is_builtin:
                return compile_sdrf_columns_from_schemas([self.name])
            else:
                # For custom schemas, we need to parse the uploaded YAML file
                # This would require implementing custom parsing logic
                # For now, return empty dict and implement later
                return {}

        except Exception as e:
            print(f"Error loading schema {self.name}: {e}")
            return {}

    def get_schema_content(self):
        """Get the raw content of the schema YAML file."""
        try:
            if self.schema_file:
                return self.schema_file.read().decode("utf-8")
        except Exception as e:
            print(f"Error reading schema file {self.name}: {e}")
        return ""

    def increment_usage(self):
        """Increment the usage count for this schema."""
        self.usage_count = models.F("usage_count") + 1
        self.save(update_fields=["usage_count"])

    @classmethod
    def sync_builtin_schemas(cls):
        """
        Synchronize builtin schemas from sdrf-pipelines package.
        Extracts and uploads the actual YAML schema files from the package.
        """
        try:
            import pickle
            import pickletools

            from django.core.files.base import ContentFile

            from sdrf_pipelines.sdrf.schemas import SchemaRegistry

            from .utils import get_all_default_schema_names

            builtin_schemas = get_all_default_schema_names()
            registry = SchemaRegistry()
            created_count = 0
            updated_count = 0

            for schema_name in builtin_schemas:
                schema_obj = registry.get_schema(schema_name)
                if not schema_obj:
                    print(f"Warning: Could not get schema object for '{schema_name}'")
                    continue

                # Convert schema object to YAML content
                schema_dict = {"name": schema_name, "version": "1.0", "columns": []}

                # Extract column definitions
                for column in schema_obj.columns:
                    column_dict = {
                        "name": column.name,
                    }

                    # Add available attributes
                    if hasattr(column, "type") and column.type:
                        column_dict["type"] = column.type
                    if hasattr(column, "required"):
                        column_dict["required"] = column.required
                    if hasattr(column, "ontology_type") and column.ontology_type:
                        column_dict["ontology_type"] = column.ontology_type
                    if hasattr(column, "description") and column.description:
                        column_dict["description"] = column.description

                    schema_dict["columns"].append(column_dict)

                schema_obj_pickle = pickletools.optimize(pickle.dumps(schema_obj))

                display_name = schema_name.replace("_", " ").title()
                description_map = {
                    "minimum": "Basic required columns only - ideal for simple experiments",
                    "default": "Standard proteomics columns - good starting point for most experiments",
                    "proteomics": "Comprehensive proteomics schema with advanced metadata",
                    "metabolomics": "Metabolomics-specific columns and annotations",
                    "human": "Human sample-specific columns and ontologies",
                    "vertebrates": "Vertebrate organism columns and taxonomies",
                    "nonvertebrates": "Non-vertebrate organism columns and taxonomies",
                    "plants": "Plant-specific columns and ontologies",
                    "cell_lines": "Cell line experiment columns and metadata",
                }
                description = description_map.get(schema_name, f"Builtin schema: {display_name}")

                # Determine tags
                tags = []
                if "proteomics" in schema_name or schema_name in ["default", "minimum"]:
                    tags.append("proteomics")
                if "metabolomics" in schema_name:
                    tags.append("metabolomics")
                if schema_name in ["human", "vertebrates", "nonvertebrates", "plants"]:
                    tags.append("organism-specific")

                # Determine if this schema should be active by default
                # Only 'minimum' schema is active by default for new installations
                is_active_default = schema_name == "minimum"

                # Create or update schema
                schema, created = cls.objects.get_or_create(
                    name=schema_name,
                    defaults={
                        "display_name": display_name,
                        "description": description,
                        "is_builtin": True,
                        "is_active": is_active_default,
                        "is_public": True,
                        "tags": tags,
                    },
                )

                # Save YAML file content
                file_name = f"{schema_name}.pkl"
                schema.schema_file.save(file_name, ContentFile(schema_obj_pickle), save=False)
                schema.save()

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            return {"created": created_count, "updated": updated_count}

        except Exception as e:
            print(f"Error syncing builtin schemas: {e}")
            return {"created": 0, "updated": 0, "error": str(e)}

    @classmethod
    def get_available_schemas(cls, user=None):
        """
        Get schemas available to a user.
        Includes builtin schemas, user's own schemas, and public custom schemas.
        """
        queryset = cls.objects.filter(is_active=True)

        if user and user.is_authenticated:
            # Include builtin schemas, user's own schemas, and public schemas
            queryset = queryset.filter(models.Q(is_builtin=True) | models.Q(creator=user) | models.Q(is_public=True))
        else:
            # Only builtin schemas and public schemas for anonymous users
            queryset = queryset.filter(models.Q(is_builtin=True) | models.Q(is_public=True))

        return queryset.order_by("-is_builtin", "name")


class BaseMetadataTableTemplate(AbstractResource):
    """
    Abstract base model for metadata table templates.

    This model provides the core functionality for metadata table templates and can be
    extended by other applications to create custom template implementations.

    Key extension points:
    - Override get_custom_column_types() to add app-specific column types
    - Override get_template_validators() to add validation rules
    - Override customize_field_mapping() to modify field display customization
    - Override get_template_context() to provide additional template data
    """

    name = models.TextField(help_text="Name of the template")
    description = models.TextField(blank=True, null=True, help_text="Description of the template")

    # Schema relationships
    schemas = models.ManyToManyField(
        Schema,
        related_name="%(app_label)s_%(class)s_templates",
        blank=True,
        help_text="Schemas used to create this template",
    )

    # Template configuration
    user_columns = models.ManyToManyField(
        MetadataColumn,
        related_name="%(app_label)s_%(class)s_templates",
        blank=True,
        help_text="User-editable metadata columns",
    )

    # Field masking for display customization
    field_mask_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text="Mapping for customizing field display names",
    )

    # Template metadata
    is_default = models.BooleanField(default=False, help_text="Whether this is a default template")

    class Meta(AbstractResource.Meta):
        abstract = True
        ordering = ["-is_default", "name"]

    def get_custom_column_types(self):
        """
        Override this method in subclasses to provide custom column types.

        Returns:
            dict: Dictionary of custom column type configurations

        Example:
            return {
                'protein_identifier': {
                    'name': 'Protein Identifier',
                    'validation_pattern': r'^[A-Z0-9_]+$',
                    'description': 'UniProt protein identifier',
                    'ontology_source': 'uniprot'
                }
            }
        """
        return {}

    def get_template_validators(self):
        """
        Override this method in subclasses to provide custom template validation rules.

        Returns:
            list: List of validator functions for template validation
        """
        return []

    def customize_field_mapping(self, base_mapping):
        """
        Override this method in subclasses to customize field display mapping.

        Args:
            base_mapping: Base field mapping dictionary

        Returns:
            dict: Customized field mapping
        """
        return base_mapping

    def get_template_context(self):
        """
        Override this method in subclasses to provide additional template context.

        Returns:
            dict: Additional context data for template processing
        """
        return {}

    def validate_template_configuration(self):
        """
        Override this method in subclasses to perform custom template validation.

        Raises:
            ValidationError: If template configuration is invalid
        """
        for validator in self.get_template_validators():
            validator(self)

    def get_extended_field_mapping(self):
        """
        Get field mapping with custom extensions applied.

        Returns:
            dict: Extended field mapping dictionary
        """
        base_mapping = dict(self.field_mask_mapping)
        return self.customize_field_mapping(base_mapping)


class MetadataTableTemplate(BaseMetadataTableTemplate):
    """
    Concrete implementation of metadata table template.

    This is the default implementation provided by CUPCAKE Vanilla.
    Applications can either use this directly or create their own
    implementations by extending BaseMetadataTableTemplate.
    """

    class Meta(BaseMetadataTableTemplate.Meta):
        app_label = "ccv"
        ordering = ["-is_default", "name"]
        abstract = False

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.resource_type:
            self.resource_type = ResourceType.METADATA_TABLE_TEMPLATE
        super().save(*args, **kwargs)

    def get_all_columns(self):
        """Get all columns in this template."""
        return list(self.user_columns.all())

    def reorder_columns_by_schema(
        self, schema_names: list[str] = None, schema_ids: list[int] = None, schema_dir: str = None
    ):
        """
        Reorder columns in this metadata table template based on SDRF schema definitions.

        Args:
            schema_names: List of schema names to use for column ordering
            schema_ids: List of schema IDs to use for column ordering
            schema_dir: Optional directory containing custom schemas

        Returns:
            bool: True if reordering was successful, False otherwise
        """
        from .utils import compile_sdrf_columns_from_schemas

        if not schema_names and not schema_ids:
            raise ValueError("Must specify at least one schema or schema_ids")
        if schema_names and schema_ids:
            raise ValueError("Cannot specify both schema_names and schema_ids")

        # Get all columns in this template
        current_columns = list(self.user_columns.all().order_by("column_position"))

        if not current_columns:
            return True  # Nothing to reorder

        # Get schema-based column ordering
        sections = compile_sdrf_columns_from_schemas(schema_names, schema_ids, schema_dir)
        section_order = ["source_name", "characteristics", "special", "comment", "factor_value"]
        # Create mapping of column names to column objects
        column_map = {}
        for s in section_order:
            column_map[s] = {}
        for col in current_columns:
            col_name = col.name.lower()
            if col_name not in column_map:
                if col_name == "source name":
                    column_map["source_name"] = {col_name: [col]}
                elif col_name.startswith("characteristics"):
                    if col_name not in column_map["characteristics"]:
                        column_map["characteristics"][col_name] = []
                    column_map["characteristics"][col_name].append(col)
                elif col_name.startswith("comment"):
                    if col_name not in column_map["comment"]:
                        column_map["comment"][col_name] = []
                    column_map["comment"][col_name].append(col)
                elif col_name.startswith("factor value"):
                    if col_name not in column_map["factor_value"]:
                        column_map["factor_value"][col_name] = []
                    column_map["factor_value"][col_name].append(col)
                else:
                    if col_name not in column_map["special"]:
                        column_map["special"][col_name] = []
                    column_map["special"][col_name].append(col)

        processed_columns = set()
        current_position = 0

        # Process columns by schema sections in defined order
        for section in section_order:
            schema_columns = sections.get(section, [])
            # First, process schema columns
            for schema_col_name in schema_columns:
                schema_col_lower = schema_col_name.lower()
                if schema_col_lower in column_map[section] and schema_col_lower not in processed_columns:
                    columns = column_map[section][schema_col_lower]
                    for column in columns:
                        column.column_position = current_position
                        column.save(update_fields=["column_position"])
                        current_position += 1
                    processed_columns.add(schema_col_lower)
            # Then, process remaining columns in this section not in schema
            for col_name, columns in column_map[section].items():
                if col_name not in processed_columns:
                    for column in columns:
                        column.column_position = current_position
                        column.save(update_fields=["column_position"])
                        current_position += 1

        return True

    def add_column_with_auto_reorder(self, column_data: dict, position: int = None, auto_reorder: bool = True):
        """Add a new column to this metadata table template and automatically reorder columns."""
        column = self.add_column_to_template(column_data, position=position)
        result = {"column": column, "reordered": False, "schema_ids_used": [], "message": "Column added successfully"}

        if auto_reorder:
            schema_ids = set()
            for col in self.user_columns.all():
                if col.template and col.template.schema:
                    schema_ids.add(col.template.schema.id)

            if schema_ids:
                schema_ids_list = list(schema_ids)
                try:
                    reorder_success = self.reorder_columns_by_schema(schema_ids=schema_ids_list)
                    if reorder_success:
                        result["reordered"] = True
                        result["schema_ids_used"] = schema_ids_list
                        result["message"] = f"Column added and reordered using {len(schema_ids_list)} schema(s)"
                except Exception as e:
                    print(f"Warning: Failed to reorder template columns by schema: {e}")

        return result

    def create_table_from_template(
        self, table_name: str, creator=None, sample_count: int = 1, description: str = None, lab_group=None, **kwargs
    ) -> "MetadataTable":
        """
        Create a new MetadataTable based on this template.

        Args:
            table_name: Name for the new metadata table
            creator: User who will be the creator of the table
            sample_count: Number of samples for the table
            description: Description for the new table
            lab_group: Lab group for the table
            **kwargs: Additional arguments to pass to MetadataTable creation

        Returns:
            MetadataTable: The newly created table with columns from this template
        """
        # Create the metadata table
        table_data = {
            "name": table_name,
            "description": description or f"Table created from template: {self.name}",
            "sample_count": sample_count,
            "owner": creator,
            "lab_group": lab_group,
            **kwargs,
        }

        # Remove None values
        table_data = {k: v for k, v in table_data.items() if v is not None}

        # Create the table
        metadata_table = MetadataTable.objects.create(**table_data)

        try:
            # Copy columns from template to table
            template_columns = self.user_columns.all().order_by("column_position")

            for template_column in template_columns:
                try:
                    # Create column for the table based on template column
                    MetadataColumn.objects.create(
                        metadata_table=metadata_table,
                        name=template_column.name,
                        type=template_column.type,
                        column_position=template_column.column_position,
                        value=template_column.value or "",
                        template=template_column.template,  # Link to original column template if exists
                        ontology_type=template_column.ontology_type,
                        ontology_options=template_column.ontology_options,
                        custom_ontology_filters=template_column.custom_ontology_filters,
                        mandatory=template_column.mandatory,
                        hidden=template_column.hidden,
                        readonly=template_column.readonly,
                        auto_generated=template_column.auto_generated,
                        modifiers=template_column.modifiers or [],
                    )

                except Exception:
                    # Log error and continue
                    continue

            # If this template is based on schemas, reorder the columns accordingly
            if self.schemas.exists():
                schema_ids = list(self.schemas.values_list("id", flat=True))
                metadata_table.reorder_columns_by_schema(schema_ids=schema_ids)

            return metadata_table

        except Exception as e:
            # Clean up table if column creation fails
            metadata_table.delete()
            raise Exception(f"Failed to create table from template: {str(e)}")

    def create_table_from_schemas(
        self,
        table_name: str,
        schema_ids: list[int] = None,
        schemas: list[str] = None,
        description: str = None,
        creator=None,
        sample_count: int = 1,
        **kwargs,
    ) -> "MetadataTable":
        """
        Create a new MetadataTable based on schema definitions, using associated column templates.

        Args:
            table_name: Name for the new metadata table
            schema_ids: List of schema IDs to use (preferred)
            schemas: List of schema names to use (legacy support)
            description: Description for the new table
            creator: User who will be the creator of the table
            sample_count: Number of samples for the table
            **kwargs: Additional arguments to pass to MetadataTable creation

        Returns:
            MetadataTable: The newly created table with columns
        """
        schema_objects = []

        if schema_ids:
            for schema_id in schema_ids:
                try:
                    schema_obj = Schema.objects.get(id=schema_id, is_active=True)
                    schema_objects.append(schema_obj)
                except Schema.DoesNotExist:
                    print(f"Warning: Schema with ID {schema_id} not found or not active")
        elif schemas:
            for schema_name in schemas:
                try:
                    schema_obj = Schema.objects.get(name=schema_name, is_active=True)
                    schema_objects.append(schema_obj)
                except Schema.DoesNotExist:
                    print(f"Warning: Schema '{schema_name}' not found or not active")
        else:
            try:
                minimum_schema = Schema.objects.get(name="minimum", is_active=True)
                schema_objects = [minimum_schema]
            except Schema.DoesNotExist:
                raise ValueError("No schemas provided and minimum schema not found")

        schema_names = [s.display_name or s.name for s in schema_objects]
        table_data = {
            "name": table_name,
            "description": description or f'Table created from schemas: {", ".join(schema_names)}',
            "sample_count": sample_count,
            "creator": creator,
            **kwargs,
        }

        # Remove None values
        table_data = {k: v for k, v in table_data.items() if v is not None}

        # Create the table
        metadata_table = MetadataTable.objects.create(**table_data)

        try:
            # Get column templates linked to the schemas
            column_templates = []
            seen_template_ids = set()

            for schema_obj in schema_objects:
                # Get all column templates linked to this schema
                schema_templates = schema_obj.column_templates.filter(is_active=True).order_by("default_position", "id")

                for col_template in schema_templates:
                    if col_template.id not in seen_template_ids:
                        column_templates.append(col_template)
                        seen_template_ids.add(col_template.id)

            # Create columns from linked templates
            position = 0
            for column_template in column_templates:
                try:
                    # Create column from template
                    MetadataColumn.objects.create(
                        metadata_table=metadata_table,
                        name=column_template.column_name,
                        type=column_template.column_type,
                        column_position=position,
                        value=column_template.default_value or "",
                        template=column_template,
                        ontology_type=column_template.ontology_type,
                        ontology_options=column_template.ontology_options,
                        custom_ontology_filters=column_template.custom_ontology_filters,
                        mandatory=False,
                        hidden=False,
                        readonly=False,
                        auto_generated=False,
                    )
                    position += 1

                    # Update template usage
                    column_template.usage_count += 1
                    column_template.last_used_at = timezone.now()
                    column_template.save(update_fields=["usage_count", "last_used_at"])

                except Exception as e:
                    # Log error and continue
                    print(f"Error creating column from template {column_template.column_name}: {e}")
                    continue

            # Apply schema-based reordering to ensure correct order
            if schema_ids:
                metadata_table.reorder_columns_by_schema(schema_ids=schema_ids)
            else:
                metadata_table.reorder_columns_by_schema(schema_names=[s.name for s in schema_objects])

            return metadata_table

        except Exception as e:
            # Clean up table if column creation fails
            metadata_table.delete()
            raise Exception(f"Failed to create table from schemas: {str(e)}")

    def _find_template_for_column(self, column_name: str, schemas: list[str]) -> "MetadataColumnTemplate":
        """
        Find the best matching MetadataColumnTemplate for a schema column.

        Args:
            column_name: Name of the column from schema
            schemas: List of schemas being processed

        Returns:
            MetadataColumnTemplate or None if no match found
        """
        # Parse column name to get the actual field name
        display_name = column_name
        if "[" in column_name and "]" in column_name:
            display_name = column_name.split("[")[1].split("]")[0]

        # Try to find template by exact column name match first
        template = MetadataColumnTemplate.objects.filter(
            column_name=column_name, source_schema__in=schemas, is_active=True
        ).first()

        if template:
            return template

        # Try to find by display name match
        template = MetadataColumnTemplate.objects.filter(
            name=display_name, source_schema__in=schemas, is_active=True
        ).first()

        if template:
            return template

        # Try to find by column name without schema restriction
        template = MetadataColumnTemplate.objects.filter(
            column_name=column_name, is_active=True, is_system_template=True
        ).first()

        if template:
            return template

        # Finally, try by display name without schema restriction
        template = MetadataColumnTemplate.objects.filter(
            name=display_name, is_active=True, is_system_template=True
        ).first()

        return template

    def _create_column_from_template(
        self, template: "MetadataColumnTemplate", metadata_table: "MetadataTable", column_name: str, position: int
    ) -> "MetadataColumn":
        """
        Create a MetadataColumn based on a template.

        Args:
            template: The template to base the column on
            metadata_table: The table to add the column to
            column_name: The actual column name from schema
            position: Position in the table

        Returns:
            MetadataColumn: The created column
        """
        column = MetadataColumn.objects.create(
            metadata_table=metadata_table,
            name=column_name,
            type=template.column_type,
            column_position=position,
            value=template.default_value,
            template=template,
            # Copy template configurations
            ontology_type=template.ontology_type,
            ontology_options=template.ontology_options,
            custom_ontology_filters=template.custom_ontology_filters,
            # Default behaviors (can be overridden later)
            mandatory=False,
            hidden=False,
            readonly=False,
            auto_generated=False,
        )

        return column

    def _create_basic_column(
        self, column_name: str, metadata_table: "MetadataTable", position: int
    ) -> "MetadataColumn":
        """
        Create a basic MetadataColumn when no template is available.

        Args:
            column_name: Name of the column
            metadata_table: The table to add the column to
            position: Position in the table

        Returns:
            MetadataColumn: The created column
        """
        # Determine column type from name
        if column_name.startswith("characteristics["):
            column_type = "characteristics"
        elif column_name.startswith("comment["):
            column_type = "comment"
        elif column_name.startswith("factor value["):
            column_type = "factor_value"
        elif column_name == "source name":
            column_type = "source_name"
        else:
            column_type = "special"

        column = MetadataColumn.objects.create(
            metadata_table=metadata_table,
            name=column_name,
            type=column_type,
            column_position=position,
            mandatory=False,
            hidden=False,
            readonly=False,
            auto_generated=False,
        )

        return column

    def add_column_to_template(self, column_data: dict, position: int = None):
        """
        Add a new column to this metadata table template at the specified position.

        Args:
            column_data: Dictionary containing column data
            position: Position to insert the column (None for end)

        Returns:
            MetadataColumn: The created column
        """

        current_columns = list(self.user_columns.all().order_by("column_position"))
        if position is not None:
            for i, col in enumerate(current_columns):
                if col.column_position >= position:
                    col.column_position = col.column_position + 1
                    col.save(update_fields=["column_position"])
        else:
            # If no position specified, add at the end
            position = len(current_columns)
        column_data["column_position"] = position
        column = MetadataColumn.objects.create(**column_data)
        self.user_columns.add(column)
        return column

    def remove_column_from_template(self, column_id: int):
        """
        Remove a column from the template and adjust positions of remaining columns.

        Args:
            column_id: ID of the column to remove

        Returns:
            bool: True if column was removed, False if not found
        """
        try:
            column = self.user_columns.get(id=column_id)
            removed_position = column.column_position

            # Remove from template
            self.user_columns.remove(column)

            # Shift remaining columns down
            remaining_columns = self.user_columns.filter(column_position__gt=removed_position)
            for col in remaining_columns:
                col.column_position = col.column_position - 1
                col.save(update_fields=["column_position"])

            # Delete the column if it's not used elsewhere
            if not column.user_templates.exists() and not column.metadata_table:
                column.delete()

            return True
        except MetadataColumn.DoesNotExist:
            return False

    def reorder_template_column(self, column_id: int, new_position: int):
        """
        Move a column to a new position within the template, adjusting other columns as needed.

        Args:
            column_id: ID of the column to move
            new_position: New position for the column

        Returns:
            bool: True if reordering was successful, False if column not found
        """
        try:
            column = self.user_columns.get(id=column_id)
            old_position = column.column_position

            if old_position == new_position:
                return True  # No change needed

            # Get all template columns
            template_columns = list(self.user_columns.all())
            max_position = len(template_columns) - 1
            new_position = max(0, min(new_position, max_position))

            if old_position < new_position:
                # Moving down: shift columns between old and new position up
                for col in template_columns:
                    if old_position < col.column_position <= new_position:
                        col.column_position = col.column_position - 1
                        col.save(update_fields=["column_position"])
            else:
                # Moving up: shift columns between new and old position down
                for col in template_columns:
                    if new_position <= col.column_position < old_position:
                        col.column_position = col.column_position + 1
                        col.save(update_fields=["column_position"])

            # Update the moved column's position
            column.column_position = new_position
            column.save(update_fields=["column_position"])

            return True
        except MetadataColumn.DoesNotExist:
            return False

    def normalize_template_column_positions(self):
        """
        Ensure template column positions are sequential starting from 0 with no gaps.
        """
        columns = list(self.user_columns.all().order_by("column_position", "id"))
        for index, column in enumerate(columns):
            if column.column_position != index:
                column.column_position = index
                column.save(update_fields=["column_position"])

    def duplicate_column_in_template(self, column_id: int, new_name: str = None):
        """
        Duplicate a column within the template.

        Args:
            column_id: ID of the column to duplicate
            new_name: Name for the duplicated column (auto-generated if None)

        Returns:
            MetadataColumn: The duplicated column, or None if original not found
        """
        try:
            original_column = self.user_columns.get(id=column_id)

            # Create data for the new column
            column_data = {
                "name": new_name or f"{original_column.name} (Copy)",
                "type": original_column.type,
                "value": original_column.value,
                "ontology_type": original_column.ontology_type,
                "ontology_options": original_column.ontology_options,
                "custom_ontology_filters": original_column.custom_ontology_filters,
                "mandatory": original_column.mandatory,
                "hidden": original_column.hidden,
                "readonly": original_column.readonly,
                "auto_generated": False,
                "modifiers": original_column.modifiers,
            }

            # Add the duplicated column right after the original
            new_position = original_column.column_position + 1
            return self.add_column_to_template(column_data, new_position)

        except MetadataColumn.DoesNotExist:
            return None

    @classmethod
    def create_from_schemas(
        cls,
        name: str,
        schema_ids: list[int] = None,
        schemas: list[str] = None,
        creator=None,
        lab_group=None,
        description: str = None,
        **kwargs,
    ):
        """
        Create a new MetadataTableTemplate based on schema definitions.

        Args:
            name: Name for the new template
            schema_ids: List of schema IDs to use (preferred)
            schemas: List of schema names to use (legacy support)
            creator: User who will be the creator of the template
            lab_group: Lab group for the template
            description: Description for the template
            **kwargs: Additional arguments for template creation

        Returns:
            MetadataTableTemplate: The newly created template with columns
        """
        # Handle schema IDs or names
        schema_objects = []

        if schema_ids:
            # Use schema IDs (preferred)
            for schema_id in schema_ids:
                try:
                    schema_obj = Schema.objects.get(id=schema_id, is_active=True)
                    schema_objects.append(schema_obj)
                except Schema.DoesNotExist:
                    print(f"Warning: Schema with ID {schema_id} not found or not active")
        elif schemas:
            # Legacy support: Use schema names
            for schema_name in schemas:
                try:
                    schema_obj = Schema.objects.get(name=schema_name, is_active=True)
                    schema_objects.append(schema_obj)
                except Schema.DoesNotExist:
                    print(f"Warning: Schema '{schema_name}' not found or not active")
        else:
            # Default to minimum schema
            try:
                minimum_schema = Schema.objects.get(name="minimum", is_active=True)
                schema_objects = [minimum_schema]
            except Schema.DoesNotExist:
                raise ValueError("No schemas provided and minimum schema not found")

        # Create the template
        schema_names = [s.display_name or s.name for s in schema_objects]
        # Convert is_public to visibility if provided
        visibility = kwargs.get("visibility", "private")
        if "is_public" in kwargs:
            visibility = "public" if kwargs.get("is_public", False) else "private"

        template_data = {
            "name": name,
            "description": description or f'Template created from schemas: {", ".join(schema_names)}',
            "owner": creator,
            "lab_group": lab_group,
            "visibility": visibility,
            "is_default": kwargs.get("is_default", False),
            **{k: v for k, v in kwargs.items() if k not in ["is_public", "is_default", "visibility"]},
        }

        # Remove None values
        template_data = {k: v for k, v in template_data.items() if v is not None}

        # Create the template
        template = cls.objects.create(**template_data)

        try:
            if schema_objects:
                template.schemas.set(schema_objects)
                for schema_obj in schema_objects:
                    schema_obj.usage_count += 1
                    schema_obj.save(update_fields=["usage_count"])

            column_templates = []
            seen_template_ids = set()

            for schema_obj in schema_objects:
                schema_templates = schema_obj.column_templates.filter(is_active=True).order_by("default_position", "id")

                for col_template in schema_templates:
                    if col_template.id not in seen_template_ids:
                        column_templates.append(col_template)
                        seen_template_ids.add(col_template.id)

            # Create columns from linked templates
            position = 0
            for column_template in column_templates:
                try:
                    # Use column template data to create the column
                    column_data = {
                        "name": column_template.column_name,
                        "type": column_template.column_type,
                        "value": column_template.default_value or "",
                        "ontology_type": column_template.ontology_type,
                        "ontology_options": column_template.ontology_options,
                        "custom_ontology_filters": column_template.custom_ontology_filters,
                        "template": column_template,  # Fixed: should be 'template', not 'template_id'
                        "mandatory": False,
                        "hidden": False,
                        "readonly": False,
                        "auto_generated": False,
                    }

                    # Use template's default position if available
                    template_position = (
                        column_template.default_position if column_template.default_position is not None else position
                    )

                    template.add_column_to_template(column_data, template_position)
                    position += 1

                    # Update template usage
                    column_template.usage_count += 1
                    column_template.last_used_at = timezone.now()
                    column_template.save(update_fields=["usage_count", "last_used_at"])

                except Exception as e:
                    # Log error and continue
                    print(f"Error creating column from template {column_template.name}: {e}")
                    continue

            template.reorder_columns_by_schema(schema_ids=schema_ids)
            print(template.user_columns.all())
            return template

        except Exception as e:
            # Clean up on error
            template.delete()
            raise Exception(f"Failed to create template from schemas: {str(e)}")

    def can_view(self, user):
        """Check if user can view this template."""
        # Public templates are viewable by everyone
        if self.visibility == "public":
            return True

        # Creator can always view their own templates
        if self.owner == user:
            return True

        # Staff users can view all templates
        if user.is_staff or user.is_superuser:
            return True

        # Lab group members can view lab group templates
        if self.lab_group and user in self.lab_group.members.all():
            return True

        # Default: deny access
        return False


class FavouriteMetadataOption(models.Model):
    """
    User-defined favorite values for metadata columns to speed up data entry.
    Supports personal, group-level, and global recommendations.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="favourite_metadata_options",
        blank=True,
        null=True,
        help_text="User who created this favorite",
    )

    # Metadata identification
    name = models.CharField(max_length=255, help_text="Metadata column name")
    type = models.CharField(max_length=255, help_text="Metadata column type")
    column_template = models.ForeignKey(
        "MetadataColumnTemplate",
        on_delete=models.CASCADE,
        related_name="favourite_options",
        blank=True,
        null=True,
        help_text="Column template this favorite was created from",
    )

    # Option configuration
    value = models.TextField(blank=True, null=True, help_text="The favorite value")
    display_value = models.TextField(blank=True, null=True, help_text="Display-friendly version of the value")

    # Scope configuration
    lab_group = models.ForeignKey(
        LabGroup,
        on_delete=models.CASCADE,
        related_name="favourite_metadata_options",
        blank=True,
        null=True,
        help_text="Lab group this favorite applies to",
    )
    is_global = models.BooleanField(default=False, help_text="Whether this is a global recommendation")

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "ccv"
        ordering = ["name", "type", "display_value"]
        indexes = [
            models.Index(fields=["name", "type"]),
            models.Index(fields=["user"]),
            models.Index(fields=["is_global"]),
        ]

    def __str__(self):
        return f"{self.name}: {self.display_value or self.value}"

    def clean(self):
        """Custom validation for favorite metadata options."""
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.type:
            self.type = self.type.strip()


# ===================================================================
# ONTOLOGY AND CONTROLLED VOCABULARY MODELS
# ===================================================================


class Species(models.Model):
    """UniProt species information for controlled vocabulary."""

    code = models.CharField(max_length=255, help_text="UniProt species code")
    taxon = models.IntegerField(help_text="NCBI Taxonomy ID")
    official_name = models.CharField(max_length=255, help_text="Official species name")
    common_name = models.CharField(max_length=255, blank=True, null=True, help_text="Common species name")
    synonym = models.CharField(max_length=255, blank=True, null=True, help_text="Species synonym")

    class Meta:
        app_label = "ccv"
        ordering = ["official_name"]
        verbose_name = "Species"
        verbose_name_plural = "Species"

    def __str__(self):
        return f"{self.official_name} ({self.code})"


class Tissue(models.Model):
    """UniProt tissue controlled vocabulary."""

    identifier = models.CharField(max_length=255, primary_key=True, help_text="Tissue identifier")
    accession = models.CharField(max_length=255, help_text="Tissue accession number")
    synonyms = models.TextField(blank=True, null=True, help_text="Tissue synonyms")
    cross_references = models.TextField(blank=True, null=True, help_text="Cross-references to other databases")

    class Meta:
        app_label = "ccv"
        ordering = ["identifier"]

    def __str__(self):
        return f"{self.accession} ({self.identifier})"


class HumanDisease(models.Model):
    """UniProt human disease controlled vocabulary."""

    identifier = models.CharField(max_length=255, primary_key=True, help_text="Disease identifier")
    acronym = models.CharField(max_length=255, blank=True, null=True, help_text="Disease acronym")
    accession = models.CharField(max_length=255, help_text="Disease accession number")
    definition = models.TextField(blank=True, null=True, help_text="Disease definition")
    synonyms = models.TextField(blank=True, null=True, help_text="Disease synonyms")
    cross_references = models.TextField(blank=True, null=True, help_text="Cross-references to other databases")
    keywords = models.TextField(blank=True, null=True, help_text="Associated keywords")

    class Meta:
        app_label = "ccv"
        ordering = ["identifier"]
        verbose_name = "Human Disease"
        verbose_name_plural = "Human Diseases"

    def __str__(self):
        return f"{self.accession} ({self.identifier})"


class SubcellularLocation(models.Model):
    """UniProt subcellular location controlled vocabulary."""

    location_identifier = models.TextField(blank=True, null=True, help_text="Location identifier")
    topology_identifier = models.TextField(blank=True, null=True, help_text="Topology identifier")
    orientation_identifier = models.TextField(blank=True, null=True, help_text="Orientation identifier")
    accession = models.CharField(max_length=255, primary_key=True, help_text="Subcellular location accession")
    definition = models.TextField(blank=True, null=True, help_text="Location definition")
    synonyms = models.TextField(blank=True, null=True, help_text="Location synonyms")
    content = models.TextField(blank=True, null=True, help_text="Content description")
    is_a = models.TextField(blank=True, null=True, help_text="Parent relationships")
    part_of = models.TextField(blank=True, null=True, help_text="Part-of relationships")
    keyword = models.TextField(blank=True, null=True, help_text="Associated keywords")
    gene_ontology = models.TextField(blank=True, null=True, help_text="Gene Ontology terms")
    annotation = models.TextField(blank=True, null=True, help_text="Additional annotations")
    references = models.TextField(blank=True, null=True, help_text="Literature references")
    links = models.TextField(blank=True, null=True, help_text="External links")

    class Meta:
        app_label = "ccv"
        ordering = ["accession"]
        verbose_name = "Subcellular Location"
        verbose_name_plural = "Subcellular Locations"

    def __str__(self):
        return f"{self.location_identifier} ({self.accession})"


class MSUniqueVocabularies(models.Model):
    """Mass spectrometry controlled vocabulary from HUPO-PSI."""

    accession = models.CharField(max_length=255, primary_key=True, help_text="MS term accession")
    name = models.CharField(max_length=255, help_text="Term name")
    definition = models.TextField(blank=True, null=True, help_text="Term definition")
    term_type = models.TextField(
        blank=True,
        null=True,
        help_text="Type of term (e.g., instrument, cleavage agent)",
    )

    class Meta:
        app_label = "ccv"
        ordering = ["accession"]
        verbose_name = "MS Vocabulary Term"
        verbose_name_plural = "MS Vocabulary Terms"

    def __str__(self):
        return f"{self.name} ({self.accession})"


class Unimod(models.Model):
    """Unimod protein modification controlled vocabulary."""

    accession = models.CharField(max_length=255, primary_key=True, help_text="Unimod accession")
    name = models.CharField(max_length=255, help_text="Modification name")
    definition = models.TextField(blank=True, null=True, help_text="Modification definition")
    additional_data = models.JSONField(blank=True, null=True, help_text="Additional modification data")

    class Meta:
        app_label = "ccv"
        ordering = ["accession"]
        verbose_name = "Unimod Modification"
        verbose_name_plural = "Unimod Modifications"

    def __str__(self):
        return f"{self.name} ({self.accession})"


class MetadataColumnTemplate(AbstractResource):
    """
    Template for metadata columns that can be reused and shared between users.
    Provides predefined column configurations with ontology mappings and custom enhancements.
    """

    # Template identification
    name = models.CharField(max_length=255, help_text="Template name")
    description = models.TextField(blank=True, null=True, help_text="Description of the template")

    # Column configuration (inherited by MetadataColumn when template is applied)
    column_name = models.CharField(max_length=255, help_text="Default name for the metadata column")
    column_type = models.CharField(
        max_length=255,
        default="characteristics",
        help_text="Data type (e.g., 'factor value', 'characteristics')",
    )
    default_value = models.TextField(blank=True, null=True, help_text="Default value for the column")
    default_position = models.IntegerField(
        blank=True, null=True, help_text="Default column position when used in tables"
    )
    # Note: mandatory, hidden, readonly are applied when template is used in MetadataColumn
    # These are table-specific properties, not template properties

    ontology_choices = [
        ("species", "Species"),
        ("tissue", "Tissue"),
        ("human_disease", "Human Disease"),
        ("subcellular_location", "Subcellular Location"),
        ("ms_unique_vocabularies", "MS Unique Vocabularies"),
        ("unimod", "Unimod Modifications"),
        ("ncbi_taxonomy", "NCBI Taxonomy"),
        ("mondo", "MONDO Disease"),
        ("uberon", "UBERON Anatomy"),
        ("chebi", "ChEBI"),
        ("cell_ontology", "Cell Ontology"),
        ("psi_ms", "PSI-MS Controlled Vocabulary"),
    ]

    # Ontology configuration
    ontology_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=ontology_choices,
        help_text="Type of ontology to use for validation and suggestions",
    )

    ontology_options = models.JSONField(blank=True, null=True, help_text="Ontology options")

    custom_ontology_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom filters to apply when querying the ontology",
    )

    # Template enhancements
    enable_typeahead = models.BooleanField(default=True, help_text="Enable typeahead suggestions in forms")
    excel_validation = models.BooleanField(default=True, help_text="Add dropdown validation in Excel exports")
    custom_validation_rules = models.JSONField(
        default=dict, blank=True, help_text="Custom validation rules for this template"
    )
    api_enhancements = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional API enhancements and configurations",
    )

    # Sharing and permissions

    shared_with_users = models.ManyToManyField(
        User,
        through="MetadataColumnTemplateShare",
        through_fields=("template", "user"),
        related_name="shared_column_templates",
        blank=True,
        help_text="Users this template is explicitly shared with",
    )

    # Template metadata
    is_system_template = models.BooleanField(default=False, help_text="Whether this is a system-provided template")
    usage_count = models.IntegerField(default=0, help_text="Number of times this template has been used")

    # Tags and categories
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags for categorizing and searching templates",
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Category for organizing templates",
    )
    source_schema = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Schema name this template was loaded from",
    )
    schema = models.ForeignKey(
        "Schema",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="column_templates",
        help_text="Schema model this template is associated with",
    )
    staff_only = models.BooleanField(default=False, help_text="Whether only staff can edit this column")
    # Audit trail
    last_used_at = models.DateTimeField(blank=True, null=True, help_text="When this template was last used")
    base_column = models.BooleanField(
        default=False, help_text="Whether this is a base column template for core metadata"
    )
    possible_default_values = models.JSONField(
        default=list,
        blank=True,
        help_text="List of possible default sdrf values for this column template",
    )

    class Meta(AbstractResource.Meta):
        app_label = "ccv"
        ordering = ["-usage_count", "name"]

    def __str__(self):
        return f"{self.name} ({self.column_name}[{self.column_type}])"

    def save(self, *args, **kwargs):
        if not self.resource_type:
            self.resource_type = ResourceType.METADATA_COLUMN_TEMPLATE
        super().save(*args, **kwargs)

    def clean(self):
        """Custom validation for templates."""
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.column_name:
            self.column_name = self.column_name.strip()
        if self.column_type:
            self.column_type = self.column_type.strip()

    def get_ontology_suggestions(self, search_term: str = "", limit: int = 20, search_type: str = "icontains"):
        """
        Get ontology suggestions based on the template's ontology type with enhanced search capabilities.

        Args:
            search_term: Term to search for
            limit: Maximum number of results to return
            search_type: Type of search - 'icontains', 'istartswith', or 'exact'
        """
        model_class = self.get_ontology_model()
        if not model_class:
            return []
        queryset = model_class.objects.all()

        # Use the search_type directly (already case-insensitive for istartswith and icontains)
        case_insensitive_search_type = search_type

        # Apply custom ontology filters first
        if self.custom_ontology_filters:
            for field, filter_value in self.custom_ontology_filters.items():
                if field == self.ontology_type:
                    if isinstance(filter_value, dict):
                        # Handle complex filter values like {'icontains': 'value'} or {'exact': 'value'}
                        for lookup, value in filter_value.items():
                            filter_kwargs = {f"{lookup}__{case_insensitive_search_type}": value}
                            queryset = queryset.filter(**filter_kwargs)

        # Apply search filtering based on search_type and model type
        if search_term:
            search_queries = []

            # Build search queries based on ontology type and search type
            if self.ontology_type == "species":
                search_fields = ["official_name", "common_name", "code"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "tissue":
                search_fields = ["identifier", "accession", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "human_disease":
                search_fields = ["identifier", "acronym", "accession", "definition", "synonyms", "keywords"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "subcellular_location":
                search_fields = ["accession", "location_identifier", "definition", "synonyms", "content"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "ms_unique_vocabularies":
                search_fields = ["accession", "name", "definition"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "unimod":
                search_fields = ["accession", "name", "definition"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "chebi":
                search_fields = ["identifier", "name", "definition", "synonyms", "formula"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "ncbi_taxonomy":
                search_fields = ["scientific_name", "common_name", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "mondo":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "uberon":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "cell_ontology":
                search_fields = ["identifier", "name", "definition", "synonyms", "organism", "tissue_origin"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            elif self.ontology_type == "psi_ms":
                search_fields = ["identifier", "name", "definition", "synonyms"]
                for field in search_fields:
                    search_queries.append(models.Q(**{f"{field}__{case_insensitive_search_type}": search_term}))

            # Combine all search queries with OR
            if search_queries:
                combined_query = search_queries[0]
                for query in search_queries[1:]:
                    combined_query |= query
                queryset = queryset.filter(combined_query)

        # Order by relevance with proper scientific_name prioritization
        if search_term and search_type in ["icontains", "istartswith"]:
            if self.ontology_type == "ncbi_taxonomy":
                # Prioritize scientific_name matches first and foremost
                from django.db.models import Case, IntegerField, Value, When

                queryset = queryset.annotate(
                    priority=Case(
                        When(scientific_name__iexact=search_term, then=Value(0)),
                        When(**{f"scientific_name__{search_type}": search_term}, then=Value(1)),
                        When(**{f"common_name__{search_type}": search_term}, then=Value(2)),
                        When(**{f"synonyms__{search_type}": search_term}, then=Value(3)),
                        default=Value(4),
                        output_field=IntegerField(),
                    )
                ).order_by("priority", "scientific_name")
            elif self.ontology_type == "species":
                from django.db.models import Case, IntegerField, Value, When

                queryset = queryset.annotate(
                    priority=Case(
                        When(official_name__iexact=search_term, then=Value(0)),
                        When(**{f"official_name__{search_type}": search_term}, then=Value(1)),
                        When(**{f"common_name__{search_type}": search_term}, then=Value(2)),
                        When(**{f"code__{search_type}": search_term}, then=Value(3)),
                        default=Value(4),
                        output_field=IntegerField(),
                    )
                ).order_by("priority", "official_name")
            elif self.ontology_type in [
                "tissue",
                "human_disease",
                "subcellular_location",
                "mondo",
                "uberon",
                "cell_ontology",
                "psi_ms",
                "chebi",
            ]:
                from django.db.models import Case, IntegerField, Value, When

                # For ontologies with 'name' field
                if hasattr(model_class, "name"):
                    queryset = queryset.annotate(
                        priority=Case(
                            When(name__iexact=search_term, then=Value(0)),
                            When(**{f"name__{search_type}": search_term}, then=Value(1)),
                            default=Value(2),
                            output_field=IntegerField(),
                        )
                    ).order_by("priority", "name")
                elif hasattr(model_class, "identifier"):
                    queryset = queryset.annotate(
                        priority=Case(
                            When(identifier__iexact=search_term, then=Value(0)),
                            When(**{f"identifier__{search_type}": search_term}, then=Value(1)),
                            default=Value(2),
                            output_field=IntegerField(),
                        )
                    ).order_by("priority", "identifier")
            elif self.ontology_type in ["ms_unique_vocabularies", "unimod"]:
                from django.db.models import Case, IntegerField, Value, When

                queryset = queryset.annotate(
                    priority=Case(
                        When(name__iexact=search_term, then=Value(0)),
                        When(**{f"name__{search_type}": search_term}, then=Value(1)),
                        default=Value(2),
                        output_field=IntegerField(),
                    )
                ).order_by("priority", "name")

        return list(queryset[:limit].values())

    def get_ontology_model(self):
        """Get the appropriate ontology model class based on ontology_type."""
        ontology_mapping = {
            "species": Species,
            "tissue": Tissue,
            "human_disease": HumanDisease,
            "subcellular_location": SubcellularLocation,
            "ms_unique_vocabularies": MSUniqueVocabularies,
            "unimod": Unimod,
            "chebi": ChEBICompound,
            "ncbi_taxonomy": NCBITaxonomy,
            "mondo": MondoDisease,
            "uberon": UberonAnatomy,
            "cell_ontology": CellOntology,
            "psi_ms": PSIMSOntology,
        }
        return ontology_mapping.get(self.ontology_type)

    def create_metadata_column(self, metadata_table, position=None):
        """Create a MetadataColumn instance from this template."""
        column = MetadataColumn(
            metadata_table=metadata_table,
            name=self.column_name,
            type=self.column_type,
            column_position=position or 0,
            value=self.default_value,
            ontology_type=self.ontology_type,
            ontology_options=self.ontology_options or [],
            custom_ontology_filters=self.custom_ontology_filters or {},
            enable_typeahead=self.enable_typeahead,
            excel_validation=self.excel_validation,
            custom_validation_rules=self.custom_validation_rules or {},
            api_enhancements=self.api_enhancements or {},
        )

        column.save()

        self.usage_count += 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["usage_count", "last_used_at"])

        return column


# ===================================================================
# COMPREHENSIVE ONTOLOGY MODELS FOR SDRF VALIDATION
# ===================================================================


class MondoDisease(models.Model):
    """Enhanced disease ontology from MONDO (Monarch Disease Ontology)."""

    identifier = models.CharField(max_length=255, primary_key=True)  # MONDO:XXXXXXX
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)  # Semicolon-separated
    xrefs = models.TextField(blank=True, null=True)  # Cross-references to other databases
    parent_terms = models.TextField(blank=True, null=True)  # is_a relationships
    obsolete = models.BooleanField(default=False)
    replacement_term = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["name"]
        verbose_name = "MONDO Disease"
        verbose_name_plural = "MONDO Diseases"

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class UberonAnatomy(models.Model):
    """Anatomy ontology from UBERON (Uber-anatomy ontology)."""

    identifier = models.CharField(max_length=255, primary_key=True)  # UBERON:XXXXXXX
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)  # Semicolon-separated
    xrefs = models.TextField(blank=True, null=True)  # Cross-references
    parent_terms = models.TextField(blank=True, null=True)  # is_a relationships
    part_of = models.TextField(blank=True, null=True)  # part_of relationships
    develops_from = models.TextField(blank=True, null=True)  # developmental relationships
    obsolete = models.BooleanField(default=False)
    replacement_term = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["name"]
        verbose_name = "UBERON Anatomy"
        verbose_name_plural = "UBERON Anatomy Terms"

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class NCBITaxonomy(models.Model):
    """NCBI Taxonomy for comprehensive organism data."""

    tax_id = models.IntegerField(primary_key=True)  # NCBI Taxonomy ID
    scientific_name = models.CharField(max_length=255)
    common_name = models.CharField(max_length=255, blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)  # Semicolon-separated
    rank = models.CharField(max_length=100, blank=True, null=True)  # species, genus, family, etc.
    parent_tax_id = models.IntegerField(blank=True, null=True)  # Parent in taxonomy tree
    lineage = models.TextField(blank=True, null=True)  # Full taxonomic lineage
    genetic_code = models.IntegerField(blank=True, null=True)
    mitochondrial_genetic_code = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["scientific_name"]
        verbose_name = "NCBI Taxonomy"
        verbose_name_plural = "NCBI Taxonomy"

    def __str__(self):
        if self.common_name:
            return f"{self.scientific_name} ({self.common_name}) [{self.tax_id}]"
        return f"{self.scientific_name} [{self.tax_id}]"


class ChEBICompound(models.Model):
    """Chemical compounds from ChEBI (Chemical Entities of Biological Interest)."""

    identifier = models.CharField(max_length=255, primary_key=True)  # CHEBI:XXXXXXX
    name = models.TextField()  # Support very long compound names
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)  # Semicolon-separated
    formula = models.CharField(max_length=255, blank=True, null=True)
    mass = models.FloatField(blank=True, null=True)
    charge = models.IntegerField(blank=True, null=True)
    inchi = models.TextField(blank=True, null=True)
    smiles = models.TextField(blank=True, null=True)
    parent_terms = models.TextField(blank=True, null=True)  # is_a relationships
    roles = models.TextField(blank=True, null=True)  # Biological/chemical roles
    obsolete = models.BooleanField(default=False)
    replacement_term = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["name"]
        verbose_name = "ChEBI Compound"
        verbose_name_plural = "ChEBI Compounds"

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class PSIMSOntology(models.Model):
    """Enhanced PSI-MS ontology terms for mass spectrometry."""

    identifier = models.CharField(max_length=255, primary_key=True)  # MS:XXXXXXX
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)
    parent_terms = models.TextField(blank=True, null=True)  # is_a relationships
    category = models.CharField(max_length=255, blank=True, null=True)  # instrument, method, etc.
    obsolete = models.BooleanField(default=False)
    replacement_term = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["name"]
        verbose_name = "PSI-MS Ontology"
        verbose_name_plural = "PSI-MS Ontology Terms"

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class CellOntology(models.Model):
    """Cell types and cell lines from Cell Ontology (CL) and Cellosaurus."""

    identifier = models.CharField(max_length=255, primary_key=True)  # CL:XXXXXXX or CVCL_XXXX
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)  # Semicolon-separated
    accession = models.CharField(max_length=255, blank=True, null=True)  # Original accession
    cell_line = models.BooleanField(default=False)  # True for cell lines, False for primary cell types
    organism = models.CharField(max_length=255, blank=True, null=True)
    tissue_origin = models.CharField(max_length=255, blank=True, null=True)
    disease_context = models.CharField(max_length=255, blank=True, null=True)
    parent_terms = models.TextField(blank=True, null=True)  # is_a relationships
    part_of = models.TextField(blank=True, null=True)  # part_of relationships
    develops_from = models.TextField(blank=True, null=True)  # develops_from relationships
    source = models.CharField(max_length=50, default="cl")  # 'cl', 'cellosaurus', 'manual'
    obsolete = models.BooleanField(default=False)
    replacement_term = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccv"
        ordering = ["name"]
        verbose_name = "Cell Ontology"
        verbose_name_plural = "Cell Ontology Terms"

    def __str__(self):
        cell_type = "Cell Line" if self.cell_line else "Cell Type"
        return f"{self.name} ({self.identifier}) [{cell_type}]"


class MetadataColumnTemplateShare(models.Model):
    """
    Through model for sharing templates between users.
    Tracks permissions and sharing metadata.
    """

    template = models.ForeignKey(MetadataColumnTemplate, on_delete=models.CASCADE, related_name="template_shares")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="template_shares_received")
    shared_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="template_shares_given",
        help_text="User who shared the template",
    )

    PERMISSION_CHOICES = [
        ("view", "View Only"),
        ("use", "Use Template"),
        ("edit", "Edit Template"),
    ]

    permission_level = models.CharField(
        max_length=10,
        choices=PERMISSION_CHOICES,
        default="use",
        help_text="Level of access granted",
    )

    shared_at = models.DateTimeField(auto_now_add=True)
    last_accessed_at = models.DateTimeField(
        blank=True, null=True, help_text="When the user last accessed this template"
    )

    class Meta:
        app_label = "ccv"
        unique_together = ["template", "user"]
        indexes = [
            models.Index(fields=["user", "permission_level"]),
            models.Index(fields=["template", "shared_at"]),
        ]

    def __str__(self):
        return f"{self.template.name} shared with {self.user.username} ({self.permission_level})"


# Task tracking models are imported where needed
