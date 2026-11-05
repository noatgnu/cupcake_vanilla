"""Request and response shapes of the CUPCAKE Salted Caramel custom actions, for the OpenAPI schema."""

from rest_framework import serializers

from .serializers import BillingRecordSerializer


class TierPriceRequestSerializer(serializers.Serializer):
    """An amount to price with the tier's modifiers."""

    base_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, coerce_to_string=False)


class TierPriceSerializer(serializers.Serializer):
    """The amount after the tier's multiplier and discount."""

    tier_name = serializers.CharField()
    base_price = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    base_rate_multiplier = serializers.DecimalField(max_digits=6, decimal_places=3, coerce_to_string=False)
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=False)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    currency = serializers.CharField()


class CostBreakdownSerializer(serializers.Serializer):
    """Cost of a quantity at this price."""

    service_price_id = serializers.IntegerField()
    billable_item_type = serializers.CharField()
    service_tier = serializers.CharField()
    billing_unit = serializers.CharField()
    quantity_requested = serializers.DecimalField(max_digits=10, decimal_places=3, coerce_to_string=False)
    quantity_billable = serializers.DecimalField(max_digits=10, decimal_places=3, coerce_to_string=False)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    setup_fee = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    bulk_discount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    currency = serializers.CharField()


class BillingRecordApprovedSerializer(serializers.Serializer):
    """The approved billing record."""

    message = serializers.CharField()
    billing_record = BillingRecordSerializer()


class StatusTotalSerializer(serializers.Serializer):
    """Records and amount in one status."""

    count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    label = serializers.CharField()


class PeriodTotalSerializer(serializers.Serializer):
    """Records and amount in one month."""

    count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)


class BillingSummaryStatsSerializer(serializers.Serializer):
    """Totals of the billing records the user can see."""

    total_records = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    by_status = serializers.DictField(child=StatusTotalSerializer(), help_text="Keyed by status code")
    by_period = serializers.DictField(child=PeriodTotalSerializer(), help_text="Keyed by month, YYYY-MM")
    average_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class CostCenterTotalSerializer(serializers.Serializer):
    """Records and amount of one cost centre."""

    cost_center = serializers.CharField()
    record_count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
