"""
Serializers for CUPCAKE Core Macaron (CCM) models.

Provides REST API serialization for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import serializers

from ccc.models import Annotation, LabGroupPermission

logger = logging.getLogger(__name__)

from .models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentAnnotation,
    InstrumentJob,
    InstrumentJobAnnotation,
    InstrumentPermission,
    InstrumentUsage,
    InstrumentUsageJobAnnotation,
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


def queue_annotation_transcription(annotation, auto_transcribe=True):
    """
    Queue transcription task for audio/video annotations.

    Args:
        annotation: The Annotation object to transcribe
        auto_transcribe: Whether to automatically queue transcription (default: True)
    """
    if not auto_transcribe:
        return

    if not getattr(settings, "USE_WHISPER", False):
        return

    if not getattr(settings, "ENABLE_CUPCAKE_RED_VELVET", False):
        return

    annotation_type = annotation.annotation_type
    if annotation_type not in ["audio", "video"]:
        return

    if not annotation.file:
        return

    if annotation.transcribed:
        return

    try:
        from ccc.tasks.transcribe_tasks import transcribe_audio, transcribe_audio_from_video

        file_path = annotation.file.path
        model_path = settings.WHISPERCPP_DEFAULT_MODEL

        if annotation_type == "audio":
            transcribe_audio.delay(
                audio_path=file_path,
                model_path=model_path,
                annotation_id=annotation.id,
                language="auto",
                translate=True,
            )
            logger.info(f"Queued audio transcription for annotation {annotation.id}")
        elif annotation_type == "video":
            transcribe_audio_from_video.delay(
                video_path=file_path,
                model_path=model_path,
                annotation_id=annotation.id,
                language="auto",
                translate=True,
            )
            logger.info(f"Queued video transcription for annotation {annotation.id}")

    except Exception as e:
        logger.error(f"Failed to queue transcription for annotation {annotation.id}: {str(e)}")


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
            "allow_overlapping_bookings",
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
    metadata_table_template_name = serializers.CharField(source="metadata_table_template.name", read_only=True)
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    staff_usernames = serializers.StringRelatedField(source="staff", many=True, read_only=True)
    lab_group_name = serializers.CharField(source="lab_group.name", read_only=True)
    project_name = serializers.CharField(source="project.project_name", read_only=True)

    # Choice field display values
    job_type_display = serializers.CharField(source="get_job_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sample_type_display = serializers.CharField(source="get_sample_type_display", read_only=True)

    # Permission fields
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    can_edit_metadata = serializers.SerializerMethodField()
    can_edit_staff_only_columns = serializers.SerializerMethodField()

    def get_can_edit(self, obj):
        """Check if current user can edit this job."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_edit(request.user)
        return False

    def get_can_delete(self, obj):
        """Check if current user can delete this job."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_delete(request.user)
        return False

    def get_can_edit_metadata(self, obj):
        """Check if current user can edit metadata for this job."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_user_edit_metadata(request.user)
        return False

    def get_can_edit_staff_only_columns(self, obj):
        """
        Check if current user can edit staff-only columns.

        Rules:
        - If staff assigned: Only assigned staff can edit (staff are always direct lab_group members)
        - If no staff but lab_group exists: Direct lab_group members can edit (not subgroup members)

        Note: Staff-only permissions require DIRECT membership in the lab_group for security.
        """
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            user = request.user
            if not obj.metadata_table:
                return False
            assigned_staff = obj.staff.all()
            has_assigned_staff = (
                assigned_staff.exists() if hasattr(assigned_staff, "exists") else len(assigned_staff) > 0
            )
            if has_assigned_staff:
                return user in assigned_staff
            else:
                if obj.lab_group and obj.lab_group.members.filter(id=user.id).exists():
                    return True
            return False
        return False

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
            "project",
            "project_name",
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
            "metadata_table_template",
            "metadata_table_template_name",
            "metadata_table",
            "metadata_table_name",
            "stored_reagent",
            "instrument_start_time",
            "instrument_end_time",
            "personnel_start_time",
            "personnel_end_time",
            "created_at",
            "updated_at",
            "submitted_at",
            "completed_at",
            "can_edit",
            "can_delete",
            "can_edit_metadata",
            "can_edit_staff_only_columns",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "user_username",
            "instrument_name",
            "metadata_table_template_name",
            "metadata_table_name",
            "staff_usernames",
            "lab_group_name",
            "project_name",
            "job_type_display",
            "status_display",
            "sample_type_display",
            "can_edit",
            "can_delete",
            "can_edit_metadata",
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
        Validate staff assignment and lab_group requirements.

        Rules:
        1. If staff is assigned, lab_group MUST be present
        2. All assigned staff MUST be DIRECT members of the lab_group (not subgroup members)
        3. All assigned staff MUST have can_process_jobs permission for the lab_group
        4. Staff and lab_group can both be cleared (set to empty/None)

        Note: Staff assignment requires DIRECT membership in the lab_group for security.
        """
        staff = attrs.get("staff")
        lab_group = attrs.get("lab_group")

        # Get existing values if not in attrs (for partial updates)
        if self.instance:
            if staff is None:
                staff = list(self.instance.staff.all())
            if lab_group is None:
                lab_group = self.instance.lab_group

        # Rule 1: If staff is assigned, lab_group is required
        if staff and not lab_group:
            raise serializers.ValidationError(
                {"lab_group": "Lab group is required when staff members are assigned to the job"}
            )

        # Rules 2 & 3: Validate staff members
        if staff and lab_group:
            invalid_staff = []
            not_direct_member_staff = []

            for staff_user in staff:
                # Check if staff is a DIRECT member of the lab_group (not subgroup)
                if not lab_group.members.filter(id=staff_user.id).exists():
                    not_direct_member_staff.append(staff_user.username)
                    continue

                # Check if staff has can_process_jobs permission
                has_permission = LabGroupPermission.objects.filter(
                    user=staff_user, lab_group=lab_group, can_process_jobs=True
                ).exists()

                if not has_permission:
                    invalid_staff.append(staff_user.username)

            if not_direct_member_staff:
                raise serializers.ValidationError(
                    {
                        "staff": f"The following users are not direct members of the lab group: {', '.join(not_direct_member_staff)}"
                    }
                )

            if invalid_staff:
                raise serializers.ValidationError(
                    {
                        "staff": f"The following users don't have can_process_jobs permission for this lab group: {', '.join(invalid_staff)}"
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
        - Overlapping bookings: If overlapping bookings exist and overlaps are allowed, requires approval

        Overlap handling:
        - If allow_overlapping_bookings is False and overlap detected: Reject booking
        - If allow_overlapping_bookings is True and overlap detected: Require approval
        - If no overlap: Follow normal auto-approval logic

        If ALL pre-approval conditions are met, booking is auto-approved.
        If ANY condition fails, booking requires manual approval.
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

            overlapping_bookings = InstrumentUsage.objects.filter(
                instrument=instrument, time_started__lt=time_ended, time_ended__gt=time_started
            )

            if self.instance:
                overlapping_bookings = overlapping_bookings.exclude(id=self.instance.id)

            if overlapping_bookings.exists():
                if not instrument.allow_overlapping_bookings:
                    raise serializers.ValidationError(
                        "This instrument does not allow overlapping bookings. "
                        f"There are {overlapping_bookings.count()} existing booking(s) during this time period."
                    )
                requires_approval = True
                approval_reasons.append(f"overlaps with {overlapping_bookings.count()} existing booking(s)")

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

    annotation = serializers.PrimaryKeyRelatedField(queryset=Annotation.objects.all(), required=False, allow_null=True)
    annotation_data = serializers.JSONField(write_only=True, required=False)
    instrument_name = serializers.CharField(source="instrument.instrument_name", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.annotation_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", required=False, allow_blank=True)
    transcribed = serializers.BooleanField(source="annotation.transcribed", read_only=True)
    transcription = serializers.CharField(
        source="annotation.transcription", required=False, allow_blank=True, allow_null=True
    )
    language = serializers.CharField(source="annotation.language", required=False, allow_blank=True, allow_null=True)
    translation = serializers.CharField(
        source="annotation.translation", required=False, allow_blank=True, allow_null=True
    )
    scratched = serializers.BooleanField(source="annotation.scratched", required=False)
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
            "annotation_data",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "instrument_name",
            "folder_name",
            "annotation_name",
            "annotation_type",
            "transcribed",
            "file_url",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        """Ensure either annotation or annotation_data is provided."""
        annotation = data.get("annotation")
        annotation_data = data.get("annotation_data")

        if not annotation and not annotation_data:
            raise serializers.ValidationError(
                "Either 'annotation' (ID) or 'annotation_data' (object) must be provided."
            )

        return data

    def create(self, validated_data):
        """
        Create instrument annotation with non-file annotation.
        Use annotation_data for nested object: {"instrument": 1, "folder": 2, "annotation_data": {"annotation": "text", "annotationType": "text", "auto_transcribe": true}}
        Use annotation for existing ID: {"instrument": 1, "folder": 2, "annotation": 5}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")
            auto_transcribe = annotation_data.get("auto_transcribe", True)

            if not annotation_text:
                raise serializers.ValidationError(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}}
                )

            user = self.context["request"].user
            folder = validated_data.get("folder")

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                folder=folder,
                owner=user,
            )

            queue_annotation_transcription(annotation, auto_transcribe)

            validated_data["annotation"] = annotation

        if "order" not in validated_data:
            instrument = validated_data.get("instrument")
            folder = validated_data.get("folder")
            if instrument and folder:
                order = InstrumentAnnotation.objects.filter(instrument=instrument, folder=folder).count()
                validated_data["order"] = order

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Update instrument annotation and nested annotation fields.
        Use annotation_data: {"annotation_data": {"annotation": "updated text", "language": "en"}}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data and instance.annotation:
            if "annotation" in annotation_data:
                instance.annotation.annotation = annotation_data["annotation"]
            if "transcription" in annotation_data:
                instance.annotation.transcription = annotation_data["transcription"]
            if "language" in annotation_data:
                instance.annotation.language = annotation_data["language"]
            if "translation" in annotation_data:
                instance.annotation.translation = annotation_data["translation"]
            if "scratched" in annotation_data:
                instance.annotation.scratched = annotation_data["scratched"]
            instance.annotation.save()

        return super().update(instance, validated_data)

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


class InstrumentJobAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentJobAnnotation model."""

    annotation = serializers.PrimaryKeyRelatedField(queryset=Annotation.objects.all(), required=False, allow_null=True)
    annotation_data = serializers.JSONField(write_only=True, required=False)
    instrument_job_name = serializers.CharField(source="instrument_job.job_name", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.annotation_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", required=False, allow_blank=True)
    annotation_user = serializers.CharField(source="annotation.user.username", read_only=True)
    transcribed = serializers.BooleanField(source="annotation.transcribed", read_only=True)
    transcription = serializers.CharField(
        source="annotation.transcription", required=False, allow_blank=True, allow_null=True
    )
    language = serializers.CharField(source="annotation.language", required=False, allow_blank=True, allow_null=True)
    translation = serializers.CharField(
        source="annotation.translation", required=False, allow_blank=True, allow_null=True
    )
    scratched = serializers.BooleanField(source="annotation.scratched", required=False)
    file_url = serializers.SerializerMethodField()

    # Permission fields
    can_view = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = InstrumentJobAnnotation
        fields = [
            "id",
            "instrument_job",
            "instrument_job_name",
            "folder",
            "folder_name",
            "annotation",
            "annotation_data",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "annotation_user",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "role",
            "order",
            "can_view",
            "can_edit",
            "can_delete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "instrument_job_name",
            "folder_name",
            "annotation_name",
            "annotation_type",
            "annotation_user",
            "transcribed",
            "file_url",
            "can_view",
            "can_edit",
            "can_delete",
            "created_at",
            "updated_at",
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
            from django.urls import reverse

            token = obj.annotation.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.annotation.id})
            return request.build_absolute_uri(f"{download_path}?token={token}")
        except Exception:
            return None

    def get_can_view(self, obj):
        """Check if user can view this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_view(request.user)
        return False

    def get_can_edit(self, obj):
        """Check if user can edit this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_edit(request.user)
        return False

    def get_can_delete(self, obj):
        """Check if user can delete this annotation."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.can_delete(request.user)
        return False


class InstrumentUsageJobAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentUsageJobAnnotation model."""

    instrument_job_annotation_details = InstrumentJobAnnotationSerializer(
        source="instrument_job_annotation", read_only=True
    )
    instrument_name = serializers.CharField(source="instrument_usage.instrument.instrument_name", read_only=True)
    job_name = serializers.CharField(source="instrument_job_annotation.instrument_job.job_name", read_only=True)

    class Meta:
        model = InstrumentUsageJobAnnotation
        fields = [
            "id",
            "instrument_job_annotation",
            "instrument_job_annotation_details",
            "instrument_usage",
            "instrument_name",
            "job_name",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "instrument_job_annotation_details",
            "instrument_name",
            "job_name",
            "created_at",
            "updated_at",
        ]


class StoredReagentAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for StoredReagentAnnotation model."""

    annotation = serializers.PrimaryKeyRelatedField(queryset=Annotation.objects.all(), required=False, allow_null=True)
    annotation_data = serializers.JSONField(write_only=True, required=False)
    stored_reagent_name = serializers.CharField(source="stored_reagent.reagent.name", read_only=True)
    folder_name = serializers.CharField(source="folder.folder_name", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.annotation_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", required=False, allow_blank=True)
    transcribed = serializers.BooleanField(source="annotation.transcribed", read_only=True)
    transcription = serializers.CharField(
        source="annotation.transcription", required=False, allow_blank=True, allow_null=True
    )
    language = serializers.CharField(source="annotation.language", required=False, allow_blank=True, allow_null=True)
    translation = serializers.CharField(
        source="annotation.translation", required=False, allow_blank=True, allow_null=True
    )
    scratched = serializers.BooleanField(source="annotation.scratched", required=False)
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
            "annotation_data",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "stored_reagent_name",
            "folder_name",
            "annotation_name",
            "annotation_type",
            "transcribed",
            "file_url",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        """Ensure either annotation or annotation_data is provided."""
        annotation = data.get("annotation")
        annotation_data = data.get("annotation_data")

        if not annotation and not annotation_data:
            raise serializers.ValidationError(
                "Either 'annotation' (ID) or 'annotation_data' (object) must be provided."
            )

        return data

    def create(self, validated_data):
        """
        Create stored reagent annotation with non-file annotation.
        Use annotation_data for nested object: {"storedReagent": 1, "folder": 2, "annotation_data": {"annotation": "text", "annotationType": "text", "auto_transcribe": true}}
        Use annotation for existing ID: {"storedReagent": 1, "folder": 2, "annotation": 5}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")
            auto_transcribe = annotation_data.get("auto_transcribe", True)

            if not annotation_text:
                raise serializers.ValidationError(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}}
                )

            user = self.context["request"].user
            folder = validated_data.get("folder")

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                folder=folder,
                owner=user,
            )

            queue_annotation_transcription(annotation, auto_transcribe)

            validated_data["annotation"] = annotation

        if "order" not in validated_data:
            stored_reagent = validated_data.get("stored_reagent")
            folder = validated_data.get("folder")
            if stored_reagent and folder:
                order = StoredReagentAnnotation.objects.filter(stored_reagent=stored_reagent, folder=folder).count()
                validated_data["order"] = order

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Update stored reagent annotation and nested annotation fields.
        Use annotation_data: {"annotation_data": {"annotation": "updated text", "language": "en"}}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data and instance.annotation:
            if "annotation" in annotation_data:
                instance.annotation.annotation = annotation_data["annotation"]
            if "transcription" in annotation_data:
                instance.annotation.transcription = annotation_data["transcription"]
            if "language" in annotation_data:
                instance.annotation.language = annotation_data["language"]
            if "translation" in annotation_data:
                instance.annotation.translation = annotation_data["translation"]
            if "scratched" in annotation_data:
                instance.annotation.scratched = annotation_data["scratched"]
            instance.annotation.save()

        return super().update(instance, validated_data)

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

    annotation = serializers.PrimaryKeyRelatedField(queryset=Annotation.objects.all(), required=False, allow_null=True)
    annotation_data = serializers.JSONField(write_only=True, required=False)
    maintenance_log_title = serializers.CharField(source="maintenance_log.maintenance_type", read_only=True)
    annotation_name = serializers.CharField(source="annotation.name", read_only=True)
    annotation_type = serializers.CharField(source="annotation.annotation_type", read_only=True)
    annotation_text = serializers.CharField(source="annotation.annotation", required=False, allow_blank=True)
    transcribed = serializers.BooleanField(source="annotation.transcribed", read_only=True)
    transcription = serializers.CharField(
        source="annotation.transcription", required=False, allow_blank=True, allow_null=True
    )
    language = serializers.CharField(source="annotation.language", required=False, allow_blank=True, allow_null=True)
    translation = serializers.CharField(
        source="annotation.translation", required=False, allow_blank=True, allow_null=True
    )
    scratched = serializers.BooleanField(source="annotation.scratched", required=False)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceLogAnnotation
        fields = [
            "id",
            "maintenance_log",
            "maintenance_log_title",
            "annotation",
            "annotation_data",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "maintenance_log_title",
            "annotation_name",
            "annotation_type",
            "transcribed",
            "file_url",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        """Ensure either annotation or annotation_data is provided."""
        annotation = data.get("annotation")
        annotation_data = data.get("annotation_data")

        if not annotation and not annotation_data:
            raise serializers.ValidationError(
                "Either 'annotation' (ID) or 'annotation_data' (object) must be provided."
            )

        return data

    def create(self, validated_data):
        """
        Create maintenance log annotation with non-file annotation.
        Use annotation_data for nested object: {"maintenanceLog": 1, "annotation_data": {"annotation": "text", "annotationType": "text", "auto_transcribe": true}}
        Use annotation for existing ID: {"maintenanceLog": 1, "annotation": 5}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")
            auto_transcribe = annotation_data.get("auto_transcribe", True)

            if not annotation_text:
                raise serializers.ValidationError(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}}
                )

            user = self.context["request"].user

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                owner=user,
            )

            queue_annotation_transcription(annotation, auto_transcribe)

            validated_data["annotation"] = annotation

        if "order" not in validated_data:
            maintenance_log = validated_data.get("maintenance_log")
            if maintenance_log:
                order = MaintenanceLogAnnotation.objects.filter(maintenance_log=maintenance_log).count()
                validated_data["order"] = order

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Update maintenance log annotation and nested annotation fields.
        Use annotation_data: {"annotation_data": {"annotation": "updated text", "language": "en"}}
        """
        annotation_data = validated_data.pop("annotation_data", None)

        if annotation_data and instance.annotation:
            if "annotation" in annotation_data:
                instance.annotation.annotation = annotation_data["annotation"]
            if "transcription" in annotation_data:
                instance.annotation.transcription = annotation_data["transcription"]
            if "language" in annotation_data:
                instance.annotation.language = annotation_data["language"]
            if "translation" in annotation_data:
                instance.annotation.translation = annotation_data["translation"]
            if "scratched" in annotation_data:
                instance.annotation.scratched = annotation_data["scratched"]
            instance.annotation.save()

        return super().update(instance, validated_data)

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
    session_name = serializers.CharField(source="session.session_name", read_only=True)
    step_description = serializers.CharField(source="step.step_description", read_only=True)
    is_within_deletion_window = serializers.SerializerMethodField()
    is_deletable = serializers.SerializerMethodField()

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
            "session",
            "session_name",
            "step",
            "step_description",
            "is_within_deletion_window",
            "is_deletable",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "reagent_name",
            "user_username",
            "action_type_display",
            "session_name",
            "step_description",
            "is_within_deletion_window",
            "is_deletable",
        ]

    def get_is_within_deletion_window(self, obj):
        """Check if reagent action is within the deletion time window."""
        return obj.is_within_deletion_window()

    def get_is_deletable(self, obj):
        """Check if current user can delete this reagent action."""
        request = self.context.get("request")
        if not request or not hasattr(request, "user"):
            return False
        return obj.user_can_delete(request.user)

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
