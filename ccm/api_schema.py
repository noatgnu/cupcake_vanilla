"""Request and response shapes of the CUPCAKE Macaron custom actions, for the OpenAPI schema."""

from rest_framework import serializers

from ccv.serializers import MetadataColumnSerializer, MetadataTableSerializer

from .serializers import InstrumentJobSerializer


class WarrantyCheckSerializer(serializers.Serializer):
    """Warranty state of the instrument."""

    warrantyValid = serializers.BooleanField()
    warrantyExpiration = serializers.DateField(allow_null=True)
    message = serializers.CharField()


class MaintenanceCheckSerializer(serializers.Serializer):
    """Maintenance state of the instrument."""

    maintenanceRequired = serializers.BooleanField()
    lastMaintenance = serializers.DateTimeField(allow_null=True)
    message = serializers.CharField()


class InstrumentTestNotificationSerializer(serializers.Serializer):
    """A test notification about the instrument, sent to the requesting user or another user."""

    notification_type = serializers.ChoiceField(
        choices=["warranty_expiring", "maintenance_due", "maintenance_completed"], default="maintenance_due"
    )
    recipient_id = serializers.IntegerField(required=False, allow_null=True)


class ReagentTestNotificationSerializer(serializers.Serializer):
    """A test notification about the stored reagent, sent to the requesting user or another user."""

    notification_type = serializers.ChoiceField(choices=["low_stock", "expired", "expiring_soon"], default="low_stock")
    recipient_id = serializers.IntegerField(required=False, allow_null=True)


class TestNotificationSentSerializer(serializers.Serializer):
    """The test notification that was sent."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    notification_type = serializers.CharField()


class MetadataColumnFieldsSerializer(serializers.Serializer):
    """A column to add to the metadata table."""

    name = serializers.CharField()
    type = serializers.CharField(default="characteristics")
    value = serializers.CharField(required=False, allow_blank=True)
    mandatory = serializers.BooleanField(default=False)
    hidden = serializers.BooleanField(default=False)
    readonly = serializers.BooleanField(default=False)


class MetadataColumnAddedSerializer(serializers.Serializer):
    """The column that was added."""

    message = serializers.CharField()
    column = MetadataColumnSerializer()


class MetadataValueUpdateSerializer(serializers.Serializer):
    """A new default value for a column of the metadata table."""

    column_id = serializers.IntegerField()
    value = serializers.CharField(allow_blank=True, required=False)


class MetadataValueUpdatedSerializer(serializers.Serializer):
    """The column whose default value was changed."""

    message = serializers.CharField()
    column_name = serializers.CharField()
    new_value = serializers.CharField(allow_blank=True)


class JobChangedSerializer(serializers.Serializer):
    """The job after the change."""

    message = serializers.CharField()
    job = InstrumentJobSerializer()


class JobAutocompleteSerializer(serializers.Serializer):
    """Values the user has entered in earlier jobs."""

    funders = serializers.ListField(child=serializers.CharField())
    cost_centers = serializers.ListField(child=serializers.CharField())
    search_engines = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), help_text="Versions used, by search engine"
    )


class ColumnValuesSerializer(serializers.Serializer):
    """Distinct values of a column across the project's job metadata, most recent first."""

    values = serializers.ListField(child=serializers.CharField())


class JobMetadataFromTemplateSerializer(serializers.Serializer):
    """A template to build the job's metadata table from."""

    template_id = serializers.IntegerField()
    name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    sample_count = serializers.IntegerField(required=False)
    lab_group_id = serializers.IntegerField(required=False, allow_null=True)


class JobMetadataCreatedSerializer(serializers.Serializer):
    """The metadata table created for the job."""

    message = serializers.CharField()
    metadata_table = MetadataTableSerializer()
    job_id = serializers.IntegerField()


class TranscriptionQueuedSerializer(serializers.Serializer):
    """The annotation whose transcription was queued."""

    message = serializers.CharField()
    annotation_id = serializers.IntegerField()
