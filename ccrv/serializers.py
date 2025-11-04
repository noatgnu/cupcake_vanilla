"""
CUPCAKE Red Velvet (CCRV) Serializers.

Django REST Framework serializers for project and protocol management models,
faithfully representing the migrated model structure.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import serializers

from ccc.models import RemoteHost
from ccm.models import Reagent
from ccm.serializers import ReagentSerializer

from .models import (
    InstrumentUsageSessionAnnotation,
    InstrumentUsageStepAnnotation,
    Project,
    ProtocolModel,
    ProtocolRating,
    ProtocolReagent,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotation,
    SessionAnnotationFolder,
    StepAnnotation,
    StepReagent,
    StepVariation,
    TimeKeeper,
    TimeKeeperEvent,
)

User = get_user_model()

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


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
        from ccrv.tasks.transcribe_tasks import transcribe_audio, transcribe_audio_from_video
        from ccv.task_models import AsyncTaskStatus

        file_path = annotation.file.path
        model_path = settings.WHISPERCPP_DEFAULT_MODEL

        task_type = "TRANSCRIBE_AUDIO" if annotation_type == "audio" else "TRANSCRIBE_VIDEO"

        task_status = AsyncTaskStatus.objects.create(
            task_type=task_type,
            status="QUEUED",
            user=annotation.owner,
            parameters={
                "annotation_id": annotation.id,
                "file_path": file_path,
                "language": "auto",
                "translate": True,
            },
            queue_name="transcribe",
        )

        if annotation_type == "audio":
            job = transcribe_audio.delay(
                audio_path=file_path,
                model_path=model_path,
                annotation_id=annotation.id,
                language="auto",
                translate=True,
                task_id=str(task_status.id),
            )
            task_status.rq_job_id = job.id
            task_status.save(update_fields=["rq_job_id"])
            logger.info(f"Queued audio transcription for annotation {annotation.id} with task {task_status.id}")
        elif annotation_type == "video":
            job = transcribe_audio_from_video.delay(
                video_path=file_path,
                model_path=model_path,
                annotation_id=annotation.id,
                language="auto",
                translate=True,
                task_id=str(task_status.id),
            )
            task_status.rq_job_id = job.id
            task_status.save(update_fields=["rq_job_id"])
            logger.info(f"Queued video transcription for annotation {annotation.id} with task {task_status.id}")

    except Exception as e:
        logger.error(f"Failed to queue transcription for annotation {annotation.id}: {str(e)}")


class UserBasicSerializer(serializers.ModelSerializer):
    """Basic user information for nested serialization."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]
        read_only_fields = ["id", "username", "first_name", "last_name", "email"]


class RemoteHostSerializer(serializers.ModelSerializer):
    """Serializer for remote hosts in distributed system (CCC RemoteHost)."""

    class Meta:
        model = RemoteHost
        fields = [
            "id",
            "host_name",
            "host_port",
            "host_protocol",
            "host_description",
            "host_token",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProtocolRatingSerializer(serializers.ModelSerializer):
    """Serializer for protocol ratings with original validation."""

    user_username = serializers.CharField(source="user.username", read_only=True)
    user_display_name = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolRating
        fields = [
            "id",
            "protocol",
            "user",
            "user_username",
            "user_display_name",
            "complexity_rating",
            "duration_rating",
            "created_at",
            "updated_at",
            "remote_id",
            "remote_host",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_user_display_name(self, obj):
        """Get display name for user."""
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        return obj.user.username


class ProtocolStepSerializer(serializers.ModelSerializer):
    """Serializer for protocol steps with linked-list navigation."""

    next_steps = serializers.SerializerMethodField()
    section_description = serializers.CharField(source="step_section.section_description", read_only=True)
    has_next = serializers.SerializerMethodField()
    has_previous = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolStep
        fields = [
            "id",
            "protocol",
            "step_id",
            "step_description",
            "step_section",
            "section_description",
            "step_duration",
            "order",
            "previous_step",
            "next_steps",
            "has_next",
            "has_previous",
            "original",
            "branch_from",
            "created_at",
            "updated_at",
            "remote_id",
            "remote_host",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_next_steps(self, obj):
        """Get next steps in the linked list."""
        next_steps = obj.next_step.all()
        return [
            {
                "id": step.id,
                "step_description": step.step_description[:100] + "..."
                if len(step.step_description) > 100
                else step.step_description,
            }
            for step in next_steps
        ]

    def get_has_next(self, obj):
        """Check if step has next steps."""
        return obj.next_step.exists()

    def get_has_previous(self, obj):
        """Check if step has a previous step."""
        return obj.previous_step is not None


class ProtocolSectionSerializer(serializers.ModelSerializer):
    """Serializer for protocol sections with linked-list navigation."""

    steps = ProtocolStepSerializer(many=True, read_only=True)
    steps_in_order = serializers.SerializerMethodField()
    first_step = serializers.SerializerMethodField()
    last_step = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolSection
        fields = [
            "id",
            "protocol",
            "section_description",
            "section_duration",
            "order",
            "steps",
            "steps_in_order",
            "first_step",
            "last_step",
            "created_at",
            "updated_at",
            "remote_id",
            "remote_host",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_steps_in_order(self, obj):
        """Get steps in order using efficient order attribute (new optimized method)."""
        ordered_steps = obj.get_steps_by_order()
        return [
            {
                "id": step.id,
                "step_description": step.step_description[:100] + "..."
                if len(step.step_description) > 100
                else step.step_description,
                "order": step.order,
            }
            for step in ordered_steps
        ]

    def get_first_step(self, obj):
        """Get first step in section."""
        first_step = obj.get_first_in_section()
        if first_step:
            return {
                "id": first_step.id,
                "step_description": first_step.step_description[:100] + "..."
                if len(first_step.step_description) > 100
                else first_step.step_description,
            }
        return None

    def get_last_step(self, obj):
        """Get last step in section."""
        last_step = obj.get_last_in_section()
        if last_step:
            return {
                "id": last_step.id,
                "step_description": last_step.step_description[:100] + "..."
                if len(last_step.step_description) > 100
                else last_step.step_description,
            }
        return None


class ProtocolModelSerializer(serializers.ModelSerializer):
    """Serializer for protocol models with all original functionality."""

    owner_username = serializers.CharField(source="owner.username", read_only=True)
    owner_display_name = serializers.SerializerMethodField()
    editors_usernames = serializers.StringRelatedField(source="editors", many=True, read_only=True)
    viewers_usernames = serializers.StringRelatedField(source="viewers", many=True, read_only=True)

    # Related data
    sections = ProtocolSectionSerializer(many=True, read_only=True)
    ratings = ProtocolRatingSerializer(many=True, read_only=True)
    remote_host_info = RemoteHostSerializer(source="remote_host", read_only=True)

    # Computed fields
    steps_count = serializers.SerializerMethodField()
    average_complexity = serializers.SerializerMethodField()
    average_duration = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolModel
        fields = [
            "id",
            "protocol_id",
            "protocol_created_on",
            "protocol_doi",
            "protocol_title",
            "protocol_url",
            "protocol_version_uri",
            "protocol_description",
            "enabled",
            "model_hash",
            "owner",
            "owner_username",
            "owner_display_name",
            "editors",
            "editors_usernames",
            "viewers",
            "viewers_usernames",
            "sections",
            "ratings",
            "steps_count",
            "average_complexity",
            "average_duration",
            "remote_id",
            "remote_host",
            "remote_host_info",
            "is_vaulted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_owner_display_name(self, obj):
        """Get display name for owner."""
        if obj.owner and obj.owner.first_name and obj.owner.last_name:
            return f"{obj.owner.first_name} {obj.owner.last_name}"
        return obj.owner.username if obj.owner else None

    def get_steps_count(self, obj):
        """Get total number of steps in protocol."""
        return obj.steps.count()

    def get_average_complexity(self, obj):
        """Get average complexity rating."""
        ratings = obj.ratings.all()
        if not ratings.exists():
            return None
        return sum(r.complexity_rating for r in ratings) / ratings.count()

    def get_average_duration(self, obj):
        """Get average duration rating."""
        ratings = obj.ratings.all()
        if not ratings.exists():
            return None
        return sum(r.duration_rating for r in ratings) / ratings.count()


class SessionSerializer(serializers.ModelSerializer):
    """Serializer for experimental sessions with original functionality."""

    owner_username = serializers.CharField(source="owner.username", read_only=True)
    owner_display_name = serializers.SerializerMethodField()
    editors_usernames = serializers.StringRelatedField(source="editors", many=True, read_only=True)
    viewers_usernames = serializers.StringRelatedField(source="viewers", many=True, read_only=True)

    # Related data
    remote_host_info = RemoteHostSerializer(source="remote_host", read_only=True)

    # Computed fields
    protocol_count = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    is_running = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    import_info = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "id",
            "unique_id",
            "name",
            "enabled",
            "processing",
            "started_at",
            "ended_at",
            "owner",
            "owner_username",
            "owner_display_name",
            "editors",
            "editors_usernames",
            "viewers",
            "viewers_usernames",
            "protocols",
            "protocol_count",
            "duration",
            "is_running",
            "status",
            "import_info",
            "remote_id",
            "remote_host",
            "remote_host_info",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "unique_id", "created_at", "updated_at"]

    def get_owner_display_name(self, obj):
        """Get display name for owner."""
        if obj.owner and obj.owner.first_name and obj.owner.last_name:
            return f"{obj.owner.first_name} {obj.owner.last_name}"
        return obj.owner.username if obj.owner else None

    def get_protocol_count(self, obj):
        """Get number of protocols in session."""
        return obj.protocols.count()

    def get_duration(self, obj):
        """Get session duration in seconds."""
        if obj.started_at and obj.ended_at:
            return (obj.ended_at - obj.started_at).total_seconds()
        return None

    def get_is_running(self, obj):
        """Check if session is currently running."""
        return obj.started_at and not obj.ended_at

    def get_status(self, obj):
        """Get human-readable session status."""
        if obj.processing:
            return "processing"
        elif obj.started_at and not obj.ended_at:
            return "running"
        elif obj.ended_at:
            return "completed"
        elif obj.enabled:
            return "ready"
        else:
            return "draft"

    def get_import_info(self, obj):
        """Get import source information."""
        return {"is_imported": obj.is_imported, "import_source_info": obj.import_source_info}


class SessionAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for session annotations with metadata table functionality."""

    session_name = serializers.CharField(source="session.name", read_only=True)
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
    metadata_table_name = serializers.CharField(source="metadata_table.name", read_only=True)
    metadata_table_id = serializers.IntegerField(source="metadata_table.id", read_only=True)
    metadata_columns_count = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = SessionAnnotation
        fields = [
            "id",
            "session",
            "session_name",
            "annotation",
            "annotation_type",
            "annotation_text",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "order",
            "metadata_table",
            "metadata_table_name",
            "metadata_table_id",
            "metadata_columns_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "session_name",
            "annotation_type",
            "transcribed",
            "file_url",
            "metadata_table_name",
            "metadata_table_id",
            "metadata_columns_count",
        ]

    def get_metadata_columns_count(self, obj):
        """Get the number of metadata columns for this session annotation."""
        return obj.get_metadata_columns().count()

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


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for projects with AbstractResource integration."""

    owner_username = serializers.CharField(source="owner.username", read_only=True)
    owner_display_name = serializers.SerializerMethodField()

    # Related data
    remote_host_info = RemoteHostSerializer(source="remote_host", read_only=True)
    sessions = serializers.PrimaryKeyRelatedField(many=True, queryset=Session.objects.all(), required=False)

    # Computed fields
    session_count = serializers.SerializerMethodField()
    active_session_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "project_name",
            "project_description",
            "owner",
            "owner_username",
            "owner_display_name",
            "sessions",
            "session_count",
            "active_session_count",
            "remote_id",
            "remote_host",
            "remote_host_info",
            "is_vaulted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_owner_display_name(self, obj):
        """Get display name for owner."""
        if obj.owner and obj.owner.first_name and obj.owner.last_name:
            return f"{obj.owner.first_name} {obj.owner.last_name}"
        return obj.owner.username if obj.owner else None

    def get_session_count(self, obj):
        """Get total number of sessions."""
        return obj.sessions.count()

    def get_active_session_count(self, obj):
        """Get number of enabled sessions."""
        return obj.sessions.filter(enabled=True).count()


class ProjectCreateSerializer(ProjectSerializer):
    """Serializer for creating projects with automatic owner assignment."""

    class Meta(ProjectSerializer.Meta):
        fields = [
            "id",
            "project_name",
            "project_description",
            "owner",
            "sessions",
            "remote_id",
            "remote_host",
            "is_vaulted",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        """Create project with current user as owner."""
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class ProtocolModelCreateSerializer(ProtocolModelSerializer):
    """Serializer for creating protocols with automatic owner assignment."""

    class Meta(ProtocolModelSerializer.Meta):
        fields = [
            "id",
            "protocol_id",
            "protocol_created_on",
            "protocol_doi",
            "protocol_title",
            "protocol_url",
            "protocol_version_uri",
            "protocol_description",
            "enabled",
            "model_hash",
            "owner",
            "editors",
            "viewers",
            "remote_id",
            "remote_host",
            "is_vaulted",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        """Create protocol with current user as owner."""
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class SessionCreateSerializer(SessionSerializer):
    """Serializer for creating sessions with automatic owner assignment."""

    class Meta(SessionSerializer.Meta):
        fields = [
            "id",
            "unique_id",
            "name",
            "enabled",
            "owner",
            "protocols",
            "editors",
            "viewers",
            "remote_id",
            "remote_host",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        """Create session with current user as owner."""
        validated_data["owner"] = self.context["request"].user
        # Generate unique_id automatically
        import uuid

        validated_data["unique_id"] = uuid.uuid4()
        return super().create(validated_data)


class ProtocolReagentSerializer(serializers.ModelSerializer):
    """Serializer for ProtocolReagent model with reagent details."""

    reagent = ReagentSerializer(read_only=True)
    reagent_id = serializers.PrimaryKeyRelatedField(source="reagent", queryset=Reagent.objects.all(), write_only=True)
    reagent_name = serializers.CharField(source="reagent.name", read_only=True)
    reagent_unit = serializers.CharField(source="reagent.unit", read_only=True)

    class Meta:
        model = ProtocolReagent
        fields = [
            "id",
            "protocol",
            "reagent",
            "reagent_id",
            "reagent_name",
            "reagent_unit",
            "quantity",
            "created_at",
            "updated_at",
            "remote_id",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class StepReagentSerializer(serializers.ModelSerializer):
    """Serializer for StepReagent model with reagent details and scaling."""

    reagent = ReagentSerializer(read_only=True)
    reagent_id = serializers.PrimaryKeyRelatedField(source="reagent", queryset=Reagent.objects.all(), write_only=True)
    reagent_name = serializers.CharField(source="reagent.name", read_only=True)
    reagent_unit = serializers.CharField(source="reagent.unit", read_only=True)
    scaled_quantity = serializers.SerializerMethodField()

    class Meta:
        model = StepReagent
        fields = [
            "id",
            "step",
            "reagent",
            "reagent_id",
            "reagent_name",
            "reagent_unit",
            "quantity",
            "scalable",
            "scalable_factor",
            "scaled_quantity",
            "created_at",
            "updated_at",
            "remote_id",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_scaled_quantity(self, obj):
        """Calculate scaled quantity based on scalable factor."""
        if obj.scalable and obj.scalable_factor:
            return obj.quantity * obj.scalable_factor
        return obj.quantity


class StepVariationSerializer(serializers.ModelSerializer):
    """Serializer for StepVariation model."""

    step_description = serializers.CharField(source="step.step_description", read_only=True)

    class Meta:
        model = StepVariation
        fields = [
            "id",
            "step",
            "step_description",
            "variation_description",
            "variation_duration",
            "created_at",
            "updated_at",
            "remote_id",
            "remote_host",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TimeKeeperEventSerializer(serializers.ModelSerializer):
    """Serializer for TimeKeeperEvent model."""

    class Meta:
        model = TimeKeeperEvent
        fields = [
            "id",
            "time_keeper",
            "event_type",
            "event_time",
            "duration_at_event",
            "notes",
        ]
        read_only_fields = ["id", "event_time"]


class TimeKeeperSerializer(serializers.ModelSerializer):
    """Serializer for TimeKeeper model with session and step details."""

    session_name = serializers.CharField(source="session.name", read_only=True)
    step_description = serializers.CharField(source="step.step_description", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    duration_formatted = serializers.SerializerMethodField()
    original_duration_formatted = serializers.SerializerMethodField()
    events = TimeKeeperEventSerializer(many=True, read_only=True)

    class Meta:
        model = TimeKeeper
        fields = [
            "id",
            "name",
            "start_time",
            "session",
            "session_name",
            "step",
            "step_description",
            "user",
            "user_username",
            "started",
            "current_duration",
            "duration_formatted",
            "original_duration",
            "original_duration_formatted",
            "events",
            "remote_id",
            "remote_host",
        ]
        read_only_fields = ["id", "start_time", "user"]

    def get_duration_formatted(self, obj):
        """Format duration in human-readable format."""
        if obj.current_duration:
            hours = obj.current_duration // 3600
            minutes = (obj.current_duration % 3600) // 60
            seconds = obj.current_duration % 60
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return "0s"

    def get_original_duration_formatted(self, obj):
        """Format original duration in human-readable format."""
        if obj.original_duration:
            hours = obj.original_duration // 3600
            minutes = (obj.original_duration % 3600) // 60
            seconds = obj.original_duration % 60
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return None


class StepAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for StepAnnotation model."""

    session_name = serializers.CharField(source="session.name", read_only=True)
    step_description = serializers.CharField(source="step.step_description", read_only=True)
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
    instrument_usage_ids = serializers.SerializerMethodField()

    class Meta:
        model = StepAnnotation
        fields = [
            "id",
            "session",
            "session_name",
            "step",
            "step_description",
            "annotation",
            "annotation_name",
            "annotation_type",
            "annotation_text",
            "transcribed",
            "transcription",
            "language",
            "translation",
            "scratched",
            "file_url",
            "instrument_usage_ids",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "session_name",
            "step_description",
            "annotation_name",
            "annotation_type",
            "transcribed",
            "file_url",
            "instrument_usage_ids",
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
            token = obj.annotation.generate_download_token(request.user)
            download_path = reverse("ccc:annotation-download", kwargs={"pk": obj.annotation.id})
            return request.build_absolute_uri(f"{download_path}?token={token}")
        except Exception:
            return None

    def get_instrument_usage_ids(self, obj):
        """Get list of linked instrument usage booking IDs."""
        return list(obj.instrument_usage_links.values_list("instrument_usage_id", flat=True))


class SessionAnnotationFolderSerializer(serializers.ModelSerializer):
    """Serializer for SessionAnnotationFolder model."""

    session_name = serializers.CharField(source="session.name", read_only=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True)

    class Meta:
        model = SessionAnnotationFolder
        fields = [
            "id",
            "session",
            "session_name",
            "folder",
            "folder_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "session_name",
            "folder_name",
            "created_at",
        ]


class InstrumentUsageStepAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentUsageStepAnnotation model."""

    step_annotation_details = StepAnnotationSerializer(source="step_annotation", read_only=True)
    instrument_name = serializers.CharField(source="instrument_usage.instrument.instrument_name", read_only=True)

    class Meta:
        model = InstrumentUsageStepAnnotation
        fields = [
            "id",
            "step_annotation",
            "step_annotation_details",
            "instrument_usage",
            "instrument_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "step_annotation_details",
            "instrument_name",
            "created_at",
        ]


class InstrumentUsageSessionAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for InstrumentUsageSessionAnnotation model."""

    session_annotation_details = SessionAnnotationSerializer(source="session_annotation", read_only=True)
    instrument_name = serializers.CharField(source="instrument_usage.instrument.instrument_name", read_only=True)

    class Meta:
        model = InstrumentUsageSessionAnnotation
        fields = [
            "id",
            "session_annotation",
            "session_annotation_details",
            "instrument_usage",
            "instrument_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "session_annotation_details",
            "instrument_name",
            "created_at",
        ]
