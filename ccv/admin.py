"""
Django Admin configuration for CUPCAKE Vanilla metadata models.
"""

from django.contrib import admin
from django.db import models

from simple_history.admin import SimpleHistoryAdmin

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


@admin.register(MetadataTable)
class MetadataTableAdmin(SimpleHistoryAdmin):
    """Admin interface for MetadataTable model."""

    list_display = [
        "name",
        "description",
        "sample_count",
        "get_column_count",
        "owner",
        "lab_group",
        "is_published",
        "is_locked",
        "created_at",
    ]
    list_filter = ["is_published", "is_locked", "lab_group", "owner", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["-created_at", "name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "description", "sample_count", "version")},
        ),
        ("Ownership", {"fields": ("owner", "lab_group", "visibility")}),
        ("Status", {"fields": ("is_locked", "is_published")}),
        (
            "Optional Association",
            {"fields": ("content_type", "object_id"), "classes": ("collapse",)},
        ),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(MetadataColumn)
class MetadataColumnAdmin(SimpleHistoryAdmin):
    """Admin interface for MetadataColumn model."""

    list_display = [
        "name",
        "type",
        "column_position",
        "value_preview",
        "mandatory",
        "hidden",
        "readonly",
        "metadata_table",
        "created_at",
    ]
    list_filter = [
        "type",
        "mandatory",
        "hidden",
        "readonly",
        "auto_generated",
        "not_applicable",
        "created_at",
        "metadata_table",
    ]
    search_fields = ["name", "type", "value"]
    ordering = ["column_position", "name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "type", "column_position", "value", "not_applicable")},
        ),
        (
            "Configuration",
            {"fields": ("mandatory", "hidden", "auto_generated", "readonly")},
        ),
        (
            "Advanced",
            {"fields": ("modifiers", "metadata_table"), "classes": ("collapse",)},
        ),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def value_preview(self, obj):
        """Display a truncated preview of the value."""
        if obj.value:
            return (obj.value[:50] + "...") if len(obj.value) > 50 else obj.value
        return "-"

    value_preview.short_description = "Value"

    # Removed content_object_link - now using metadata_table directly


@admin.register(SamplePool)
class SamplePoolAdmin(SimpleHistoryAdmin):
    """Admin interface for SamplePool model."""

    list_display = [
        "pool_name",
        "total_samples",
        "is_reference",
        "metadata_table",
        "created_at",
    ]
    list_filter = ["is_reference", "created_at", "metadata_table"]
    search_fields = ["pool_name", "pool_description"]
    ordering = ["pool_name"]
    readonly_fields = ["created_at", "updated_at", "sdrf_value"]

    fieldsets = (
        ("Basic Information", {"fields": ("pool_name", "pool_description")}),
        (
            "Pool Composition",
            {"fields": ("pooled_only_samples", "pooled_and_independent_samples")},
        ),
        (
            "SDRF Metadata",
            {"fields": ("is_reference", "sdrf_value"), "classes": ("collapse",)},
        ),
        ("Association", {"fields": ("metadata_table",), "classes": ("collapse",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def total_samples(self, obj):
        """Display the total number of samples in the pool."""
        return obj.get_total_samples()

    total_samples.short_description = "Total Samples"

    # Removed content_object_link - now using metadata_table directly


@admin.register(MetadataTableTemplate)
class MetadataTableTemplateAdmin(SimpleHistoryAdmin):
    """Admin interface for MetadataTableTemplate model."""

    list_display = [
        "name",
        "owner",
        "lab_group",
        "column_count",
        "visibility",
        "is_default",
        "created_at",
    ]
    list_filter = ["visibility", "is_default", "created_at", "owner", "lab_group"]
    search_fields = ["name", "description"]
    ordering = ["-is_default", "name"]
    readonly_fields = ["created_at", "updated_at"]
    filter_horizontal = ["user_columns"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "owner", "lab_group", "visibility")}),
        ("Template Configuration", {"fields": ("user_columns", "field_mask_mapping")}),
        ("Settings", {"fields": ("is_default",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def column_count(self, obj):
        """Display the number of columns in the template."""
        return obj.user_columns.count()

    column_count.short_description = "Column Count"


@admin.register(FavouriteMetadataOption)
class FavouriteMetadataOptionAdmin(SimpleHistoryAdmin):
    """Admin interface for FavouriteMetadataOption model."""

    list_display = [
        "name",
        "type",
        "display_value_preview",
        "user",
        "lab_group",
        "is_global",
        "created_at",
    ]
    list_filter = ["type", "is_global", "lab_group", "user", "created_at"]
    search_fields = ["name", "type", "value", "display_value"]
    ordering = ["name", "type"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Metadata Information", {"fields": ("name", "type")}),
        ("Option Configuration", {"fields": ("value", "display_value")}),
        ("Scope", {"fields": ("user", "lab_group", "is_global")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def display_value_preview(self, obj):
        """Display a preview of the display value or value."""
        value = obj.display_value or obj.value
        if value:
            return (value[:50] + "...") if len(value) > 50 else value
        return "-"

    display_value_preview.short_description = "Display Value"


# ===================================================================
# ONTOLOGY AND CONTROLLED VOCABULARY ADMIN
# ===================================================================


@admin.register(Species)
class SpeciesAdmin(admin.ModelAdmin):
    """Admin interface for Species model."""

    list_display = ["code", "official_name", "common_name", "taxon"]
    list_filter = ["taxon"]
    search_fields = ["code", "official_name", "common_name", "synonym"]
    ordering = ["official_name"]
    readonly_fields = []

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("code", "official_name", "common_name", "synonym")},
        ),
        ("Taxonomy", {"fields": ("taxon",)}),
    )


@admin.register(Tissue)
class TissueAdmin(admin.ModelAdmin):
    """Admin interface for Tissue model."""

    list_display = ["identifier", "accession", "synonyms_preview"]
    search_fields = ["identifier", "accession", "synonyms"]
    ordering = ["identifier"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "accession")}),
        (
            "Additional Data",
            {"fields": ("synonyms", "cross_references"), "classes": ("collapse",)},
        ),
    )

    def synonyms_preview(self, obj):
        """Display a truncated preview of synonyms."""
        if obj.synonyms:
            return (obj.synonyms[:50] + "...") if len(obj.synonyms) > 50 else obj.synonyms
        return "-"

    synonyms_preview.short_description = "Synonyms"


@admin.register(HumanDisease)
class HumanDiseaseAdmin(admin.ModelAdmin):
    """Admin interface for HumanDisease model."""

    list_display = ["identifier", "acronym", "accession", "definition_preview"]
    list_filter = ["acronym"]
    search_fields = ["identifier", "acronym", "accession", "definition", "synonyms"]
    ordering = ["identifier"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "acronym", "accession")}),
        ("Description", {"fields": ("definition", "synonyms")}),
        (
            "Additional Data",
            {"fields": ("cross_references", "keywords"), "classes": ("collapse",)},
        ),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(SubcellularLocation)
class SubcellularLocationAdmin(admin.ModelAdmin):
    """Admin interface for SubcellularLocation model."""

    list_display = ["accession", "location_identifier", "definition_preview"]
    search_fields = ["accession", "location_identifier", "definition", "synonyms"]
    ordering = ["accession"]

    fieldsets = (
        (
            "Identifiers",
            {
                "fields": (
                    "accession",
                    "location_identifier",
                    "topology_identifier",
                    "orientation_identifier",
                )
            },
        ),
        ("Description", {"fields": ("definition", "synonyms", "content")}),
        ("Relationships", {"fields": ("is_a", "part_of"), "classes": ("collapse",)}),
        (
            "Additional Data",
            {
                "fields": (
                    "keyword",
                    "gene_ontology",
                    "annotation",
                    "references",
                    "links",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:80] + "...") if len(obj.definition) > 80 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(MSUniqueVocabularies)
class MSUniqueVocabulariesAdmin(admin.ModelAdmin):
    """Admin interface for MSUniqueVocabularies model."""

    list_display = ["accession", "name", "term_type", "definition_preview"]
    list_filter = ["term_type"]
    search_fields = ["accession", "name", "definition"]
    ordering = ["accession"]

    fieldsets = (
        ("Basic Information", {"fields": ("accession", "name", "term_type")}),
        ("Description", {"fields": ("definition",)}),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(Unimod)
class UnimodAdmin(admin.ModelAdmin):
    """Admin interface for Unimod model."""

    list_display = ["accession", "name", "definition_preview", "has_additional_data"]
    search_fields = ["accession", "name", "definition"]
    ordering = ["accession"]

    fieldsets = (
        ("Basic Information", {"fields": ("accession", "name")}),
        ("Description", {"fields": ("definition",)}),
        ("Additional Data", {"fields": ("additional_data",), "classes": ("collapse",)}),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"

    def has_additional_data(self, obj):
        """Show whether additional data exists."""
        return bool(obj.additional_data)

    has_additional_data.boolean = True
    has_additional_data.short_description = "Has Additional Data"


# ===================================================================
# NEW COMPREHENSIVE ONTOLOGY ADMIN
# ===================================================================


@admin.register(MondoDisease)
class MondoDiseaseAdmin(admin.ModelAdmin):
    """Admin interface for MONDO Disease Ontology."""

    list_display = ["identifier", "name", "obsolete", "definition_preview", "created_at"]
    list_filter = ["obsolete", "created_at"]
    search_fields = ["identifier", "name", "definition", "synonyms"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "name", "definition")}),
        ("Relationships", {"fields": ("synonyms", "xrefs", "parent_terms")}),
        ("Status", {"fields": ("obsolete", "replacement_term")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(UberonAnatomy)
class UberonAnatomyAdmin(admin.ModelAdmin):
    """Admin interface for UBERON Anatomy Ontology."""

    list_display = ["identifier", "name", "obsolete", "definition_preview", "created_at"]
    list_filter = ["obsolete", "created_at"]
    search_fields = ["identifier", "name", "definition", "synonyms"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "name", "definition")}),
        ("Relationships", {"fields": ("synonyms", "xrefs", "parent_terms", "part_of", "develops_from")}),
        ("Status", {"fields": ("obsolete", "replacement_term")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(NCBITaxonomy)
class NCBITaxonomyAdmin(admin.ModelAdmin):
    """Admin interface for NCBI Taxonomy."""

    list_display = ["tax_id", "scientific_name", "common_name", "rank", "created_at"]
    list_filter = ["rank", "created_at"]
    search_fields = ["tax_id", "scientific_name", "common_name", "synonyms"]
    ordering = ["scientific_name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("tax_id", "scientific_name", "common_name", "synonyms")}),
        ("Taxonomy", {"fields": ("rank", "parent_tax_id", "lineage")}),
        ("Genetics", {"fields": ("genetic_code", "mitochondrial_genetic_code")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(ChEBICompound)
class ChEBICompoundAdmin(admin.ModelAdmin):
    """Admin interface for ChEBI Chemical Compounds."""

    list_display = ["identifier", "name", "formula", "mass", "charge", "has_structure", "obsolete", "created_at"]
    list_filter = ["obsolete", "charge", "created_at"]
    search_fields = ["identifier", "name", "definition", "synonyms", "formula", "roles"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "name", "definition", "synonyms")}),
        ("Chemical Properties", {"fields": ("formula", "mass", "charge")}),
        ("Structure Information", {"fields": ("inchi", "smiles"), "classes": ("collapse",)}),
        ("Relationships", {"fields": ("parent_terms", "roles")}),
        ("Status", {"fields": ("obsolete", "replacement_term")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def has_structure(self, obj):
        """Show whether compound has structural information."""
        return bool(obj.inchi or obj.smiles)

    has_structure.boolean = True
    has_structure.short_description = "Has Structure"


@admin.register(PSIMSOntology)
class PSIMSOntologyAdmin(admin.ModelAdmin):
    """Admin interface for PSI-MS Ontology."""

    list_display = ["identifier", "name", "category", "obsolete", "definition_preview", "created_at"]
    list_filter = ["category", "obsolete", "created_at"]
    search_fields = ["identifier", "name", "definition", "synonyms", "category"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "name", "definition", "category")}),
        ("Relationships", {"fields": ("synonyms", "parent_terms")}),
        ("Status", {"fields": ("obsolete", "replacement_term")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def definition_preview(self, obj):
        """Display a truncated preview of the definition."""
        if obj.definition:
            return (obj.definition[:100] + "...") if len(obj.definition) > 100 else obj.definition
        return "-"

    definition_preview.short_description = "Definition"


@admin.register(CellOntology)
class CellOntologyAdmin(admin.ModelAdmin):
    """Admin interface for Cell Ontology."""

    list_display = ["identifier", "name", "cell_line", "organism", "source", "obsolete", "created_at"]
    list_filter = ["cell_line", "source", "obsolete", "organism", "created_at"]
    search_fields = ["identifier", "name", "synonyms", "organism", "tissue_origin", "disease_context"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("identifier", "name", "definition", "synonyms")}),
        ("Cell Classification", {"fields": ("cell_line", "source", "accession")}),
        ("Biological Context", {"fields": ("organism", "tissue_origin", "disease_context")}),
        ("Relationships", {"fields": ("parent_terms", "part_of", "develops_from")}),
        ("Status", {"fields": ("obsolete", "replacement_term")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_list_display(self, request):
        """Customize list display based on user preferences."""
        base_display = list(self.list_display)
        # Could add user-specific customizations here
        return base_display


@admin.register(MetadataColumnTemplate)
class MetadataColumnTemplateAdmin(admin.ModelAdmin):
    """Admin interface for MetadataColumnTemplate model."""

    list_display = [
        "name",
        "column_name",
        "column_type",
        "ontology_type",
        "schema",
        "visibility",
        "owner",
        "lab_group",
        "usage_count",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "visibility",
        "ontology_type",
        "schema",
        "is_active",
        "is_system_template",
        "enable_typeahead",
        "excel_validation",
        "created_at",
    ]
    search_fields = [
        "name",
        "description",
        "column_name",
        "creator__username",
        "lab_group__name",
        "tags",
        "category",
    ]
    ordering = ["-usage_count", "name"]
    readonly_fields = ["usage_count", "last_used_at", "created_at", "updated_at"]

    fieldsets = (
        (
            "Template Information",
            {
                "fields": (
                    "name",
                    "description",
                    "category",
                    "tags",
                )
            },
        ),
        (
            "Column Configuration",
            {
                "fields": (
                    "column_name",
                    "column_type",
                    "default_value",
                    "default_position",
                )
            },
        ),
        (
            "Ontology Settings",
            {
                "fields": (
                    "ontology_type",
                    "custom_ontology_filters",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Enhancements",
            {
                "fields": (
                    "enable_typeahead",
                    "excel_validation",
                    "custom_validation_rules",
                    "api_enhancements",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Schema Association",
            {
                "fields": (
                    "schema",
                    "source_schema",
                )
            },
        ),
        (
            "Access & Sharing",
            {
                "fields": (
                    "visibility",
                    "owner",
                    "lab_group",
                    "is_system_template",
                    "is_active",
                )
            },
        ),
        (
            "Usage Statistics",
            {
                "fields": (
                    "usage_count",
                    "last_used_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        """Make owner readonly for existing objects."""
        readonly_fields = list(self.readonly_fields)
        if obj:  # Editing existing object
            readonly_fields.append("owner")
        return readonly_fields

    def save_model(self, request, obj, form, change):
        """Set owner when creating new templates."""
        if not change:  # Creating new object
            obj.owner = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Filter templates based on user permissions for non-superusers."""
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            # Show only templates the user can view
            queryset = queryset.filter(
                models.Q(creator=request.user)
                | models.Q(visibility__in=["public", "global"])
                | models.Q(visibility="lab_group", lab_group__members=request.user)
                | models.Q(shared_with_users=request.user)
            ).distinct()
        return queryset


@admin.register(MetadataColumnTemplateShare)
class MetadataColumnTemplateShareAdmin(admin.ModelAdmin):
    """Admin interface for MetadataColumnTemplateShare model."""

    list_display = [
        "template",
        "user",
        "permission_level",
        "shared_by",
        "shared_at",
        "last_accessed_at",
    ]
    list_filter = [
        "permission_level",
        "shared_at",
        "last_accessed_at",
    ]
    search_fields = [
        "template__name",
        "user__username",
        "shared_by__username",
    ]
    ordering = ["-shared_at"]
    readonly_fields = ["shared_at", "last_accessed_at"]

    fieldsets = (
        (
            "Share Information",
            {
                "fields": (
                    "template",
                    "user",
                    "permission_level",
                )
            },
        ),
        (
            "Sharing Details",
            {
                "fields": (
                    "shared_by",
                    "shared_at",
                    "last_accessed_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        """Make shared_by readonly for existing objects."""
        readonly_fields = list(self.readonly_fields)
        if obj:  # Editing existing object
            readonly_fields.append("shared_by")
        return readonly_fields

    def save_model(self, request, obj, form, change):
        """Set shared_by when creating new shares."""
        if not change:  # Creating new object
            obj.shared_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Filter shares based on user permissions for non-superusers."""
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            # Show only shares the user created or received
            queryset = queryset.filter(models.Q(shared_by=request.user) | models.Q(user=request.user))
        return queryset


@admin.register(Schema)
class SchemaAdmin(admin.ModelAdmin):
    """Admin interface for Schema model."""

    list_display = [
        "name",
        "display_name",
        "is_builtin",
        "is_active",
        "is_public",
        "usage_count",
        "file_size_kb",
        "creator",
        "created_at",
    ]
    list_filter = ["is_builtin", "is_active", "is_public", "tags", "created_at", "creator"]
    search_fields = ["name", "display_name", "description"]
    ordering = ["-is_builtin", "name"]
    readonly_fields = ["file_size", "file_hash", "usage_count", "created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "display_name", "description")}),
        ("Schema File", {"fields": ("schema_file", "file_size", "file_hash")}),
        ("Classification", {"fields": ("is_builtin", "tags")}),
        (
            "Availability Control",
            {
                "fields": ("is_active", "is_public"),
                "description": "Control whether this schema is available for creating templates. Only active schemas appear in the frontend dropdown.",
            },
        ),
        ("Ownership", {"fields": ("creator",)}),
        ("Statistics", {"fields": ("usage_count",), "classes": ("collapse",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def file_size_kb(self, obj):
        """Display file size in KB."""
        if obj.file_size:
            return f"{obj.file_size / 1024:.1f} KB"
        return "-"

    file_size_kb.short_description = "File Size"

    def save_model(self, request, obj, form, change):
        """Set creator for new schemas."""
        if not change and not obj.creator:
            obj.creator = request.user
        super().save_model(request, obj, form, change)

    actions = ["sync_builtin_schemas_action", "activate_schemas_action", "deactivate_schemas_action"]

    def sync_builtin_schemas_action(self, request, queryset):
        """Admin action to sync builtin schemas."""
        try:
            result = Schema.sync_builtin_schemas()
            if "error" in result:
                self.message_user(request, f"Error syncing schemas: {result['error']}", level="ERROR")
            else:
                created = result.get("created", 0)
                updated = result.get("updated", 0)
                self.message_user(
                    request, f"Schema sync completed: {created} created, {updated} updated", level="SUCCESS"
                )
        except Exception as e:
            self.message_user(request, f"Error during schema sync: {str(e)}", level="ERROR")

    sync_builtin_schemas_action.short_description = "Sync builtin schemas from sdrf-pipelines"

    def activate_schemas_action(self, request, queryset):
        """Admin action to activate selected schemas."""
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f"Activated {updated} schema(s). These schemas are now available for creating templates.",
            level="SUCCESS",
        )

    activate_schemas_action.short_description = "Activate selected schemas"

    def deactivate_schemas_action(self, request, queryset):
        """Admin action to deactivate selected schemas."""
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f"Deactivated {updated} schema(s). These schemas are no longer available for creating templates.",
            level="SUCCESS",
        )

    deactivate_schemas_action.short_description = "Deactivate selected schemas"


# Admin site customization
admin.site.site_header = "CUPCAKE Vanilla Administration"
admin.site.site_title = "CUPCAKE Vanilla Admin"
admin.site.index_title = "Metadata Management System"
