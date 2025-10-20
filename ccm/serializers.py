"""
Serializers for CUPCAKE Core Macaron (CCM) models.

Provides REST API serialization for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import serializers

from ccc.models import LabGroupPermission

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

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Basic user serializer for nested relationships."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]
        read_only_fields = ["id", "username", "first_name", "last_name", "email"]


class InstrumentSerializer(serializers.ModelSerializer):
    """Serializer for Instrument model."""

    owner_username = serializers.CharField(source="user.username", read_only=True)
    remote_host_name = serializers.CharField(source="remote_host.name", read_only=True)
    support_information_count = serializers.IntegerField(source="support_information.count", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    metadata_table_id = serializers.IntegerField(source="metadata_table.id", read_only=True)
    maintenance_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Instrument
        fields = [
            "id",
            "instrument_name",
            "instrument_description",
            "image",
            "enabled",
            "remote_id",
            "remote_host",
            "remote_host_name",
            "max_days_ahead_pre_approval",
            "max_days_within_usage_pre_approval",
            "support_information",
            "support_information_count",
            "last_warranty_notification_sent",
            "last_maintenance_notification_sent",
            "days_before_warranty_notification",
            "days_before_maintenance_notification",
            "accepts_bookings",
            "user",
            "owner_username",
            "is_vaulted",
            "metadata_table",
            "metadata_table_name",
            "metadata_table_id",
            "maintenance_overdue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "owner_username",
            "remote_host_name",
            "support_information_count",
            "metadata_table_name",
            "metadata_table_id",
            "maintenance_overdue",
        ]

    def get_maintenance_overdue(self, obj):
        """Check if instrument maintenance is overdue."""
        return obj.is_maintenance_overdue()

    def validate_instrument_name(self, value):
        """Validate instrument name is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("Instrument name cannot be empty.")
        return value.strip()


class InstrumentJobSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentJob model."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    staff_usernames = serializers.StringRelatedField(source="staff", many=True, read_only=True)
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)

    # Choice field display values
    job_type_display = serializers.CharField(source="get_job_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sample_type_display = serializers.CharField(source="get_sample_type_display", read_only=True)

    class Meta:
        model = InstrumentJob
        fields = [
            "id",
            "user",
            "user_username",
            "instrument",
            "instrument_name",
            "instrument_usage",
            "lab_group",
            "lab_group_name",
            "job_type",
            "job_type_display",
            "job_name",
            "status",
            "status_display",
            "sample_number",
            "sample_type",
            "sample_type_display",
            "injection_volume",
            "injection_unit",
            "search_engine",
            "search_engine_version",
            "search_details",
            "method",
            "location",
            "funder",
            "cost_center",
            "assigned",
            "staff",
            "staff_usernames",
            "metadata_table",
            "metadata_table_name",
            "user_annotations",
            "staff_annotations",
            "stored_reagent",
            "instrument_start_time",
            "instrument_end_time",
            "personnel_start_time",
            "personnel_end_time",
            "created_at",
            "updated_at",
            "submitted_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "user_username",
            "instrument_name",
            "metadata_table_name",
            "staff_usernames",
            "lab_group_name",
            "job_type_display",
            "status_display",
            "sample_type_display",
        ]

    def validate_job_name(self, value):
        """Validate job name is reasonable length."""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Job name cannot exceed 1000 characters.")
        return value

    def validate_sample_number(self, value):
        """Validate sample number is positive."""
        if value is not None and value <= 0:
            raise serializers.ValidationError("Sample number must be positive.")
        return value

    def validate_injection_volume(self, value):
        """Validate injection volume is positive."""
        if value is not None and value <= 0:
            raise serializers.ValidationError("Injection volume must be positive.")
        return value

    def validate(self, attrs):
        """
        Validate that assigned staff members have can_process_jobs permission for the lab_group.

        Staff can only be assigned if they have can_process_jobs=True permission
        for the specified lab_group.
        """
        staff = attrs.get("staff", [])
        lab_group = attrs.get("lab_group")

        if staff and lab_group:
            invalid_staff = []
            for staff_user in staff:
                has_permission = LabGroupPermission.objects.filter(
                    user=staff_user, lab_group=lab_group, can_process_jobs=True
                ).exists()

                if not has_permission:
                    invalid_staff.append(staff_user.username)

            if invalid_staff:
                raise serializers.ValidationError(
                    {
                        "staff": f"The following users cannot be assigned as they don't have can_process_jobs permission for this lab group: {', '.join(invalid_staff)}"
                    }
                )

        return attrs


class InstrumentUsageSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentUsage model."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True)

    class Meta:
        model = InstrumentUsage
        fields = [
            "id",
            "user",
            "user_username",
            "instrument",
            "instrument_name",
            "time_started",
            "time_ended",
            "usage_hours",
            "description",
            "approved",
            "maintenance",
            "approved_by",
            "approved_by_username",
            "remote_id",
            "remote_host",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "user_username",
            "instrument_name",
            "approved_by_username",
        ]

    def validate(self, data):
        """
        Validate usage time fields and determine if approval is required.

        Pre-approval conditions:
        - max_days_ahead_pre_approval: Booking starts within N days from now
        - max_days_within_usage_pre_approval: Booking duration is N days or less

        If BOTH conditions are met, booking is auto-approved.
        If EITHER condition fails, booking requires manual approval.
        """
        from django.utils import timezone

        time_started = data.get("time_started")
        time_ended = data.get("time_ended")
        instrument = data.get("instrument") or (self.instance.instrument if self.instance else None)

        if self.instance:
            time_started = time_started or self.instance.time_started
            time_ended = time_ended or self.instance.time_ended

        if time_started and time_ended and time_started >= time_ended:
            raise serializers.ValidationError("End time must be after start time.")

        if time_started and time_ended:
            duration = time_ended - time_started
            hours = duration.total_seconds() / 3600
            data["usage_hours"] = round(hours, 2)

        if instrument and time_started and time_ended:
            now = timezone.now()
            requires_approval = False
            approval_reasons = []

            if instrument.max_days_ahead_pre_approval is not None and instrument.max_days_ahead_pre_approval > 0:
                days_until_booking = (time_started - now).days
                if days_until_booking > instrument.max_days_ahead_pre_approval:
                    requires_approval = True
                    approval_reasons.append(
                        f"booking starts in {days_until_booking} days "
                        f"(exceeds {instrument.max_days_ahead_pre_approval} day limit for pre-approval)"
                    )

            if (
                instrument.max_days_within_usage_pre_approval is not None
                and instrument.max_days_within_usage_pre_approval > 0
            ):
                booking_duration_days = (time_ended - time_started).days
                if booking_duration_days > instrument.max_days_within_usage_pre_approval:
                    requires_approval = True
                    approval_reasons.append(
                        f"booking duration is {booking_duration_days} days "
                        f"(exceeds {instrument.max_days_within_usage_pre_approval} day limit for pre-approval)"
                    )

            if requires_approval and "approved" not in data:
                data["approved"] = False

            if not requires_approval and "approved" not in data:
                data["approved"] = True

        return data

    def validate_usage_hours(self, value):
        """Validate usage hours is non-negative."""
        if value is not None and value < 0:
            raise serializers.ValidationError("Usage hours cannot be negative.")
        return value


class MaintenanceLogSerializer(serializers.ModelSerializer):
    """Serializer for MaintenanceLog model."""

    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    maintenance_type_display = serializers.CharField(source="get_maintenance_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MaintenanceLog
        fields = [
            "id",
            "instrument",
            "instrument_name",
            "maintenance_date",
            "maintenance_type",
            "maintenance_type_display",
            "status",
            "status_display",
            "maintenance_description",
            "maintenance_notes",
            "created_by",
            "created_by_username",
            "is_template",
            "annotation_folder",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "instrument_name",
            "created_by_username",
            "maintenance_type_display",
            "status_display",
        ]


class StorageObjectSerializer(serializers.ModelSerializer):
    """Serializer for StorageObject model."""

    stored_at_name = serializers.CharField(source="stored_at.object_name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    full_path = serializers.SerializerMethodField()

    class Meta:
        model = StorageObject
        fields = [
            "id",
            "object_type",
            "object_name",
            "object_description",
            "stored_at",
            "stored_at_name",
            "full_path",
            "remote_id",
            "remote_host",
            "can_delete",
            "png_base64",
            "user",
            "user_username",
            "access_lab_groups",
            "is_vaulted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "stored_at_name", "user_username", "full_path"]

    def get_full_path(self, obj):
        """Get the full hierarchical path to root."""
        return obj.get_full_path()

    def validate_object_name(self, value):
        """Validate object name is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("Object name cannot be empty.")
        return value.strip()


class ReagentSerializer(serializers.ModelSerializer):
    """Serializer for Reagent model."""

    class Meta:
        model = Reagent
        fields = ["id", "name", "unit", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StoredReagentSerializer(serializers.ModelSerializer):
    """Serializer for StoredReagent model."""

    reagent_name = serializers.CharField(source="reagent.name", read_only=True)
    reagent_unit = serializers.CharField(source="reagent.unit", read_only=True)
    storage_object_name = serializers.CharField(source="storage_object.object_name", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    metadata_table_id = serializers.IntegerField(source="metadata_table.id", read_only=True)
    current_quantity = serializers.SerializerMethodField()

    class Meta:
        model = StoredReagent
        fields = [
            "id",
            "reagent",
            "reagent_name",
            "reagent_unit",
            "storage_object",
            "storage_object_name",
            "quantity",
            "current_quantity",
            "notes",
            "user",
            "png_base64",
            "barcode",
            "shareable",
            "access_users",
            "access_lab_groups",
            "access_all",
            "expiration_date",
            "low_stock_threshold",
            "notify_on_low_stock",
            "last_notification_sent",
            "metadata_table",
            "metadata_table_name",
            "metadata_table_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "reagent_name",
            "reagent_unit",
            "storage_object_name",
            "metadata_table_name",
            "metadata_table_id",
            "current_quantity",
        ]

    def validate_quantity(self, value):
        """Validate quantity is non-negative."""
        if value is not None and value < 0:
            raise serializers.ValidationError("Quantity cannot be negative.")
        return value

    def get_current_quantity(self, obj):
        """
        Calculate current quantity by summing initial quantity + reagent actions.

        Action types:
        - 'add': positive quantity change (+)
        - 'reserve': negative quantity change (-)
        """
        from django.db.models import Case, F, Sum, When

        from .models import ReagentAction

        # Start with the initial/base quantity
        current_qty = obj.quantity or 0.0

        # Sum all reagent actions for this stored reagent
        actions_sum = (
            ReagentAction.objects.filter(reagent=obj).aggregate(
                total_change=Sum(
                    Case(
                        When(action_type="add", then=F("quantity")),
                        When(action_type="reserve", then=-F("quantity")),
                        default=0.0,
                    )
                )
            )["total_change"]
            or 0.0
        )

        return round(current_qty + actions_sum, 2)


class ExternalContactDetailsSerializer(serializers.ModelSerializer):
    """Serializer for ExternalContactDetails model."""

    class Meta:
        model = ExternalContactDetails
        fields = ["id", "contact_method_alt_name", "contact_type", "contact_value", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ExternalContactSerializer(serializers.ModelSerializer):
    """Serializer for ExternalContact model."""

    contact_details = ExternalContactDetailsSerializer(many=True, read_only=True)
    contact_details_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ExternalContactDetails.objects.all(),
        source="contact_details",
        write_only=True,
        required=False,
    )
    owner_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ExternalContact
        fields = [
            "id",
            "contact_name",
            "user",
            "owner_username",
            "contact_details",
            "contact_details_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "owner_username"]


class SupportInformationSerializer(serializers.ModelSerializer):
    """Serializer for SupportInformation model."""

    vendor_contacts = ExternalContactSerializer(many=True, read_only=True)
    vendor_contacts_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ExternalContact.objects.all(),
        source="vendor_contacts",
        write_only=True,
        required=False,
    )
    manufacturer_contacts = ExternalContactSerializer(many=True, read_only=True)
    manufacturer_contacts_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ExternalContact.objects.all(),
        source="manufacturer_contacts",
        write_only=True,
        required=False,
    )
    location_name = serializers.CharField(source="location.object_name", read_only=True)

    class Meta:
        model = SupportInformation
        fields = [
            "id",
            "vendor_name",
            "vendor_contacts",
            "vendor_contacts_ids",
            "manufacturer_name",
            "manufacturer_contacts",
            "manufacturer_contacts_ids",
            "serial_number",
            "maintenance_frequency_days",
            "location",
            "location_name",
            "warranty_start_date",
            "warranty_end_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "location_name",
            "created_at",
            "updated_at",
        ]


class ReagentSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for ReagentSubscription model."""

    reagent_name = serializers.CharField(source="stored_reagent.reagent.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ReagentSubscription
        fields = [
            "id",
            "user",
            "user_username",
            "stored_reagent",
            "reagent_name",
            "notify_on_low_stock",
            "notify_on_expiry",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "reagent_name", "user_username"]


class InstrumentAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentAnnotation model."""

    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.resource_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = InstrumentAnnotation
        fields = [
            "id",
            "instrument",
            "instrument_name",
            "folder",
            "folder_name",
            "annotation",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "instrument_name",
            "folder_name",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "created_at",
        ]

    def get_file_url(self, obj):
        """Get signed download URL for annotation file if exists."""
        if not obj.annotation or not obj.annotation.file:
            return None

        request = self.context.get("request")
        if not request or not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        if not obj.annotation.can_view(request.user):
            return None

        try:
            token = obj.annotation.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.annotation.id})
            return request.build_absolute_uri(f"{download_path}?token={token}")
        except Exception:
            return None


class StoredReagentAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for StoredReagentAnnotation model."""

    stored_reagent_name = serializers.CharField(source="stored_reagent.reagent.name", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.resource_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = StoredReagentAnnotation
        fields = [
            "id",
            "stored_reagent",
            "stored_reagent_name",
            "folder",
            "folder_name",
            "annotation",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "stored_reagent_name",
            "folder_name",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "created_at",
        ]

    def get_file_url(self, obj):
        """Get signed download URL for annotation file if exists."""
        if not obj.annotation or not obj.annotation.file:
            return None

        request = self.context.get("request")
        if not request or not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        if not obj.annotation.can_view(request.user):
            return None

        try:
            token = obj.annotation.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.annotation.id})
            return request.build_absolute_uri(f"{download_path}?token={token}")
        except Exception:
            return None


class MaintenanceLogAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for MaintenanceLogAnnotation model."""

    maintenance_log_title = serializers.CharField(source="maintenance_log.maintenance_type", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.resource_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceLogAnnotation
        fields = [
            "id",
            "maintenance_log",
            "maintenance_log_title",
            "annotation",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "order",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "maintenance_log_title",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "file_url",
            "created_at",
        ]

    def get_file_url(self, obj):
        """
        Get signed download URL for annotation file if exists.
        Uses MaintenanceLogAnnotation permission check which requires can_manage on instrument.
        """
        if not obj.annotation or not obj.annotation.file:
            return None

        request = self.context.get("request")
        if not request or not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        if not obj.can_view(request.user):
            return None

        try:
            token = obj.annotation.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.annotation.id})
            return request.build_absolute_uri(f"{download_path}?token={token}")
        except Exception:
            return None


class ReagentActionSerializer(serializers.ModelSerializer):
    """Serializer for ReagentAction model."""

    reagent_name = serializers.CharField(source="reagent.reagent.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    action_type_display = serializers.CharField(source="get_action_type_display", read_only=True)

    class Meta:
        model = ReagentAction
        fields = [
            "id",
            "reagent",
            "reagent_name",
            "user",
            "user_username",
            "action_type",
            "action_type_display",
            "quantity",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "reagent_name", "user_username", "action_type_display"]

    def validate_quantity(self, value):
        """Validate quantity is positive."""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be positive.")
        return value


# Detailed serializers for expanded representations
class InstrumentDetailSerializer(InstrumentSerializer):
    """Detailed serializer for Instrument with related data."""

    support_information = SupportInformationSerializer(many=True, read_only=True)

    class Meta(InstrumentSerializer.Meta):
        fields = InstrumentSerializer.Meta.fields + ["support_information"]


class InstrumentJobDetailSerializer(InstrumentJobSerializer):
    """Detailed serializer for InstrumentJob with related data."""

    user_details = UserBasicSerializer(source="user", read_only=True)
    instrument_details = InstrumentSerializer(source="instrument", read_only=True)
    staff_details = UserBasicSerializer(source="staff", many=True, read_only=True)

    class Meta(InstrumentJobSerializer.Meta):
        fields = InstrumentJobSerializer.Meta.fields + ["user_details", "instrument_details", "staff_details"]


class InstrumentPermissionSerializer(serializers.ModelSerializer):
    """Serializer for instrument permissions."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_display_name = serializers.SerializerMethodField()
    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)

    class Meta:
        model = InstrumentPermission
        fields = [
            "id",
            "instrument",
            "instrument_name",
            "user",
            "user_username",
            "user_display_name",
            "can_view",
            "can_book",
            "can_manage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "user_username", "user_display_name", "instrument_name"]

    def get_user_display_name(self, obj):
        """Get user's display name."""
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        return obj.user.username
