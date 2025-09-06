"""
CUPCAKE Red Velvet (CCRV) Django Admin Configuration.

Comprehensive admin interface for project and protocol management models.
Provides intuitive interfaces for managing research projects, protocols,
sessions, and their relationships.
"""

from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Project,
    ProtocolModel,
    ProtocolRating,
    ProtocolReagent,
    ProtocolSection,
    ProtocolStep,
    Session,
    StepReagent,
    StepVariation,
    TimeKeeper,
)


class BaseResourceAdmin(SimpleHistoryAdmin):
    """Base admin class for AbstractResource models with common functionality."""

    readonly_fields = ["created_at", "updated_at", "remote_id", "remote_host"]

    def get_readonly_fields(self, request, obj=None):
        """Add unique_id to read-only fields if the model has it."""
        fields = list(self.readonly_fields)
        if hasattr(self.model, "_meta") and any(field.name == "unique_id" for field in self.model._meta.fields):
            if "unique_id" not in fields:
                fields.append("unique_id")
        return fields

    def owner_display(self, obj):
        """Display owner with link to user admin."""
        if obj.owner:
            url = reverse("admin:auth_user_change", args=[obj.owner.pk])
            return format_html('<a href="{}">{}</a>', url, obj.owner.get_full_name() or obj.owner.username)
        return "No owner"

    owner_display.short_description = "Owner"
    owner_display.admin_order_field = "owner"


@admin.register(Project)
class ProjectAdmin(BaseResourceAdmin):
    """Admin interface for research projects with comprehensive management features."""

    list_display = ["project_name", "owner_display", "is_vaulted", "sessions_count", "lab_group", "created_at"]
    list_filter = ["is_vaulted", "created_at", "updated_at", "lab_group", "remote_host"]
    search_fields = ["project_name", "project_description", "owner__username", "owner__first_name", "owner__last_name"]
    filter_horizontal = ["sessions"]

    fieldsets = (
        ("Project Information", {"fields": ("project_name", "project_description", "owner", "lab_group")}),
        ("Sessions", {"fields": ("sessions",), "description": "Experimental sessions associated with this project"}),
        ("System Information", {"fields": ("is_vaulted", "created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def sessions_count(self, obj):
        """Display count of associated sessions."""
        count = obj.sessions.count()
        if count > 0:
            url = reverse("admin:ccrv_session_changelist")
            return format_html('<a href="{}?projects__id__exact={}">{} sessions</a>', url, obj.id, count)
        return "0 sessions"

    sessions_count.short_description = "Sessions"

    def get_queryset(self, request):
        """Optimize queryset with select_related and prefetch_related."""
        return (
            super()
            .get_queryset(request)
            .select_related("owner", "lab_group", "remote_host")
            .prefetch_related("sessions", "editors", "viewers")
        )


@admin.register(ProtocolModel)
class ProtocolModelAdmin(BaseResourceAdmin):
    """Admin interface for lab protocols with protocols.io integration."""

    list_display = [
        "protocol_title",
        "owner_display",
        "enabled",
        "protocol_doi",
        "sections_count",
        "steps_count",
        "ratings_count",
    ]
    list_filter = ["enabled", "created_at", "updated_at", "lab_group", "protocol_created_on", "remote_host"]
    search_fields = [
        "protocol_title",
        "protocol_description",
        "protocol_doi",
        "owner__username",
        "owner__first_name",
        "owner__last_name",
    ]
    filter_horizontal = ["editors", "viewers"]

    fieldsets = (
        (
            "Protocol Information",
            {"fields": ("protocol_title", "protocol_description", "enabled", "owner", "lab_group")},
        ),
        (
            "Protocols.io Integration",
            {
                "fields": (
                    "protocol_id",
                    "protocol_doi",
                    "protocol_url",
                    "protocol_version_uri",
                    "protocol_created_on",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Permissions", {"fields": ("editors", "viewers"), "classes": ("collapse",)}),
        ("System Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def sections_count(self, obj):
        """Display count of protocol sections."""
        count = obj.sections.count()
        if count > 0:
            url = reverse("admin:ccrv_protocolsection_changelist")
            return format_html('<a href="{}?protocol__id__exact={}">{} sections</a>', url, obj.id, count)
        return "0 sections"

    sections_count.short_description = "Sections"

    def steps_count(self, obj):
        """Display count of protocol steps."""
        count = obj.steps.count()
        if count > 0:
            url = reverse("admin:ccrv_protocolstep_changelist")
            return format_html('<a href="{}?protocol__id__exact={}">{} steps</a>', url, obj.id, count)
        return "0 steps"

    steps_count.short_description = "Steps"

    def ratings_count(self, obj):
        """Display count of protocol ratings."""
        count = obj.ratings.count()
        if count > 0:
            url = reverse("admin:ccrv_protocolrating_changelist")
            return format_html('<a href="{}?protocol__id__exact={}">{} ratings</a>', url, obj.id, count)
        return "0 ratings"

    ratings_count.short_description = "Ratings"

    def get_queryset(self, request):
        """Optimize queryset with annotations."""
        return (
            super()
            .get_queryset(request)
            .select_related("owner", "lab_group", "remote_host")
            .prefetch_related("editors", "viewers")
            .annotate(sections_count=Count("sections"), steps_count=Count("steps"), ratings_count=Count("ratings"))
        )


@admin.register(Session)
class SessionAdmin(BaseResourceAdmin):
    """Admin interface for experimental sessions."""

    list_display = ["name", "owner_display", "enabled", "processing", "protocols_count", "duration", "created_at"]
    list_filter = ["enabled", "processing", "created_at", "updated_at", "started_at", "ended_at", "lab_group"]
    search_fields = ["name", "unique_id", "owner__username", "owner__first_name", "owner__last_name"]
    filter_horizontal = ["protocols", "editors", "viewers"]

    fieldsets = (
        ("Session Information", {"fields": ("name", "enabled", "processing", "owner", "lab_group")}),
        ("Protocols", {"fields": ("protocols",), "description": "Lab protocols used in this session"}),
        ("Time Tracking", {"fields": ("started_at", "ended_at"), "description": "Session timing information"}),
        ("Permissions", {"fields": ("editors", "viewers"), "classes": ("collapse",)}),
        ("System Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def protocols_count(self, obj):
        """Display count of associated protocols."""
        count = obj.protocols.count()
        if count > 0:
            url = reverse("admin:ccrv_protocolmodel_changelist")
            return format_html('<a href="{}?sessions__id__exact={}">{} protocols</a>', url, obj.id, count)
        return "0 protocols"

    protocols_count.short_description = "Protocols"

    def duration(self, obj):
        """Display session duration if available."""
        if obj.started_at and obj.ended_at:
            duration = obj.ended_at - obj.started_at
            return str(duration)
        elif obj.started_at:
            return "In progress"
        return "Not started"

    duration.short_description = "Duration"

    def get_queryset(self, request):
        """Optimize queryset with related data."""
        return (
            super()
            .get_queryset(request)
            .select_related("owner", "lab_group", "remote_host")
            .prefetch_related("protocols", "editors", "viewers")
        )


@admin.register(ProtocolRating)
class ProtocolRatingAdmin(SimpleHistoryAdmin):
    """Admin interface for protocol ratings and reviews."""

    list_display = ["protocol", "user", "complexity_rating", "duration_rating", "created_at"]
    list_filter = ["complexity_rating", "duration_rating", "created_at", "updated_at", "remote_host"]
    search_fields = ["protocol__protocol_title", "user__username", "user__first_name", "user__last_name"]
    readonly_fields = ["created_at", "updated_at", "remote_id", "remote_host"]

    fieldsets = (
        ("Rating Information", {"fields": ("protocol", "user", "complexity_rating", "duration_rating")}),
        ("System Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("protocol", "user", "remote_host")


class ProtocolStepInline(admin.TabularInline):
    """Inline admin for protocol steps within sections."""

    model = ProtocolStep
    fields = ["step_description", "step_duration", "order", "original"]
    readonly_fields = ["created_at"]
    extra = 0
    ordering = ["order", "id"]


@admin.register(ProtocolSection)
class ProtocolSectionAdmin(SimpleHistoryAdmin):
    """Admin interface for protocol sections with step management."""

    list_display = ["protocol", "section_description_short", "section_duration", "order", "steps_count"]
    list_filter = ["created_at", "updated_at", "remote_host"]
    search_fields = ["section_description", "protocol__protocol_title"]
    readonly_fields = ["created_at", "updated_at", "remote_id", "remote_host"]
    inlines = [ProtocolStepInline]

    fieldsets = (
        ("Section Information", {"fields": ("protocol", "section_description", "section_duration", "order")}),
        ("System Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def section_description_short(self, obj):
        """Display truncated section description."""
        if obj.section_description:
            return (
                obj.section_description[:50] + "..." if len(obj.section_description) > 50 else obj.section_description
            )
        return "No description"

    section_description_short.short_description = "Description"

    def steps_count(self, obj):
        """Display count of steps in this section."""
        count = obj.steps.count()
        if count > 0:
            url = reverse("admin:ccrv_protocolstep_changelist")
            return format_html('<a href="{}?step_section__id__exact={}">{} steps</a>', url, obj.id, count)
        return "0 steps"

    steps_count.short_description = "Steps"

    def get_queryset(self, request):
        """Optimize queryset."""
        return (
            super().get_queryset(request).select_related("protocol", "remote_host").annotate(steps_count=Count("steps"))
        )


@admin.register(ProtocolStep)
class ProtocolStepAdmin(SimpleHistoryAdmin):
    """Admin interface for individual protocol steps."""

    list_display = ["step_description_short", "protocol", "step_section", "step_duration", "order", "original"]
    list_filter = ["original", "created_at", "updated_at", "step_section", "remote_host"]
    search_fields = ["step_description", "protocol__protocol_title", "step_section__section_description"]
    readonly_fields = ["created_at", "updated_at", "remote_id", "remote_host"]

    fieldsets = (
        (
            "Step Information",
            {"fields": ("protocol", "step_section", "step_id", "step_description", "step_duration", "order")},
        ),
        (
            "Navigation",
            {
                "fields": ("previous_step", "original", "branch_from"),
                "description": "Linked-list navigation and branching",
            },
        ),
        ("System Information", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def step_description_short(self, obj):
        """Display truncated step description."""
        if obj.step_description:
            return obj.step_description[:50] + "..." if len(obj.step_description) > 50 else obj.step_description
        return "No description"

    step_description_short.short_description = "Description"

    def get_queryset(self, request):
        """Optimize queryset."""
        return (
            super()
            .get_queryset(request)
            .select_related("protocol", "step_section", "previous_step", "branch_from", "remote_host")
        )


@admin.register(ProtocolReagent)
class ProtocolReagentAdmin(SimpleHistoryAdmin):
    """Admin interface for protocol-reagent relationships."""

    list_display = ["protocol", "reagent", "quantity", "created_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["protocol__protocol_title", "reagent__name"]
    readonly_fields = ["created_at", "updated_at", "remote_id"]

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("protocol", "reagent")


@admin.register(StepReagent)
class StepReagentAdmin(SimpleHistoryAdmin):
    """Admin interface for step-reagent relationships."""

    list_display = ["step", "reagent", "quantity", "scalable", "scalable_factor"]
    list_filter = ["scalable", "created_at", "updated_at"]
    search_fields = ["step__step_description", "reagent__name", "step__protocol__protocol_title"]
    readonly_fields = ["created_at", "updated_at", "remote_id"]

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("step", "step__protocol", "reagent")


@admin.register(StepVariation)
class StepVariationAdmin(SimpleHistoryAdmin):
    """Admin interface for protocol step variations."""

    list_display = ["step", "variation_description_short", "variation_duration", "created_at"]
    list_filter = ["created_at", "updated_at", "remote_host"]
    search_fields = ["variation_description", "step__step_description", "step__protocol__protocol_title"]
    readonly_fields = ["created_at", "updated_at", "remote_id", "remote_host"]

    def variation_description_short(self, obj):
        """Display truncated variation description."""
        return (
            obj.variation_description[:50] + "..." if len(obj.variation_description) > 50 else obj.variation_description
        )

    variation_description_short.short_description = "Variation"

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("step", "step__protocol", "remote_host")


@admin.register(TimeKeeper)
class TimeKeeperAdmin(SimpleHistoryAdmin):
    """Admin interface for time tracking records."""

    list_display = ["session", "step", "user", "current_duration", "started", "start_time"]
    list_filter = ["started", "start_time"]
    search_fields = ["session__name", "step__step_description", "user__username", "user__first_name", "user__last_name"]
    readonly_fields = ["start_time", "remote_id", "remote_host"]

    fieldsets = (
        ("Time Tracking Information", {"fields": ("session", "step", "user", "started", "current_duration")}),
        ("System Information", {"fields": ("start_time",), "classes": ("collapse",)}),
        ("Distributed System", {"fields": ("remote_id", "remote_host"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("session", "step", "user", "remote_host")
