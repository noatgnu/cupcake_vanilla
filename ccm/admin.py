from django.contrib import admin
from django.utils.html import format_html

from .forms import InstrumentAdminForm, StorageObjectAdminForm, StoredReagentAdminForm
from .models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentAnnotation,
    InstrumentJob,
    InstrumentPermission,
    InstrumentUsage,
    MaintenanceLog,
    MaintenanceLogAnnotation,
    Reagent,
    ReagentAction,
    ReagentSubscription,
    StorageObject,
    StoredReagent,
    StoredReagentAnnotation,
    SupportInformation,
)


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    form = InstrumentAdminForm
    list_display = ["instrument_name", "image_preview", "enabled", "accepts_bookings", "created_at"]
    list_filter = ["enabled", "accepts_bookings", "created_at"]
    search_fields = ["instrument_name", "instrument_description"]
    readonly_fields = ["created_at", "updated_at", "image_preview"]

    def image_preview(self, obj):
        """Display thumbnail of instrument image in admin."""
        if obj.image and obj.image.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.image
            )
        return "No image"

    image_preview.short_description = "Image"


@admin.register(StorageObject)
class StorageObjectAdmin(admin.ModelAdmin):
    form = StorageObjectAdminForm
    list_display = ["object_name", "image_preview", "object_type", "stored_at", "can_delete", "created_at"]
    list_filter = ["object_type", "can_delete", "created_at"]
    search_fields = ["object_name", "object_description"]
    readonly_fields = ["created_at", "updated_at", "image_preview"]

    def image_preview(self, obj):
        """Display thumbnail of storage object image in admin."""
        if obj.png_base64 and obj.png_base64.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.png_base64
            )
        return "No image"

    image_preview.short_description = "Image"


@admin.register(Reagent)
class ReagentAdmin(admin.ModelAdmin):
    list_display = ["name", "unit", "created_at"]
    search_fields = ["name", "unit"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(StoredReagent)
class StoredReagentAdmin(admin.ModelAdmin):
    form = StoredReagentAdminForm
    list_display = ["reagent", "storage_object", "quantity", "image_preview", "expiration_date", "shareable"]
    list_filter = ["shareable", "notify_on_low_stock", "expiration_date", "created_at"]
    search_fields = ["reagent__name", "storage_object__object_name", "notes", "barcode"]
    readonly_fields = ["created_at", "updated_at", "last_notification_sent", "image_preview"]

    def image_preview(self, obj):
        """Display thumbnail of stored reagent image in admin."""
        if obj.png_base64 and obj.png_base64.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.png_base64
            )
        return "No image"

    image_preview.short_description = "Image"


@admin.register(ExternalContactDetails)
class ExternalContactDetailsAdmin(admin.ModelAdmin):
    list_display = ["contact_method_alt_name", "contact_type", "contact_value"]
    list_filter = ["contact_type"]
    search_fields = ["contact_method_alt_name", "contact_value"]


@admin.register(ExternalContact)
class ExternalContactAdmin(admin.ModelAdmin):
    list_display = ["contact_name", "user"]
    search_fields = ["contact_name"]


@admin.register(SupportInformation)
class SupportInformationAdmin(admin.ModelAdmin):
    list_display = ["manufacturer_name", "vendor_name", "serial_number", "warranty_end_date"]
    list_filter = ["warranty_start_date", "warranty_end_date"]
    search_fields = ["manufacturer_name", "vendor_name", "serial_number"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ReagentSubscription)
class ReagentSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "stored_reagent", "notify_on_low_stock", "notify_on_expiry", "created_at"]
    list_filter = ["notify_on_low_stock", "notify_on_expiry", "created_at"]
    search_fields = ["user__username", "stored_reagent__reagent__name"]
    readonly_fields = ["created_at"]


@admin.register(ReagentAction)
class ReagentActionAdmin(admin.ModelAdmin):
    list_display = ["action_type", "reagent", "quantity", "user", "session", "step", "created_at"]
    list_filter = ["action_type", "created_at"]
    search_fields = ["reagent__reagent__name", "user__username", "notes"]
    raw_id_fields = ["reagent", "user", "session", "step"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(InstrumentUsage)
class InstrumentUsageAdmin(admin.ModelAdmin):
    list_display = ["instrument", "user", "time_started", "time_ended", "approved", "maintenance"]
    list_filter = ["approved", "maintenance", "time_started"]
    search_fields = ["instrument__instrument_name", "user__username", "description"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ["instrument", "maintenance_type", "status", "maintenance_date", "created_by"]
    list_filter = ["maintenance_type", "status", "maintenance_date", "is_template"]
    search_fields = ["instrument__instrument_name", "maintenance_description", "maintenance_notes"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "maintenance_date"


@admin.register(InstrumentJob)
class InstrumentJobAdmin(admin.ModelAdmin):
    list_display = [
        "job_name_display",
        "instrument",
        "user",
        "lab_group",
        "project",
        "status",
        "job_type",
        "sample_number",
        "billing_hours",
        "created_at",
    ]
    list_filter = ["status", "job_type", "sample_type", "assigned", "lab_group", "created_at", "completed_at"]
    search_fields = [
        "job_name",
        "user__username",
        "user__email",
        "instrument__instrument_name",
        "lab_group__name",
        "project__project_name",
        "cost_center",
        "funder",
    ]
    raw_id_fields = [
        "user",
        "instrument",
        "instrument_usage",
        "lab_group",
        "project",
        "metadata_table_template",
        "metadata_table",
        "stored_reagent",
    ]
    filter_horizontal = ["staff", "user_annotations", "staff_annotations"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("job_name", "job_type", "status", "user", "instrument", "lab_group", "project")},
        ),
        (
            "Permissions",
            {"fields": ("permission_info",), "classes": ("collapse",)},
        ),
        ("Sample Information", {"fields": ("sample_number", "sample_type", "injection_volume", "injection_unit")}),
        (
            "Technical Details",
            {
                "fields": ("method", "location", "search_engine", "search_engine_version", "search_details"),
                "classes": ("collapse",),
            },
        ),
        (
            "Billing & Administrative",
            {
                "fields": ("cost_center", "funder"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("metadata_table_template", "metadata_table"),
                "classes": ("collapse",),
            },
        ),
        ("Staff Assignment", {"fields": ("assigned", "staff"), "classes": ("collapse",)}),
        (
            "Time Tracking",
            {
                "fields": (
                    "instrument_start_time",
                    "instrument_end_time",
                    "personnel_start_time",
                    "personnel_end_time",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Resources & Attachments",
            {
                "fields": ("instrument_usage", "stored_reagent", "user_annotations", "staff_annotations"),
                "classes": ("collapse",),
            },
        ),
        ("Timestamps", {"fields": ("submitted_at", "completed_at"), "classes": ("collapse",)}),
    )

    readonly_fields = ["created_at", "updated_at", "permission_info"]
    date_hierarchy = "created_at"

    def job_name_display(self, obj):
        """Display job name or fallback."""
        return obj.job_name or f"{obj.get_job_type_display()} Job #{obj.id}"

    job_name_display.short_description = "Job Name"

    def billing_hours(self, obj):
        """Display billing hours summary."""
        inst_hours = obj.instrument_hours
        pers_hours = obj.personnel_hours
        if inst_hours > 0 or pers_hours > 0:
            return f"I:{inst_hours:.1f}h P:{pers_hours:.1f}h"
        return "No time recorded"

    billing_hours.short_description = "Billing Hours (Instrument:Personnel)"

    def permission_info(self, obj):
        """Display permission information for the job."""
        if not obj.pk:
            return "Save job first to see permissions"

        info = []
        if obj.status == "draft":
            info.append(f"🔒 Draft - Only owner ({obj.user.username}) can edit")
        else:
            info.append(f"📝 {obj.get_status_display()}")
            editors = []
            if obj.lab_group:
                editors.append(f"Lab Group: {obj.lab_group.name}")
            if obj.staff.exists():
                staff_names = ", ".join([s.username for s in obj.staff.all()[:3]])
                if obj.staff.count() > 3:
                    staff_names += f" (+{obj.staff.count() - 3} more)"
                editors.append(f"Staff: {staff_names}")
            if editors:
                info.append("Can edit: " + " | ".join(editors))
            else:
                info.append("⚠️ No assigned staff or lab group")

        return format_html("<br>".join(info))

    permission_info.short_description = "Permissions"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "user",
                "instrument",
                "lab_group",
                "project",
                "metadata_table",
                "metadata_table_template",
                "stored_reagent",
            )
            .prefetch_related("staff")
        )


@admin.register(InstrumentPermission)
class InstrumentPermissionAdmin(admin.ModelAdmin):
    list_display = ["instrument", "user", "can_view", "can_book", "can_manage", "created_at"]
    list_filter = ["can_view", "can_book", "can_manage", "created_at"]
    search_fields = ["instrument__instrument_name", "user__username", "user__email"]
    raw_id_fields = ["instrument", "user"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(InstrumentAnnotation)
class InstrumentAnnotationAdmin(admin.ModelAdmin):
    list_display = ["instrument", "folder", "annotation", "order", "created_at"]
    list_filter = ["folder", "created_at"]
    search_fields = ["instrument__instrument_name", "annotation__file_name", "folder__folder_name"]
    raw_id_fields = ["instrument", "annotation", "folder"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["instrument", "folder", "order"]


@admin.register(StoredReagentAnnotation)
class StoredReagentAnnotationAdmin(admin.ModelAdmin):
    list_display = ["stored_reagent", "folder", "annotation", "order", "created_at"]
    list_filter = ["folder", "created_at"]
    search_fields = ["stored_reagent__reagent__name", "annotation__file_name", "folder__folder_name"]
    raw_id_fields = ["stored_reagent", "annotation", "folder"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["stored_reagent", "folder", "order"]


@admin.register(MaintenanceLogAnnotation)
class MaintenanceLogAnnotationAdmin(admin.ModelAdmin):
    list_display = ["maintenance_log", "annotation", "order", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["maintenance_log__maintenance_description", "annotation__file_name"]
    raw_id_fields = ["maintenance_log", "annotation"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["maintenance_log", "order"]
