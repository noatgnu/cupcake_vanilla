"""Request and response shapes of the CUPCAKE Red Velvet custom actions, for the OpenAPI schema."""

from django.apps import apps

from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

from ccv.serializers import MetadataColumnSerializer, MetadataTableSerializer

from .serializers import (
    ProtocolRatingSerializer,
    ProtocolReagentSerializer,
    ProtocolSectionSerializer,
    ProtocolStepSerializer,
    SessionSerializer,
    StepReagentSerializer,
    TimeKeeperSerializer,
)

if apps.is_installed("ccmc"):
    from ccmc.serializers import WebRTCSessionSerializer

    WEBRTC_SESSION = WebRTCSessionSerializer
    WEBRTC_SESSION_LIST = WebRTCSessionSerializer(many=True)
else:
    WEBRTC_SESSION = OpenApiTypes.OBJECT
    WEBRTC_SESSION_LIST = OpenApiTypes.OBJECT


class ProtocolEnabledSerializer(serializers.Serializer):
    """The protocol's new enabled state."""

    message = serializers.CharField()
    enabled = serializers.BooleanField()


class ExportUrlSerializer(serializers.Serializer):
    """Signed link to the HTML export."""

    download_url = serializers.URLField()


class SessionChangedSerializer(serializers.Serializer):
    """The session after the change."""

    message = serializers.CharField()
    session = SessionSerializer()


class ProtocolIdSerializer(serializers.Serializer):
    """An enabled protocol."""

    protocol_id = serializers.IntegerField()


class RateProtocolSerializer(ProtocolIdSerializer):
    """Ratings for a protocol; an existing rating by the same user is replaced."""

    complexity_rating = serializers.IntegerField(min_value=0, max_value=10)
    duration_rating = serializers.IntegerField(min_value=0, max_value=10)


class RatingSavedSerializer(serializers.Serializer):
    """The created or updated rating."""

    message = serializers.CharField()
    rating = ProtocolRatingSerializer()


class OrderSerializer(serializers.Serializer):
    """A position, counted from 0."""

    order = serializers.IntegerField(min_value=0)


class SectionMovedSerializer(serializers.Serializer):
    """The section after the move."""

    message = serializers.CharField()
    section = ProtocolSectionSerializer()


class StepMovedSerializer(serializers.Serializer):
    """The step after the move."""

    message = serializers.CharField()
    step = ProtocolStepSerializer()


class ReagentQuantitySerializer(serializers.Serializer):
    """A reagent and the quantity the protocol uses."""

    reagent_id = serializers.IntegerField()
    quantity = serializers.FloatField()


class BulkAddReagentsSerializer(ProtocolIdSerializer):
    """Reagents to add to one of the user's protocols."""

    reagents = ReagentQuantitySerializer(many=True)


class ReagentsAddedSerializer(serializers.Serializer):
    """The protocol reagents that were added; invalid entries are skipped."""

    message = serializers.CharField()
    reagents = ProtocolReagentSerializer(many=True)


class ScalingFactorSerializer(serializers.Serializer):
    """A new scaling factor for the reagent."""

    scalable_factor = serializers.FloatField()


class ScalingUpdatedSerializer(serializers.Serializer):
    """The reagent with its new scaling factor."""

    message = serializers.CharField()
    reagent = StepReagentSerializer()


class BulkScaleSerializer(serializers.Serializer):
    """A scaling factor for every scalable reagent of a step."""

    step_id = serializers.IntegerField()
    scale_factor = serializers.FloatField()


class TimerStartedSerializer(serializers.Serializer):
    """The running timer."""

    message = serializers.CharField()
    time_keeper = TimeKeeperSerializer()


class TimerStoppedSerializer(TimerStartedSerializer):
    """The timer with the seconds it has left."""

    current_duration = serializers.IntegerField()


class SessionTimingSerializer(serializers.Serializer):
    """The user's timers in a session, added up."""

    session_id = serializers.CharField()
    total_timers = serializers.IntegerField()
    total_duration_seconds = serializers.IntegerField()
    total_duration_formatted = serializers.CharField()


class MetadataTableCreatedSerializer(serializers.Serializer):
    """The metadata table created for the annotation."""

    message = serializers.CharField()
    metadata_table = MetadataTableSerializer()


class AnnotationColumnSerializer(serializers.Serializer):
    """A column to add to the annotation's metadata table."""

    name = serializers.CharField()
    type = serializers.CharField(default="characteristics")
    value = serializers.CharField(required=False, allow_blank=True)
    mandatory = serializers.BooleanField(default=False)
    hidden = serializers.BooleanField(default=False)
    readonly = serializers.BooleanField(default=False)
    position = serializers.IntegerField(required=False, allow_null=True)


class AnnotationColumnAddedSerializer(serializers.Serializer):
    """The column that was added."""

    message = serializers.CharField()
    column = MetadataColumnSerializer()


class ColumnValueSerializer(serializers.Serializer):
    """A new value for the column."""

    value = serializers.CharField(allow_blank=True)
