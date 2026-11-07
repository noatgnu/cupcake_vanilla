"""Request and response shapes of the CUPCAKE Vanilla custom actions, for the OpenAPI schema."""

from rest_framework import serializers

from ccc.models import AsyncTaskStatus, ResourceVisibility

from .serializers import (
    CellOntologySerializer,
    MetadataColumnSerializer,
    MetadataColumnTemplateSerializer,
    MetadataTableSerializer,
    OntologySuggestionSerializer,
)


class AsyncTaskDetailSerializer(serializers.Serializer):
    """A background task with its parameters, result and, when it failed, the traceback."""

    id = serializers.UUIDField()
    task_type = serializers.CharField()
    status = serializers.ChoiceField(choices=AsyncTaskStatus.TASK_STATUS_CHOICES)
    metadata_table_id = serializers.IntegerField(allow_null=True)
    metadata_table_name = serializers.CharField(allow_null=True)
    parameters = serializers.JSONField()
    result = serializers.JSONField()
    progress_percentage = serializers.FloatField()
    progress_description = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    duration = serializers.FloatField(allow_null=True, help_text="Seconds since the task started, or until it ended")
    error_message = serializers.CharField(allow_blank=True)
    traceback = serializers.CharField(allow_null=True)


class TaskDownloadUrlSerializer(serializers.Serializer):
    """Signed link to the file a task produced, valid for ten minutes."""

    download_url = serializers.URLField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    file_size = serializers.IntegerField()
    expires_at = serializers.DateTimeField(help_text="When the file itself is removed")
    expires_in_hours = serializers.IntegerField()


class AvailableValidationSchemaSerializer(serializers.Serializer):
    """A validation schema shipped with sdrf-pipelines."""

    name = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    column_count = serializers.IntegerField()
    extends = serializers.CharField(allow_null=True)
    usable_alone = serializers.BooleanField()
    layer = serializers.CharField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    latest_version = serializers.CharField(allow_null=True)
    versions = serializers.ListField(child=serializers.CharField())


class CleanupResultSerializer(serializers.Serializer):
    """Outcome of removing expired task result files."""

    message = serializers.CharField()
    files_cleaned = serializers.IntegerField()
    errors = serializers.IntegerField()


class ColumnReferenceSerializer(serializers.Serializer):
    """A column by id and name."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class AddColumnSerializer(serializers.Serializer):
    """A column to add, optionally at a position."""

    column_data = serializers.JSONField(help_text="Fields of the new column, as for creating a metadata column")
    position = serializers.IntegerField(required=False, allow_null=True)


class AddColumnWithAutoReorderSerializer(AddColumnSerializer):
    """A column to add, after which the columns are put back in schema order."""

    auto_reorder = serializers.BooleanField(default=True)


class ColumnAddedSerializer(serializers.Serializer):
    """The column that was added."""

    message = serializers.CharField()
    column = MetadataColumnSerializer()


class ColumnAddedWithReorderSerializer(ColumnAddedSerializer):
    """The column that was added, and whether the columns were reordered."""

    reordered = serializers.BooleanField()
    schema_ids_used = serializers.ListField(child=serializers.IntegerField())


class ColumnIdSerializer(serializers.Serializer):
    """A column of the table."""

    column_id = serializers.IntegerField()


class ReorderColumnSerializer(ColumnIdSerializer):
    """A column and its new position."""

    new_position = serializers.IntegerField()


class SchemaIdsSerializer(serializers.Serializer):
    """Schemas whose column order to apply; all schemas of the table when empty."""

    schema_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class ReorderBySchemaSerializer(SchemaIdsSerializer):
    """Schemas to reorder by, and whether to run the reordering in the background."""

    async_processing = serializers.BooleanField(default=False)


class ReorderQueuedSerializer(serializers.Serializer):
    """A queued column reordering job."""

    task_id = serializers.UUIDField()
    message = serializers.CharField()
    metadata_table_id = serializers.IntegerField()
    schema_ids = serializers.ListField(child=serializers.IntegerField())


class ReorderResultSerializer(serializers.Serializer):
    """What the reordering changed."""

    metadata_table_id = serializers.IntegerField()
    reordered_columns = serializers.IntegerField()
    reordered_pools = serializers.IntegerField()
    schema_ids_used = serializers.ListField(child=serializers.IntegerField())


class ReorderCompletedSerializer(serializers.Serializer):
    """A column reordering that ran to completion."""

    message = serializers.CharField()
    metadata_table_id = serializers.IntegerField()
    schema_ids = serializers.ListField(child=serializers.IntegerField())
    result = ReorderResultSerializer()


class ElectronSettingsSerializer(serializers.Serializer):
    """Settings of the desktop build."""

    database_backend = serializers.CharField(allow_null=True)
    sync_operations_only = serializers.BooleanField()


class SystemInfoSerializer(serializers.Serializer):
    """How this installation runs background work."""

    async_tasks_enabled = serializers.BooleanField()
    is_electron_environment = serializers.BooleanField()
    sync_operations_only = serializers.BooleanField()
    electron_settings = ElectronSettingsSerializer(required=False)


class CombineTablesSerializer(serializers.Serializer):
    """Tables to combine into a new table."""

    source_table_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    target_name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    apply_schema_reordering = serializers.BooleanField(default=True)


class CombineTablesRowwiseSerializer(CombineTablesSerializer):
    """Tables to stack into a new table, keeping all columns (union) or only shared ones (intersection)."""

    merge_strategy = serializers.ChoiceField(choices=["union", "intersection"], default="union")


class CombinedTableSerializer(serializers.Serializer):
    """The table that was created."""

    message = serializers.CharField()
    combined_table = MetadataTableSerializer()


class AffectedModifierSerializer(serializers.Serializer):
    """A sample-specific value that refers to samples being removed."""

    modifier_index = serializers.IntegerField()
    column_name = serializers.CharField()
    samples = serializers.CharField()
    invalid_indices = serializers.ListField(child=serializers.IntegerField())
    value = serializers.CharField(allow_blank=True)


class AffectedPoolSerializer(serializers.Serializer):
    """A pool that contains samples being removed."""

    pool_name = serializers.CharField()
    invalid_pooled_only = serializers.ListField(child=serializers.IntegerField())
    invalid_pooled_and_independent = serializers.ListField(child=serializers.IntegerField())


class SampleCountCheckSerializer(serializers.Serializer):
    """Whether a sample count change is possible and which data it would remove."""

    valid = serializers.BooleanField()
    warnings = serializers.ListField(child=serializers.CharField())
    affected_modifiers = AffectedModifierSerializer(many=True)
    affected_pools = AffectedPoolSerializer(many=True)
    samples_to_remove = serializers.ListField(child=serializers.IntegerField())


class SampleCountChangeCheckSerializer(SampleCountCheckSerializer):
    """The current and proposed sample counts with the outcome of the check."""

    current_sample_count = serializers.IntegerField()
    new_sample_count = serializers.IntegerField()


class SampleCountUpdatedSerializer(serializers.Serializer):
    """A sample count that was changed."""

    message = serializers.CharField()
    old_sample_count = serializers.IntegerField()
    new_sample_count = serializers.IntegerField()
    cleanup_performed = serializers.BooleanField()
    validation_result = SampleCountCheckSerializer()


class SampleCountRejectedSerializer(serializers.Serializer):
    """A sample count change that is invalid or removes data without confirmation."""

    error = serializers.CharField()
    message = serializers.CharField(required=False)
    validation_result = SampleCountCheckSerializer()


class ValidateTableSerializer(serializers.Serializer):
    """Options for validating the table against SDRF schemas."""

    validation_options = serializers.JSONField(
        required=False,
        help_text="schema_names (list), validate_sdrf_format, include_pools and skip_ontology",
    )
    async_processing = serializers.BooleanField(default=False)


class TableValidatedSerializer(serializers.Serializer):
    """Outcome of a validation that ran to completion."""

    message = serializers.CharField()
    metadata_table_id = serializers.IntegerField()
    validation_options = serializers.JSONField()
    result = serializers.JSONField(help_text="Per-schema results with errors, warnings and a summary")


class ReplaceValueSerializer(serializers.Serializer):
    """A value to replace and its replacement."""

    old_value = serializers.CharField(allow_blank=True)
    new_value = serializers.CharField(allow_blank=True)
    update_pools = serializers.BooleanField(default=True)


class ReplaceTableValueSerializer(ReplaceValueSerializer):
    """A value to replace in one column, by id or name, or in every column."""

    column_id = serializers.IntegerField(required=False)
    column_name = serializers.CharField(required=False)


class ValueReplacementSerializer(serializers.Serializer):
    """Counts of what a value replacement changed."""

    message = serializers.CharField()
    old_value = serializers.CharField(allow_blank=True)
    new_value = serializers.CharField(allow_blank=True)
    modifiers_merged = serializers.IntegerField()
    modifiers_deleted = serializers.IntegerField()
    samples_reverted_to_default = serializers.IntegerField()
    pool_columns_updated = serializers.IntegerField()


class TableValueReplacementSerializer(ValueReplacementSerializer):
    """Counts of what a value replacement across the table changed."""

    columns_checked = serializers.IntegerField()
    columns_updated = serializers.IntegerField()


class ColumnValueReplacementSerializer(ValueReplacementSerializer):
    """Counts of what a value replacement in the column changed."""

    default_value_updated = serializers.BooleanField()


class ColumnIdsSerializer(serializers.Serializer):
    """Columns of the table."""

    column_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)


class StaffOnlyUpdateSerializer(ColumnIdsSerializer):
    """Columns to mark as staff-only, or to unmark."""

    staff_only = serializers.BooleanField()


class ColumnsDeletedSerializer(serializers.Serializer):
    """Columns that were deleted, and those the user may not delete."""

    message = serializers.CharField()
    deleted_count = serializers.IntegerField()
    deleted_columns = ColumnReferenceSerializer(many=True)
    permission_denied_columns = ColumnReferenceSerializer(many=True)


class StaffOnlyColumnSerializer(ColumnReferenceSerializer):
    """A column and its staff-only flag."""

    staff_only = serializers.BooleanField()


class StaffOnlyUpdatedSerializer(serializers.Serializer):
    """Columns that were updated, and those the user may not change."""

    message = serializers.CharField()
    updated_count = serializers.IntegerField()
    updated_columns = StaffOnlyColumnSerializer(many=True)
    permission_denied_columns = ColumnReferenceSerializer(many=True)
    staff_only = serializers.BooleanField()


class AutofillVariationSerializer(serializers.Serializer):
    """Values one column takes across the generated samples."""

    column_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=["range", "list", "pattern"])
    start = serializers.IntegerField(required=False, help_text="First number of a range")
    end = serializers.IntegerField(required=False, help_text="Last number of a range")
    step = serializers.IntegerField(required=False, help_text="Step of a range")
    values = serializers.ListField(child=serializers.JSONField(), required=False, help_text="Values of a list")
    pattern = serializers.CharField(required=False, help_text="Pattern with {i} for the running number")
    count = serializers.IntegerField(required=False, help_text="How many values the pattern produces")


class AutofillSerializer(serializers.Serializer):
    """Samples to copy and the column variations to fill the table with."""

    template_samples = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    target_sample_count = serializers.IntegerField(min_value=1)
    variations = AutofillVariationSerializer(many=True)
    fill_strategy = serializers.ChoiceField(
        choices=["cartesian_product", "sequential", "interleaved"], default="cartesian_product"
    )


class AutofillSummarySerializer(serializers.Serializer):
    """What the autofill changed."""

    status = serializers.ChoiceField(choices=["success"])
    samples_modified = serializers.IntegerField()
    columns_modified = serializers.IntegerField()
    variations_combinations = serializers.IntegerField()
    strategy = serializers.CharField()


class AutofillErrorsSerializer(serializers.Serializer):
    """Problems with the autofill request."""

    errors = serializers.ListField(child=serializers.CharField())


class ColumnMappingEntrySerializer(serializers.Serializer):
    """A file column and the table column it maps to; a new column is created when columnId is null."""

    fileColIndex = serializers.IntegerField()
    columnId = serializers.IntegerField(allow_null=True)


class FileHeaderSerializer(serializers.Serializer):
    """A column header of the uploaded file."""

    fileColIndex = serializers.IntegerField()
    header = serializers.CharField()


class TableColumnPositionSerializer(serializers.Serializer):
    """A column of the table and its position."""

    columnId = serializers.IntegerField()
    columnName = serializers.CharField()
    columnPosition = serializers.IntegerField()


class ColumnMappingSuggestionSerializer(serializers.Serializer):
    """Headers of the file, columns of the table and a suggested pairing for the user to review."""

    fileHeaders = FileHeaderSerializer(many=True)
    tableColumns = TableColumnPositionSerializer(many=True)
    suggestedMapping = ColumnMappingEntrySerializer(many=True)
    fileRowCount = serializers.IntegerField()
    tableSampleCount = serializers.IntegerField()


class ModifierSerializer(serializers.Serializer):
    """A value that applies to some samples only."""

    samples = serializers.CharField(help_text="Sample numbers, such as 1-3,5")
    value = serializers.CharField(allow_blank=True)


class OverrideMatchedColumnSerializer(serializers.Serializer):
    """How a mapped column would change."""

    columnId = serializers.IntegerField()
    columnName = serializers.CharField()
    fileHeader = serializers.CharField()
    fileColIndex = serializers.IntegerField()
    currentValue = serializers.CharField(allow_null=True)
    newValue = serializers.CharField(allow_null=True)
    currentModifiers = ModifierSerializer(many=True)
    newModifiers = ModifierSerializer(many=True)
    rowsChanged = serializers.IntegerField()


class OverrideNewColumnSerializer(serializers.Serializer):
    """A column the override would add."""

    fileHeader = serializers.CharField()
    fileColIndex = serializers.IntegerField()
    columnType = serializers.CharField()
    newValue = serializers.CharField(allow_null=True)
    newModifiers = ModifierSerializer(many=True)
    warning = serializers.CharField(allow_blank=True)


class ColumnOverridePreviewSerializer(serializers.Serializer):
    """Changes the override would make; nothing is written."""

    columnsMatched = OverrideMatchedColumnSerializer(many=True)
    columnsToAdd = OverrideNewColumnSerializer(many=True)
    warnings = serializers.ListField(child=serializers.CharField())
    sampleCountMismatch = serializers.BooleanField()
    fileRowCount = serializers.IntegerField()


class ColumnOverrideAppliedSerializer(serializers.Serializer):
    """Changes the override made."""

    message = serializers.CharField()
    columnsUpdated = serializers.IntegerField()
    columnsAdded = serializers.IntegerField()
    warnings = serializers.ListField(child=serializers.CharField())
    updatedColumns = ColumnReferenceSerializer(many=True)


class ShareTokenSerializer(serializers.Serializer):
    """Token for the read-only link to the table."""

    share_token = serializers.UUIDField()


class SdrfDataValidationSerializer(serializers.Serializer):
    """Columns to check against an SDRF schema."""

    metadata_ids = serializers.ListField(child=serializers.IntegerField())
    sample_number = serializers.IntegerField(default=1)
    schema_name = serializers.CharField(default="default")
    skip_ontology = serializers.BooleanField(default=False)


class SdrfDataValidityReportSerializer(serializers.Serializer):
    """Outcome of an SDRF check."""

    valid = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.JSONField())
    warnings = serializers.ListField(child=serializers.JSONField())
    sample_count = serializers.IntegerField()


class ColumnOntologySuggestionsSerializer(serializers.Serializer):
    """Ontology terms matching the search, for the column's ontology."""

    ontology_type = serializers.CharField(allow_null=True)
    suggestions = OntologySuggestionSerializer(many=True)
    search_term = serializers.CharField(allow_blank=True)
    search_type = serializers.ChoiceField(choices=["icontains", "istartswith", "exact"])
    limit = serializers.IntegerField()
    count = serializers.IntegerField()
    custom_filters = serializers.JSONField(allow_null=True)
    has_more = serializers.BooleanField()
    remote_pending = serializers.BooleanField(help_text="A lookup in the remote vocabulary service is still running")


class ValueSerializer(serializers.Serializer):
    """A value to check."""

    value = serializers.CharField(allow_blank=True)


class ValueValiditySerializer(serializers.Serializer):
    """Whether the value is a term of the column's ontology; close terms are suggested when it is not."""

    valid = serializers.BooleanField()
    value = serializers.CharField(allow_blank=True)
    ontology_type = serializers.CharField(allow_null=True)
    suggestions = serializers.ListField(child=serializers.JSONField(), required=False)


class ColumnValueUpdateSerializer(serializers.Serializer):
    """A new value for the column default, for some samples, or for every sample."""

    value = serializers.CharField(allow_blank=True)
    sample_indices = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_null=True, help_text="1-based"
    )
    value_type = serializers.ChoiceField(choices=["default", "sample_specific", "replace_all"], default="default")


class ColumnValueChangesSerializer(serializers.Serializer):
    """The column default and sample-specific values before and after the update."""

    old_default = serializers.CharField(allow_null=True, allow_blank=True)
    new_default = serializers.CharField(allow_null=True, allow_blank=True)
    old_modifiers = ModifierSerializer(many=True)
    new_modifiers = ModifierSerializer(many=True)
    updated_samples = serializers.ListField(child=serializers.IntegerField())


class ColumnValueUpdatedSerializer(serializers.Serializer):
    """The updated column and what changed."""

    message = serializers.CharField()
    column = MetadataColumnSerializer()
    changes = ColumnValueChangesSerializer()
    value_type = serializers.CharField()


class SampleValueSerializer(serializers.Serializer):
    """A value for one sample."""

    sample_index = serializers.IntegerField(min_value=1)
    value = serializers.CharField(allow_blank=True)


class BulkSampleValuesSerializer(serializers.Serializer):
    """Values for several samples."""

    updates = SampleValueSerializer(many=True)


class FailedSampleUpdateSerializer(serializers.Serializer):
    """A sample value that was not applied."""

    sample_index = serializers.JSONField()
    error = serializers.CharField()


class BulkSampleValuesUpdatedSerializer(serializers.Serializer):
    """Counts of the applied values and the updated column."""

    message = serializers.CharField()
    updated_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    column = MetadataColumnSerializer()
    failed_updates = FailedSampleUpdateSerializer(many=True, required=False)


class OntologyMappingAppliedSerializer(serializers.Serializer):
    """Whether an ontology was assigned to the column."""

    applied = serializers.BooleanField()
    ontology_type = serializers.CharField(allow_null=True)
    message = serializers.CharField()


class DetectedOntologyTypeSerializer(serializers.Serializer):
    """The ontology a column of this name and type uses."""

    column_name = serializers.CharField()
    column_type = serializers.CharField(allow_blank=True)
    detected_ontology_type = serializers.CharField(allow_null=True)


class FieldChangeSerializer(serializers.Serializer):
    """A field that changed between two versions of the column."""

    field = serializers.CharField()
    old_value = serializers.JSONField()
    new_value = serializers.JSONField()


class ColumnSnapshotSerializer(serializers.Serializer):
    """The column as it was after a change."""

    name = serializers.CharField()
    type = serializers.CharField()
    value = serializers.CharField(allow_null=True, allow_blank=True)
    column_position = serializers.IntegerField(allow_null=True)
    mandatory = serializers.BooleanField()
    hidden = serializers.BooleanField()
    readonly = serializers.BooleanField()
    modifiers = ModifierSerializer(many=True, allow_null=True)
    ontology_type = serializers.CharField(allow_null=True, allow_blank=True)
    not_applicable = serializers.BooleanField()
    not_available = serializers.BooleanField()


class ColumnHistoryEntrySerializer(serializers.Serializer):
    """One recorded change of the column."""

    history_id = serializers.IntegerField()
    history_date = serializers.DateTimeField()
    history_type = serializers.CharField(help_text="Created, Changed or Deleted")
    history_user = serializers.CharField(allow_null=True)
    history_user_id = serializers.IntegerField(allow_null=True)
    changes = FieldChangeSerializer(many=True)
    snapshot = ColumnSnapshotSerializer()


class ColumnHistorySerializer(serializers.Serializer):
    """A page of the column's change history, newest first."""

    count = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    has_more = serializers.BooleanField()
    history = ColumnHistoryEntrySerializer(many=True)


class DuplicateColumnSerializer(ColumnIdSerializer):
    """A column to copy, optionally under a new name."""

    new_name = serializers.CharField(required=False, allow_blank=True)


class TemplateReorderQueuedSerializer(serializers.Serializer):
    """A queued template column reordering job."""

    task_id = serializers.UUIDField()
    message = serializers.CharField()
    template_id = serializers.IntegerField()
    schema_ids = serializers.ListField(child=serializers.IntegerField())


class TemplateReorderResultSerializer(serializers.Serializer):
    """What the template reordering changed."""

    template_id = serializers.IntegerField()
    reordered_columns = serializers.IntegerField()
    schema_ids_used = serializers.ListField(child=serializers.IntegerField())


class TemplateReorderCompletedSerializer(serializers.Serializer):
    """A template column reordering that ran to completion."""

    message = serializers.CharField()
    template_id = serializers.IntegerField()
    schema_ids = serializers.ListField(child=serializers.IntegerField())
    result = TemplateReorderResultSerializer()


class MetadataTableIdSerializer(serializers.Serializer):
    """A metadata table."""

    metadata_table_id = serializers.IntegerField()


class TemplateAppliedSerializer(serializers.Serializer):
    """Columns created on the table from the template."""

    message = serializers.CharField()
    created_columns = MetadataColumnSerializer(many=True)


class AvailableSchemaSerializer(serializers.Serializer):
    """A schema the user may build templates and tables from."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    is_builtin = serializers.BooleanField()
    tags = serializers.ListField(child=serializers.CharField())
    usage_count = serializers.IntegerField()
    file_size = serializers.IntegerField()
    created_at = serializers.DateTimeField(allow_null=True)
    layer = serializers.CharField(allow_blank=True)
    usable_alone = serializers.BooleanField()
    version = serializers.CharField(allow_blank=True)
    extends = serializers.CharField(allow_blank=True)


class SchemaSelectionSerializer(serializers.Serializer):
    """Schemas by id or by name; a default schema is used when neither is given."""

    name = serializers.CharField()
    schema_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    schemas = serializers.ListField(child=serializers.CharField(), required=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TemplateFromSchemaSerializer(SchemaSelectionSerializer):
    """A template to build from schemas."""

    lab_group_id = serializers.IntegerField(required=False, allow_null=True)
    lab_group = serializers.IntegerField(
        required=False, allow_null=True, help_text="Used when lab_group_id is not given"
    )
    visibility = serializers.ChoiceField(
        choices=ResourceVisibility.choices,
        required=False,
        help_text="Owner only (private), the lab group (group, needs lab_group_id) or everyone (public)",
    )
    is_public = serializers.BooleanField(required=False, help_text="Used when visibility is not given")
    is_default = serializers.BooleanField(default=False)


class TableFromSchemasSerializer(SchemaSelectionSerializer):
    """A metadata table to build from schemas."""

    sample_count = serializers.IntegerField(default=1)
    lab_group_id = serializers.IntegerField(required=False, allow_null=True)


class TableFromTemplateSerializer(serializers.Serializer):
    """A metadata table to build from a template."""

    name = serializers.CharField()
    template_id = serializers.IntegerField()
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sample_count = serializers.IntegerField(default=1)
    lab_group_id = serializers.IntegerField(required=False, allow_null=True)


class FieldMaskMappingSerializer(serializers.Serializer):
    """Display names of the template's columns, keyed by column name."""

    field_mask_mapping = serializers.DictField(child=serializers.CharField())


class FieldMaskUpdatedSerializer(FieldMaskMappingSerializer):
    """The saved display names."""

    message = serializers.CharField()


class TemplateFieldMaskSerializer(FieldMaskMappingSerializer):
    """The template's display names."""

    template_name = serializers.CharField()
    template_id = serializers.IntegerField()


class MaskedColumnSerializer(serializers.Serializer):
    """A template column with the name shown for it."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.CharField()
    display_name = serializers.CharField()
    has_field_mask = serializers.BooleanField()
    column_position = serializers.IntegerField(allow_null=True)
    mandatory = serializers.BooleanField()
    hidden = serializers.BooleanField()


class TemplateColumnsWithMasksSerializer(TemplateFieldMaskSerializer):
    """The template's columns with their display names."""

    columns = MaskedColumnSerializer(many=True)


class SchemaSyncSerializer(serializers.Serializer):
    """Which changes from the linked schemas to apply."""

    add_new = serializers.BooleanField(default=True)
    update_existing = serializers.BooleanField(default=True)
    remove_orphans = serializers.BooleanField(default=False)


class SchemaSyncedSerializer(serializers.Serializer):
    """Counts of the columns the synchronisation changed."""

    message = serializers.CharField()
    added = serializers.IntegerField()
    updated = serializers.IntegerField()
    removed = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())
    schemas = serializers.ListField(child=serializers.CharField())


class SchemaSyncFailedSerializer(serializers.Serializer):
    """A synchronisation that could not run."""

    error = serializers.CharField()
    added = serializers.IntegerField()
    updated = serializers.IntegerField()
    removed = serializers.IntegerField()


class TemplateColumnsDeletedSerializer(serializers.Serializer):
    """Template columns that were deleted."""

    message = serializers.CharField()
    deleted_count = serializers.IntegerField()
    deleted_columns = ColumnReferenceSerializer(many=True)


class TemplateStaffOnlyUpdatedSerializer(serializers.Serializer):
    """Template columns whose staff-only flag was changed."""

    message = serializers.CharField()
    updated_count = serializers.IntegerField()
    updated_columns = StaffOnlyColumnSerializer(many=True)
    staff_only = serializers.BooleanField()


class SdrfImportedSerializer(serializers.Serializer):
    """What an SDRF import created."""

    message = serializers.CharField()
    created_columns = serializers.IntegerField()
    created_pools = serializers.IntegerField()
    pools_detected = serializers.BooleanField()
    sn_rows_count = serializers.IntegerField()
    pooled_rows_count = serializers.IntegerField()
    sample_rows = serializers.IntegerField()


class ExcelImportedSerializer(serializers.Serializer):
    """What an Excel import created."""

    message = serializers.CharField()
    created_columns = serializers.IntegerField()
    created_pools = serializers.IntegerField()
    sample_rows = serializers.IntegerField()
    has_hidden_data = serializers.BooleanField()
    has_pool_data = serializers.BooleanField()


class UniqueColumnValuesSerializer(serializers.Serializer):
    """The distinct values of the columns sharing a name."""

    name = serializers.CharField()
    types = serializers.DictField(child=serializers.IntegerField(), help_text="Number of columns per column type")
    unique_values = serializers.ListField(child=serializers.CharField())
    value_count = serializers.IntegerField()


class CollectedUniqueValuesSerializer(serializers.Serializer):
    """Distinct values of the table's columns, keyed by lower-cased column name."""

    metadata_table_id = serializers.IntegerField()
    metadata_table_name = serializers.CharField()
    unique_values_only = serializers.BooleanField()
    metadata_columns = serializers.DictField(child=UniqueColumnValuesSerializer())
    total_unique_values = serializers.IntegerField()


class CollectedColumnsSerializer(serializers.Serializer):
    """The table's columns."""

    metadata_table_id = serializers.IntegerField()
    metadata_table_name = serializers.CharField()
    unique_values_only = serializers.BooleanField()
    metadata_columns = MetadataColumnSerializer(many=True)
    total_columns = serializers.IntegerField()


class ColumnFromTemplateSerializer(MetadataTableIdSerializer):
    """The table to add the column to, optionally at a position."""

    position = serializers.IntegerField(required=False, allow_null=True)


class ColumnFromTemplateCreatedSerializer(serializers.Serializer):
    """The column created from the template."""

    message = serializers.CharField()
    column_id = serializers.IntegerField()
    template_usage_count = serializers.IntegerField()


class ShareColumnTemplateSerializer(serializers.Serializer):
    """A user to share the template with, and what they may do with it."""

    user_id = serializers.IntegerField()
    permission_level = serializers.ChoiceField(choices=["view", "use", "edit"], default="use")


class ColumnTemplateSharedSerializer(serializers.Serializer):
    """The share that was created or updated."""

    message = serializers.CharField()
    share_id = serializers.IntegerField()
    user = serializers.CharField(help_text="Username of the user the template is shared with")
    permission_level = serializers.CharField()


class UserIdSerializer(serializers.Serializer):
    """A user."""

    user_id = serializers.IntegerField()


class TemplateOntologySuggestionsSerializer(serializers.Serializer):
    """Ontology terms matching the search, for the template's ontology."""

    suggestions = OntologySuggestionSerializer(many=True)
    has_more = serializers.BooleanField()
    total_count = serializers.IntegerField()
    message = serializers.CharField(required=False, help_text="Present when the template has no ontology")
    ontology_type = serializers.CharField(required=False)
    search_term = serializers.CharField(required=False, allow_blank=True)
    search_type = serializers.CharField(required=False)
    remote_pending = serializers.BooleanField(required=False)


class ColumnTemplateGroupSerializer(serializers.Serializer):
    """Column templates that share a column name and type."""

    column_name = serializers.CharField()
    column_type = serializers.CharField()
    schema_count = serializers.IntegerField()
    schemas = serializers.ListField(child=serializers.CharField())
    template_ids = serializers.ListField(child=serializers.IntegerField())
    sample_template = MetadataColumnTemplateSerializer(allow_null=True)


class ColumnTemplateGroupPageSerializer(serializers.Serializer):
    """A page of column template groups."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, help_text="Query string of the next page")
    previous = serializers.CharField(allow_null=True, help_text="Query string of the previous page")
    results = ColumnTemplateGroupSerializer(many=True)


class TermSuggestionSerializer(serializers.Serializer):
    """An ontology term offered while typing; the fields after match_type depend on the ontology."""

    identifier = serializers.CharField()
    name = serializers.CharField()
    definition = serializers.CharField(allow_blank=True)
    synonyms = serializers.ListField(child=serializers.CharField(), required=False)
    source = serializers.CharField(required=False)
    match_type = serializers.ChoiceField(choices=["exact", "fuzzy"])
    category = serializers.CharField(required=False)
    cell_type = serializers.CharField(required=False)
    organism = serializers.CharField(required=False, allow_blank=True)
    tissue_origin = serializers.CharField(required=False, allow_blank=True)
    xrefs = serializers.ListField(child=serializers.CharField(), required=False)


class TermSuggestionsSerializer(serializers.Serializer):
    """Terms matching the search; empty when the search is shorter than the minimum."""

    results = TermSuggestionSerializer(many=True)


class CellLinesSerializer(serializers.Serializer):
    """Cell lines, optionally of one organism."""

    results = CellOntologySerializer(many=True)


class OntologySearchResultsSerializer(serializers.Serializer):
    """Ontology terms matching the search across one ontology or the common ones."""

    ontology_type = serializers.CharField(help_text="The requested ontology, or all")
    suggestions = OntologySuggestionSerializer(many=True)
    search_term = serializers.CharField()
    search_type = serializers.ChoiceField(choices=["contains", "startswith"])
    limit = serializers.IntegerField()
    count = serializers.IntegerField()
    custom_filters = serializers.JSONField(allow_null=True)
    has_more = serializers.BooleanField()
    remote_pending = serializers.BooleanField()


class SchemasSyncedSerializer(serializers.Serializer):
    """Counts of the builtin schemas that were synchronised."""

    message = serializers.CharField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()


class NamedValueSerializer(serializers.Serializer):
    """A value with a readable name."""

    name = serializers.CharField()
    value = serializers.CharField()


class SdrfColumnsSerializer(serializers.Serializer):
    """SDRF columns that have default values."""

    columns = serializers.ListField(child=serializers.CharField())
    total = serializers.IntegerField()


class ColumnDefaultsSerializer(serializers.Serializer):
    """Default values of an SDRF column."""

    column = serializers.CharField()
    config = serializers.JSONField(help_text="type and values, plus format details for structured columns")


class ColumnSearchSerializer(serializers.Serializer):
    """SDRF columns whose name contains the query, with their default values."""

    query = serializers.CharField()
    matches = serializers.DictField(child=serializers.JSONField())
    total = serializers.IntegerField()


class StructuredOptionsSerializer(serializers.Serializer):
    """Options of a structured (key=value) SDRF column, grouped by kind."""

    column = serializers.CharField()
    field_type = serializers.CharField(allow_null=True)
    options = serializers.DictField(child=serializers.ListField(child=serializers.JSONField()))


class LabelOptionsSerializer(serializers.Serializer):
    """Label values for label-free, TMT and SILAC experiments."""

    label_free = serializers.ListField(child=serializers.CharField())
    tmt_labels = serializers.ListField(child=serializers.CharField())
    silac_labels = serializers.ListField(child=serializers.CharField())


class ModificationsOfTypeSerializer(serializers.Serializer):
    """Modifications of the requested kind."""

    type = serializers.ChoiceField(choices=["fixed", "variable"])
    modifications = NamedValueSerializer(many=True)


class ModificationsSerializer(serializers.Serializer):
    """Fixed and variable modifications."""

    fixed = NamedValueSerializer(many=True)
    variable = NamedValueSerializer(many=True)


class InstrumentModelsSerializer(serializers.Serializer):
    """Common instrument models."""

    instruments = serializers.ListField(child=serializers.CharField())


class CleavageAgentsOfTypeSerializer(serializers.Serializer):
    """Cleavage agents of the requested kind."""

    type = serializers.ChoiceField(choices=["enzymatic", "non_enzymatic"])
    agents = serializers.ListField(child=serializers.JSONField())


class CleavageAgentsSerializer(serializers.Serializer):
    """Enzymatic agents, with names and values, and non-enzymatic ones."""

    enzymatic = NamedValueSerializer(many=True)
    non_enzymatic = serializers.ListField(child=serializers.CharField())


class CompoundFieldsSerializer(serializers.Serializer):
    """SDRF columns made of several key=value parts, with their formats."""

    compound_fields = serializers.ListField(child=serializers.CharField())
    schemas = serializers.DictField(child=serializers.JSONField())


class CompoundSchemaSerializer(serializers.Serializer):
    """Format of a compound SDRF column."""

    column = serializers.CharField()
    schema = serializers.JSONField(help_text="format, separator and the parts the value is made of")


class CompoundValueSerializer(serializers.Serializer):
    """A value of a compound SDRF column to check."""

    column = serializers.CharField()
    value = serializers.CharField(allow_blank=True)


class CompoundValidityCheckSerializer(serializers.Serializer):
    """Whether the value matches the column format."""

    valid = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.CharField())


class CompoundValidationSerializer(CompoundValueSerializer):
    """The checked value and the outcome."""

    validation = CompoundValidityCheckSerializer()


class ColumnNameSuggestionsSerializer(serializers.Serializer):
    """SDRF column names starting like the partial input."""

    partial = serializers.CharField()
    suggestions = serializers.ListField(child=serializers.CharField())
    total = serializers.IntegerField()


class QuickValueCategoriesSerializer(serializers.Serializer):
    """Categories that quick values are available for."""

    available_categories = serializers.ListField(child=serializers.CharField())


class QuickValuesSerializer(serializers.Serializer):
    """Common values of a category: a list, or lists grouped by kind."""

    category = serializers.CharField()
    values = serializers.JSONField()


class SchemaColumnDefinitionSerializer(serializers.Serializer):
    """An SDRF column as an sdrf-pipelines schema defines it."""

    name = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    requirement = serializers.CharField(allow_null=True)
    allow_pooled = serializers.BooleanField()
    allow_not_applicable = serializers.BooleanField()
    allow_not_available = serializers.BooleanField()
    allow_anonymized = serializers.BooleanField()
    validators = serializers.ListField(child=serializers.JSONField())


class SchemaColumnDefinitionsSerializer(serializers.Serializer):
    """Columns of the requested schemas, each listed once."""

    schemas = serializers.ListField(child=serializers.CharField())
    columns = SchemaColumnDefinitionSerializer(many=True)
    total = serializers.IntegerField()


class VocabularyInUseSerializer(serializers.Serializer):
    """Why a vocabulary could not be deleted."""

    error = serializers.CharField()
    columns = serializers.IntegerField()
    templates = serializers.IntegerField()
