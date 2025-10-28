"""ViewSets for CUPCAKE Core Macaron (CCM) models.

Provides REST API endpoints for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ccc.models import AnnotationFolder, ResourceType
from ccc.serializers import AnnotationFolderSerializer
from ccv.models import LabGroup, MetadataColumn, MetadataTableTemplate
from ccv.serializers import MetadataColumnSerializer, MetadataTableSerializer

from .communication import send_maintenance_alert, send_reagent_alert
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
from .permissions import InstrumentJobPermission
from .serializers import (
    ExternalContactDetailsSerializer,
    ExternalContactSerializer,
    InstrumentAnnotationSerializer,
    InstrumentDetailSerializer,
    InstrumentJobDetailSerializer,
    InstrumentJobSerializer,
    InstrumentPermissionSerializer,
    InstrumentSerializer,
    InstrumentUsageSerializer,
    MaintenanceLogAnnotationSerializer,
    MaintenanceLogSerializer,
    ReagentActionSerializer,
    ReagentSerializer,
    ReagentSubscriptionSerializer,
    StorageObjectSerializer,
    StoredReagentAnnotationSerializer,
    StoredReagentSerializer,
    SupportInformationSerializer,
)


class BaseViewSet(viewsets.ModelViewSet):
    """Base viewset with common functionality."""

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()

        # For models that have a user field, filter by ownership or staff access
        if hasattr(self.queryset.model, "user"):
            # Users can see their own objects or objects they're assigned to
            user_filter = Q(user=self.request.user)

            # For models with staff relationship, include those too
            if hasattr(self.queryset.model, "staff"):
                user_filter |= Q(staff=self.request.user)

            # Staff users can see all objects
            if self.request.user.is_staff:
                return queryset
            else:
                return queryset.filter(user_filter)

        return queryset


class InstrumentViewSet(BaseViewSet):
    """ViewSet for Instrument model."""

    queryset = Instrument.objects.all()
    serializer_class = InstrumentSerializer
    filterset_fields = ["enabled", "accepts_bookings", "is_vaulted", "user"]
    search_fields = ["instrument_name", "instrument_description"]
    ordering_fields = ["instrument_name", "created_at", "updated_at"]
    ordering = ["instrument_name"]

    def get_serializer_class(self):
        """Use detailed serializer for retrieve action."""
        if self.action == "retrieve":
            return InstrumentDetailSerializer
        return InstrumentSerializer

    def get_queryset(self):
        """Filter instruments based on user permissions."""
        queryset = super().get_queryset()

        if self.request.user.is_staff:
            return queryset
        else:
            # Regular users can see enabled, non-vaulted instruments and their own
            return queryset.filter(Q(enabled=True, is_vaulted=False) | Q(user=self.request.user))

    def perform_create(self, serializer):
        """
        Set the user when creating an instrument.
        Only staff or admin users can create instruments.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can create instruments")
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """
        Update an instrument.
        Only staff or admin users can update instruments.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can update instruments")
        serializer.save()

    def perform_destroy(self, instance):
        """
        Delete an instrument.
        Only staff or admin users can delete instruments.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can delete instruments")
        instance.delete()

    @action(detail=True, methods=["post"])
    def check_warranty(self, request, pk=None):
        """Check warranty status for an instrument."""
        instrument = self.get_object()

        try:
            result = instrument.check_warranty_expiration()
            # Extract warranty info from support information
            warranty_expiration = None
            if hasattr(instrument, "support_information") and instrument.support_information.exists():
                support_info = instrument.support_information.first()
                if support_info and support_info.warranty_end_date:
                    warranty_expiration = support_info.warranty_end_date.isoformat()

            return Response(
                {
                    "warrantyValid": not result,  # result is True if warranty is expiring/expired
                    "warrantyExpiration": warranty_expiration,
                    "message": "Warranty check completed",
                }
            )
        except Exception as e:
            return Response({"error": f"Warranty check failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["post"])
    def check_maintenance(self, request, pk=None):
        """Check maintenance status for an instrument."""
        instrument = self.get_object()

        try:
            result = instrument.check_upcoming_maintenance()
            # Extract last maintenance info
            last_maintenance = None
            last_maintenance_log = (
                instrument.maintenance_logs.filter(status="completed").order_by("-maintenance_date").first()
            )
            if last_maintenance_log and last_maintenance_log.maintenance_date:
                last_maintenance = last_maintenance_log.maintenance_date.isoformat()

            return Response(
                {
                    "maintenanceRequired": result,
                    "lastMaintenance": last_maintenance,
                    "message": "Maintenance check completed",
                }
            )
        except Exception as e:
            return Response(
                {"error": f"Maintenance check failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def send_test_notification(self, request, pk=None):
        """
        Send a test notification for this instrument.
        Only accessible by staff or admin users.

        Request body should contain:
        - notification_type: One of 'warranty_expiring', 'maintenance_due', 'maintenance_completed'
        - recipient_id: Optional user ID to send to (defaults to current user)
        """
        if not (request.user.is_staff or request.user.is_superuser):
            return Response(
                {"error": "Only staff or admin users can send test notifications"},
                status=status.HTTP_403_FORBIDDEN,
            )

        instrument = self.get_object()

        notification_type = request.data.get("notification_type", "maintenance_due")
        recipient_id = request.data.get("recipient_id")

        valid_types = ["warranty_expiring", "maintenance_due", "maintenance_completed"]
        if notification_type not in valid_types:
            return Response(
                {"error": f"Invalid notification_type. Must be one of: {', '.join(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine recipient
        if recipient_id:
            User = get_user_model()
            try:
                recipient = User.objects.get(pk=recipient_id)
            except User.DoesNotExist:
                return Response({"error": "Recipient user not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            recipient = request.user

        # Send test notification
        maintenance_info = {"test": True, "notification_type": notification_type}
        success = send_maintenance_alert(
            instrument=instrument,
            message_type=notification_type,
            maintenance_info=maintenance_info,
            notify_users=[recipient],
        )

        if success:
            return Response(
                {
                    "success": True,
                    "message": f"Test notification sent to {recipient.username}",
                    "notification_type": notification_type,
                }
            )
        else:
            return Response(
                {"error": "Failed to send notification. CCMC may not be available."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def metadata(self, request, pk=None):
        """Get metadata table details for this instrument."""
        instrument = self.get_object()

        if not instrument.metadata_table:
            return Response({"error": "No metadata table found for this instrument"}, status=status.HTTP_404_NOT_FOUND)

        serializer = MetadataTableSerializer(instrument.metadata_table)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def add_metadata_column(self, request, pk=None):
        """Add a column to the instrument's metadata table."""
        instrument = self.get_object()

        if not instrument.metadata_table:
            return Response({"error": "No metadata table found for this instrument"}, status=status.HTTP_404_NOT_FOUND)

        # Get column data from request
        column_data = request.data

        if not column_data.get("name"):
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Create the column linked to this metadata table
            column = MetadataColumn.objects.create(
                metadata_table=instrument.metadata_table,
                name=column_data["name"],
                type=column_data.get("type", "characteristics"),
                value=column_data.get("value", ""),
                column_position=instrument.metadata_table.get_column_count(),
                mandatory=column_data.get("mandatory", False),
                hidden=column_data.get("hidden", False),
                readonly=column_data.get("readonly", False),
            )

            serializer = MetadataColumnSerializer(column)
            return Response(
                {"message": "Column added successfully", "column": serializer.data}, status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to create column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["delete"], url_path="remove_metadata_column/(?P<column_id>[^/.]+)")
    def remove_metadata_column(self, request, pk=None, column_id=None):
        """Remove a column from the instrument's metadata table."""
        instrument = self.get_object()

        if not instrument.metadata_table:
            return Response({"error": "No metadata table found for this instrument"}, status=status.HTTP_404_NOT_FOUND)

        try:
            column = get_object_or_404(MetadataColumn, id=column_id, metadata_table=instrument.metadata_table)

            column_name = column.name
            column.delete()

            return Response({"message": f'Column "{column_name}" removed successfully'})

        except Exception as e:
            return Response(
                {"error": f"Failed to remove column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["patch"])
    def update_metadata_value(self, request, pk=None):
        """Update default values in the instrument's metadata table."""
        instrument = self.get_object()

        if not instrument.metadata_table:
            return Response({"error": "No metadata table found for this instrument"}, status=status.HTTP_404_NOT_FOUND)

        column_id = request.data.get("column_id")
        new_value = request.data.get("value", "")

        if not column_id:
            return Response({"error": "column_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            column = get_object_or_404(MetadataColumn, id=column_id, metadata_table=instrument.metadata_table)

            column.value = new_value
            column.save()

            return Response(
                {"message": "Metadata value updated successfully", "column_name": column.name, "new_value": new_value}
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to update metadata value: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["get"])
    def folders(self, request, pk=None):
        """Get annotation folders for this instrument."""
        instrument = self.get_object()

        if not instrument.user:
            return Response({"error": "Instrument has no user assigned"}, status=status.HTTP_404_NOT_FOUND)

        folders = AnnotationFolder.objects.filter(
            owner=instrument.user,
            resource_type=ResourceType.FILE,
            folder_name__in=["Manuals", "Certificates", "Maintenance"],
        )

        serializer = AnnotationFolderSerializer(folders, many=True)
        return Response(serializer.data)


class InstrumentJobViewSet(BaseViewSet):
    """ViewSet for InstrumentJob model."""

    queryset = InstrumentJob.objects.all()
    serializer_class = InstrumentJobSerializer
    permission_classes = [IsAuthenticated, InstrumentJobPermission]
    filterset_fields = [
        "job_type",
        "status",
        "sample_type",
        "assigned",
        "user",
        "instrument",
        "metadata_table",
        "project",
    ]
    search_fields = ["job_name", "method", "search_details", "location", "funder"]
    ordering_fields = ["job_name", "status", "created_at", "updated_at", "submitted_at", "completed_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        """Use detailed serializer for retrieve action."""
        if self.action == "retrieve":
            return InstrumentJobDetailSerializer
        return InstrumentJobSerializer

    def perform_create(self, serializer):
        """Set the user when creating a job."""
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """Check permissions before updating job."""
        job = self.get_object()
        if not job.can_edit(self.request.user):
            raise PermissionDenied("You don't have permission to edit this job")
        serializer.save()

    def perform_destroy(self, instance):
        """Check permissions before deleting job."""
        if not instance.can_delete(self.request.user):
            raise PermissionDenied("You don't have permission to delete this job")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """Submit a job for processing."""
        job = self.get_object()

        if job.status != "draft":
            return Response({"error": "Only draft jobs can be submitted"}, status=status.HTTP_400_BAD_REQUEST)

        job.status = "submitted"
        job.submitted_at = timezone.now()
        job.save()

        serializer = self.get_serializer(job)
        return Response({"message": "Job submitted successfully", "job": serializer.data})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark a job as completed."""
        job = self.get_object()

        if job.status not in ["submitted", "pending", "in_progress"]:
            return Response(
                {"error": "Job is not in a state that can be completed"}, status=status.HTTP_400_BAD_REQUEST
            )

        job.status = "completed"
        job.completed_at = timezone.now()
        job.save()

        serializer = self.get_serializer(job)
        return Response({"message": "Job completed successfully", "job": serializer.data})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a job."""
        job = self.get_object()

        if job.status == "completed":
            return Response({"error": "Cannot cancel a completed job"}, status=status.HTTP_400_BAD_REQUEST)

        job.status = "cancelled"
        job.save()

        serializer = self.get_serializer(job)
        return Response({"message": "Job cancelled successfully", "job": serializer.data})

    @action(detail=False, methods=["get"])
    def my_jobs(self, request):
        """Get current user's jobs."""
        user_jobs = self.get_queryset().filter(user=request.user)

        page = self.paginate_queryset(user_jobs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(user_jobs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def assigned_jobs(self, request):
        """Get jobs assigned to current user (for staff)."""
        assigned_jobs = self.get_queryset().filter(staff=request.user)

        page = self.paginate_queryset(assigned_jobs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(assigned_jobs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def autocomplete_fields(self, request):
        """
        Get distinct funder and cost_center values from user's existing jobs for autocomplete.

        Returns unique, non-null values that the current user has used in their previous jobs.
        """
        user_jobs = self.get_queryset().filter(user=request.user)

        funders = (
            user_jobs.exclude(funder__isnull=True)
            .exclude(funder__exact="")
            .values_list("funder", flat=True)
            .distinct()
            .order_by("funder")
        )

        cost_centers = (
            user_jobs.exclude(cost_center__isnull=True)
            .exclude(cost_center__exact="")
            .values_list("cost_center", flat=True)
            .distinct()
            .order_by("cost_center")
        )

        return Response({"funders": list(funders), "cost_centers": list(cost_centers)})

    @action(detail=True, methods=["post"])
    def create_metadata_from_template(self, request, pk=None):
        """Create a metadata table for this job from an existing template."""
        job = self.get_object()

        # Check if job already has a metadata table
        if job.metadata_table:
            return Response({"error": "Job already has a metadata table"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate required fields
        template_id = request.data.get("template_id")
        if not template_id:
            return Response({"error": "Template ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get the template
            template = MetadataTableTemplate.objects.get(id=template_id)

            # Check if user has access to this template
            if not template.can_view(request.user):
                return Response({"error": "You do not have access to this template"}, status=status.HTTP_403_FORBIDDEN)

            # Get optional parameters
            custom_name = request.data.get("name")
            description = request.data.get("description")
            sample_count = request.data.get("sample_count", job.sample_number or 1)
            lab_group_id = request.data.get("lab_group_id")

            # Generate table name if not provided
            if not custom_name:
                job_name = job.job_name or f"{job.get_job_type_display()} Job"
                custom_name = f"{job_name} - Metadata"

            # Get lab group if specified
            lab_group = None
            if lab_group_id:
                try:
                    lab_group = LabGroup.objects.get(id=lab_group_id)
                    # Check if user is member of this lab group (includes bubble-up from sub-groups)
                    if not lab_group.is_member(request.user):
                        return Response(
                            {"error": "You are not a member of the specified lab group"},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                except LabGroup.DoesNotExist:
                    return Response({"error": "Lab group not found"}, status=status.HTTP_404_NOT_FOUND)

            # Create metadata table from template
            metadata_table = template.create_table_from_template(
                table_name=custom_name,
                creator=request.user,
                sample_count=sample_count,
                description=description or f"Metadata table for job: {job}",
                lab_group=lab_group,
            )

            # Set source_app to 'ccm' to mark it as CCM-managed
            metadata_table.source_app = "ccm"
            metadata_table.save(update_fields=["source_app"])

            # Link the metadata table to the job
            job.metadata_table = metadata_table
            job.save(update_fields=["metadata_table"])

            # Return the created metadata table info
            serializer = MetadataTableSerializer(metadata_table)
            return Response(
                {
                    "message": "Metadata table created successfully from template",
                    "metadata_table": serializer.data,
                    "job_id": job.id,
                },
                status=status.HTTP_201_CREATED,
            )

        except MetadataTableTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to create metadata table from template: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class InstrumentUsageViewSet(BaseViewSet):
    """ViewSet for InstrumentUsage model."""

    queryset = InstrumentUsage.objects.all()
    serializer_class = InstrumentUsageSerializer
    filterset_fields = {
        "user": ["exact"],
        "instrument": ["exact"],
        "approved": ["exact"],
        "maintenance": ["exact"],
        "approved_by": ["exact"],
        "time_started": ["gte", "lte", "gt", "lt"],
        "time_ended": ["gte", "lte", "gt", "lt"],
    }
    search_fields = ["description"]
    ordering_fields = ["time_started", "time_ended", "usage_hours", "created_at"]
    ordering = ["-time_started"]

    def perform_create(self, serializer):
        """Set the user when creating usage record."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def my_usage(self, request):
        """Get current user's usage records."""
        user_usage = self.get_queryset().filter(user=request.user)

        page = self.paginate_queryset(user_usage)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(user_usage, many=True)
        return Response(serializer.data)


class MaintenanceLogViewSet(BaseViewSet):
    """ViewSet for MaintenanceLog model."""

    queryset = MaintenanceLog.objects.all()
    serializer_class = MaintenanceLogSerializer
    filterset_fields = ["maintenance_type", "status", "instrument", "created_by", "is_template"]
    search_fields = ["maintenance_description", "maintenance_notes"]
    ordering_fields = ["maintenance_date", "maintenance_type", "status", "created_at"]
    ordering = ["-maintenance_date"]

    def get_queryset(self):
        """
        Filter maintenance logs based on instrument permission system.
        Users can see logs they created, logs for instruments they own,
        or logs for instruments they have manage permissions on.
        """
        user = self.request.user
        queryset = super().get_queryset()

        if user.is_staff or user.is_superuser:
            return queryset

        permitted_instrument_ids = InstrumentPermission.objects.filter(user=user, can_manage=True).values_list(
            "instrument_id", flat=True
        )

        return queryset.filter(
            Q(created_by=user) | Q(instrument__user=user) | Q(instrument_id__in=permitted_instrument_ids)
        )

    def perform_create(self, serializer):
        """
        Create maintenance log.
        Requires can_manage permission on the instrument or staff/superuser.
        """
        user = self.request.user
        instrument = serializer.validated_data.get("instrument")

        if not instrument:
            raise PermissionDenied("Instrument is required for maintenance logs")

        if not (user.is_staff or user.is_superuser or instrument.user_can_manage(user)):
            raise PermissionDenied("Only staff or users with manage permissions can create maintenance logs")

        serializer.save(created_by=user)

    def perform_update(self, serializer):
        """
        Update maintenance log.
        Uses instrument permission system.
        """
        maintenance_log = serializer.instance

        if not maintenance_log.user_can_edit(self.request.user):
            raise PermissionDenied("You do not have permission to edit this maintenance log")

        serializer.save()

    def perform_destroy(self, instance):
        """
        Delete maintenance log.
        Uses instrument permission system.
        """
        if not instance.user_can_delete(self.request.user):
            raise PermissionDenied("You do not have permission to delete this maintenance log")

        instance.delete()


class StorageObjectViewSet(BaseViewSet):
    """ViewSet for StorageObject model."""

    queryset = StorageObject.objects.select_related("stored_at", "user", "remote_host").all()
    serializer_class = StorageObjectSerializer
    filterset_fields = {
        "object_type": ["exact"],
        "stored_at": ["exact", "isnull"],
        "can_delete": ["exact"],
        "is_vaulted": ["exact"],
        "user": ["exact"],
    }
    search_fields = ["object_name", "object_description"]
    ordering_fields = ["object_name", "object_type", "created_at", "updated_at"]
    ordering = ["object_name"]

    def get_queryset(self):
        """Filter storage objects by user access."""
        user = self.request.user

        if user.is_staff or user.is_superuser:
            return self.queryset

        accessible_ids = set()
        all_storage_objects = StorageObject.objects.prefetch_related("access_lab_groups", "stored_at").all()

        for storage_obj in all_storage_objects:
            if storage_obj.can_access(user):
                accessible_ids.add(storage_obj.id)

        return self.queryset.filter(Q(id__in=accessible_ids) | Q(user=user))

    def perform_create(self, serializer):
        """Set the user when creating a storage object."""
        serializer.save(user=self.request.user)


class ReagentViewSet(BaseViewSet):
    """ViewSet for Reagent model."""

    queryset = Reagent.objects.all()
    serializer_class = ReagentSerializer
    filterset_fields = ["unit"]
    search_fields = ["name", "unit"]
    ordering_fields = ["name", "unit", "created_at"]
    ordering = ["name"]


class StoredReagentViewSet(BaseViewSet):
    """ViewSet for StoredReagent model."""

    queryset = StoredReagent.objects.all()
    serializer_class = StoredReagentSerializer
    filterset_fields = ["reagent", "quantity", "expiration_date"]
    search_fields = ["reagent__name", "notes", "reagent__unit", "barcode"]
    ordering_fields = ["quantity", "expiration_date", "created_at"]
    ordering = ["reagent__name"]

    def get_queryset(self):
        """
        Filter stored reagents with optional sub-storage inclusion.

        Query parameters:
        - storage_object: Filter by storage object ID
        - include_sub_storage: If 'true', include reagents from all nested child storage objects
        """
        queryset = super().get_queryset()

        storage_object_id = self.request.query_params.get("storage_object")
        include_sub_storage = self.request.query_params.get("include_sub_storage", "").lower() == "true"

        if storage_object_id:
            try:
                storage_obj = StorageObject.objects.get(id=storage_object_id)

                if include_sub_storage:

                    def get_all_sub_storage_ids(storage):
                        """Recursively get all child storage object IDs."""
                        ids = [storage.id]
                        for child in StorageObject.objects.filter(stored_at=storage):
                            ids.extend(get_all_sub_storage_ids(child))
                        return ids

                    all_storage_ids = get_all_sub_storage_ids(storage_obj)
                    queryset = queryset.filter(storage_object_id__in=all_storage_ids)
                else:
                    queryset = queryset.filter(storage_object_id=storage_object_id)
            except StorageObject.DoesNotExist:
                queryset = queryset.none()

        return queryset

    def perform_create(self, serializer):
        """Set the user when creating a stored reagent."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """Get stored reagents with low stock based on individual threshold."""
        low_stock_reagents = self.get_queryset().filter(
            quantity__lte=models.F("low_stock_threshold"), low_stock_threshold__isnull=False, quantity__gt=0
        )

        serializer = self.get_serializer(low_stock_reagents, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def send_test_notification(self, request, pk=None):
        """
        Send a test notification for this stored reagent.
        Only accessible by staff or admin users.

        Request body should contain:
        - notification_type: One of 'low_stock', 'expired', 'expiring_soon'
        - recipient_id: Optional user ID to send to (defaults to current user)
        """
        if not (request.user.is_staff or request.user.is_superuser):
            return Response(
                {"error": "Only staff or admin users can send test notifications"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stored_reagent = self.get_object()

        notification_type = request.data.get("notification_type", "low_stock")
        recipient_id = request.data.get("recipient_id")

        valid_types = ["low_stock", "expired", "expiring_soon"]
        if notification_type not in valid_types:
            return Response(
                {"error": f"Invalid notification_type. Must be one of: {', '.join(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine recipient
        if recipient_id:
            User = get_user_model()
            try:
                recipient = User.objects.get(pk=recipient_id)
            except User.DoesNotExist:
                return Response({"error": "Recipient user not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            recipient = request.user

        # Send test notification
        success = send_reagent_alert(
            stored_reagent=stored_reagent, alert_type=notification_type, notify_users=[recipient]
        )

        if success:
            return Response(
                {
                    "success": True,
                    "message": f"Test notification sent to {recipient.username}",
                    "notification_type": notification_type,
                }
            )
        else:
            return Response(
                {"error": "Failed to send notification. CCMC may not be available."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def metadata(self, request, pk=None):
        """Get metadata table details for this stored reagent."""
        stored_reagent = self.get_object()

        if not stored_reagent.metadata_table:
            return Response(
                {"error": "No metadata table found for this stored reagent"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = MetadataTableSerializer(stored_reagent.metadata_table)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def add_metadata_column(self, request, pk=None):
        """Add a column to the stored reagent's metadata table."""
        stored_reagent = self.get_object()

        if not stored_reagent.metadata_table:
            return Response(
                {"error": "No metadata table found for this stored reagent"}, status=status.HTTP_404_NOT_FOUND
            )

        # Get column data from request
        column_data = request.data

        if not column_data.get("name"):
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Create the column linked to this metadata table
            column = MetadataColumn.objects.create(
                metadata_table=stored_reagent.metadata_table,
                name=column_data["name"],
                type=column_data.get("type", "characteristics"),
                value=column_data.get("value", ""),
                column_position=stored_reagent.metadata_table.get_column_count(),
                mandatory=column_data.get("mandatory", False),
                hidden=column_data.get("hidden", False),
                readonly=column_data.get("readonly", False),
            )

            serializer = MetadataColumnSerializer(column)
            return Response(
                {"message": "Column added successfully", "column": serializer.data}, status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to create column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["delete"], url_path="remove_metadata_column/(?P<column_id>[^/.]+)")
    def remove_metadata_column(self, request, pk=None, column_id=None):
        """Remove a column from the stored reagent's metadata table."""
        stored_reagent = self.get_object()

        if not stored_reagent.metadata_table:
            return Response(
                {"error": "No metadata table found for this stored reagent"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            from ccv.models import MetadataColumn

            column = get_object_or_404(MetadataColumn, id=column_id, metadata_table=stored_reagent.metadata_table)

            column_name = column.name
            column.delete()

            return Response({"message": f'Column "{column_name}" removed successfully'})

        except Exception as e:
            return Response(
                {"error": f"Failed to remove column: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["patch"])
    def update_metadata_value(self, request, pk=None):
        """Update default values in the stored reagent's metadata table."""
        stored_reagent = self.get_object()

        if not stored_reagent.metadata_table:
            return Response(
                {"error": "No metadata table found for this stored reagent"}, status=status.HTTP_404_NOT_FOUND
            )

        column_id = request.data.get("column_id")
        new_value = request.data.get("value", "")

        if not column_id:
            return Response({"error": "column_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from ccv.models import MetadataColumn

            column = get_object_or_404(MetadataColumn, id=column_id, metadata_table=stored_reagent.metadata_table)

            column.value = new_value
            column.save()

            return Response(
                {"message": "Metadata value updated successfully", "column_name": column.name, "new_value": new_value}
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to update metadata value: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["get"])
    def folders(self, request, pk=None):
        """Get annotation folders for this stored reagent."""
        stored_reagent = self.get_object()

        if not stored_reagent.user:
            return Response({"error": "StoredReagent has no user assigned"}, status=status.HTTP_404_NOT_FOUND)

        folders = AnnotationFolder.objects.filter(
            owner=stored_reagent.user,
            resource_type=ResourceType.FILE,
            folder_name__in=["MSDS", "Certificates", "Manuals"],
        )

        serializer = AnnotationFolderSerializer(folders, many=True)
        return Response(serializer.data)


class ExternalContactViewSet(BaseViewSet):
    """ViewSet for ExternalContact model. Staff/admin only."""

    queryset = ExternalContact.objects.all()
    serializer_class = ExternalContactSerializer
    filterset_fields = ["user"]
    search_fields = ["contact_name"]
    ordering_fields = ["contact_name", "created_at"]
    ordering = ["contact_name"]

    def get_queryset(self):
        """Only staff and admin users can view external contacts."""
        if self.request.user.is_staff or self.request.user.is_superuser:
            return self.queryset
        return self.queryset.none()

    def perform_create(self, serializer):
        """
        Set the user when creating an external contact.
        Only staff or admin users can create external contacts.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can create external contacts")
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """Only staff or admin users can update external contacts."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can update external contacts")
        serializer.save()

    def perform_destroy(self, instance):
        """Only staff or admin users can delete external contacts."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can delete external contacts")
        instance.delete()


class ExternalContactDetailsViewSet(BaseViewSet):
    """ViewSet for ExternalContactDetails model. Staff/admin only."""

    queryset = ExternalContactDetails.objects.all()
    serializer_class = ExternalContactDetailsSerializer
    filterset_fields = ["contact_type"]
    search_fields = ["contact_method_alt_name", "contact_value"]
    ordering_fields = ["contact_type", "created_at"]
    ordering = ["contact_type"]

    def get_queryset(self):
        """Only staff and admin users can view external contact details."""
        if self.request.user.is_staff or self.request.user.is_superuser:
            return self.queryset
        return self.queryset.none()

    def perform_create(self, serializer):
        """
        Create external contact details.
        Only staff or admin users can create external contact details.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can create external contact details")
        serializer.save()

    def perform_update(self, serializer):
        """Only staff or admin users can update external contact details."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can update external contact details")
        serializer.save()

    def perform_destroy(self, instance):
        """Only staff or admin users can delete external contact details."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can delete external contact details")
        instance.delete()


class SupportInformationViewSet(BaseViewSet):
    """ViewSet for SupportInformation model. Staff/admin only."""

    queryset = SupportInformation.objects.all()
    serializer_class = SupportInformationSerializer
    filterset_fields = ["vendor_name", "manufacturer_name", "location", "warranty_start_date", "warranty_end_date"]
    search_fields = ["vendor_name", "manufacturer_name", "serial_number"]
    ordering_fields = ["warranty_start_date", "warranty_end_date", "created_at"]
    ordering = ["-warranty_end_date"]

    def get_queryset(self):
        """Only staff and admin users can view support information."""
        if self.request.user.is_staff or self.request.user.is_superuser:
            return self.queryset
        return self.queryset.none()

    def perform_create(self, serializer):
        """
        Create support information.
        Only staff or admin users can create support information.
        """
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can create support information")
        serializer.save()

    def perform_update(self, serializer):
        """Only staff or admin users can update support information."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can update support information")
        serializer.save()

    def perform_destroy(self, instance):
        """Only staff or admin users can delete support information."""
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            raise PermissionDenied("Only staff or admin users can delete support information")
        instance.delete()


class ReagentSubscriptionViewSet(BaseViewSet):
    """ViewSet for ReagentSubscription model."""

    queryset = ReagentSubscription.objects.all()
    serializer_class = ReagentSubscriptionSerializer
    filterset_fields = ["stored_reagent", "user", "notify_on_low_stock", "notify_on_expiry"]
    search_fields = ["stored_reagent__reagent__name", "user__username"]
    ordering_fields = ["created_at"]
    ordering = ["stored_reagent__reagent__name"]

    def perform_create(self, serializer):
        """Set the user when creating subscription."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def my_subscriptions(self, request):
        """Get current user's reagent subscriptions."""
        user_subscriptions = self.get_queryset().filter(user=request.user)

        serializer = self.get_serializer(user_subscriptions, many=True)
        return Response(serializer.data)


class ReagentActionViewSet(BaseViewSet):
    """ViewSet for ReagentAction model."""

    queryset = ReagentAction.objects.all()
    serializer_class = ReagentActionSerializer
    filterset_fields = ["reagent", "user", "action_type", "session", "step"]
    search_fields = ["reagent__reagent__name", "notes"]
    ordering_fields = ["quantity", "created_at"]
    ordering = ["-created_at"]

    def perform_create(self, serializer):
        """Set the user when creating action record."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def my_actions(self, request):
        """Get current user's reagent actions."""
        user_actions = self.get_queryset().filter(user=request.user)

        page = self.paginate_queryset(user_actions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(user_actions, many=True)
        return Response(serializer.data)


class InstrumentPermissionViewSet(BaseViewSet):
    """ViewSet for InstrumentPermission model."""

    queryset = InstrumentPermission.objects.all()
    serializer_class = InstrumentPermissionSerializer
    filterset_fields = ["instrument", "user", "can_view", "can_book", "can_manage"]
    search_fields = ["instrument__instrument_name", "user__username"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        """Filter permissions by user access."""
        user = self.request.user
        if user.is_staff:
            return self.queryset
        # Users can only see permissions for instruments they can manage
        return self.queryset.filter(
            Q(instrument__created_by=user)
            | Q(instrument__instrumentpermission__user=user, instrument__instrumentpermission__can_manage=True)
        ).distinct()


class InstrumentAnnotationFilter(django_filters.FilterSet):
    """Filter for InstrumentAnnotation with scratched support."""

    scratched = django_filters.BooleanFilter(field_name="annotation__scratched")

    class Meta:
        model = InstrumentAnnotation
        fields = ["instrument", "folder", "annotation", "scratched"]


class InstrumentAnnotationViewSet(BaseViewSet):
    """
    ViewSet for InstrumentAnnotation model.

    Permissions:
    - Maintenance documents: Only staff can view and edit
    - Other documents (Manuals, Certificates): Users with view rights can see,
      only managers can upload/edit/delete
    """

    queryset = InstrumentAnnotation.objects.all()
    serializer_class = InstrumentAnnotationSerializer
    filterset_class = InstrumentAnnotationFilter
    search_fields = ["annotation__annotation", "folder__folder_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter annotations by instrument access permissions and folder type."""
        user = self.request.user
        queryset = self.queryset.select_related("instrument", "folder")

        if user.is_staff:
            return queryset

        accessible_annotations = []
        for annotation_junction in queryset:
            instrument = annotation_junction.instrument
            folder = annotation_junction.folder

            # Maintenance documents are staff-only
            if folder.folder_name == "Maintenance":
                continue

            # For other documents, check if user can view the instrument
            if instrument.user_can_view(user):
                accessible_annotations.append(annotation_junction.id)

        return queryset.filter(id__in=accessible_annotations)

    def create(self, request, *args, **kwargs):
        """Create instrument annotation, handling annotation_data if provided."""
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")

            if not annotation_text:
                return Response(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from ccc.models import Annotation

            folder_id = request.data.get("folder")
            from ccc.models import AnnotationFolder

            folder = AnnotationFolder.objects.get(id=folder_id) if folder_id else None

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                folder=folder,
                owner=request.user,
            )

            data = request.data.copy()
            data["annotation"] = annotation.id
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update instrument annotation, handling annotation_data if provided."""
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

    def perform_create(self, serializer):
        """Only managers can upload documents."""
        instrument = serializer.validated_data.get("instrument")
        if not instrument.user_can_manage(self.request.user):
            raise PermissionDenied("Only instrument managers can upload annotations")
        serializer.save()

    def perform_update(self, serializer):
        """Only managers can edit documents."""
        instrument = serializer.instance.instrument
        if not instrument.user_can_manage(self.request.user):
            raise PermissionDenied("Only instrument managers can edit annotations")
        serializer.save()

    def perform_destroy(self, instance):
        """Only managers can delete documents."""
        if not instance.instrument.user_can_manage(self.request.user):
            raise PermissionDenied("Only instrument managers can delete annotations")
        instance.delete()


class StoredReagentAnnotationFilter(django_filters.FilterSet):
    """Filter for StoredReagentAnnotation with scratched support."""

    scratched = django_filters.BooleanFilter(field_name="annotation__scratched")

    class Meta:
        model = StoredReagentAnnotation
        fields = ["stored_reagent", "folder", "annotation", "scratched"]


class StoredReagentAnnotationViewSet(BaseViewSet):
    """
    ViewSet for StoredReagentAnnotation model.

    Permissions:
    - View: Users who can access the storage object can view documents
    - Upload/Edit/Delete: Only staff or the original creator (stored_reagent.user)
    """

    queryset = StoredReagentAnnotation.objects.all()
    serializer_class = StoredReagentAnnotationSerializer
    filterset_class = StoredReagentAnnotationFilter
    search_fields = ["annotation__annotation", "folder__folder_name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order"]

    def get_queryset(self):
        """Filter annotations by stored reagent access permissions."""
        user = self.request.user
        queryset = self.queryset.select_related("stored_reagent__storage_object", "stored_reagent__user")

        if user.is_staff or user.is_superuser:
            return queryset

        accessible_annotations = []
        for annotation_junction in queryset:
            stored_reagent = annotation_junction.stored_reagent
            # Users who can access the storage can view documents
            if stored_reagent.storage_object and stored_reagent.storage_object.can_access(user):
                accessible_annotations.append(annotation_junction.id)

        return queryset.filter(id__in=accessible_annotations)

    def create(self, request, *args, **kwargs):
        """Create stored reagent annotation, handling annotation_data if provided."""
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")

            if not annotation_text:
                return Response(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from ccc.models import Annotation

            folder_id = request.data.get("folder")
            from ccc.models import AnnotationFolder

            folder = AnnotationFolder.objects.get(id=folder_id) if folder_id else None

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                folder=folder,
                owner=request.user,
            )

            data = request.data.copy()
            data["annotation"] = annotation.id
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update stored reagent annotation, handling annotation_data if provided."""
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

    def perform_create(self, serializer):
        """Only staff or creator can upload documents."""
        stored_reagent = serializer.validated_data.get("stored_reagent")
        user = self.request.user

        if not (user.is_staff or user.is_superuser or stored_reagent.user == user):
            raise PermissionDenied("Only staff or the reagent creator can upload annotations")
        serializer.save()

    def perform_update(self, serializer):
        """Only staff or creator can edit documents."""
        stored_reagent = serializer.instance.stored_reagent
        user = self.request.user

        if not (user.is_staff or user.is_superuser or stored_reagent.user == user):
            raise PermissionDenied("Only staff or the reagent creator can edit annotations")
        serializer.save()

    def perform_destroy(self, instance):
        """Only staff or creator can delete documents."""
        stored_reagent = instance.stored_reagent
        user = self.request.user

        if not (user.is_staff or user.is_superuser or stored_reagent.user == user):
            raise PermissionDenied("Only staff or the reagent creator can delete annotations")
        instance.delete()


class MaintenanceLogAnnotationFilter(django_filters.FilterSet):
    """Filter for MaintenanceLogAnnotation with scratched support."""

    scratched = django_filters.BooleanFilter(field_name="annotation__scratched")

    class Meta:
        model = MaintenanceLogAnnotation
        fields = ["maintenance_log", "annotation", "scratched"]


class MaintenanceLogAnnotationViewSet(BaseViewSet):
    """ViewSet for MaintenanceLogAnnotation model."""

    queryset = MaintenanceLogAnnotation.objects.select_related(
        "maintenance_log", "maintenance_log__instrument", "annotation"
    ).all()
    serializer_class = MaintenanceLogAnnotationSerializer
    filterset_class = MaintenanceLogAnnotationFilter
    search_fields = ["annotation__annotation", "annotation__name"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order", "created_at"]

    def get_queryset(self):
        """
        Filter maintenance log annotations based on instrument permission system.
        Users can see annotations for maintenance logs they created, logs for instruments they own,
        or logs for instruments they have manage permissions on.
        """
        user = self.request.user
        queryset = super().get_queryset()

        if user.is_staff or user.is_superuser:
            return queryset

        permitted_instrument_ids = InstrumentPermission.objects.filter(user=user, can_manage=True).values_list(
            "instrument_id", flat=True
        )

        return queryset.filter(
            Q(maintenance_log__created_by=user)
            | Q(maintenance_log__instrument__user=user)
            | Q(maintenance_log__instrument_id__in=permitted_instrument_ids)
        )

    def create(self, request, *args, **kwargs):
        """Create maintenance log annotation, handling annotation_data if provided."""
        annotation_data = request.data.get("annotation_data")

        if annotation_data:
            annotation_type = annotation_data.get("annotation_type", "text")
            annotation_text = annotation_data.get("annotation", "")

            if not annotation_text:
                return Response(
                    {"annotation_data": {"annotation": "This field is required for non-file annotations."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from ccc.models import Annotation

            annotation = Annotation.objects.create(
                annotation=annotation_text,
                annotation_type=annotation_type,
                transcription=annotation_data.get("transcription"),
                language=annotation_data.get("language"),
                translation=annotation_data.get("translation"),
                scratched=annotation_data.get("scratched", False),
                owner=request.user,
            )

            data = request.data.copy()
            data["annotation"] = annotation.id
            if "annotation_data" in data:
                del data["annotation_data"]
            request._full_data = data

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update maintenance log annotation, handling annotation_data if provided."""
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

    def perform_create(self, serializer):
        """
        Create maintenance log annotation.
        Requires can_manage permission on the instrument or staff/superuser.
        """
        user = self.request.user
        maintenance_log = serializer.validated_data.get("maintenance_log")

        if not maintenance_log:
            raise PermissionDenied("Maintenance log is required")

        if not maintenance_log.user_can_edit(user):
            raise PermissionDenied("You do not have permission to add annotations to this maintenance log")

        serializer.save()

    def perform_update(self, serializer):
        """
        Update maintenance log annotation.
        Uses instrument permission system through maintenance log.
        """
        maintenance_log_annotation = serializer.instance

        if not maintenance_log_annotation.can_edit(self.request.user):
            raise PermissionDenied("You do not have permission to edit this maintenance log annotation")

        serializer.save()

    def perform_destroy(self, instance):
        """
        Delete maintenance log annotation.
        Uses instrument permission system through maintenance log.
        """
        if not instance.can_delete(self.request.user):
            raise PermissionDenied("You do not have permission to delete this maintenance log annotation")

        instance.delete()
