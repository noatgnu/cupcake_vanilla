"""
CUPCAKE Salted Caramel (CCSC) Billing Serializers.

DRF serializers for billing and financial management functionality
with comprehensive validation and nested relationships.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

from rest_framework import serializers

from .models import BillableItemType, BillingRecord, ServicePrice, ServiceTier

User = get_user_model()


class ServiceTierSerializer(serializers.ModelSerializer):
    """
    Serializer for ServiceTier model with calculated fields.
    """

    features_display = serializers.SerializerMethodField()
    active_prices_count = serializers.SerializerMethodField()

    class Meta:
        model = ServiceTier
        fields = [
            "id",
            "tier_name",
            "description",
            "priority_level",
            "features",
            "features_display",
            "max_concurrent_bookings",
            "advance_booking_days",
            "base_rate_multiplier",
            "discount_percentage",
            "is_active",
            "created_at",
            "updated_at",
            "active_prices_count",
        ]
        read_only_fields = ["created_at", "updated_at", "active_prices_count"]

    def get_features_display(self, obj):
        """Return features as formatted string for display."""
        if obj.features:
            return ", ".join(obj.features)
        return "No features listed"

    def get_active_prices_count(self, obj):
        """Return count of active service prices for this tier."""
        return obj.prices.filter(is_active=True).count()

    def validate_discount_percentage(self, value):
        """Ensure discount percentage is valid."""
        if value < 0 or value > 100:
            raise serializers.ValidationError("Discount percentage must be between 0 and 100.")
        return value

    def validate_base_rate_multiplier(self, value):
        """Ensure base rate multiplier is valid."""
        if value <= 0:
            raise serializers.ValidationError("Base rate multiplier must be positive.")
        return value


class BillableItemTypeSerializer(serializers.ModelSerializer):
    """
    Serializer for BillableItemType model with ContentType handling.
    """

    content_type_display = serializers.CharField(source="content_type.model", read_only=True)
    app_label = serializers.CharField(source="content_type.app_label", read_only=True)
    default_billing_unit_display = serializers.CharField(source="get_default_billing_unit_display", read_only=True)
    active_prices_count = serializers.SerializerMethodField()

    class Meta:
        model = BillableItemType
        fields = [
            "id",
            "name",
            "description",
            "content_type",
            "content_type_display",
            "app_label",
            "default_billing_unit",
            "default_billing_unit_display",
            "requires_approval",
            "is_active",
            "created_at",
            "updated_at",
            "active_prices_count",
        ]
        read_only_fields = ["created_at", "updated_at", "active_prices_count"]

    def get_active_prices_count(self, obj):
        """Return count of active service prices for this item type."""
        return obj.prices.filter(is_active=True).count()


class ServicePriceSerializer(serializers.ModelSerializer):
    """
    Serializer for ServicePrice model with nested relationships and calculations.
    """

    billable_item_name = serializers.CharField(source="billable_item_type.name", read_only=True)
    service_tier_name = serializers.CharField(source="service_tier.tier_name", read_only=True)
    billing_unit_display = serializers.CharField(source="get_billing_unit_display", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = ServicePrice
        fields = [
            "id",
            "billable_item_type",
            "billable_item_name",
            "service_tier",
            "service_tier_name",
            "base_price",
            "currency",
            "billing_unit",
            "billing_unit_display",
            "minimum_charge_units",
            "setup_fee",
            "bulk_threshold",
            "bulk_discount_percentage",
            "effective_from",
            "effective_until",
            "is_active",
            "created_at",
            "updated_at",
            "is_current",
        ]
        read_only_fields = ["created_at", "updated_at", "is_current"]

    def get_is_current(self, obj):
        """Check if this price is currently effective."""
        return obj.is_current()

    def validate_base_price(self, value):
        """Ensure base price is positive."""
        if value < 0:
            raise serializers.ValidationError("Base price must be non-negative.")
        return value

    def validate_bulk_discount_percentage(self, value):
        """Ensure bulk discount percentage is valid."""
        if value < 0 or value > 100:
            raise serializers.ValidationError("Bulk discount percentage must be between 0 and 100.")
        return value

    def validate(self, data):
        """Validate the entire ServicePrice instance."""
        # Check bulk discount logic
        bulk_threshold = data.get("bulk_threshold")
        bulk_discount = data.get("bulk_discount_percentage", 0)

        if bulk_threshold and bulk_threshold <= 0:
            raise serializers.ValidationError("Bulk threshold must be positive if specified.")

        if bulk_discount > 0 and not bulk_threshold:
            raise serializers.ValidationError("Bulk threshold is required when bulk discount is specified.")

        # Check date validity
        effective_from = data.get("effective_from")
        effective_until = data.get("effective_until")

        if effective_until and effective_from and effective_until <= effective_from:
            raise serializers.ValidationError("Effective until date must be after effective from date.")

        return data


class ServicePriceCalculationSerializer(serializers.Serializer):
    """
    Serializer for price calculation requests.
    """

    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=0)
    apply_bulk_discount = serializers.BooleanField(default=True)


class BillingRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for BillingRecord model with comprehensive nested data.
    """

    username = serializers.CharField(source="user.username", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    service_tier_name = serializers.CharField(source="service_tier.tier_name", read_only=True)
    billable_item_name = serializers.CharField(source="service_price.billable_item_type.name", read_only=True)
    billing_unit_display = serializers.CharField(source="service_price.get_billing_unit_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True)
    can_be_modified = serializers.SerializerMethodField()
    cost_breakdown = serializers.SerializerMethodField()
    billing_period_days = serializers.SerializerMethodField()

    # Generic relation fields
    content_type_display = serializers.CharField(source="content_type.model", read_only=True)
    app_label = serializers.CharField(source="content_type.app_label", read_only=True)

    class Meta:
        model = BillingRecord
        fields = [
            "id",
            "content_type",
            "content_type_display",
            "app_label",
            "object_id",
            "user",
            "username",
            "user_email",
            "service_tier",
            "service_tier_name",
            "service_price",
            "billable_item_name",
            "billing_unit_display",
            "quantity",
            "unit_price",
            "setup_fee",
            "subtotal",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "currency",
            "status",
            "status_display",
            "billing_period_start",
            "billing_period_end",
            "billing_period_days",
            "description",
            "notes",
            "cost_center",
            "funder",
            "created_at",
            "updated_at",
            "approved_at",
            "approved_by",
            "approved_by_username",
            "can_be_modified",
            "cost_breakdown",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "approved_at",
            "approved_by",
            "can_be_modified",
            "cost_breakdown",
            "billing_period_days",
        ]

    def get_can_be_modified(self, obj):
        """Check if billing record can be modified."""
        return obj.can_be_modified()

    def get_cost_breakdown(self, obj):
        """Get detailed cost breakdown."""
        return obj.get_cost_breakdown()

    def get_billing_period_days(self, obj):
        """Calculate billing period duration in days."""
        if obj.billing_period_start and obj.billing_period_end:
            delta = obj.billing_period_end - obj.billing_period_start
            return delta.days
        return None

    def validate_quantity(self, value):
        """Ensure quantity is positive."""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be positive.")
        return value

    def validate_total_amount(self, value):
        """Ensure total amount is non-negative."""
        if value < 0:
            raise serializers.ValidationError("Total amount cannot be negative.")
        return value

    def validate(self, data):
        """Validate the entire BillingRecord instance."""
        # Check billing period
        period_start = data.get("billing_period_start")
        period_end = data.get("billing_period_end")

        if period_start and period_end and period_end <= period_start:
            raise serializers.ValidationError("Billing period end must be after start.")

        # Validate amounts are consistent
        quantity = data.get("quantity", 0)
        unit_price = data.get("unit_price", 0)
        setup_fee = data.get("setup_fee", 0)
        discount_amount = data.get("discount_amount", 0)
        tax_amount = data.get("tax_amount", 0)

        expected_subtotal = quantity * unit_price
        expected_total = expected_subtotal + setup_fee - discount_amount + tax_amount

        subtotal = data.get("subtotal")
        total_amount = data.get("total_amount")

        if subtotal and abs(subtotal - expected_subtotal) > Decimal("0.01"):
            raise serializers.ValidationError("Subtotal does not match quantity × unit price.")

        if total_amount and abs(total_amount - expected_total) > Decimal("0.01"):
            raise serializers.ValidationError("Total amount calculation is incorrect.")

        return data


class BillingRecordCreateSerializer(BillingRecordSerializer):
    """
    Specialized serializer for creating billing records with auto-calculation.
    """

    class Meta(BillingRecordSerializer.Meta):
        # Remove calculated fields from create operations
        read_only_fields = BillingRecordSerializer.Meta.read_only_fields + ["unit_price", "subtotal", "total_amount"]

    def create(self, validated_data):
        """Create billing record with automatic price calculation."""
        service_price = validated_data["service_price"]
        quantity = validated_data["quantity"]

        # Calculate pricing based on ServicePrice
        cost_breakdown = service_price.calculate_total_cost(quantity)

        # Set calculated values
        validated_data["unit_price"] = cost_breakdown["unit_price"]
        validated_data["subtotal"] = cost_breakdown["subtotal"]
        validated_data["setup_fee"] = cost_breakdown["setup_fee"]
        validated_data["discount_amount"] = cost_breakdown["bulk_discount"]
        validated_data["total_amount"] = cost_breakdown["total"]
        validated_data["currency"] = cost_breakdown["currency"]

        return super().create(validated_data)


class BillingRecordSummarySerializer(serializers.Serializer):
    """
    Serializer for billing summary statistics.
    """

    total_records = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    by_status = serializers.DictField()
    by_period = serializers.DictField()
    average_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class BillingApprovalSerializer(serializers.Serializer):
    """
    Serializer for billing approval actions.
    """

    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
