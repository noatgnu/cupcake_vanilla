"""
Serializers for CUPCAKE Core Macaron (CCM) models.

Provides REST API serialization for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

from django.contrib.auth import get_user_model

from rest_framework import serializers

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
        ]

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
        """Validate usage time fields."""
        time_started = data.get("time_started")
        time_ended = data.get("time_ended")

        if time_started and time_ended and time_started >= time_ended:
            raise serializers.ValidationError("End time must be after start time.")

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

    class Meta:
        model = StorageObject
        fields = [
            "id",
            "object_type",
            "object_name",
            "object_description",
            "stored_at",
            "stored_at_name",
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
        read_only_fields = ["id", "created_at", "updated_at", "stored_at_name", "user_username"]

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
        fields = ["id", "contact_type", "value", "is_primary", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ExternalContactSerializer(serializers.ModelSerializer):
    """Serializer for ExternalContact model."""

    contact_details = ExternalContactDetailsSerializer(many=True, read_only=True)

    class Meta:
        model = ExternalContact
        fields = [
            "id",
            "first_name",
            "last_name",
            "organization",
            "role",
            "notes",
            "contact_details",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SupportInformationSerializer(serializers.ModelSerializer):
    """Serializer for SupportInformation model."""

    contact_name = serializers.CharField(source="contact.first_name", read_only=True)
    contact_organization = serializers.CharField(source="contact.organization", read_only=True)

    class Meta:
        model = SupportInformation
        fields = [
            "id",
            "contact",
            "contact_name",
            "contact_organization",
            "support_type",
            "description",
            "warranty_expiration",
            "service_contract_number",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "contact_name", "contact_organization"]


class ReagentSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for ReagentSubscription model."""

    reagent_name = serializers.CharField(source="reagent.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ReagentSubscription
        fields = [
            "id",
            "reagent",
            "reagent_name",
            "user",
            "user_username",
            "subscription_type",
            "threshold_quantity",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "reagent_name", "user_username"]


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


class InstrumentAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for instrument annotations."""

    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    annotation_title = serializers.CharField(source="annotation.annotation", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)

    class Meta:
        model = InstrumentAnnotation
        fields = [
            "id",
            "instrument",
            "instrument_name",
            "annotation",
            "annotation_title",
            "folder",
            "folder_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class StoredReagentAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for stored reagent annotations."""

    reagent_name = serializers.CharField(source="stored_reagent.reagent.name", read_only=True)
    annotation_title = serializers.CharField(source="annotation.annotation", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)

    class Meta:
        model = StoredReagentAnnotation
        fields = [
            "id",
            "stored_reagent",
            "reagent_name",
            "annotation",
            "annotation_title",
            "folder",
            "folder_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MaintenanceLogAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for maintenance log annotations."""

    instrument_name = serializers.CharField(source="maintenance_log.instrument.instrument_name", read_only=True)
    annotation_title = serializers.CharField(source="annotation.annotation", read_only=True)

    class Meta:
        model = MaintenanceLogAnnotation
        fields = [
            "id",
            "maintenance_log",
            "instrument_name",
            "annotation",
            "annotation_title",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InstrumentPermissionSerializer(serializers.ModelSerializer):
    """Serializer for instrument permissions."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_display_name = serializers.SerializerMethodField()
    granted_by_username = serializers.CharField(source="granted_by.username", read_only=True)
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
            "permission_type",
            "granted_by",
            "granted_by_username",
            "granted_at",
        ]
        read_only_fields = ["id", "granted_by", "granted_at"]

    def get_user_display_name(self, obj):
        """Get user's display name."""
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        return obj.user.username

    def create(self, validated_data):
        """Set granted_by to current user."""
        request = self.context["request"]
        validated_data["granted_by"] = request.user
        return super().create(validated_data)
