"""ViewSets for CUPCAKE Core Macaron (CCM) models.

Provides REST API endpoints for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentJob,
    InstrumentPermission,
    InstrumentUsage,
    MaintenanceLog,
    Reagent,
    ReagentAction,
    ReagentSubscription,
    StorageObject,
    StoredReagent,
    SupportInformation,
)
from .serializers import (
    ExternalContactDetailsSerializer,
    ExternalContactSerializer,
    InstrumentDetailSerializer,
    InstrumentJobDetailSerializer,
    InstrumentJobSerializer,
    InstrumentPermissionSerializer,
    InstrumentSerializer,
    InstrumentUsageSerializer,
    MaintenanceLogSerializer,
    ReagentActionSerializer,
    ReagentSerializer,
    ReagentSubscriptionSerializer,
    StorageObjectSerializer,
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
        """Set the user when creating an instrument."""
        serializer.save(user=self.request.user)

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

    @action(detail=True, methods=["get"])
    def metadata(self, request, pk=None):
        """Get metadata table details for this instrument."""
        instrument = self.get_object()

        if not instrument.metadata_table:
            return Response({"error": "No metadata table found for this instrument"}, status=status.HTTP_404_NOT_FOUND)

        from ccv.serializers import MetadataTableSerializer

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
            from ccv.models import MetadataColumn
            from ccv.serializers import MetadataColumnSerializer

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
            from ccv.models import MetadataColumn

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
            from ccv.models import MetadataColumn

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


class InstrumentJobViewSet(BaseViewSet):
    """ViewSet for InstrumentJob model."""

    queryset = InstrumentJob.objects.all()
    serializer_class = InstrumentJobSerializer
    filterset_fields = ["job_type", "status", "sample_type", "assigned", "user", "instrument", "metadata_table"]
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
            from ccv.models import LabGroup, MetadataTableTemplate

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
            from ccv.serializers import MetadataTableSerializer

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
    filterset_fields = ["user", "instrument", "approved", "maintenance", "approved_by"]
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
        """Staff can see all maintenance logs, others see none."""
        if self.request.user.is_staff:
            return super().get_queryset()
        else:
            return self.queryset.none()


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

        from django.db.models import Q

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
    filterset_fields = ["reagent", "storage_object", "quantity", "expiration_date"]
    search_fields = ["reagent__name", "notes", "unit"]
    ordering_fields = ["quantity", "expiration_date", "created_at"]
    ordering = ["reagent__name"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """Get stored reagents with low stock based on individual threshold."""
        low_stock_reagents = self.get_queryset().filter(
            quantity__lte=models.F("low_stock_threshold"), low_stock_threshold__isnull=False, quantity__gt=0
        )

        serializer = self.get_serializer(low_stock_reagents, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def metadata(self, request, pk=None):
        """Get metadata table details for this stored reagent."""
        stored_reagent = self.get_object()

        if not stored_reagent.metadata_table:
            return Response(
                {"error": "No metadata table found for this stored reagent"}, status=status.HTTP_404_NOT_FOUND
            )

        from ccv.serializers import MetadataTableSerializer

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
            from ccv.models import MetadataColumn
            from ccv.serializers import MetadataColumnSerializer

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


class ExternalContactViewSet(BaseViewSet):
    """ViewSet for ExternalContact model."""

    queryset = ExternalContact.objects.all()
    serializer_class = ExternalContactSerializer
    filterset_fields = ["user"]
    search_fields = ["contact_name"]
    ordering_fields = ["contact_name", "created_at"]
    ordering = ["contact_name"]


class ExternalContactDetailsViewSet(BaseViewSet):
    """ViewSet for ExternalContactDetails model."""

    queryset = ExternalContactDetails.objects.all()
    serializer_class = ExternalContactDetailsSerializer
    filterset_fields = ["contact_type"]
    search_fields = ["contact_method_alt_name", "contact_value"]
    ordering_fields = ["contact_type", "created_at"]
    ordering = ["contact_type"]


class SupportInformationViewSet(BaseViewSet):
    """ViewSet for SupportInformation model."""

    queryset = SupportInformation.objects.all()
    serializer_class = SupportInformationSerializer
    filterset_fields = ["vendor_name", "manufacturer_name", "location", "warranty_start_date", "warranty_end_date"]
    search_fields = ["vendor_name", "manufacturer_name", "serial_number"]
    ordering_fields = ["warranty_start_date", "warranty_end_date", "created_at"]
    ordering = ["-warranty_end_date"]


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
    filterset_fields = ["reagent", "user", "action_type"]
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
