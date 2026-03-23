from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .forms import InstrumentAdminForm, StorageObjectAdminForm, StoredReagentAdminForm
from .models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentAnnotation,
    InstrumentJob,
    InstrumentJobAnnotation,
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
    list_display = [
        "instrument_name",
        "image_preview",
        "enabled",
        "accepts_bookings",
        "bookings_count",
        "jobs_count",
        "created_at",
    ]
    list_filter = ["enabled", "accepts_bookings", "is_vaulted", "created_at"]
    search_fields = ["instrument_name", "instrument_description"]
    readonly_fields = ["created_at", "updated_at", "image_preview"]
    autocomplete_fields = ["user"]
    list_per_page = 50

    fieldsets = (
        ("Basic Information", {"fields": ("instrument_name", "instrument_description", "image", "image_preview")}),
        ("Settings", {"fields": ("enabled", "accepts_bookings", "allow_overlapping_bookings")}),
        ("Ownership", {"fields": ("user", "is_vaulted")}),
        (
            "Notifications",
            {
                "fields": (
                    "days_before_warranty_notification",
                    "days_before_maintenance_notification",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def image_preview(self, obj):
        """Display thumbnail of instrument image in admin."""
        if obj.image and obj.image.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.image
            )
        return "No image"

    image_preview.short_description = "Image"

    def bookings_count(self, obj):
        """Display count of bookings."""
        count = obj.instrument_usage.count()
        if count > 0:
            url = reverse("admin:ccm_instrumentusage_changelist") + f"?instrument__id__exact={obj.id}"
            return format_html('<a href="{}">{}</a>', url, count)
        return "0"

    bookings_count.short_description = "Bookings"

    def jobs_count(self, obj):
        """Display count of jobs."""
        count = obj.jobs.count()
        if count > 0:
            url = reverse("admin:ccm_instrumentjob_changelist") + f"?instrument__id__exact={obj.id}"
            return format_html('<a href="{}">{}</a>', url, count)
        return "0"

    jobs_count.short_description = "Jobs"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("user")

    actions = ["enable_instruments", "disable_instruments", "enable_bookings", "disable_bookings"]

    def enable_instruments(self, request, queryset):
        """Enable selected instruments."""
        updated = queryset.update(enabled=True)
        self.message_user(request, f"Enabled {updated} instrument(s).")

    enable_instruments.short_description = "Enable selected instruments"

    def disable_instruments(self, request, queryset):
        """Disable selected instruments."""
        updated = queryset.update(enabled=False)
        self.message_user(request, f"Disabled {updated} instrument(s).")

    disable_instruments.short_description = "Disable selected instruments"

    def enable_bookings(self, request, queryset):
        """Enable bookings for selected instruments."""
        updated = queryset.update(accepts_bookings=True)
        self.message_user(request, f"Enabled bookings for {updated} instrument(s).")

    enable_bookings.short_description = "Enable bookings"

    def disable_bookings(self, request, queryset):
        """Disable bookings for selected instruments."""
        updated = queryset.update(accepts_bookings=False)
        self.message_user(request, f"Disabled bookings for {updated} instrument(s).")

    disable_bookings.short_description = "Disable bookings"


@admin.register(StorageObject)
class StorageObjectAdmin(admin.ModelAdmin):
    form = StorageObjectAdminForm
    list_display = [
        "object_name",
        "image_preview",
        "object_type",
        "stored_at",
        "reagents_count",
        "can_delete",
        "created_at",
    ]
    list_filter = ["object_type", "can_delete", "created_at"]
    search_fields = ["object_name", "object_description"]
    readonly_fields = ["created_at", "updated_at", "image_preview"]
    autocomplete_fields = ["stored_at"]
    list_per_page = 50

    fieldsets = (
        ("Basic Information", {"fields": ("object_name", "object_description", "object_type")}),
        ("Location", {"fields": ("stored_at",)}),
        ("Image", {"fields": ("png_base64", "image_preview")}),
        ("Settings", {"fields": ("can_delete",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def image_preview(self, obj):
        """Display thumbnail of storage object image in admin."""
        if obj.png_base64 and obj.png_base64.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.png_base64
            )
        return "No image"

    image_preview.short_description = "Image"

    def reagents_count(self, obj):
        """Display count of stored reagents."""
        count = obj.stored_reagents.count()
        if count > 0:
            url = reverse("admin:ccm_storedreagent_changelist") + f"?storage_object__id__exact={obj.id}"
            return format_html('<a href="{}">{}</a>', url, count)
        return "0"

    reagents_count.short_description = "Reagents"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("stored_at")


@admin.register(Reagent)
class ReagentAdmin(admin.ModelAdmin):
    list_display = ["name", "unit", "stored_count", "created_at"]
    search_fields = ["name", "unit"]
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 50

    fieldsets = (
        ("Reagent Information", {"fields": ("name", "unit")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def stored_count(self, obj):
        """Display count of stored instances."""
        count = obj.stored_reagents.count()
        if count > 0:
            url = reverse("admin:ccm_storedreagent_changelist") + f"?reagent__id__exact={obj.id}"
            return format_html('<a href="{}">{}</a>', url, count)
        return "0"

    stored_count.short_description = "Stored"


@admin.register(StoredReagent)
class StoredReagentAdmin(admin.ModelAdmin):
    form = StoredReagentAdminForm
    list_display = [
        "reagent",
        "storage_object",
        "quantity",
        "image_preview",
        "expiration_status",
        "low_stock_status",
        "shareable",
    ]
    list_filter = ["shareable", "notify_on_low_stock", "expiration_date", "created_at"]
    search_fields = ["reagent__name", "storage_object__object_name", "notes", "barcode"]
    readonly_fields = ["created_at", "updated_at", "last_notification_sent", "image_preview"]
    autocomplete_fields = ["reagent", "storage_object", "user"]
    list_per_page = 50
    date_hierarchy = "expiration_date"

    fieldsets = (
        ("Reagent Information", {"fields": ("reagent", "storage_object", "quantity", "barcode")}),
        ("Image", {"fields": ("png_base64", "image_preview")}),
        ("Expiration & Alerts", {"fields": ("expiration_date", "notify_on_low_stock", "low_stock_threshold")}),
        ("Sharing", {"fields": ("shareable",)}),
        ("Notes", {"fields": ("notes",)}),
        ("Ownership", {"fields": ("user",)}),
        ("Audit", {"fields": ("created_at", "updated_at", "last_notification_sent"), "classes": ("collapse",)}),
    )

    def image_preview(self, obj):
        """Display thumbnail of stored reagent image in admin."""
        if obj.png_base64 and obj.png_base64.startswith("data:image/"):
            return format_html(
                '<img src="{}" style="max-width: 50px; max-height: 50px; border: 1px solid #ddd;" />', obj.png_base64
            )
        return "No image"

    image_preview.short_description = "Image"

    def expiration_status(self, obj):
        """Display expiration status with color coding."""
        from django.utils import timezone

        if not obj.expiration_date:
            return "-"
        days_until = (obj.expiration_date - timezone.now().date()).days
        if days_until < 0:
            return format_html('<span style="color:red;">Expired</span>')
        elif days_until <= 30:
            return format_html('<span style="color:orange;">{} days</span>', days_until)
        else:
            return format_html('<span style="color:green;">{} days</span>', days_until)

    expiration_status.short_description = "Expires In"

    def low_stock_status(self, obj):
        """Display low stock warning."""
        if obj.notify_on_low_stock and obj.low_stock_threshold and obj.quantity <= obj.low_stock_threshold:
            return format_html('<span style="color:red;">LOW</span>')
        return "-"

    low_stock_status.short_description = "Stock"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("reagent", "storage_object", "user")


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
    list_display = ["instrument", "user", "time_started", "time_ended", "duration", "approved", "maintenance"]
    list_filter = ["approved", "maintenance", "time_started", "instrument"]
    search_fields = ["instrument__instrument_name", "user__username", "description"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["instrument", "user", "approved_by"]
    list_per_page = 50
    date_hierarchy = "time_started"

    fieldsets = (
        ("Booking Information", {"fields": ("instrument", "user")}),
        ("Time", {"fields": ("time_started", "time_ended", "usage_hours")}),
        ("Status", {"fields": ("approved", "approved_by", "maintenance")}),
        ("Details", {"fields": ("description",), "classes": ("collapse",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def duration(self, obj):
        """Display booking duration."""
        if obj.time_started and obj.time_ended:
            delta = obj.time_ended - obj.time_started
            hours = delta.total_seconds() / 3600
            return f"{hours:.1f}h"
        return "-"

    duration.short_description = "Duration"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("instrument", "user", "approved_by")

    actions = ["approve_bookings", "reject_bookings"]

    def approve_bookings(self, request, queryset):
        """Approve selected bookings."""
        updated = queryset.filter(approved=False).update(approved=True, approved_by=request.user)
        self.message_user(request, f"Approved {updated} booking(s).")

    approve_bookings.short_description = "Approve selected bookings"

    def reject_bookings(self, request, queryset):
        """Reject selected bookings."""
        updated = queryset.filter(approved=True).update(approved=False, approved_by=None)
        self.message_user(request, f"Rejected {updated} booking(s).")

    reject_bookings.short_description = "Reject selected bookings"


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
        "instrument",
        "instrument_usage",
        "metadata_table_template",
        "metadata_table",
        "stored_reagent",
    ]
    autocomplete_fields = ["user", "lab_group", "project", "staff"]

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


@admin.register(InstrumentJobAnnotation)
class InstrumentJobAnnotationAdmin(admin.ModelAdmin):
    list_display = ["instrument_job", "folder", "annotation", "order", "created_at"]
    list_filter = ["folder", "created_at"]
    search_fields = ["instrument_job__job_name", "annotation__file_name", "folder__folder_name"]
    raw_id_fields = ["instrument_job", "annotation", "folder"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["instrument_job", "folder", "order"]
