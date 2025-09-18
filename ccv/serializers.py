"""
Django REST Framework serializers for CUPCAKE Vanilla metadata models.
"""

from rest_framework import serializers

from .models import (
    CellOntology,
    ChEBICompound,
    FavouriteMetadataOption,
    HumanDisease,
    MetadataColumn,
    MetadataColumnTemplate,
    MetadataColumnTemplateShare,
    MetadataTable,
    MetadataTableTemplate,
    MondoDisease,
    MSUniqueVocabularies,
    NCBITaxonomy,
    PSIMSOntology,
    SamplePool,
    Schema,
    Species,
    SubcellularLocation,
    Tissue,
    UberonAnatomy,
    Unimod,
)
from .task_models import AsyncTaskStatus


class MetadataTableSerializer(serializers.ModelSerializer):
    """Serializer for MetadataTable model."""

    columns = serializers.SerializerMethodField()
    sample_pools = serializers.SerializerMethodField()
    column_count = serializers.IntegerField(source="get_column_count", read_only=True)
    sample_range = serializers.CharField(source="get_sample_range", read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)
    can_edit = serializers.SerializerMethodField()

    # Field for confirming sample count changes that would remove data
    sample_count_confirmed = serializers.BooleanField(
        default=False,
        write_only=True,
        required=False,
        help_text="Confirmation that user understands reducing sample count will remove data",
    )

    class Meta:
        model = MetadataTable
        fields = [
            "id",
            "name",
            "description",
            "sample_count",
            "sample_count_confirmed",
            "version",
            "owner",
            "owner_username",
            "lab_group",
            "lab_group_name",
            "is_locked",
            "is_published",
            "content_type",
            "object_id",
            "columns",
            "sample_pools",
            "column_count",
            "sample_range",
            "can_edit",
            "source_app",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_columns(self, obj):
        """Get the columns for this metadata table."""
        columns = obj.columns.all().order_by("column_position")
        return MetadataColumnSerializer(columns, many=True, context=self.context).data

    def get_sample_pools(self, obj):
        """Get the sample pools for this metadata table."""
        sample_pools = obj.sample_pools.all().order_by("created_at")
        return SamplePoolSerializer(sample_pools, many=True, context=self.context).data

    def get_can_edit(self, obj):
        """Check if current user can edit this table."""
        request = self.context.get("request")
        if request and request.user:
            return obj.can_edit(request.user)
        return False

    def validate(self, attrs):
        """Validate sample count changes and require confirmation if data will be removed."""
        # Check if sample_count is being updated
        if "sample_count" in attrs:
            new_sample_count = attrs["sample_count"]

            # If updating an existing instance
            if self.instance:
                current_sample_count = self.instance.sample_count

                # If reducing sample count, validate and require confirmation
                if new_sample_count < current_sample_count:
                    validation_result = self.instance.validate_sample_count_change(new_sample_count)

                    # If there are warnings (data will be removed) and no confirmation
                    if validation_result["warnings"] and not attrs.get("sample_count_confirmed", False):
                        # Provide detailed error with information about what will be affected
                        error_details = {
                            "current_sample_count": current_sample_count,
                            "new_sample_count": new_sample_count,
                            "requires_confirmation": True,
                            "validation_result": validation_result,
                        }

                        raise serializers.ValidationError(
                            {
                                "sample_count": f"Reducing sample count from {current_sample_count} to {new_sample_count} will remove data. Set sample_count_confirmed=true to proceed.",
                                "sample_count_confirmation_details": error_details,
                            }
                        )

        return attrs

    def create(self, validated_data):
        """Handle creation with sample_count_confirmed field removal."""
        # Remove the confirmation field from validated_data since it's not a model field
        validated_data.pop("sample_count_confirmed", False)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Handle sample count updates with proper cleanup."""
        # Remove the confirmation field from validated_data since it's not a model field
        validated_data.pop("sample_count_confirmed", False)

        # Check if sample_count is being updated
        if "sample_count" in validated_data:
            new_sample_count = validated_data["sample_count"]

            # If reducing sample count, apply the change with cleanup
            if new_sample_count < instance.sample_count:
                # Remove sample_count from validated_data to handle it separately
                validated_data.pop("sample_count")

                # Update other fields first
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save()

                # Apply sample count change with cleanup
                instance.apply_sample_count_change(new_sample_count)

                return instance

        # For normal updates (no sample count reduction), use default behavior
        return super().update(instance, validated_data)


class MetadataColumnSerializer(serializers.ModelSerializer):
    """Serializer for MetadataColumn model."""

    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    template_name = serializers.CharField(source="template.name", read_only=True)

    class Meta:
        model = MetadataColumn
        fields = [
            "id",
            "metadata_table",
            "metadata_table_name",
            "template",
            "template_name",
            "name",
            "type",
            "column_position",
            "value",
            "not_applicable",
            "mandatory",
            "hidden",
            "auto_generated",
            "readonly",
            "modifiers",
            "ontology_type",
            "ontology_options",
            "suggested_values",
            "enable_typeahead",
            "possible_default_values",
            "staff_only",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "suggested_values", "possible_default_values"]

    def validate_modifiers(self, value):
        """Validate that modifiers is a valid JSON structure."""
        if value and not isinstance(value, list):
            raise serializers.ValidationError("Modifiers must be a valid JSON array.")
        return value


class SamplePoolSerializer(serializers.ModelSerializer):
    """Serializer for SamplePool model."""

    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    total_samples = serializers.IntegerField(source="get_total_samples", read_only=True)
    all_sample_indices = serializers.ListField(source="get_all_sample_indices", read_only=True)
    metadata_columns = serializers.SerializerMethodField()

    class Meta:
        model = SamplePool
        fields = [
            "id",
            "pool_name",
            "pool_description",
            "pooled_only_samples",
            "pooled_and_independent_samples",
            "is_reference",
            "sdrf_value",
            "metadata_table",
            "metadata_table_name",
            "total_samples",
            "all_sample_indices",
            "metadata_columns",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_metadata_columns(self, obj):
        """Get the metadata columns for this sample pool."""
        columns = obj.metadata_columns.all().order_by("column_position")
        return MetadataColumnSerializer(columns, many=True, context=self.context).data

    def validate_pooled_only_samples(self, value):
        """Validate that pooled_only_samples is a list of integers."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of sample indices.")
        for item in value:
            if not isinstance(item, int) or item < 1:
                raise serializers.ValidationError("Sample indices must be positive integers.")
        return value

    def validate_pooled_and_independent_samples(self, value):
        """Validate that pooled_and_independent_samples is a list of integers."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of sample indices.")
        for item in value:
            if not isinstance(item, int) or item < 1:
                raise serializers.ValidationError("Sample indices must be positive integers.")
        return value


class MetadataTableTemplateSerializer(serializers.ModelSerializer):
    """Serializer for MetadataTableTemplate model."""

    owner_username = serializers.CharField(source="owner.username", read_only=True)
    user_columns = MetadataColumnSerializer(many=True, read_only=True)
    user_column_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of MetadataColumn IDs to associate with this template",
    )
    column_count = serializers.IntegerField(source="user_columns.count", read_only=True)

    class Meta:
        model = MetadataTableTemplate
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "owner_username",
            "lab_group",
            "user_columns",
            "user_column_ids",
            "field_mask_mapping",
            "visibility",
            "is_default",
            "column_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        user_column_ids = validated_data.pop("user_column_ids", [])
        template = super().create(validated_data)

        if user_column_ids:
            user_columns = MetadataColumn.objects.filter(id__in=user_column_ids)
            template.user_columns.set(user_columns)

        return template

    def update(self, instance, validated_data):
        user_column_ids = validated_data.pop("user_column_ids", None)
        template = super().update(instance, validated_data)

        if user_column_ids is not None:
            user_columns = MetadataColumn.objects.filter(id__in=user_column_ids)
            template.user_columns.set(user_columns)

        return template

    def validate_field_mask_mapping(self, value):
        """Validate that field_mask_mapping is a valid JSON structure."""
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("Field mask mapping must be a valid JSON object.")
        return value


class FavouriteMetadataOptionSerializer(serializers.ModelSerializer):
    """Serializer for FavouriteMetadataOption model."""

    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = FavouriteMetadataOption
        fields = [
            "id",
            "name",
            "type",
            "column_template",
            "value",
            "display_value",
            "user",
            "user_username",
            "lab_group",
            "lab_group_name",
            "is_global",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, data):
        """Validate that global options don't have user or lab_group."""
        if data.get("is_global"):
            if data.get("user") or data.get("lab_group"):
                raise serializers.ValidationError(
                    "Global options cannot be associated with a specific user or lab group."
                )
        return data


class MetadataExportSerializer(serializers.Serializer):
    """Serializer for metadata export requests."""

    metadata_table_id = serializers.IntegerField(help_text="ID of the MetadataTable to export")
    metadata_column_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="List of MetadataColumn IDs to export",
    )
    sample_number = serializers.IntegerField(min_value=1, help_text="Number of samples")
    export_format = serializers.ChoiceField(
        choices=["excel", "csv", "sdrf"], default="excel", help_text="Export format"
    )
    include_pools = serializers.BooleanField(default=False, help_text="Whether to include sample pools in export")
    async_processing = serializers.BooleanField(
        default=False, help_text="Whether to process the export asynchronously via task queue"
    )
    pool_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="List of SamplePool IDs to include (if include_pools is True)",
    )
    lab_group_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="List of lab group IDs for favourite options (can be empty for none, or multiple IDs)",
    )


class MetadataImportSerializer(serializers.Serializer):
    """Serializer for metadata import requests."""

    file = serializers.FileField(help_text="SDRF file to import")
    metadata_table_id = serializers.IntegerField(help_text="ID of the metadata table to import data into")
    import_type = serializers.ChoiceField(
        choices=["user_metadata", "staff_metadata", "both"],
        default="user_metadata",
        help_text="Type of metadata to import",
    )
    create_pools = serializers.BooleanField(default=True, help_text="Whether to create sample pools from SDRF data")
    replace_existing = serializers.BooleanField(default=False, help_text="Whether to replace existing metadata columns")
    async_processing = serializers.BooleanField(
        default=False, help_text="Whether to process the import asynchronously via task queue"
    )

    def validate_metadata_table_id(self, value):
        """Validate that the metadata table exists."""
        try:
            MetadataTable.objects.get(id=value)
        except MetadataTable.DoesNotExist:
            raise serializers.ValidationError("Invalid metadata table ID.")
        return value


class ChunkedImportSerializer(serializers.Serializer):
    """Serializer for chunked import requests."""

    chunked_upload_id = serializers.UUIDField(help_text="ID of the completed chunked upload")
    metadata_table_id = serializers.IntegerField(help_text="ID of the metadata table to import data into")
    replace_existing = serializers.BooleanField(default=False, help_text="Whether to replace existing metadata columns")
    validate_ontologies = serializers.BooleanField(default=True, help_text="Whether to validate ontology terms")
    create_pools = serializers.BooleanField(
        default=True, help_text="Whether to create sample pools from detected patterns"
    )

    def validate_metadata_table_id(self, value):
        """Validate that the metadata table exists."""
        try:
            MetadataTable.objects.get(id=value)
        except MetadataTable.DoesNotExist:
            raise serializers.ValidationError("Invalid metadata table ID.")
        return value

    def validate_chunked_upload_id(self, value):
        """Validate that the chunked upload exists and is complete."""
        try:
            from ccv.chunked_upload import MetadataFileUpload

            upload = MetadataFileUpload.objects.get(id=value)
            if upload.status != upload.COMPLETE:
                raise serializers.ValidationError("Chunked upload is not complete.")
        except MetadataFileUpload.DoesNotExist:
            raise serializers.ValidationError("Invalid chunked upload ID.")
        return value


class MetadataCollectionSerializer(serializers.Serializer):
    """Serializer for metadata collection requests."""

    metadata_table_id = serializers.IntegerField(help_text="ID of the metadata table to collect data from")
    metadata_names = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Specific metadata names to filter (optional)",
    )
    unique_values_only = serializers.BooleanField(
        default=False, help_text="Return only unique values for filtered metadata"
    )

    def validate_metadata_table_id(self, value):
        """Validate that the metadata table exists."""
        try:
            MetadataTable.objects.get(id=value)
        except MetadataTable.DoesNotExist:
            raise serializers.ValidationError("Invalid metadata table ID.")
        return value


# ===================================================================
# ONTOLOGY AND CONTROLLED VOCABULARY SERIALIZERS
# ===================================================================


class SpeciesSerializer(serializers.ModelSerializer):
    """Serializer for Species model."""

    class Meta:
        model = Species
        fields = ["code", "taxon", "official_name", "common_name", "synonym"]
        read_only_fields = ["code", "taxon", "official_name", "common_name", "synonym"]


class TissueSerializer(serializers.ModelSerializer):
    """Serializer for Tissue model."""

    class Meta:
        model = Tissue
        fields = ["identifier", "accession", "synonyms", "cross_references"]
        read_only_fields = ["identifier", "accession", "synonyms", "cross_references"]


class HumanDiseaseSerializer(serializers.ModelSerializer):
    """Serializer for HumanDisease model."""

    class Meta:
        model = HumanDisease
        fields = [
            "identifier",
            "acronym",
            "accession",
            "definition",
            "synonyms",
            "cross_references",
            "keywords",
        ]
        read_only_fields = [
            "identifier",
            "acronym",
            "accession",
            "definition",
            "synonyms",
            "cross_references",
            "keywords",
        ]


class SubcellularLocationSerializer(serializers.ModelSerializer):
    """Serializer for SubcellularLocation model."""

    class Meta:
        model = SubcellularLocation
        fields = [
            "accession",
            "location_identifier",
            "topology_identifier",
            "orientation_identifier",
            "definition",
            "synonyms",
            "content",
            "is_a",
            "part_of",
            "keyword",
            "gene_ontology",
            "annotation",
            "references",
            "links",
        ]
        read_only_fields = [
            "accession",
            "location_identifier",
            "topology_identifier",
            "orientation_identifier",
            "definition",
            "synonyms",
            "content",
            "is_a",
            "part_of",
            "keyword",
            "gene_ontology",
            "annotation",
            "references",
            "links",
        ]


class MSUniqueVocabulariesSerializer(serializers.ModelSerializer):
    """Serializer for MSUniqueVocabularies model."""

    class Meta:
        model = MSUniqueVocabularies
        fields = ["accession", "name", "definition", "term_type"]
        read_only_fields = ["accession", "name", "definition", "term_type"]


class UnimodSerializer(serializers.ModelSerializer):
    """Serializer for Unimod model."""

    class Meta:
        model = Unimod
        fields = ["accession", "name", "definition", "additional_data"]
        read_only_fields = ["accession", "name", "definition", "additional_data"]


class MetadataColumnTemplateSerializer(serializers.ModelSerializer):
    """Serializer for MetadataColumnTemplate model."""

    owner_username = serializers.CharField(source="owner.username", read_only=True)
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = MetadataColumnTemplate
        fields = [
            "id",
            "name",
            "description",
            "column_name",
            "column_type",
            "default_value",
            "default_position",
            "ontology_type",
            "custom_ontology_filters",
            "enable_typeahead",
            "excel_validation",
            "custom_validation_rules",
            "api_enhancements",
            "visibility",
            "owner",
            "owner_username",
            "lab_group",
            "lab_group_name",
            "is_system_template",
            "is_active",
            "usage_count",
            "tags",
            "category",
            "created_at",
            "updated_at",
            "last_used_at",
            "can_edit",
            "can_delete",
        ]
        read_only_fields = [
            "owner",
            "owner_username",
            "usage_count",
            "created_at",
            "updated_at",
            "last_used_at",
            "can_edit",
            "can_delete",
            "base_column",
        ]

    def get_can_edit(self, obj):
        """Check if current user can edit this template."""
        request = self.context.get("request")
        if request and request.user:
            return obj.can_edit(request.user)
        return False

    def get_can_delete(self, obj):
        """Check if current user can delete this template."""
        request = self.context.get("request")
        if request and request.user:
            return obj.can_delete(request.user)
        return False

    def validate(self, attrs):
        """Custom validation for template data."""
        # Validate visibility and lab_group relationship
        visibility = attrs.get("visibility", self.instance.visibility if self.instance else "private")
        lab_group = attrs.get("lab_group", self.instance.lab_group if self.instance else None)

        if visibility == "lab_group" and not lab_group:
            raise serializers.ValidationError({"lab_group": "Lab group is required when visibility is 'lab_group'"})

        if visibility == "global":
            request = self.context.get("request")
            if not (request and request.user and request.user.is_staff):
                raise serializers.ValidationError({"visibility": "Only staff can create global templates"})

        return attrs

    def create(self, validated_data):
        """Create a new template with proper creator assignment."""
        request = self.context.get("request")
        if request and request.user:
            validated_data["owner"] = request.user

        # Set is_system_template for global templates created by staff
        if validated_data.get("visibility") == "global":
            validated_data["is_system_template"] = True

        return super().create(validated_data)


class MetadataColumnTemplateShareSerializer(serializers.ModelSerializer):
    """Serializer for MetadataColumnTemplateShare model."""

    template_name = serializers.CharField(source="template.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    shared_by_username = serializers.CharField(source="shared_by.username", read_only=True)

    class Meta:
        model = MetadataColumnTemplateShare
        fields = [
            "id",
            "template",
            "template_name",
            "user",
            "user_username",
            "shared_by",
            "shared_by_username",
            "permission_level",
            "shared_at",
            "last_accessed_at",
        ]
        read_only_fields = [
            "template_name",
            "user_username",
            "shared_by",
            "shared_by_username",
            "shared_at",
            "last_accessed_at",
        ]

    def create(self, validated_data):
        """Create a new template share with proper shared_by assignment."""
        request = self.context.get("request")
        if request and request.user:
            validated_data["shared_by"] = request.user
        return super().create(validated_data)


# ===================================================================
# COMPREHENSIVE ONTOLOGY SERIALIZERS FOR SDRF VALIDATION
# ===================================================================


class MondoDiseaseSerializer(serializers.ModelSerializer):
    """Serializer for MONDO Disease Ontology model."""

    synonyms_list = serializers.SerializerMethodField()
    parent_terms_list = serializers.SerializerMethodField()
    xrefs_list = serializers.SerializerMethodField()

    class Meta:
        model = MondoDisease
        fields = [
            "identifier",
            "name",
            "definition",
            "synonyms",
            "synonyms_list",
            "xrefs",
            "xrefs_list",
            "parent_terms",
            "parent_terms_list",
            "obsolete",
            "replacement_term",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_parent_terms_list(self, obj):
        """Return parent terms as a list."""
        return [s.strip() for s in obj.parent_terms.split(";") if s.strip()] if obj.parent_terms else []

    def get_xrefs_list(self, obj):
        """Return cross-references as a list."""
        return [s.strip() for s in obj.xrefs.split(";") if s.strip()] if obj.xrefs else []


class UberonAnatomySerializer(serializers.ModelSerializer):
    """Serializer for UBERON Anatomy Ontology model."""

    synonyms_list = serializers.SerializerMethodField()
    parent_terms_list = serializers.SerializerMethodField()
    part_of_list = serializers.SerializerMethodField()
    xrefs_list = serializers.SerializerMethodField()

    class Meta:
        model = UberonAnatomy
        fields = [
            "identifier",
            "name",
            "definition",
            "synonyms",
            "synonyms_list",
            "xrefs",
            "xrefs_list",
            "parent_terms",
            "parent_terms_list",
            "part_of",
            "part_of_list",
            "develops_from",
            "obsolete",
            "replacement_term",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_parent_terms_list(self, obj):
        """Return parent terms as a list."""
        return [s.strip() for s in obj.parent_terms.split(";") if s.strip()] if obj.parent_terms else []

    def get_part_of_list(self, obj):
        """Return part_of relationships as a list."""
        return [s.strip() for s in obj.part_of.split(";") if s.strip()] if obj.part_of else []

    def get_xrefs_list(self, obj):
        """Return cross-references as a list."""
        return [s.strip() for s in obj.xrefs.split(";") if s.strip()] if obj.xrefs else []


class NCBITaxonomySerializer(serializers.ModelSerializer):
    """Serializer for NCBI Taxonomy model."""

    synonyms_list = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = NCBITaxonomy
        fields = [
            "tax_id",
            "scientific_name",
            "common_name",
            "display_name",
            "synonyms",
            "synonyms_list",
            "rank",
            "parent_tax_id",
            "lineage",
            "genetic_code",
            "mitochondrial_genetic_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_display_name(self, obj):
        """Return formatted display name."""
        if obj.common_name:
            return f"{obj.scientific_name} ({obj.common_name})"
        return obj.scientific_name


class ChEBICompoundSerializer(serializers.ModelSerializer):
    """Serializer for ChEBI Compound model."""

    synonyms_list = serializers.SerializerMethodField()
    parent_terms_list = serializers.SerializerMethodField()
    roles_list = serializers.SerializerMethodField()

    class Meta:
        model = ChEBICompound
        fields = [
            "identifier",
            "name",
            "definition",
            "synonyms",
            "synonyms_list",
            "formula",
            "mass",
            "charge",
            "inchi",
            "smiles",
            "parent_terms",
            "parent_terms_list",
            "roles",
            "roles_list",
            "obsolete",
            "replacement_term",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_parent_terms_list(self, obj):
        """Return parent terms as a list."""
        return [s.strip() for s in obj.parent_terms.split(";") if s.strip()] if obj.parent_terms else []

    def get_roles_list(self, obj):
        """Return roles as a list."""
        return [s.strip() for s in obj.roles.split(";") if s.strip()] if obj.roles else []


class PSIMSOntologySerializer(serializers.ModelSerializer):
    """Serializer for PSI-MS Ontology model."""

    synonyms_list = serializers.SerializerMethodField()
    parent_terms_list = serializers.SerializerMethodField()

    class Meta:
        model = PSIMSOntology
        fields = [
            "identifier",
            "name",
            "definition",
            "synonyms",
            "synonyms_list",
            "parent_terms",
            "parent_terms_list",
            "category",
            "obsolete",
            "replacement_term",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_parent_terms_list(self, obj):
        """Return parent terms as a list."""
        return [s.strip() for s in obj.parent_terms.split(";") if s.strip()] if obj.parent_terms else []


class CellOntologySerializer(serializers.ModelSerializer):
    """Serializer for Cell Ontology model."""

    synonyms_list = serializers.SerializerMethodField()
    parent_terms_list = serializers.SerializerMethodField()
    part_of_list = serializers.SerializerMethodField()
    develops_from_list = serializers.SerializerMethodField()
    cell_type_display = serializers.SerializerMethodField()

    class Meta:
        model = CellOntology
        fields = [
            "identifier",
            "name",
            "definition",
            "synonyms",
            "synonyms_list",
            "accession",
            "cell_line",
            "cell_type_display",
            "organism",
            "tissue_origin",
            "disease_context",
            "parent_terms",
            "parent_terms_list",
            "part_of",
            "part_of_list",
            "develops_from",
            "develops_from_list",
            "source",
            "obsolete",
            "replacement_term",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_synonyms_list(self, obj):
        """Return synonyms as a list."""
        return [s.strip() for s in obj.synonyms.split(";") if s.strip()] if obj.synonyms else []

    def get_parent_terms_list(self, obj):
        """Return parent terms as a list."""
        return [s.strip() for s in obj.parent_terms.split(";") if s.strip()] if obj.parent_terms else []

    def get_part_of_list(self, obj):
        """Return part_of relationships as a list."""
        return [s.strip() for s in obj.part_of.split(";") if s.strip()] if obj.part_of else []

    def get_develops_from_list(self, obj):
        """Return develops_from relationships as a list."""
        return [s.strip() for s in obj.develops_from.split(";") if s.strip()] if obj.develops_from else []

    def get_cell_type_display(self, obj):
        """Return human-readable cell type."""
        return "Cell Line" if obj.cell_line else "Cell Type"


# ===================================================================
# ONTOLOGY SUGGESTION SERIALIZERS FOR SDRF VALIDATION
# ===================================================================


# ===================================================================
# SITE CONFIGURATION SERIALIZERS
# ===================================================================


# ===================================================================
# SCHEMA SERIALIZERS
# ===================================================================


class SchemaSerializer(serializers.ModelSerializer):
    """Serializer for Schema model."""

    creator_username = serializers.CharField(source="creator.username", read_only=True)
    file_size_kb = serializers.SerializerMethodField()
    schema_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Schema
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "schema_file",
            "schema_file_url",
            "is_builtin",
            "tags",
            "file_size",
            "file_size_kb",
            "file_hash",
            "usage_count",
            "creator",
            "creator_username",
            "is_active",
            "is_public",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "file_size",
            "file_hash",
            "usage_count",
            "created_at",
            "updated_at",
        ]

    def get_file_size_kb(self, obj):
        """Return file size in KB."""
        if obj.file_size:
            return round(obj.file_size / 1024, 1)
        return 0

    def get_schema_file_url(self, obj):
        """Return the URL for the schema file."""
        if obj.schema_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.schema_file.url)
            return obj.schema_file.url
        return None


class OntologySuggestionSerializer(serializers.Serializer):
    """Serializer for ontology suggestions with correct field mappings per ontology type."""

    id = serializers.CharField()
    value = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    ontology_type = serializers.CharField()
    full_data = serializers.DictField(required=False)

    def to_representation(self, instance):
        """Convert raw ontology model data to standardized suggestion format with full dictionary."""
        if isinstance(instance, dict):
            data = instance
        else:
            data = {field.name: getattr(instance, field.name) for field in instance._meta.fields}

        ontology_type = self.context.get("ontology_type", "unknown")

        # Map fields based on actual model fields and convert_sdrf_to_metadata logic
        if ontology_type == "species":
            return {
                "id": str(data.get("taxon") or data.get("code", "")),
                "value": data.get("official_name", ""),  # Species uses official_name as value
                "display_name": data.get("official_name", "")
                or data.get("official_name", ""),  # Use common_name for display
                "description": data.get("official_name", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "code": data.get("code", ""),
                    "taxon": data.get("taxon", ""),
                    "official_name": data.get("official_name", ""),
                    "common_name": data.get("common_name", ""),
                    "synonym": data.get("synonym", ""),
                },
            }

        elif ontology_type == "tissue":
            return {
                "id": data.get("accession", ""),
                "value": data.get("identifier", ""),  # Uses identifier as value (NT field)
                "display_name": data.get("identifier", ""),  # Keep original identifier as display_name
                "description": data.get("synonyms", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "accession": data.get("accession", ""),
                    "synonyms": data.get("synonyms", ""),
                    "cross_references": data.get("cross_references", ""),
                },
            }

        elif ontology_type == "human_disease":
            return {
                "id": data.get("accession", ""),  # accession contains the code (MONDO:0007254)
                "value": data.get("identifier", ""),  # identifier contains the name (breast carcinoma)
                "display_name": data.get("identifier", ""),  # identifier contains the human readable name
                "description": data.get("definition", "") or data.get("synonyms", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "acronym": data.get("acronym", ""),
                    "accession": data.get("accession", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "cross_references": data.get("cross_references", ""),
                    "keywords": data.get("keywords", ""),
                },
            }

        elif ontology_type == "subcellular_location":
            return {
                "id": data.get("accession", ""),
                "value": data.get("location_identifier", "") or data.get("accession", ""),
                "display_name": data.get("location_identifier", "") or data.get("accession", ""),
                "description": data.get("definition", "") or data.get("synonyms", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "location_identifier": data.get("location_identifier", ""),
                    "topology_identifier": data.get("topology_identifier", ""),
                    "orientation_identifier": data.get("orientation_identifier", ""),
                    "accession": data.get("accession", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                },
            }

        elif ontology_type == "unimod":
            # Unpack additional_data for Unimod entries
            additional_data = data.get("additional_data", [])
            general_data = {}
            specs = {}

            # Parse additional_data to extract key information
            if additional_data:
                for item in additional_data:
                    key = item.get("id", "")
                    value = item.get("description", "")

                    # Check if this is a spec-specific field (spec_<number>_<field>)
                    if key.startswith("spec_") and "_" in key[5:]:
                        parts = key.split("_", 2)  # Split into ['spec', '<number>', '<field>']
                        if len(parts) >= 3:
                            spec_num = parts[1]
                            field_name = parts[2]

                            # Initialize spec dictionary if it doesn't exist
                            if spec_num not in specs:
                                specs[spec_num] = {}

                            specs[spec_num][field_name] = value
                    else:
                        # General modification properties
                        general_data[key] = value

            return {
                "id": data.get("accession", ""),
                "value": data.get("accession", ""),  # Unimod uses accession
                "display_name": data.get("name", ""),  # Keep original name as display_name
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "accession": data.get("accession", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "additional_data": additional_data,  # Raw additional data
                    "general_properties": general_data,  # Non-spec specific data
                    "specifications": specs,  # Grouped spec data by number
                    # Direct access to key modification properties
                    "delta_mono_mass": general_data.get("delta_mono_mass", ""),
                    "delta_avge_mass": general_data.get("delta_avge_mass", ""),
                    "delta_composition": general_data.get("delta_composition", ""),
                    "record_id": general_data.get("record_id", ""),
                    "date_posted": general_data.get("date_time_posted", ""),
                    "date_modified": general_data.get("date_time_modified", ""),
                    "approved": general_data.get("approved", ""),
                },
            }

        elif ontology_type in ["ms_unique_vocabularies", "ms_terms"]:
            return {
                "id": data.get("accession", ""),
                "value": data.get("accession", ""),  # MS terms use accession for label fields
                "display_name": data.get("name", ""),  # Keep original name as display_name
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "accession": data.get("accession", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "term_type": data.get("term_type", ""),
                },
            }

        elif ontology_type == "ncbi_taxonomy":
            return {
                "id": str(data.get("tax_id", "")),
                "value": data.get("scientific_name", ""),
                "display_name": data.get("scientific_name", ""),
                "description": data.get("common_name", "") or data.get("synonyms", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "tax_id": data.get("tax_id", ""),
                    "scientific_name": data.get("scientific_name", ""),
                    "common_name": data.get("common_name", ""),
                    "synonyms": data.get("synonyms", ""),
                    "rank": data.get("rank", ""),
                    "division": data.get("division", ""),
                },
            }

        elif ontology_type == "chebi":
            return {
                "id": data.get("identifier", ""),  # CHEBI:XXXXXXX
                "value": data.get("identifier", ""),
                "display_name": data.get("name", ""),  # Keep original name as display_name
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "formula": data.get("formula", ""),
                    "mass": data.get("mass", ""),
                    "charge": data.get("charge", ""),
                    "inchi": data.get("inchi", ""),
                    "smiles": data.get("smiles", ""),
                    "parent_terms": data.get("parent_terms", ""),
                    "roles": data.get("roles", ""),
                },
            }

        elif ontology_type == "mondo":
            return {
                "id": data.get("identifier", ""),  # MONDO:XXXXXXX
                "value": data.get("identifier", ""),
                "display_name": data.get("name", ""),  # Keep original name as display_name
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "xrefs": data.get("xrefs", ""),
                    "parent_terms": data.get("parent_terms", ""),
                    "obsolete": data.get("obsolete", False),
                    "replacement_term": data.get("replacement_term", ""),
                },
            }

        elif ontology_type == "uberon":
            return {
                "id": data.get("identifier", ""),  # UBERON:XXXXXXX
                "value": data.get("identifier", ""),
                "display_name": data.get("name", ""),
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "xrefs": data.get("xrefs", ""),
                    "parent_terms": data.get("parent_terms", ""),
                    "part_of": data.get("part_of", ""),
                    "develops_from": data.get("develops_from", ""),
                    "obsolete": data.get("obsolete", False),
                    "replacement_term": data.get("replacement_term", ""),
                },
            }

        elif ontology_type in ["cell_ontology", "cellosaurus"]:
            return {
                "id": data.get("identifier", ""),
                "value": data.get("identifier", ""),
                "display_name": data.get("name", ""),
                "description": data.get("definition", "") or data.get("organism", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "organism": data.get("organism", ""),
                    "category": data.get("category", ""),
                    "xrefs": data.get("xrefs", ""),
                    "parent_terms": data.get("parent_terms", ""),
                    "obsolete": data.get("obsolete", False),
                },
            }

        elif ontology_type == "psi_ms":
            return {
                "id": data.get("identifier", ""),  # MS:XXXXXXX
                "value": data.get("identifier", ""),
                "display_name": data.get("name", ""),  # Keep original name as display_name
                "description": data.get("definition", "") or "",
                "ontology_type": ontology_type,
                "full_data": {
                    "identifier": data.get("identifier", ""),
                    "name": data.get("name", ""),
                    "definition": data.get("definition", ""),
                    "synonyms": data.get("synonyms", ""),
                    "xrefs": data.get("xrefs", ""),
                    "parent_terms": data.get("parent_terms", ""),
                    "is_obsolete": data.get("is_obsolete", False),
                },
            }

        else:
            # Generic fallback
            return {
                "id": str(data.get("accession") or data.get("identifier") or data.get("id", "")),
                "value": data.get("accession") or data.get("identifier") or data.get("name", ""),
                "display_name": data.get("name") or data.get("identifier") or data.get("accession", ""),
                "description": data.get("definition", "") or data.get("description", "") or "",
                "ontology_type": ontology_type,
                "full_data": data,  # Return all available data for unknown types
            }


class AsyncTaskStatusSerializer(serializers.ModelSerializer):
    """Serializer for AsyncTaskStatus model."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    duration = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = AsyncTaskStatus
        fields = [
            "id",
            "task_type",
            "task_type_display",
            "status",
            "status_display",
            "user",
            "user_username",
            "metadata_table",
            "metadata_table_name",
            "parameters",
            "result",
            "progress_current",
            "progress_total",
            "progress_percentage",
            "progress_description",
            "created_at",
            "started_at",
            "completed_at",
            "duration",
            "error_message",
            "rq_job_id",
            "queue_name",
        ]
        read_only_fields = [
            "id",
            "user_username",
            "created_at",
            "started_at",
            "completed_at",
            "duration",
            "progress_percentage",
            "task_type_display",
            "status_display",
            "metadata_table_name",
        ]

    def get_duration(self, obj):
        """Return task duration in seconds."""
        return obj.duration

    def get_progress_percentage(self, obj):
        """Return progress as percentage."""
        return obj.progress_percentage


class AsyncTaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing async tasks."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    duration = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = AsyncTaskStatus
        fields = [
            "id",
            "task_type",
            "task_type_display",
            "status",
            "status_display",
            "user",
            "user_username",
            "metadata_table",
            "metadata_table_name",
            "progress_percentage",
            "progress_description",
            "created_at",
            "started_at",
            "completed_at",
            "duration",
            "error_message",
        ]
        read_only_fields = [
            "id",
            "user_username",
            "task_type",
            "task_type_display",
            "status",
            "status_display",
            "metadata_table",
            "metadata_table_name",
            "progress_percentage",
            "progress_description",
            "created_at",
            "started_at",
            "completed_at",
            "duration",
            "error_message",
        ]

    def get_duration(self, obj):
        """Return task duration in seconds."""
        return obj.duration

    def get_progress_percentage(self, obj):
        """Return progress as percentage."""
        return obj.progress_percentage


class BulkExportSerializer(serializers.Serializer):
    """Serializer for bulk metadata export requests."""

    metadata_table_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=50,
        help_text="List of MetadataTable IDs to export (max 50 tables)",
    )
    include_pools = serializers.BooleanField(default=True, help_text="Whether to include sample pools in export")
    validate_sdrf = serializers.BooleanField(default=False, help_text="Whether to validate SDRF format")


class MetadataValidationSerializer(serializers.Serializer):
    """Serializer for metadata table validation requests."""

    metadata_table_id = serializers.IntegerField(help_text="ID of the metadata table to validate")
    validate_sdrf_format = serializers.BooleanField(
        default=True, help_text="Whether to validate SDRF format compliance"
    )
    validate_ontologies = serializers.BooleanField(default=True, help_text="Whether to validate ontology terms")
    validate_structure = serializers.BooleanField(default=True, help_text="Whether to validate table structure")
    include_pools = serializers.BooleanField(default=True, help_text="Whether to include sample pools in validation")
    async_processing = serializers.BooleanField(
        default=False, help_text="Whether to process the validation asynchronously via task queue"
    )

    def validate_metadata_table_id(self, value):
        """Validate that the metadata table exists."""
        try:
            MetadataTable.objects.get(id=value)
            return value
        except MetadataTable.DoesNotExist:
            raise serializers.ValidationError("Metadata table not found.")


class BulkExcelExportSerializer(serializers.Serializer):
    """Serializer for bulk Excel template export requests."""

    metadata_table_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=50,
        help_text="List of MetadataTable IDs to export (max 50 tables)",
    )
    metadata_column_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="Optional list of specific column IDs to export",
    )
    include_pools = serializers.BooleanField(default=True, help_text="Whether to include sample pools in export")
    lab_group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="Optional list of lab group IDs for favourites",
    )


class TaskCreateResponseSerializer(serializers.Serializer):
    """Serializer for task creation responses."""

    task_id = serializers.UUIDField(help_text="ID of the created task")
    message = serializers.CharField(help_text="Success message")


class SampleCountValidationSerializer(serializers.Serializer):
    """Serializer for validating sample count changes."""

    new_sample_count = serializers.IntegerField(min_value=0, help_text="New sample count for the table")


class SampleCountUpdateSerializer(serializers.Serializer):
    """Serializer for updating sample count with confirmation."""

    new_sample_count = serializers.IntegerField(min_value=0, help_text="New sample count for the table")
    confirmed = serializers.BooleanField(
        default=False, help_text="User confirmation that they understand data will be removed"
    )
