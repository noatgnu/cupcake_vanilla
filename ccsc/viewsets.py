"""
CUPCAKE Salted Caramel (CCSC) Billing ViewSets.

DRF ViewSets for billing and financial management functionality
with custom actions for approvals, calculations, and reporting.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from .models import BillableItemType, BillingRecord, ServicePrice, ServiceTier
from .serializers import (
    BillableItemTypeSerializer,
    BillingApprovalSerializer,
    BillingRecordCreateSerializer,
    BillingRecordSerializer,
    BillingRecordSummarySerializer,
    ServicePriceCalculationSerializer,
    ServicePriceSerializer,
    ServiceTierSerializer,
)

User = get_user_model()


class BillingPermission(permissions.BasePermission):
    """
    Custom permission for billing operations.

    - Read: Any authenticated user can view their own records
    - Write: Staff users can create/modify billing records
    - Approve: Only staff users can approve billing records
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Read permissions for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions for staff
        return request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # Staff can access everything
        if request.user.is_staff:
            return True

        # Users can view their own billing records
        if hasattr(obj, "user") and obj.user == request.user:
            return request.method in permissions.SAFE_METHODS

        return False


class ServiceTierViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing service tiers with pricing calculations.
    """

    queryset = ServiceTier.objects.all()
    serializer_class = ServiceTierSerializer
    permission_classes = [BillingPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "priority_level"]
    search_fields = ["tier_name", "description"]
    ordering_fields = ["tier_name", "priority_level", "created_at"]
    ordering = ["-priority_level", "tier_name"]

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()

        # Staff can see all tiers, users only see active ones
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)

        return queryset

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def calculate_price(self, request, pk=None):
        """
        Calculate price for a given base amount using this tier's modifiers.
        """
        tier = self.get_object()

        try:
            base_price = Decimal(str(request.data.get("base_price", 0)))
        except (ValueError, TypeError):
            return Response({"error": "Invalid base_price. Must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        if base_price < 0:
            return Response({"error": "Base price must be non-negative."}, status=status.HTTP_400_BAD_REQUEST)

        final_price = tier.calculate_price(base_price)

        return Response(
            {
                "tier_name": tier.tier_name,
                "base_price": base_price,
                "base_rate_multiplier": tier.base_rate_multiplier,
                "discount_percentage": tier.discount_percentage,
                "final_price": final_price,
                "currency": "USD",  # Default currency
            }
        )

    @action(detail=False, methods=["get"])
    def active_tiers(self, request):
        """Get only active service tiers."""
        active_tiers = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(active_tiers, many=True)
        return Response(serializer.data)


class BillableItemTypeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing billable item types and their configurations.
    """

    queryset = BillableItemType.objects.all()
    serializer_class = BillableItemTypeSerializer
    permission_classes = [BillingPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "requires_approval", "default_billing_unit"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()

        # Staff can see all item types, users only see active ones
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)

        return queryset

    @action(detail=False, methods=["get"])
    def by_content_type(self, request):
        """Get billable item types grouped by content type."""
        app_label = request.query_params.get("app_label")
        model = request.query_params.get("model")

        queryset = self.get_queryset()

        if app_label:
            queryset = queryset.filter(content_type__app_label=app_label)

        if model:
            queryset = queryset.filter(content_type__model=model)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ServicePriceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing service prices with cost calculations.
    """

    queryset = ServicePrice.objects.all()
    serializer_class = ServicePriceSerializer
    permission_classes = [BillingPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "billing_unit", "currency"]
    search_fields = ["billable_item_type__name", "service_tier__tier_name"]
    ordering_fields = ["base_price", "effective_from", "created_at"]
    ordering = ["-effective_from"]

    def get_queryset(self):
        """Filter queryset with advanced filtering options."""
        queryset = super().get_queryset()

        # Filter by service tier
        tier_id = self.request.query_params.get("service_tier")
        if tier_id:
            queryset = queryset.filter(service_tier_id=tier_id)

        # Filter by billable item type
        item_type_id = self.request.query_params.get("billable_item_type")
        if item_type_id:
            queryset = queryset.filter(billable_item_type_id=item_type_id)

        # Filter by current effectiveness
        current_only = self.request.query_params.get("current_only", "").lower() == "true"
        if current_only:
            now = timezone.now()
            queryset = queryset.filter(is_active=True, effective_from__lte=now).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=now)
            )

        # Staff can see all prices, users only see active ones
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)

        return queryset

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def calculate_cost(self, request, pk=None):
        """
        Calculate total cost for a given quantity using this price.
        """
        price = self.get_object()
        serializer = ServicePriceCalculationSerializer(data=request.data)

        if serializer.is_valid():
            quantity = serializer.validated_data["quantity"]
            apply_bulk_discount = serializer.validated_data["apply_bulk_discount"]

            cost_breakdown = price.calculate_total_cost(quantity, apply_bulk_discount)

            response_data = {
                "service_price_id": price.id,
                "billable_item_type": price.billable_item_type.name,
                "service_tier": price.service_tier.tier_name,
                "billing_unit": price.get_billing_unit_display(),
                **cost_breakdown,
            }

            return Response(response_data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"])
    def current_prices(self, request):
        """Get only currently effective service prices."""
        current_prices = (
            self.get_queryset()
            .filter(
                **{f + "__lte": timezone.now() for f in ["effective_from"]},
                **{f + "__gte": timezone.now() for f in ["effective_until"] if hasattr(self.get_queryset().model, f)},
            )
            .filter(is_active=True)
        )

        # Apply additional filtering
        now = timezone.now()
        current_prices = current_prices.filter(effective_from__lte=now).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=now)
        )

        serializer = self.get_serializer(current_prices, many=True)
        return Response(serializer.data)


class BillingRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing billing records with approval workflow and reporting.
    """

    queryset = BillingRecord.objects.all()
    permission_classes = [BillingPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "currency", "cost_center"]
    search_fields = ["description", "notes", "funder", "cost_center"]
    ordering_fields = ["created_at", "total_amount", "billing_period_start"]
    ordering = ["-created_at"]
    pagination_class = LimitOffsetPagination

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "create":
            return BillingRecordCreateSerializer
        return BillingRecordSerializer

    def get_queryset(self):
        """Filter queryset based on user permissions and query parameters."""
        queryset = super().get_queryset()

        # Users can only see their own records unless they're staff
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)

        # Filter by user (staff can specify user_id)
        user_id = self.request.query_params.get("user_id")
        if user_id and self.request.user.is_staff:
            queryset = queryset.filter(user_id=user_id)

        # Filter by date range
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(billing_period_start__gte=start_date)
        if end_date:
            queryset = queryset.filter(billing_period_end__lte=end_date)

        # Filter by content type
        app_label = self.request.query_params.get("app_label")
        model = self.request.query_params.get("model")

        if app_label:
            queryset = queryset.filter(content_type__app_label=app_label)
        if model:
            queryset = queryset.filter(content_type__model=model)

        return queryset

    def perform_create(self, serializer):
        """Set the user when creating billing records."""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def approve(self, request, pk=None):
        """
        Approve a pending billing record.
        """
        billing_record = self.get_object()
        serializer = BillingApprovalSerializer(data=request.data)

        if serializer.is_valid():
            if billing_record.approve(request.user):
                # Add notes if provided
                notes = serializer.validated_data.get("notes")
                if notes:
                    if billing_record.notes:
                        billing_record.notes += f"\n\nApproval notes: {notes}"
                    else:
                        billing_record.notes = f"Approval notes: {notes}"
                    billing_record.save()

                response_serializer = self.get_serializer(billing_record)
                return Response(
                    {"message": "Billing record approved successfully", "billing_record": response_serializer.data}
                )
            else:
                return Response(
                    {"error": "Billing record cannot be approved in current state"}, status=status.HTTP_400_BAD_REQUEST
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Get billing summary statistics.
        """
        queryset = self.get_queryset()

        # Basic totals
        total_records = queryset.count()
        total_amount = queryset.aggregate(Sum("total_amount"))["total_amount__sum"] or 0
        average_amount = queryset.aggregate(Avg("total_amount"))["total_amount__avg"] or 0

        # By status breakdown
        by_status = {}
        for status_choice in BillingRecord.STATUS_CHOICES:
            status_code = status_choice[0]
            count = queryset.filter(status=status_code).count()
            amount = queryset.filter(status=status_code).aggregate(Sum("total_amount"))["total_amount__sum"] or 0
            by_status[status_code] = {"count": count, "total_amount": amount, "label": status_choice[1]}

        # By time period (last 12 months)
        from datetime import timedelta

        now = timezone.now()
        by_period = {}

        for i in range(12):
            month_start = now.replace(day=1) - timedelta(days=30 * i)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            month_queryset = queryset.filter(billing_period_start__gte=month_start, billing_period_start__lte=month_end)

            month_key = month_start.strftime("%Y-%m")
            by_period[month_key] = {
                "count": month_queryset.count(),
                "total_amount": month_queryset.aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            }

        summary_data = {
            "total_records": total_records,
            "total_amount": total_amount,
            "currency": "USD",  # Default currency
            "by_status": by_status,
            "by_period": dict(sorted(by_period.items())),
            "average_amount": average_amount,
        }

        serializer = BillingRecordSummarySerializer(summary_data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def pending_approval(self, request):
        """
        Get billing records pending approval.
        """
        if not request.user.is_staff:
            return Response({"error": "Only staff users can view pending approvals"}, status=status.HTTP_403_FORBIDDEN)

        pending_records = self.get_queryset().filter(status="pending")
        serializer = self.get_serializer(pending_records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_records(self, request):
        """
        Get current user's billing records.
        """
        user_records = self.get_queryset().filter(user=request.user)

        # Apply pagination
        page = self.paginate_queryset(user_records)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(user_records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_cost_center(self, request):
        """
        Get billing records grouped by cost center.
        """
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff users can view cost center breakdown"}, status=status.HTTP_403_FORBIDDEN
            )

        cost_centers = (
            self.get_queryset()
            .values("cost_center")
            .annotate(record_count=Count("id"), total_amount=Sum("total_amount"))
            .filter(cost_center__isnull=False)
            .order_by("-total_amount")
        )

        return Response(list(cost_centers))
