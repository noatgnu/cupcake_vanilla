"""
CUPCAKE Red Velvet (CCRV) ViewSets.

Django REST Framework viewsets for project and protocol management API endpoints,
faithfully representing the migrated functionality.
"""

import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
)
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ccc.api_schema import ActionMessageSerializer, DetailSerializer, ErrorSerializer
from ccc.mixins import DeletionLogMixin
from ccc.models import Annotation, LabGroup, ResourceVisibility
from ccc.permissions import IsOwnerOrReadOnly
from ccc.serializers import AnnotationFolderSerializer
from ccm.api_schema import TranscriptionQueuedSerializer
from ccv.serializers import MetadataColumnSerializer, MetadataTableSerializer

from .api_schema import (
    WEBRTC_SESSION,
    WEBRTC_SESSION_LIST,
    AnnotationColumnAddedSerializer,
    AnnotationColumnSerializer,
    BulkAddReagentsSerializer,
    BulkScaleSerializer,
    ColumnValueSerializer,
    ExportUrlSerializer,
    MetadataTableCreatedSerializer,
    OrderSerializer,
    ProtocolEnabledSerializer,
    ProtocolIdSerializer,
    RateProtocolSerializer,
    RatingSavedSerializer,
    ReagentsAddedSerializer,
    ScalingFactorSerializer,
    ScalingUpdatedSerializer,
    SectionMovedSerializer,
    SessionChangedSerializer,
    SessionTimingSerializer,
    StepMovedSerializer,
    TimerStartedSerializer,
    TimerStoppedSerializer,
)
from .export_utils import save_protocol_export_to_temp, save_session_export_to_temp
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
from .permissions import (
    ModelEditDeletePermission,
    OwnerOrEditorWritePermission,
    ProtocolAccessPermission,
    SessionAccessPermission,
    asks_for_one,
    is_owner_or_editor,
    is_rater,
    is_session_member,
    is_staff_or_superuser,
    protocol_viewer_q,
    protocol_visible_to,
    require_owner_or_editor,
    session_viewer_q,
    visible_booking_links,
    visible_through_session,
)
from .serializers import (
    InstrumentUsageSessionAnnotationSerializer,
    InstrumentUsageStepAnnotationSerializer,
    ProjectCreateSerializer,
    ProjectSerializer,
    ProtocolModelCreateSerializer,
    ProtocolModelSerializer,
    ProtocolRatingSerializer,
    ProtocolReagentSerializer,
    ProtocolSectionSerializer,
    ProtocolStepSerializer,
    SessionAnnotationFolderSerializer,
    SessionAnnotationSerializer,
    SessionCreateSerializer,
    SessionSerializer,
    StepAnnotationSerializer,
    StepReagentSerializer,
    StepVariationSerializer,
    TimeKeeperSerializer,
    queue_annotation_transcription,
)

logger = logging.getLogger(__name__)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing experimental projects.

    Integrates with AbstractResource for ownership and lab group permissions.
    """

    queryset = Project.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_serializer_class(self):
        if self.action == "create":
            return ProjectCreateSerializer
        return ProjectSerializer

    def get_queryset(self):
        """Filter projects based on user permissions from AbstractResource (includes bubble-up from sub-groups)."""
        user = self.request.user
        if is_staff_or_superuser(user):
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(Q(owner=user) | Q(lab_group_id__in=accessible_groups)).distinct()

    @extend_schema(tags=["projects"], responses={200: SessionSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def sessions(self, request, pk=None):
        """Get all sessions for this project."""
        project = self.get_object()
        sessions = project.sessions.all()
        serializer = SessionSerializer(sessions, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(tags=["projects"], filters=False, responses={200: ProjectSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def my_projects(self, request):
        """Get projects owned by the current user."""
        projects = Project.objects.filter(owner=request.user)
        serializer = self.get_serializer(projects, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["projects"], filters=False, responses={200: ProjectSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def vaulted_projects(self, request):
        """Get vaulted/imported projects for the current user."""
        projects = self.get_queryset().filter(is_vaulted=True)
        serializer = self.get_serializer(projects, many=True)
        return Response(serializer.data)


class ProtocolModelViewSet(DeletionLogMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing experimental protocols.

    Preserves all original functionality including protocols.io integration.
    Supports filtering by access type: public, owned, or shared.
    """

    queryset = ProtocolModel.objects.all()
    permission_classes = [permissions.IsAuthenticated, ProtocolAccessPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "updated_at": ["gte", "lte"],
    }

    def get_serializer_class(self):
        if self.action == "create":
            return ProtocolModelCreateSerializer
        return ProtocolModelSerializer

    def get_queryset(self):
        """
        Filter protocols based on user permissions and optional access_type parameter.

        Query parameters:
        - access_type: Filter by access type ('public', 'owned', 'shared')
          - 'public': Protocols with public visibility
          - 'owned': Protocols owned by the current user
          - 'shared': Protocols shared with the user (editor/viewer or via lab group)
        """
        user = self.request.user
        base_queryset = self.queryset

        if is_staff_or_superuser(user):
            queryset = base_queryset
        else:
            queryset = base_queryset.filter(protocol_viewer_q(user, include_public_sessions=self.detail)).distinct()

        access_type = self.request.query_params.get("access_type", None)

        if access_type == "public":
            queryset = queryset.filter(visibility=ResourceVisibility.PUBLIC)
        elif access_type == "owned":
            queryset = queryset.filter(owner=user)
        elif access_type == "shared":
            queryset = queryset.filter(protocol_viewer_q(user)).exclude(owner=user).distinct()

        return queryset

    @extend_schema(
        tags=["protocols"],
        request=None,
        responses={200: ProtocolEnabledSerializer},
    )
    @action(detail=True, methods=["post"])
    def toggle_enabled(self, request, pk=None):
        """Toggle the enabled status of this protocol."""
        protocol = self.get_object()
        protocol.enabled = not protocol.enabled
        protocol.save(update_fields=["enabled"])

        return Response(
            {"message": f'Protocol {"enabled" if protocol.enabled else "disabled"}', "enabled": protocol.enabled}
        )

    @extend_schema(tags=["protocols"], responses={200: ProtocolStepSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        """Get all steps for this protocol."""
        protocol = self.get_object()
        steps = protocol.steps.all()
        serializer = ProtocolStepSerializer(steps, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], responses={200: ProtocolSectionSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def sections(self, request, pk=None):
        """Get all sections for this protocol."""
        protocol = self.get_object()
        sections = protocol.sections.all()
        serializer = ProtocolSectionSerializer(sections, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], responses={200: ProtocolRatingSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def ratings(self, request, pk=None):
        """Get all ratings for this protocol."""
        protocol = self.get_object()
        ratings = protocol.ratings.all()
        serializer = ProtocolRatingSerializer(ratings, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], filters=False, responses={200: ProtocolModelSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def enabled_protocols(self, request):
        """Get all enabled protocols."""
        protocols = self.get_queryset().filter(enabled=True)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], filters=False, responses={200: ProtocolModelSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def vaulted_protocols(self, request):
        """Get vaulted/imported protocols."""
        protocols = self.get_queryset().filter(is_vaulted=True)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], filters=False, responses={200: ProtocolModelSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def public_protocols(self, request):
        """Get all publicly accessible protocols."""
        protocols = self.get_queryset().filter(visibility=ResourceVisibility.PUBLIC)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], filters=False, responses={200: ProtocolModelSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def my_protocols(self, request):
        """Get protocols owned by the current user."""
        protocols = self.get_queryset().filter(owner=request.user)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["protocols"], filters=False, responses={200: ProtocolModelSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def shared_with_me(self, request):
        """Get protocols shared with the current user (not owned by them)."""
        user = request.user
        protocols = self.get_queryset().filter(protocol_viewer_q(user)).exclude(owner=user).distinct()

        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["protocols"],
        parameters=[OpenApiParameter("session", int, description="Include the annotations of this session")],
        responses={200: ExportUrlSerializer},
    )
    @action(detail=True, methods=["get"])
    def get_export_url(self, request, pk=None):
        """
        Generate a signed download URL for protocol HTML export.

        Query parameters:
            session: Optional session ID to include session-specific annotations

        Returns:
            {"download_url": "URL with signed token"}
        """
        protocol = self.get_object()
        session_id = request.query_params.get("session")

        token = protocol.generate_export_token(request.user, session_id=session_id)
        download_path = f"/api/v1/protocols/{protocol.id}/export_html/"
        download_url = request.build_absolute_uri(f"{download_path}?token={token}")

        return Response({"download_url": download_url})

    @extend_schema(
        tags=["protocols"],
        auth=[],
        parameters=[OpenApiParameter("token", str, required=True, description="Signed token from get_export_url")],
        responses={
            (200, "text/html"): OpenApiTypes.STR,
            (400, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Missing token"),
            (403, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Invalid token or no access"),
            (404, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Session not found"),
        },
    )
    @action(detail=True, methods=["get"], permission_classes=[])
    def export_html(self, request, pk=None):
        """
        Export protocol as HTML document using signed token.

        Query parameters:
            token: Required signed token for download

        Generates temporary HTML file and serves via X-Accel-Redirect.
        """
        signed_token = request.query_params.get("token")
        if not signed_token:
            return HttpResponse("Missing token", status=400)

        protocol, user, session_id = ProtocolModel.verify_export_token(signed_token)

        if not protocol:
            return HttpResponse("Invalid or expired token", status=403)

        if protocol.id != int(pk):
            return HttpResponse("Token does not match protocol", status=403)

        if not (protocol_visible_to(protocol, user) or protocol.can_view(user)):
            return HttpResponse("Permission denied", status=403)

        session = None
        if session_id:
            try:
                session = Session.objects.get(id=session_id, protocols=protocol)
                if not session.can_view(user):
                    return HttpResponse("Permission denied for session", status=403)
            except Session.DoesNotExist:
                return HttpResponse("Session not found", status=404)

        temp_path, filename = save_protocol_export_to_temp(protocol, session=session)

        is_electron = getattr(settings, "IS_ELECTRON_ENVIRONMENT", False)

        if is_electron:
            media_root = Path(settings.MEDIA_ROOT)
            full_path = media_root / temp_path

            with open(full_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            response = HttpResponse(html_content, content_type="text/html")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        else:
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"/internal/media/{temp_path}"
            response["Content-Type"] = "text/html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

        origin = request.META.get("HTTP_ORIGIN")
        cors_allowed_origins = getattr(settings, "CORS_ORIGIN_WHITELIST", [])

        if origin and origin in cors_allowed_origins:
            response["X-Accel-CORS-Origin"] = origin
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response["Access-Control-Allow-Headers"] = ", ".join(getattr(settings, "CORS_ALLOW_HEADERS", []))

        return response


class SessionViewSet(DeletionLogMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing experimental sessions.

    Preserves original session management and import tracking functionality.
    """

    queryset = Session.objects.all()
    permission_classes = [permissions.IsAuthenticated, SessionAccessPermission]
    public_actions = ("retrieve", "get_export_url", "webrtc_sessions")
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        "unique_id": ["exact"],
        "enabled": ["exact"],
        "processing": ["exact"],
        "projects": ["exact"],
        "updated_at": ["gte", "lte"],
    }
    search_fields = ["name"]
    ordering_fields = ["created_at", "started_at", "ended_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return SessionCreateSerializer
        return SessionSerializer

    def get_queryset(self):
        """Sessions the user owns, edits or views, and public sessions the user unlocked, asked for by id or unique id."""
        return visible_through_session(
            self.queryset, self.request.user, prefix="", include_public=asks_for_one(self, "unique_id")
        )

    def perform_destroy(self, instance):
        """Delete the session, then the annotations and files that only this session used."""
        annotation_ids = set(StepAnnotation.objects.filter(session=instance).values_list("annotation_id", flat=True))
        annotation_ids |= set(
            SessionAnnotation.objects.filter(session=instance).values_list("annotation_id", flat=True)
        )
        super().perform_destroy(instance)
        for annotation in Annotation.objects.filter(id__in=annotation_ids):
            if not annotation.is_attached():
                annotation.delete_with_file()

    def list(self, request, *args, **kwargs):
        """List sessions; asking for a public session by its unique id unlocks it for the user."""
        self.unlock_by_unique_id(request.query_params.get("unique_id"), request.user)
        return super().list(request, *args, **kwargs)

    def unlock_by_unique_id(self, unique_id, user):
        """Record that the user opened the public session with this unique id through its link."""
        try:
            session_uuid = uuid.UUID(str(unique_id))
        except ValueError:
            return
        session = Session.objects.filter(unique_id=session_uuid, enabled=True).first()
        if session is not None and not is_session_member(session, user):
            session.link_unlocked_by.add(user)

    @extend_schema(
        tags=["sessions"],
        request=None,
        responses={200: SessionChangedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """Start the session (original functionality)."""
        session = self.get_object()

        if session.started_at:
            return Response({"error": "Session has already been started"}, status=status.HTTP_400_BAD_REQUEST)

        # Use original logic
        session.started_at = timezone.now()
        session.enabled = True
        session.save(update_fields=["started_at", "enabled"])

        serializer = self.get_serializer(session)
        return Response({"message": "Session started successfully", "session": serializer.data})

    @extend_schema(
        tags=["sessions"],
        request=None,
        responses={200: SessionChangedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """End the session (original functionality)."""
        session = self.get_object()

        if not session.started_at:
            return Response({"error": "Session has not been started yet"}, status=status.HTTP_400_BAD_REQUEST)

        if session.ended_at:
            return Response({"error": "Session has already ended"}, status=status.HTTP_400_BAD_REQUEST)

        # Use original logic
        session.ended_at = timezone.now()
        session.processing = False
        session.save(update_fields=["ended_at", "processing"])

        serializer = self.get_serializer(session)
        return Response({"message": "Session ended successfully", "session": serializer.data})

    @extend_schema(tags=["sessions"], responses={200: WEBRTC_SESSION_LIST})
    @action(detail=True, methods=["get"])
    def webrtc_sessions(self, request, pk=None):
        """Get all WebRTC sessions associated with this experimental session."""
        session = self.get_object()

        from ccmc.serializers import WebRTCSessionSerializer

        webrtc_sessions = session.webrtc_sessions.all().select_related("initiated_by").prefetch_related("peers__user")

        serializer = WebRTCSessionSerializer(webrtc_sessions, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=["sessions"],
        request=None,
        responses={200: WEBRTC_SESSION},
    )
    @action(detail=True, methods=["post"])
    def join_default_webrtc(self, request, pk=None):
        """
        Get or create the default WebRTC session for this experimental session.

        By default, all users joining an experimental session join the same WebRTC call
        unless they explicitly create/join a different one.
        """
        session = self.get_object()

        from ccmc.models import WebRTCSession
        from ccmc.serializers import WebRTCSessionSerializer

        default_session = (
            session.webrtc_sessions.filter(session_status__in=["waiting", "active"], is_default=True)
            .order_by("-created_at")
            .first()
        )

        if not default_session:
            default_session = WebRTCSession.objects.create(
                session_type="video_call", initiated_by=request.user, is_default=True
            )
            session.webrtc_sessions.add(default_session)

        serializer = WebRTCSessionSerializer(default_session, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=["sessions"],
        request=ProtocolIdSerializer,
        responses={200: ActionMessageSerializer, 400: ErrorSerializer, 404: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def add_protocol(self, request, pk=None):
        """Add a protocol to this session."""
        session = self.get_object()
        protocol_id = request.data.get("protocol_id")

        if not protocol_id:
            return Response({"error": "Protocol ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            protocol = ProtocolModel.objects.get(id=protocol_id, enabled=True)
            session.protocols.add(protocol)
            return Response({"message": f'Protocol "{protocol.protocol_title}" added to session'})
        except ProtocolModel.DoesNotExist:
            return Response({"error": "Protocol not found or not enabled"}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(tags=["sessions"], filters=False, responses={200: SessionSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def running_sessions(self, request):
        """Get currently running sessions."""
        running_sessions = self.get_queryset().filter(started_at__isnull=False, ended_at__isnull=True)
        serializer = self.get_serializer(running_sessions, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["sessions"], filters=False, responses={200: SessionSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def imported_sessions(self, request):
        """Get imported sessions using original is_imported property."""
        sessions = [s for s in self.get_queryset() if s.is_imported]
        serializer = self.get_serializer(sessions, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["sessions"], responses={200: AnnotationFolderSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def folders(self, request, pk=None):
        """Get annotation folders linked to this session."""
        session = self.get_object()

        session_folders = SessionAnnotationFolder.objects.filter(session=session).select_related("folder")
        folders = [sf.folder for sf in session_folders]

        serializer = AnnotationFolderSerializer(folders, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["sessions"],
        responses={200: ExportUrlSerializer},
    )
    @action(detail=True, methods=["get"])
    def get_export_url(self, request, pk=None):
        """
        Generate a signed download URL for session HTML export.

        Returns:
            {"download_url": "URL with signed token"}
        """
        session = self.get_object()

        token = session.generate_export_token(request.user)
        download_path = f"/api/v1/sessions/{session.id}/export_html/"
        download_url = request.build_absolute_uri(f"{download_path}?token={token}")

        return Response({"download_url": download_url})

    @extend_schema(
        tags=["sessions"],
        auth=[],
        parameters=[OpenApiParameter("token", str, required=True, description="Signed token from get_export_url")],
        responses={
            (200, "text/html"): OpenApiTypes.STR,
            (400, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Missing token"),
            (403, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Invalid token or no access"),
            (404, "text/html"): OpenApiResponse(OpenApiTypes.STR, description="Session not found"),
        },
    )
    @action(detail=True, methods=["get"], permission_classes=[])
    def export_html(self, request, pk=None):
        """
        Export session protocols with annotations as a self-contained HTML document using signed token.

        Query parameters:
            token: Required signed token for download

        Generates temporary HTML file and serves via X-Accel-Redirect.
        Returns an HTML file that can be archived and shared offline.
        Includes all protocol steps, annotations, and embedded media files.
        """
        signed_token = request.query_params.get("token")
        if not signed_token:
            return HttpResponse("Missing token", status=400)

        session, user = Session.verify_export_token(signed_token)

        if not session:
            return HttpResponse("Invalid or expired token", status=403)

        if session.id != int(pk):
            return HttpResponse("Token does not match session", status=403)

        if not session.can_view(user):
            return HttpResponse("Permission denied", status=403)

        temp_path, filename = save_session_export_to_temp(session)

        is_electron = getattr(settings, "IS_ELECTRON_ENVIRONMENT", False)

        if is_electron:
            media_root = Path(settings.MEDIA_ROOT)
            full_path = media_root / temp_path

            with open(full_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            response = HttpResponse(html_content, content_type="text/html")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        else:
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"/internal/media/{temp_path}"
            response["Content-Type"] = "text/html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

        origin = request.META.get("HTTP_ORIGIN")
        cors_allowed_origins = getattr(settings, "CORS_ORIGIN_WHITELIST", [])

        if origin and origin in cors_allowed_origins:
            response["X-Accel-CORS-Origin"] = origin
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response["Access-Control-Allow-Headers"] = ", ".join(getattr(settings, "CORS_ALLOW_HEADERS", []))

        return response


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("protocol", int),
            OpenApiParameter("user", int),
            OpenApiParameter("complexity_rating", int),
            OpenApiParameter("duration_rating", int),
        ]
    )
)
class ProtocolRatingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing protocol ratings.

    Preserves original validation logic from model.
    """

    queryset = ProtocolRating.objects.all()
    serializer_class = ProtocolRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Ratings of protocols the user can access, filtered by the protocol, user and rating query parameters."""
        user = self.request.user
        queryset = self.queryset
        if not is_staff_or_superuser(user):
            queryset = queryset.filter(protocol_viewer_q(user, "protocol__")).distinct()

        params = self.request.query_params
        for param, lookup in (
            ("protocol", "protocol_id"),
            ("user", "user_id"),
            ("complexity_rating", "complexity_rating"),
            ("duration_rating", "duration_rating"),
        ):
            value = params.get(param)
            if value:
                queryset = queryset.filter(**{lookup: value})
        return queryset

    def perform_create(self, serializer):
        """Set the current user as the rating user; the protocol must be one the user can view."""
        protocol = serializer.validated_data.get("protocol")
        if protocol is None or not protocol_visible_to(protocol, self.request.user):
            raise PermissionDenied("You cannot rate this protocol")
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """Only the user who gave the rating can change it; the protocol stays the same."""
        if not is_rater(serializer.instance, self.request.user):
            raise PermissionDenied("Only the user who gave this rating can change it")
        serializer.save(protocol=serializer.instance.protocol)

    def perform_destroy(self, instance):
        """Only the user who gave the rating can delete it."""
        if not is_rater(instance, self.request.user):
            raise PermissionDenied("Only the user who gave this rating can delete it")
        instance.delete()

    @extend_schema(tags=["ratings"], filters=False, responses={200: ProtocolRatingSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def my_ratings(self, request):
        """Get ratings by the current user."""
        ratings = ProtocolRating.objects.filter(user=request.user)
        serializer = self.get_serializer(ratings, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["ratings"],
        request=RateProtocolSerializer,
        responses={
            200: RatingSavedSerializer,
            201: RatingSavedSerializer,
            400: ErrorSerializer,
            403: DetailSerializer,
            404: ErrorSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    def rate_protocol(self, request):
        """Rate a protocol (create or update existing rating)."""
        protocol_id = request.data.get("protocol_id")
        complexity_rating = request.data.get("complexity_rating")
        duration_rating = request.data.get("duration_rating")

        if not all([protocol_id, complexity_rating is not None, duration_rating is not None]):
            return Response(
                {"error": "protocol_id, complexity_rating, and duration_rating are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            protocol = ProtocolModel.objects.get(id=protocol_id)
            if not protocol_visible_to(protocol, request.user):
                raise PermissionDenied("You cannot rate this protocol")
            rating, created = ProtocolRating.objects.update_or_create(
                protocol=protocol,
                user=request.user,
                defaults={"complexity_rating": complexity_rating, "duration_rating": duration_rating},
            )

            serializer = self.get_serializer(rating)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = "Rating created" if created else "Rating updated"

            return Response({"message": message, "rating": serializer.data}, status=status_code)

        except ProtocolModel.DoesNotExist:
            return Response({"error": "Protocol not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            # This will catch the validation errors from the model's save() method
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ProtocolSectionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing protocol sections.

    Preserves original linked-list navigation methods.
    """

    queryset = ProtocolSection.objects.all()
    serializer_class = ProtocolSectionSerializer
    permission_classes = [permissions.IsAuthenticated, OwnerOrEditorWritePermission]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["protocol"]
    ordering_fields = ["order"]

    def resource_of(self, section):
        """The protocol the section belongs to."""
        return section.protocol

    def perform_create(self, serializer):
        """Only the owner or an editor of the protocol can add sections."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a section to another protocol also needs the owner or an editor of that protocol."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def get_queryset(self):
        """Filter sections based on protocol permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if is_staff_or_superuser(user):
            return self.queryset

        public = asks_for_one(self, "protocol")
        return self.queryset.filter(protocol_viewer_q(user, "protocol__", include_public_sessions=public)).distinct()

    @extend_schema(tags=["sections"], responses={200: ProtocolStepSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def steps_in_order(self, request, pk=None):
        """Get steps in order using original linked-list traversal."""
        section = self.get_object()
        ordered_steps = section.get_step_in_order()
        serializer = ProtocolStepSerializer(ordered_steps, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=["sections"],
        responses={
            200: PolymorphicProxySerializer(
                component_name="StepOrNone",
                serializers=[ProtocolStepSerializer, ActionMessageSerializer],
                resource_type_field_name=None,
            )
        },
    )
    @action(detail=True, methods=["get"])
    def first_step(self, request, pk=None):
        """Get the first step in this section."""
        section = self.get_object()
        first_step = section.get_first_in_section()
        if first_step:
            serializer = ProtocolStepSerializer(first_step, context={"request": request})
            return Response(serializer.data)
        return Response({"message": "No steps in this section"})

    @extend_schema(
        tags=["sections"],
        responses={
            200: PolymorphicProxySerializer(
                component_name="StepOrNone",
                serializers=[ProtocolStepSerializer, ActionMessageSerializer],
                resource_type_field_name=None,
            )
        },
    )
    @action(detail=True, methods=["get"])
    def last_step(self, request, pk=None):
        """Get the last step in this section."""
        section = self.get_object()
        last_step = section.get_last_in_section()
        if last_step:
            serializer = ProtocolStepSerializer(last_step, context={"request": request})
            return Response(serializer.data)
        return Response({"message": "No steps in this section"})

    @extend_schema(tags=["sections"], responses={200: ProtocolStepSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def steps_by_order(self, request, pk=None):
        """Get steps efficiently ordered by order attribute (optimized method)."""
        section = self.get_object()
        ordered_steps = section.get_steps_by_order()
        serializer = ProtocolStepSerializer(ordered_steps, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=["sections"],
        request=OrderSerializer,
        responses={200: SectionMovedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def move_to_order(self, request, pk=None):
        """Move this section to a specific order position efficiently."""
        section = self.get_object()
        new_order = request.data.get("order")

        if new_order is None:
            return Response({"error": "Order parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_order = int(new_order)
            if new_order < 0:
                return Response({"error": "Order must be a non-negative integer"}, status=status.HTTP_400_BAD_REQUEST)

            section.move_to_order(new_order)
            serializer = self.get_serializer(section)
            return Response({"message": f"Section moved to order {new_order} successfully", "section": serializer.data})
        except (ValueError, TypeError):
            return Response({"error": "Order must be a valid integer"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Failed to move section: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["sections"],
        request=None,
        responses={200: ActionMessageSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def reorder_steps(self, request, pk=None):
        """Reorder all steps in this section based on their order attributes."""
        section = self.get_object()
        try:
            section.reorder_steps()
            return Response({"message": "Steps reordered successfully"})
        except Exception as e:
            return Response({"error": f"Failed to reorder steps: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class ProtocolStepViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing protocol steps.

    Preserves original linked-list manipulation and move operations.
    """

    queryset = ProtocolStep.objects.all()
    serializer_class = ProtocolStepSerializer
    permission_classes = [permissions.IsAuthenticated, OwnerOrEditorWritePermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["protocol", "step_section", "original", "branch_from"]
    search_fields = ["step_description"]
    ordering_fields = ["order", "created_at", "step_duration"]
    ordering = ["order"]

    def resource_of(self, step):
        """The protocol the step belongs to."""
        return step.protocol

    def perform_create(self, serializer):
        """Only the owner or an editor of the protocol can add steps."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a step to another protocol also needs the owner or an editor of that protocol."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def get_queryset(self):
        """Filter steps based on protocol permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if is_staff_or_superuser(user):
            return self.queryset

        public = asks_for_one(self, "protocol", "step_section")
        return self.queryset.filter(protocol_viewer_q(user, "protocol__", include_public_sessions=public)).distinct()

    @extend_schema(
        tags=["steps"],
        request=None,
        responses={200: StepMovedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def move_up(self, request, pk=None):
        """Move this step up using original linked-list logic."""
        step = self.get_object()
        try:
            step.move_up()
            serializer = self.get_serializer(step)
            return Response({"message": "Step moved up successfully", "step": serializer.data})
        except Exception as e:
            return Response({"error": f"Failed to move step: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["steps"],
        request=None,
        responses={200: StepMovedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def move_down(self, request, pk=None):
        """Move this step down using original linked-list logic."""
        step = self.get_object()
        try:
            step.move_down()
            serializer = self.get_serializer(step)
            return Response({"message": "Step moved down successfully", "step": serializer.data})
        except Exception as e:
            return Response({"error": f"Failed to move step: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(tags=["steps"], responses={200: ProtocolStepSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def next_steps(self, request, pk=None):
        """Get next steps in the linked list."""
        step = self.get_object()
        next_steps = step.next_step.all()
        serializer = self.get_serializer(next_steps, many=True)
        return Response(serializer.data)

    @extend_schema(tags=["steps"], responses={200: ProtocolStepSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def branch_steps(self, request, pk=None):
        """Get steps that branch from this step."""
        step = self.get_object()
        branch_steps = step.branch_steps.all()
        serializer = self.get_serializer(branch_steps, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["steps"],
        request=OrderSerializer,
        responses={200: StepMovedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def move_to_order(self, request, pk=None):
        """Move this step to a specific order position efficiently."""
        step = self.get_object()
        new_order = request.data.get("order")

        if new_order is None:
            return Response({"error": "Order parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_order = int(new_order)
            if new_order < 0:
                return Response({"error": "Order must be a non-negative integer"}, status=status.HTTP_400_BAD_REQUEST)

            step.move_to_order(new_order)
            serializer = self.get_serializer(step)
            return Response({"message": f"Step moved to order {new_order} successfully", "step": serializer.data})
        except (ValueError, TypeError):
            return Response({"error": "Order must be a valid integer"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Failed to move step: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["steps"],
        request=None,
        responses={200: ActionMessageSerializer, 400: ErrorSerializer},
    )
    @action(detail=False, methods=["post"])
    def reorder_by_linked_list(self, request):
        """Migrate existing data by populating order fields from linked-list traversal."""
        try:
            protocols = None
            if not is_staff_or_superuser(request.user):
                protocols = ProtocolModel.objects.filter(Q(owner=request.user) | Q(editors=request.user)).distinct()
            ProtocolStep.reorder_by_linked_list(protocols)
            return Response({"message": "Successfully populated order fields for protocol steps"})
        except Exception as e:
            return Response(
                {"error": f"Failed to reorder by linked list: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST
            )


class ProtocolReagentViewSet(ModelViewSet):
    """ViewSet for ProtocolReagent model with reagent relationship management."""

    queryset = ProtocolReagent.objects.all()
    serializer_class = ProtocolReagentSerializer
    permission_classes = [IsAuthenticated, OwnerOrEditorWritePermission]
    pagination_class = LimitOffsetPagination

    def resource_of(self, protocol_reagent):
        """The protocol the reagent belongs to."""
        return protocol_reagent.protocol

    def perform_create(self, serializer):
        """Only the owner or an editor of the protocol can add reagents."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a reagent to another protocol also needs the owner or an editor of that protocol."""
        require_owner_or_editor(serializer.validated_data.get("protocol"), self.request.user)
        serializer.save()

    def get_queryset(self):
        """Reagents of protocols the user can view."""
        queryset = super().get_queryset()
        if not is_staff_or_superuser(self.request.user):
            queryset = queryset.filter(protocol_viewer_q(self.request.user, "protocol__")).distinct()

        # Filter by protocol if specified
        protocol_id = self.request.query_params.get("protocol")
        if protocol_id:
            queryset = queryset.filter(protocol_id=protocol_id)

        # Filter by reagent if specified
        reagent_id = self.request.query_params.get("reagent")
        if reagent_id:
            queryset = queryset.filter(reagent_id=reagent_id)

        return queryset.select_related("protocol", "reagent")

    @extend_schema(
        tags=["protocol-reagents"],
        request=BulkAddReagentsSerializer,
        responses={201: ReagentsAddedSerializer, 400: ErrorSerializer, 404: ErrorSerializer},
    )
    @action(detail=False, methods=["post"])
    def bulk_add_reagents(self, request):
        """Add multiple reagents to a protocol at once."""
        protocol_id = request.data.get("protocol_id")
        reagent_data = request.data.get("reagents", [])

        if not protocol_id:
            return Response({"error": "Protocol ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            protocol = ProtocolModel.objects.get(id=protocol_id)
        except ProtocolModel.DoesNotExist:
            return Response({"error": "Protocol not found"}, status=status.HTTP_404_NOT_FOUND)
        require_owner_or_editor(protocol, request.user)

        created_reagents = []
        for reagent_item in reagent_data:
            serializer = self.get_serializer(
                data={
                    "protocol": protocol.id,
                    "reagent_id": reagent_item.get("reagent_id"),
                    "quantity": reagent_item.get("quantity"),
                }
            )
            if serializer.is_valid():
                serializer.save()
                created_reagents.append(serializer.data)

        return Response(
            {"message": f"Added {len(created_reagents)} reagents to protocol", "reagents": created_reagents},
            status=status.HTTP_201_CREATED,
        )


class StepReagentViewSet(ModelViewSet):
    """ViewSet for StepReagent model with scaling functionality."""

    queryset = StepReagent.objects.all()
    serializer_class = StepReagentSerializer
    permission_classes = [IsAuthenticated, OwnerOrEditorWritePermission]
    pagination_class = LimitOffsetPagination

    def resource_of(self, step_reagent):
        """The protocol of the step the reagent belongs to."""
        return step_reagent.step.protocol

    def perform_create(self, serializer):
        """Only the owner or an editor of the protocol can add step reagents."""
        step = serializer.validated_data.get("step")
        require_owner_or_editor(step.protocol if step else None, self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a reagent to another step also needs the owner or an editor of that step's protocol."""
        step = serializer.validated_data.get("step")
        require_owner_or_editor(step.protocol if step else None, self.request.user)
        serializer.save()

    def get_queryset(self):
        """Reagents of steps of protocols the user can view."""
        queryset = super().get_queryset()
        if not is_staff_or_superuser(self.request.user):
            public = asks_for_one(self, "step")
            queryset = queryset.filter(
                protocol_viewer_q(self.request.user, "step__protocol__", include_public_sessions=public)
            ).distinct()

        # Filter by step if specified
        step_id = self.request.query_params.get("step")
        if step_id:
            queryset = queryset.filter(step_id=step_id)

        # Filter by reagent if specified
        reagent_id = self.request.query_params.get("reagent")
        if reagent_id:
            queryset = queryset.filter(reagent_id=reagent_id)

        # Filter scalable reagents only
        scalable_only = self.request.query_params.get("scalable")
        if scalable_only == "true":
            queryset = queryset.filter(scalable=True)

        return queryset.select_related("step", "reagent")

    @extend_schema(
        tags=["step-reagents"],
        request=ScalingFactorSerializer,
        responses={200: ScalingUpdatedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def update_scaling(self, request, pk=None):
        """Update scaling factor for a step reagent."""
        step_reagent = self.get_object()
        new_factor = request.data.get("scalable_factor")

        if new_factor is None:
            return Response({"error": "scalable_factor is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_factor = float(new_factor)
        except ValueError:
            return Response({"error": "scalable_factor must be a number"}, status=status.HTTP_400_BAD_REQUEST)

        step_reagent.scalable_factor = new_factor
        step_reagent.scalable = True
        step_reagent.save()

        serializer = self.get_serializer(step_reagent)
        return Response({"message": "Scaling factor updated", "reagent": serializer.data})

    @extend_schema(
        tags=["step-reagents"],
        request=BulkScaleSerializer,
        responses={200: ActionMessageSerializer, 400: ErrorSerializer},
    )
    @action(detail=False, methods=["post"])
    def bulk_scale_reagents(self, request):
        """Apply scaling factor to multiple reagents in a step."""
        step_id = request.data.get("step_id")
        scale_factor = request.data.get("scale_factor")

        if not step_id or scale_factor is None:
            return Response({"error": "step_id and scale_factor are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            scale_factor = float(scale_factor)
        except ValueError:
            return Response({"error": "scale_factor must be a number"}, status=status.HTTP_400_BAD_REQUEST)

        step = ProtocolStep.objects.select_related("protocol").filter(id=step_id).first()
        if step is None:
            return Response({"error": "Step not found"}, status=status.HTTP_404_NOT_FOUND)
        require_owner_or_editor(step.protocol, request.user)

        updated_count = self.get_queryset().filter(step_id=step_id, scalable=True).update(scalable_factor=scale_factor)

        return Response({"message": f"Updated scaling factor for {updated_count} reagents"})


class StepVariationViewSet(ModelViewSet):
    """ViewSet for StepVariation model with step relationship management."""

    queryset = StepVariation.objects.all()
    serializer_class = StepVariationSerializer
    permission_classes = [IsAuthenticated, OwnerOrEditorWritePermission]
    pagination_class = LimitOffsetPagination

    def resource_of(self, variation):
        """The variation's session, or the step's protocol for variations without a session."""
        return variation.session or variation.step.protocol

    def require_write_access(self, serializer):
        """Raise PermissionDenied unless the user owns or edits the session, or the protocol without one."""
        session = serializer.validated_data.get("session", getattr(serializer.instance, "session", None))
        step = serializer.validated_data.get("step", getattr(serializer.instance, "step", None))
        require_owner_or_editor(session or step.protocol, self.request.user)

    def perform_create(self, serializer):
        """Only the owner or an editor of the session can add variations."""
        self.require_write_access(serializer)
        serializer.save()

    def perform_update(self, serializer):
        """Only the owner or an editor of the session can change variations."""
        self.require_write_access(serializer)
        serializer.save()

    def get_queryset(self):
        """Variations of sessions the user can view, and variations without a session of protocols the user can view."""
        queryset = super().get_queryset()
        user = self.request.user
        if not is_staff_or_superuser(user):
            queryset = queryset.filter(
                session_viewer_q(user) | (Q(session__isnull=True) & protocol_viewer_q(user, "step__protocol__"))
            ).distinct()

        # Filter by step if specified
        step_id = self.request.query_params.get("step")
        if step_id:
            queryset = queryset.filter(step_id=step_id)

        session_id = self.request.query_params.get("session")
        if session_id:
            queryset = queryset.filter(session_id=session_id)

        return queryset.select_related("step", "session", "remote_host")

    @extend_schema(
        tags=["step-variations"],
        filters=False,
        parameters=[
            OpenApiParameter("step", int),
            OpenApiParameter("session", int),
            OpenApiParameter("min_duration", int, description="Seconds"),
            OpenApiParameter("max_duration", int, description="Seconds"),
        ],
        responses={200: StepVariationSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def by_duration(self, request):
        """Get variations sorted by duration."""
        queryset = self.get_queryset().order_by("variation_duration")

        min_duration = request.query_params.get("min_duration")
        max_duration = request.query_params.get("max_duration")

        if min_duration:
            queryset = queryset.filter(variation_duration__gte=int(min_duration))
        if max_duration:
            queryset = queryset.filter(variation_duration__lte=int(max_duration))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("session", int, description="Timers of this session"),
            OpenApiParameter("step", int),
            OpenApiParameter("started", bool),
        ]
    )
)
class TimeKeeperViewSet(ModelViewSet):
    """ViewSet for TimeKeeper model with timing functionality."""

    queryset = TimeKeeper.objects.all()
    serializer_class = TimeKeeperSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """
        Timers listed for the request.

        With session: the timers of that session, when the user can view it.
        Otherwise: the user's own timers, leaving out timers of sessions the user can no longer view.
        """
        user = self.request.user
        params = self.request.query_params
        session_id = params.get("session")

        if session_id:
            session = Session.objects.filter(pk=session_id).first()
            if session and session.can_view(user):
                queryset = TimeKeeper.objects.filter(session=session)
            else:
                queryset = TimeKeeper.objects.filter(user=user, session_id=session_id)
        else:
            queryset = super().get_queryset().filter(user=user)
            own_sessions = Session.objects.filter(time_keeper__in=queryset).distinct()
            hidden = [session.id for session in own_sessions if not session.can_view(user)]
            if hidden:
                queryset = queryset.exclude(session_id__in=hidden)

        # Filter by step if specified
        step_id = self.request.query_params.get("step")
        if step_id:
            queryset = queryset.filter(step_id=step_id)

        # Filter by started status
        started = self.request.query_params.get("started")
        if started is not None:
            queryset = queryset.filter(started=started.lower() == "true")

        return queryset.select_related("session", "step", "user", "remote_host").order_by("-id")

    def get_object(self):
        """The timer with the requested id: session timers for those who can view the session, other timers for their creator."""
        time_keeper = get_object_or_404(
            TimeKeeper.objects.select_related("session", "step", "user"), pk=self.kwargs["pk"]
        )
        user = self.request.user
        allowed = time_keeper.session.can_view(user) if time_keeper.session else time_keeper.user_id == user.pk
        if not allowed:
            raise Http404
        return time_keeper

    def _require_run_access(self, time_keeper=None, session=None):
        """Session timers can be run by the session owner and editors; other timers by their creator."""
        session = session or (time_keeper.session if time_keeper else None)
        user = self.request.user
        if session is not None:
            allowed = is_owner_or_editor(session, user)
        else:
            allowed = time_keeper is None or time_keeper.user_id == user.pk
        if not allowed:
            raise PermissionDenied("You cannot change this timer")

    def perform_update(self, serializer):
        """Check run access, then save."""
        self._require_run_access(serializer.instance, serializer.validated_data.get("session"))
        serializer.save()

    def perform_destroy(self, instance):
        """Check run access, then delete."""
        self._require_run_access(instance)
        instance.delete()

    def perform_create(self, serializer):
        """
        Get or create timekeeper for session+step combination.

        Only one timekeeper should exist per session+step.
        """
        validated_data = serializer.validated_data
        session = validated_data.get("session")
        step = validated_data.get("step")
        self._require_run_access(session=session)

        if session and step:
            existing = TimeKeeper.objects.filter(session=session, step=step).first()
            if existing:
                for key, value in validated_data.items():
                    if key not in ["session", "step"]:
                        setattr(existing, key, value)
                existing.save()
                serializer.instance = existing
                return

        if "original_duration" not in validated_data and "current_duration" in validated_data:
            validated_data["original_duration"] = validated_data["current_duration"]

        serializer.save(user=self.request.user)

    @extend_schema(
        tags=["time-keepers"],
        request=None,
        responses={200: TimerStartedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def start_timer(self, request, pk=None):
        """Start the timer for this time keeper."""
        time_keeper = self.get_object()
        self._require_run_access(time_keeper)

        if time_keeper.started:
            return Response({"error": "Timer is already started"}, status=status.HTTP_400_BAD_REQUEST)

        if not time_keeper.original_duration and time_keeper.current_duration:
            time_keeper.original_duration = time_keeper.current_duration

        time_keeper.started = True
        time_keeper.start_time = timezone.now()
        time_keeper.save(update_fields=["started", "start_time", "original_duration"])

        serializer = self.get_serializer(time_keeper)
        return Response({"message": "Timer started", "time_keeper": serializer.data})

    @extend_schema(
        tags=["time-keepers"],
        request=None,
        responses={200: TimerStoppedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def stop_timer(self, request, pk=None):
        """Stop the timer and calculate remaining duration."""
        time_keeper = self.get_object()
        self._require_run_access(time_keeper)

        if not time_keeper.started:
            return Response({"error": "Timer is not started"}, status=status.HTTP_400_BAD_REQUEST)

        if not time_keeper.start_time:
            return Response(
                {"error": "Timer is marked as started but has no start time"}, status=status.HTTP_400_BAD_REQUEST
            )

        elapsed_seconds = int((timezone.now() - time_keeper.start_time).total_seconds())
        previous_duration = time_keeper.current_duration or 0
        new_duration = max(0, previous_duration - elapsed_seconds)

        time_keeper.started = False
        time_keeper.current_duration = new_duration
        time_keeper.start_time = None
        time_keeper.save(update_fields=["started", "current_duration", "start_time"])

        serializer = self.get_serializer(time_keeper)
        return Response(
            {
                "message": "Timer stopped",
                "current_duration": new_duration,
                "time_keeper": serializer.data,
            }
        )

    @extend_schema(
        tags=["time-keepers"],
        request=None,
        responses={200: TimerStoppedSerializer, 400: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        """
        Reset the timekeeper to its original duration.

        If the timer is currently running, it will be stopped first.
        Creates a reset event in the event history.
        """
        time_keeper = self.get_object()
        self._require_run_access(time_keeper)

        if not time_keeper.original_duration:
            if time_keeper.current_duration:
                time_keeper.original_duration = time_keeper.current_duration
            else:
                return Response(
                    {"error": "Cannot reset: no duration set for this timekeeper"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if time_keeper.started:
            time_keeper.started = False
            time_keeper.start_time = None

        time_keeper.current_duration = time_keeper.original_duration
        time_keeper.save(update_fields=["started", "start_time", "current_duration", "original_duration"])

        TimeKeeperEvent.objects.create(
            time_keeper=time_keeper,
            event_type="reset",
            duration_at_event=time_keeper.original_duration,
            notes="Timer reset to original duration",
        )

        serializer = self.get_serializer(time_keeper)
        return Response(
            {
                "message": "Timer reset to original duration",
                "current_duration": time_keeper.current_duration,
                "time_keeper": serializer.data,
            }
        )

    @extend_schema(tags=["time-keepers"], filters=False, responses={200: TimeKeeperSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def active_timers(self, request):
        """Get all active timers for the current user."""
        active_timers = self.get_queryset().filter(started=True)
        serializer = self.get_serializer(active_timers, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["time-keepers"],
        filters=False,
        parameters=[OpenApiParameter("session_id", int, required=True)],
        responses={200: SessionTimingSerializer, 400: ErrorSerializer},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def session_summary(self, request):
        """Get timing summary for a specific session."""
        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response({"error": "session_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        timers = self.get_queryset().filter(session_id=session_id)
        total_time = sum(t.current_duration or 0 for t in timers)

        return Response(
            {
                "session_id": session_id,
                "total_timers": timers.count(),
                "total_duration_seconds": total_time,
                "total_duration_formatted": TimeKeeperSerializer().get_duration_formatted(
                    type("obj", (), {"current_duration": total_time})()
                ),
            }
        )


class SessionAnnotationFilter(django_filters.FilterSet):
    """Filter for SessionAnnotation with scratched support."""

    scratched = django_filters.BooleanFilter(field_name="annotation__scratched")

    class Meta:
        model = SessionAnnotation
        fields = {
            "session": ["exact"],
            "annotation": ["exact"],
            "updated_at": ["gte", "lte"],
        }


class SessionAnnotationViewSet(DeletionLogMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing session annotations with metadata support.

    Provides CRUD operations and metadata table management for session annotations.
    """

    queryset = SessionAnnotation.objects.all()
    serializer_class = SessionAnnotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SessionAnnotationFilter
    search_fields = ["annotation__annotation"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter session annotations based on user permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        base_queryset = SessionAnnotation.objects.select_related("session", "annotation", "metadata_table")
        return visible_through_session(base_queryset, user, include_public=asks_for_one(self, "session"))

    def create(self, request, *args, **kwargs):
        """Create session annotation, handling annotation_data if provided."""
        session = Session.objects.filter(pk=request.data.get("session")).first()
        require_owner_or_editor(session, request.user)
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")
            auto_transcribe = annotation_data.get("auto_transcribe", True)

            if not annotation_text:
                return Response(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                owner=request.user,
            )

            queue_annotation_transcription(annotation, auto_transcribe)

            data = request.data.copy()
            data["annotation"] = annotation.id
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update session annotation, handling annotation_data if provided."""
        require_owner_or_editor(self.get_object().session, request.user)
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            instance = self.get_object()
            if instance.annotation:
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

            data = request.data.copy()
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """
        Delete session annotation; only the session owner or an editor can.

        Linked InstrumentUsage bookings of a booking annotation are deleted when the user can delete them.
        """
        require_owner_or_editor(instance.session, self.request.user)

        if instance.annotation and instance.annotation.annotation_type == "booking":
            for usage_link in instance.instrument_usage_links.all():
                if usage_link.instrument_usage.user_can_delete(self.request.user):
                    usage_link.instrument_usage.delete()

        super().perform_destroy(instance)

    @extend_schema(
        tags=["session-annotations"],
        request=None,
        responses={201: MetadataTableCreatedSerializer, 500: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def create_metadata_table(self, request, pk=None):
        """Create a metadata table for this session annotation."""
        session_annotation = self.get_object()
        require_owner_or_editor(session_annotation.session, request.user)

        try:
            metadata_table = session_annotation.create_metadata_table()
            serializer = MetadataTableSerializer(metadata_table)
            return Response(
                {"message": "Metadata table created successfully", "metadata_table": serializer.data},
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to create metadata table: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(tags=["session-annotations"], responses={200: MetadataTableSerializer, 404: ErrorSerializer})
    @action(detail=True, methods=["get"])
    def metadata_table(self, request, pk=None):
        """Get the metadata table for this session annotation."""
        session_annotation = self.get_object()

        if not session_annotation.metadata_table:
            return Response(
                {"error": "No metadata table found for this session annotation"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = MetadataTableSerializer(session_annotation.metadata_table)
        return Response(serializer.data)

    @extend_schema(
        tags=["session-annotations"],
        request=AnnotationColumnSerializer,
        responses={201: AnnotationColumnAddedSerializer, 400: ErrorSerializer, 500: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def add_metadata_column(self, request, pk=None):
        """Add a column to the session annotation's metadata table."""
        session_annotation = self.get_object()
        require_owner_or_editor(session_annotation.session, request.user)

        # Get column data from request
        column_data = request.data

        if not column_data.get("name"):
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Use the model method which handles positioning correctly
            column = session_annotation.add_metadata_column(column_data)

            serializer = MetadataColumnSerializer(column)
            return Response(
                {"message": "Column added successfully", "column": serializer.data}, status=status.HTTP_201_CREATED
            )

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to create column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["session-annotations"],
        parameters=[OpenApiParameter("column_id", int, OpenApiParameter.PATH)],
        responses={200: ActionMessageSerializer, 400: ErrorSerializer, 500: ErrorSerializer},
    )
    @action(detail=True, methods=["delete"], url_path="remove_metadata_column/(?P<column_id>[^/.]+)")
    def remove_metadata_column(self, request, pk=None, column_id=None):
        """Remove a column from the session annotation's metadata table."""
        session_annotation = self.get_object()
        require_owner_or_editor(session_annotation.session, request.user)

        try:
            session_annotation.remove_metadata_column(int(column_id))
            return Response({"message": "Column removed successfully"}, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to remove column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(tags=["session-annotations"], responses={200: MetadataColumnSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def metadata_columns(self, request, pk=None):
        """Get all metadata columns for this session annotation."""
        session_annotation = self.get_object()

        columns = session_annotation.get_metadata_columns()
        serializer = MetadataColumnSerializer(columns, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["session-annotations"],
        parameters=[OpenApiParameter("column_id", int, OpenApiParameter.PATH)],
        request=ColumnValueSerializer,
        responses={200: ActionMessageSerializer, 400: ErrorSerializer, 500: ErrorSerializer},
    )
    @action(detail=True, methods=["patch"], url_path="update_column_value/(?P<column_id>[^/.]+)")
    def update_column_value(self, request, pk=None, column_id=None):
        """Update the value of a metadata column."""
        session_annotation = self.get_object()
        require_owner_or_editor(session_annotation.session, request.user)

        value = request.data.get("value")
        if value is None:
            return Response({"error": "value is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session_annotation.update_metadata_column_value(int(column_id), value)
            return Response({"message": "Column value updated successfully"}, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to update column value: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class StepAnnotationFilter(django_filters.FilterSet):
    """Filter for StepAnnotation with scratched support."""

    scratched = django_filters.BooleanFilter(field_name="annotation__scratched")

    class Meta:
        model = StepAnnotation
        fields = {
            "session": ["exact"],
            "step": ["exact"],
            "annotation": ["exact"],
            "updated_at": ["gte", "lte"],
        }


class StepAnnotationViewSet(DeletionLogMixin, ModelViewSet):
    """ViewSet for StepAnnotation model."""

    queryset = StepAnnotation.objects.all()
    serializer_class = StepAnnotationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = StepAnnotationFilter
    search_fields = ["step__step_description", "annotation__annotation"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Step annotations of sessions the user can view."""
        user = self.request.user
        queryset = self.queryset.select_related("session", "step", "annotation").prefetch_related(
            "instrument_usage_links"
        )
        return visible_through_session(queryset, user, include_public=asks_for_one(self, "session"))

    def create(self, request, *args, **kwargs):
        """Create step annotation, handling annotation_data if provided."""
        session = Session.objects.filter(pk=request.data.get("session")).first()
        require_owner_or_editor(session, request.user)
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")
            auto_transcribe = annotation_data.get("auto_transcribe", True)

            if not annotation_text:
                return Response(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                owner=request.user,
            )

            queue_annotation_transcription(annotation, auto_transcribe)

            data = request.data.copy()
            data["annotation"] = annotation.id
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update step annotation, handling annotation_data if provided."""
        require_owner_or_editor(self.get_object().session, request.user)
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            instance = self.get_object()
            if instance.annotation:
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

            data = request.data.copy()
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """
        Delete step annotation; only the session owner or an editor can.

        Linked InstrumentUsage bookings of a booking annotation are deleted when the user can delete them.
        """
        require_owner_or_editor(instance.session, self.request.user)

        if instance.annotation and instance.annotation.annotation_type == "booking":
            for usage_link in instance.instrument_usage_links.all():
                if usage_link.instrument_usage.user_can_delete(self.request.user):
                    usage_link.instrument_usage.delete()

        super().perform_destroy(instance)

    @extend_schema(
        tags=["step-annotations"],
        request=None,
        responses={200: TranscriptionQueuedSerializer, 400: ErrorSerializer, 404: ErrorSerializer},
    )
    @action(detail=True, methods=["post"])
    def retrigger_transcription(self, request, pk=None):
        """
        Retrigger transcription and translation for audio/video annotations.

        Only available to admin and staff users.
        Clears existing transcription data and queues a new transcription task.
        """
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff and admin users can retrigger transcription")

        step_annotation = self.get_object()
        annotation = step_annotation.annotation

        if not annotation:
            return Response({"error": "No annotation found"}, status=status.HTTP_404_NOT_FOUND)

        if annotation.annotation_type not in ["audio", "video"]:
            return Response(
                {
                    "error": f"Cannot transcribe annotation of type '{annotation.annotation_type}'. Only 'audio' and 'video' types are supported."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not annotation.file:
            return Response({"error": "No file attached to this annotation"}, status=status.HTTP_400_BAD_REQUEST)

        annotation.transcribed = False
        annotation.transcription = None
        annotation.language = None
        annotation.translation = None
        annotation.save(update_fields=["transcribed", "transcription", "language", "translation"])

        queue_annotation_transcription(annotation, auto_transcribe=True)

        return Response(
            {"message": "Transcription task queued successfully", "annotation_id": annotation.id},
            status=status.HTTP_200_OK,
        )


class SessionAnnotationFolderViewSet(ModelViewSet):
    """ViewSet for SessionAnnotationFolder model."""

    queryset = SessionAnnotationFolder.objects.all()
    serializer_class = SessionAnnotationFolderSerializer
    permission_classes = [IsAuthenticated, OwnerOrEditorWritePermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["session", "folder"]
    search_fields = ["folder__name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def resource_of(self, session_folder):
        """The session the folder belongs to."""
        return session_folder.session

    def perform_create(self, serializer):
        """Only the session owner or an editor can add folders."""
        require_owner_or_editor(serializer.validated_data.get("session"), self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a folder to another session also needs the owner or an editor of that session."""
        require_owner_or_editor(serializer.validated_data.get("session"), self.request.user)
        serializer.save()

    def get_queryset(self):
        """Folders of sessions the user can view."""
        return visible_through_session(self.queryset, self.request.user)


class InstrumentUsageStepAnnotationViewSet(ModelViewSet):
    """ViewSet for InstrumentUsageStepAnnotation model."""

    queryset = InstrumentUsageStepAnnotation.objects.all()
    serializer_class = InstrumentUsageStepAnnotationSerializer
    permission_classes = [IsAuthenticated, ModelEditDeletePermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["step_annotation", "instrument_usage"]
    search_fields = ["instrument_usage__instrument__instrument_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Booking links of sessions the user can view, and links to bookings the user can see."""
        return visible_booking_links(self.queryset, self.request.user, "step_annotation__session__")

    def perform_create(self, serializer):
        """Only the session owner or an editor can link bookings."""
        require_owner_or_editor(serializer.validated_data["step_annotation"].session, self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a link to another session also needs the owner or an editor of that session."""
        target = serializer.validated_data.get("step_annotation")
        require_owner_or_editor(target.session if target else None, self.request.user)
        serializer.save()


class InstrumentUsageSessionAnnotationViewSet(ModelViewSet):
    """ViewSet for InstrumentUsageSessionAnnotation model."""

    queryset = InstrumentUsageSessionAnnotation.objects.all()
    serializer_class = InstrumentUsageSessionAnnotationSerializer
    permission_classes = [IsAuthenticated, ModelEditDeletePermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["session_annotation", "instrument_usage"]
    search_fields = ["instrument_usage__instrument__instrument_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Booking links of sessions the user can view, and links to bookings the user can see."""
        return visible_booking_links(self.queryset, self.request.user, "session_annotation__session__")

    def perform_create(self, serializer):
        """Only the session owner or an editor can link bookings."""
        require_owner_or_editor(serializer.validated_data["session_annotation"].session, self.request.user)
        serializer.save()

    def perform_update(self, serializer):
        """Moving a link to another session also needs the owner or an editor of that session."""
        target = serializer.validated_data.get("session_annotation")
        require_owner_or_editor(target.session if target else None, self.request.user)
        serializer.save()
