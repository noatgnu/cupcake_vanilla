"""
CUPCAKE Red Velvet (CCRV) ViewSets.

Django REST Framework viewsets for project and protocol management API endpoints,
faithfully representing the migrated functionality.
"""

from django.db.models import Q
from django.utils import timezone

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ccc.models import LabGroup, RemoteHost
from ccc.permissions import IsAdminUser, IsOwnerEditorViewerOrNoAccess, IsOwnerOrReadOnly
from ccc.serializers import AnnotationFolderSerializer
from ccv.serializers import MetadataColumnSerializer, MetadataTableSerializer

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
    RemoteHostSerializer,
    SessionAnnotationFolderSerializer,
    SessionAnnotationSerializer,
    SessionCreateSerializer,
    SessionSerializer,
    StepAnnotationSerializer,
    StepReagentSerializer,
    StepVariationSerializer,
    TimeKeeperSerializer,
)


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
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(Q(owner=user) | Q(lab_group_id__in=accessible_groups)).distinct()

    @action(detail=True, methods=["get"])
    def sessions(self, request, pk=None):
        """Get all sessions for this project."""
        project = self.get_object()
        sessions = project.sessions.all()
        serializer = SessionSerializer(sessions, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_projects(self, request):
        """Get projects owned by the current user."""
        projects = Project.objects.filter(owner=request.user)
        serializer = self.get_serializer(projects, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def vaulted_projects(self, request):
        """Get vaulted/imported projects for the current user."""
        projects = self.get_queryset().filter(is_vaulted=True)
        serializer = self.get_serializer(projects, many=True)
        return Response(serializer.data)


class ProtocolModelViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing experimental protocols.

    Preserves all original functionality including protocols.io integration.
    """

    queryset = ProtocolModel.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsOwnerEditorViewerOrNoAccess]

    def get_serializer_class(self):
        if self.action == "create":
            return ProtocolModelCreateSerializer
        return ProtocolModelSerializer

    def get_queryset(self):
        """Filter protocols based on user permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(
            Q(owner=user) | Q(editors=user) | Q(viewers=user) | Q(lab_group_id__in=accessible_groups)
        ).distinct()

    @action(detail=True, methods=["post"])
    def toggle_enabled(self, request, pk=None):
        """Toggle the enabled status of this protocol."""
        protocol = self.get_object()
        protocol.enabled = not protocol.enabled
        protocol.save(update_fields=["enabled"])

        return Response(
            {"message": f'Protocol {"enabled" if protocol.enabled else "disabled"}', "enabled": protocol.enabled}
        )

    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        """Get all steps for this protocol."""
        protocol = self.get_object()
        steps = protocol.steps.all()
        serializer = ProtocolStepSerializer(steps, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def sections(self, request, pk=None):
        """Get all sections for this protocol."""
        protocol = self.get_object()
        sections = protocol.sections.all()
        serializer = ProtocolSectionSerializer(sections, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def ratings(self, request, pk=None):
        """Get all ratings for this protocol."""
        protocol = self.get_object()
        ratings = protocol.ratings.all()
        serializer = ProtocolRatingSerializer(ratings, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def enabled_protocols(self, request):
        """Get all enabled protocols."""
        protocols = self.get_queryset().filter(enabled=True)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def vaulted_protocols(self, request):
        """Get vaulted/imported protocols."""
        protocols = self.get_queryset().filter(is_vaulted=True)
        serializer = self.get_serializer(protocols, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def import_from_protocols_io(self, request):
        """Import a protocol from protocols.io using the original integration."""
        url = request.data.get("url")
        if not url:
            return Response({"error": "URL is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Use the original static method
            protocol = ProtocolModel.create_protocol_from_url(url)
            protocol.owner = request.user  # Set current user as owner
            protocol.save()

            # Update the order attribute for steps in the newly imported protocol
            # Handle steps without sections first
            root_steps = ProtocolStep.objects.filter(
                protocol=protocol, step_section__isnull=True, previous_step__isnull=True
            )

            order = 0
            for root_step in root_steps:
                order = ProtocolStep._traverse_and_order(root_step, order)

            # Handle sections
            sections = protocol.sections.all().order_by("id")
            for section in sections:
                section_root_steps = ProtocolStep.objects.filter(step_section=section, previous_step__isnull=True)

                section_order = 0
                for root_step in section_root_steps:
                    section_order = ProtocolStep._traverse_and_order(root_step, section_order, section_context=True)

            serializer = self.get_serializer(protocol)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({"error": "Failed to import protocol"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SessionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing experimental sessions.

    Preserves original session management and import tracking functionality.
    """

    queryset = Session.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsOwnerEditorViewerOrNoAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["unique_id", "enabled", "processing", "projects"]
    search_fields = ["name"]
    ordering_fields = ["created_at", "started_at", "ended_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return SessionCreateSerializer
        return SessionSerializer

    def get_queryset(self):
        """Filter sessions based on user permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(
            Q(owner=user) | Q(editors=user) | Q(viewers=user) | Q(lab_group_id__in=accessible_groups)
        ).distinct()

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

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """End the session (original functionality)."""
        session = self.get_object()

        if not session.started_at:
            return Response({"error": "Session has not been started yet"}, status=status.HTTP_400_BAD_REQUEST)

        if session.ended_at:
            return Response({"error": "Session has already ended"}, status=status.HTTP_400_BAD_REQUEST)

        # Use original logic
        from django.utils import timezone

        session.ended_at = timezone.now()
        session.processing = False
        session.save(update_fields=["ended_at", "processing"])

        serializer = self.get_serializer(session)
        return Response({"message": "Session ended successfully", "session": serializer.data})

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

    @action(detail=False, methods=["get"])
    def running_sessions(self, request):
        """Get currently running sessions."""
        running_sessions = self.get_queryset().filter(started_at__isnull=False, ended_at__isnull=True)
        serializer = self.get_serializer(running_sessions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def imported_sessions(self, request):
        """Get imported sessions using original is_imported property."""
        sessions = [s for s in self.get_queryset() if s.is_imported]
        serializer = self.get_serializer(sessions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def folders(self, request, pk=None):
        """Get annotation folders linked to this session."""
        session = self.get_object()

        session_folders = SessionAnnotationFolder.objects.filter(session=session).select_related("folder")
        folders = [sf.folder for sf in session_folders]

        serializer = AnnotationFolderSerializer(folders, many=True)
        return Response(serializer.data)


class ProtocolRatingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing protocol ratings.

    Preserves original validation logic from model.
    """

    queryset = ProtocolRating.objects.all()
    serializer_class = ProtocolRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Filter ratings based on protocol access permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        # Can see ratings for protocols they have access to
        return self.queryset.filter(
            Q(protocol__owner=user)
            | Q(protocol__editors=user)
            | Q(protocol__viewers=user)
            | Q(protocol__lab_group_id__in=accessible_groups)
        ).distinct()

    def perform_create(self, serializer):
        """Set the current user as the rating user."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def my_ratings(self, request):
        """Get ratings by the current user."""
        ratings = ProtocolRating.objects.filter(user=request.user)
        serializer = self.get_serializer(ratings, many=True)
        return Response(serializer.data)

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
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Filter sections based on protocol permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(
            Q(protocol__owner=user)
            | Q(protocol__editors=user)
            | Q(protocol__viewers=user)
            | Q(protocol__lab_group_id__in=accessible_groups)
        ).distinct()

    @action(detail=True, methods=["get"])
    def steps_in_order(self, request, pk=None):
        """Get steps in order using original linked-list traversal."""
        section = self.get_object()
        ordered_steps = section.get_step_in_order()
        serializer = ProtocolStepSerializer(ordered_steps, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def first_step(self, request, pk=None):
        """Get the first step in this section."""
        section = self.get_object()
        first_step = section.get_first_in_section()
        if first_step:
            serializer = ProtocolStepSerializer(first_step, context={"request": request})
            return Response(serializer.data)
        return Response({"message": "No steps in this section"})

    @action(detail=True, methods=["get"])
    def last_step(self, request, pk=None):
        """Get the last step in this section."""
        section = self.get_object()
        last_step = section.get_last_in_section()
        if last_step:
            serializer = ProtocolStepSerializer(last_step, context={"request": request})
            return Response(serializer.data)
        return Response({"message": "No steps in this section"})

    @action(detail=True, methods=["get"])
    def steps_by_order(self, request, pk=None):
        """Get steps efficiently ordered by order attribute (optimized method)."""
        section = self.get_object()
        ordered_steps = section.get_steps_by_order()
        serializer = ProtocolStepSerializer(ordered_steps, many=True, context={"request": request})
        return Response(serializer.data)

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
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["protocol", "step_section", "original", "branch_from"]
    search_fields = ["step_description"]
    ordering_fields = ["order", "created_at", "step_duration"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter steps based on protocol permissions (includes bubble-up from sub-groups)."""
        user = self.request.user
        if user.is_superuser:
            return self.queryset

        # Get all accessible lab groups (includes parent groups via bubble-up)
        accessible_groups = LabGroup.get_accessible_group_ids(user)

        return self.queryset.filter(
            Q(protocol__owner=user)
            | Q(protocol__editors=user)
            | Q(protocol__viewers=user)
            | Q(protocol__lab_group_id__in=accessible_groups)
        ).distinct()

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

    @action(detail=True, methods=["get"])
    def next_steps(self, request, pk=None):
        """Get next steps in the linked list."""
        step = self.get_object()
        next_steps = step.next_step.all()
        serializer = self.get_serializer(next_steps, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def branch_steps(self, request, pk=None):
        """Get steps that branch from this step."""
        step = self.get_object()
        branch_steps = step.branch_steps.all()
        serializer = self.get_serializer(branch_steps, many=True)
        return Response(serializer.data)

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

    @action(detail=False, methods=["post"])
    def reorder_by_linked_list(self, request):
        """Migrate existing data by populating order fields from linked-list traversal."""
        try:
            ProtocolStep.reorder_by_linked_list()
            return Response({"message": "Successfully populated order fields for all protocol steps"})
        except Exception as e:
            return Response(
                {"error": f"Failed to reorder by linked list: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST
            )


class RemoteHostViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing remote hosts in distributed system.

    Admin-only functionality for distributed system management.
    """

    queryset = RemoteHost.objects.all()
    serializer_class = RemoteHostSerializer
    permission_classes = [IsAdminUser]


class ProtocolReagentViewSet(ModelViewSet):
    """ViewSet for ProtocolReagent model with reagent relationship management."""

    queryset = ProtocolReagent.objects.all()
    serializer_class = ProtocolReagentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Filter reagents by protocol ownership."""
        queryset = super().get_queryset()

        # Filter by protocol if specified
        protocol_id = self.request.query_params.get("protocol")
        if protocol_id:
            queryset = queryset.filter(protocol_id=protocol_id)

        # Filter by reagent if specified
        reagent_id = self.request.query_params.get("reagent")
        if reagent_id:
            queryset = queryset.filter(reagent_id=reagent_id)

        return queryset.select_related("protocol", "reagent")

    @action(detail=False, methods=["post"])
    def bulk_add_reagents(self, request):
        """Add multiple reagents to a protocol at once."""
        protocol_id = request.data.get("protocol_id")
        reagent_data = request.data.get("reagents", [])

        if not protocol_id:
            return Response({"error": "Protocol ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            protocol = ProtocolModel.objects.get(id=protocol_id, owner=request.user)
        except ProtocolModel.DoesNotExist:
            return Response({"error": "Protocol not found"}, status=status.HTTP_404_NOT_FOUND)

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
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Filter reagents by step ownership."""
        queryset = super().get_queryset()

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

        updated_count = self.get_queryset().filter(step_id=step_id, scalable=True).update(scalable_factor=scale_factor)

        return Response({"message": f"Updated scaling factor for {updated_count} reagents"})


class StepVariationViewSet(ModelViewSet):
    """ViewSet for StepVariation model with step relationship management."""

    queryset = StepVariation.objects.all()
    serializer_class = StepVariationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Filter variations by step ownership."""
        queryset = super().get_queryset()

        # Filter by step if specified
        step_id = self.request.query_params.get("step")
        if step_id:
            queryset = queryset.filter(step_id=step_id)

        return queryset.select_related("step", "remote_host")

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


class TimeKeeperViewSet(ModelViewSet):
    """ViewSet for TimeKeeper model with timing functionality."""

    queryset = TimeKeeper.objects.all()
    serializer_class = TimeKeeperSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Filter time tracking by user ownership."""
        queryset = super().get_queryset().filter(user=self.request.user)

        # Filter by session if specified
        session_id = self.request.query_params.get("session")
        if session_id:
            queryset = queryset.filter(session_id=session_id)

        # Filter by step if specified
        step_id = self.request.query_params.get("step")
        if step_id:
            queryset = queryset.filter(step_id=step_id)

        # Filter by started status
        started = self.request.query_params.get("started")
        if started is not None:
            queryset = queryset.filter(started=started.lower() == "true")

        return queryset.select_related("session", "step", "user", "remote_host")

    def perform_create(self, serializer):
        """Automatically assign current user to time keeper."""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def start_timer(self, request, pk=None):
        """Start the timer for this time keeper."""
        time_keeper = self.get_object()

        if time_keeper.started:
            return Response({"error": "Timer is already started"}, status=status.HTTP_400_BAD_REQUEST)

        time_keeper.started = True
        time_keeper.start_time = timezone.now()
        time_keeper.save()

        serializer = self.get_serializer(time_keeper)
        return Response({"message": "Timer started", "time_keeper": serializer.data})

    @action(detail=True, methods=["post"])
    def stop_timer(self, request, pk=None):
        """Stop the timer and calculate remaining duration."""
        time_keeper = self.get_object()

        if not time_keeper.started:
            return Response({"error": "Timer is not started"}, status=status.HTTP_400_BAD_REQUEST)

        elapsed_seconds = int((timezone.now() - time_keeper.start_time).total_seconds())
        previous_duration = time_keeper.current_duration or 0
        new_duration = max(0, previous_duration - elapsed_seconds)

        time_keeper.started = False
        time_keeper.current_duration = new_duration
        time_keeper.save()

        serializer = self.get_serializer(time_keeper)
        return Response(
            {
                "message": "Timer stopped",
                "current_duration": new_duration,
                "time_keeper": serializer.data,
            }
        )

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        """
        Reset the timekeeper to its original duration.

        If the timer is currently running, it will be stopped first.
        Creates a reset event in the event history.
        """
        time_keeper = self.get_object()

        if not time_keeper.original_duration:
            return Response(
                {"error": "Cannot reset: no original duration set for this timekeeper"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if time_keeper.started:
            time_keeper.started = False

        time_keeper.current_duration = time_keeper.original_duration
        time_keeper.save()

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

    @action(detail=False, methods=["get"])
    def active_timers(self, request):
        """Get all active timers for the current user."""
        active_timers = self.get_queryset().filter(started=True)
        serializer = self.get_serializer(active_timers, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
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
        fields = ["session", "annotation", "scratched"]


class SessionAnnotationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing session annotations with metadata support.

    Provides CRUD operations and metadata table management for session annotations.
    """

    queryset = SessionAnnotation.objects.all()
    serializer_class = SessionAnnotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SessionAnnotationFilter
    search_fields = ["annotation__annotation", "annotation__name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter session annotations based on user permissions."""
        user = self.request.user
        queryset = SessionAnnotation.objects.all()

        # Filter by sessions user can view
        accessible_sessions = []
        for session_annotation in queryset:
            if session_annotation.can_view(user):
                accessible_sessions.append(session_annotation.id)

        return queryset.filter(id__in=accessible_sessions)

    def create(self, request, *args, **kwargs):
        """Create session annotation, handling annotation_data if provided."""
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

            from ccc.models import Annotation
            from ccrv.serializers import queue_annotation_transcription

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
        Delete session annotation with permission checks.

        If the annotation is a booking annotation, also delete any linked InstrumentUsage bookings.
        """
        if not instance.can_delete(self.request.user):
            raise PermissionDenied("You do not have permission to delete this annotation")

        if instance.annotation and instance.annotation.annotation_type == "booking":
            for usage_link in instance.instrument_usage_links.all():
                usage_link.instrument_usage.delete()

        instance.delete()

    @action(detail=True, methods=["post"])
    def create_metadata_table(self, request, pk=None):
        """Create a metadata table for this session annotation."""
        session_annotation = self.get_object()

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

    @action(detail=True, methods=["post"])
    def add_metadata_column(self, request, pk=None):
        """Add a column to the session annotation's metadata table."""
        session_annotation = self.get_object()

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

    @action(detail=True, methods=["delete"], url_path="remove_metadata_column/(?P<column_id>[^/.]+)")
    def remove_metadata_column(self, request, pk=None, column_id=None):
        """Remove a column from the session annotation's metadata table."""
        session_annotation = self.get_object()

        try:
            session_annotation.remove_metadata_column(int(column_id))
            return Response({"message": "Column removed successfully"}, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Failed to remove column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["get"])
    def metadata_columns(self, request, pk=None):
        """Get all metadata columns for this session annotation."""
        session_annotation = self.get_object()

        columns = session_annotation.get_metadata_columns()
        serializer = MetadataColumnSerializer(columns, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"], url_path="update_column_value/(?P<column_id>[^/.]+)")
    def update_column_value(self, request, pk=None, column_id=None):
        """Update the value of a metadata column."""
        session_annotation = self.get_object()

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
        fields = ["session", "step", "annotation", "scratched"]


class StepAnnotationViewSet(ModelViewSet):
    """ViewSet for StepAnnotation model."""

    queryset = StepAnnotation.objects.all()
    serializer_class = StepAnnotationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = StepAnnotationFilter
    search_fields = ["step__step_description", "annotation__name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter annotations by user access permissions."""
        user = self.request.user
        return self.queryset.filter(session__owner=user)

    def create(self, request, *args, **kwargs):
        """Create step annotation, handling annotation_data if provided."""
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

            from ccc.models import Annotation
            from ccrv.serializers import queue_annotation_transcription

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
        Delete step annotation with permission checks.

        If the annotation is a booking annotation, also delete any linked InstrumentUsage bookings.
        """
        if not instance.can_delete(self.request.user):
            raise PermissionDenied("You do not have permission to delete this annotation")

        if instance.annotation and instance.annotation.annotation_type == "booking":
            for usage_link in instance.instrument_usage_links.all():
                usage_link.instrument_usage.delete()

        instance.delete()

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

        from ccrv.serializers import queue_annotation_transcription

        queue_annotation_transcription(annotation, auto_transcribe=True)

        return Response(
            {"message": "Transcription task queued successfully", "annotation_id": annotation.id},
            status=status.HTTP_200_OK,
        )


class SessionAnnotationFolderViewSet(ModelViewSet):
    """ViewSet for SessionAnnotationFolder model."""

    queryset = SessionAnnotationFolder.objects.all()
    serializer_class = SessionAnnotationFolderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["session", "folder"]
    search_fields = ["folder__name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter annotation folders by user access permissions."""
        user = self.request.user
        return self.queryset.filter(session__owner=user)


class InstrumentUsageStepAnnotationViewSet(ModelViewSet):
    """ViewSet for InstrumentUsageStepAnnotation model."""

    queryset = InstrumentUsageStepAnnotation.objects.all()
    serializer_class = InstrumentUsageStepAnnotationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["step_annotation", "instrument_usage"]
    search_fields = ["instrument_usage__instrument__instrument_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter instrument usage step annotations by user access permissions."""
        user = self.request.user
        return self.queryset.filter(step_annotation__session__owner=user)


class InstrumentUsageSessionAnnotationViewSet(ModelViewSet):
    """ViewSet for InstrumentUsageSessionAnnotation model."""

    queryset = InstrumentUsageSessionAnnotation.objects.all()
    serializer_class = InstrumentUsageSessionAnnotationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["session_annotation", "instrument_usage"]
    search_fields = ["instrument_usage__instrument__instrument_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter instrument usage annotations by user access permissions."""
        user = self.request.user
        return self.queryset.filter(session_annotation__session__owner=user)
