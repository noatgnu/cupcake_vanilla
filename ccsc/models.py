"""
CUPCAKE Salted Caramel (CCSC) Billing Models.

Comprehensive billing and financial management system for laboratory services
with flexible pricing, multi-tier service offerings, and cross-app integration.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords


class ServiceTier(models.Model):
    """
    Service level definitions for different types of lab services.
    Examples: Basic, Premium, Academic, Commercial, Internal
    """

    history = HistoricalRecords()

    tier_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    priority_level = models.IntegerField(default=0, help_text="Higher number = higher priority")

    # Features and benefits
    features = models.JSONField(default=list, help_text="List of tier features")
    max_concurrent_bookings = models.IntegerField(null=True, blank=True)
    advance_booking_days = models.IntegerField(default=30)

    # Pricing modifiers
    base_rate_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0.1"))],
        help_text="Multiplier applied to base rates",
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Discount percentage (0-100)",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccsc"
        ordering = ["-priority_level", "tier_name"]

    def __str__(self):
        return self.tier_name

    def calculate_price(self, base_price):
        """Calculate final price after tier modifiers."""
        price = base_price * self.base_rate_multiplier
        discount_amount = price * (self.discount_percentage / 100)
        return price - discount_amount


class BillableItemType(models.Model):
    """
    Types of items that can be billed (instruments, reagents, protocols, etc.)
    Uses ContentType for flexibility with any model.
    """

    history = HistoricalRecords()

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)

    # Billing behavior
    BILLING_UNIT_CHOICES = [
        ("hourly", "Per Hour"),
        ("daily", "Per Day"),
        ("usage", "Per Usage"),
        ("sample", "Per Sample"),
        ("flat", "Flat Rate"),
        ("custom", "Custom"),
    ]
    default_billing_unit = models.CharField(max_length=20, choices=BILLING_UNIT_CHOICES, default="hourly")

    requires_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccsc"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_default_billing_unit_display()})"


class ServicePrice(models.Model):
    """
    Flexible pricing model for services with tier-based pricing.
    """

    history = HistoricalRecords()

    billable_item_type = models.ForeignKey(BillableItemType, on_delete=models.CASCADE, related_name="prices")
    service_tier = models.ForeignKey(ServiceTier, on_delete=models.CASCADE, related_name="prices")

    # Pricing details
    base_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, default="USD")
    billing_unit = models.CharField(max_length=20, choices=BillableItemType.BILLING_UNIT_CHOICES)

    # Time-based pricing
    minimum_charge_units = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), help_text="Minimum billable units (e.g., minimum 1 hour)"
    )
    setup_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    # Bulk pricing
    bulk_threshold = models.IntegerField(null=True, blank=True, help_text="Minimum quantity for bulk pricing")
    bulk_discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    # Validity
    effective_from = models.DateTimeField(default=timezone.now)
    effective_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccsc"
        unique_together = ["billable_item_type", "service_tier", "effective_from"]
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.billable_item_type.name} - {self.service_tier.tier_name}: {self.base_price:.2f} {self.currency}"

    def is_current(self):
        """Check if this price is currently effective."""
        now = timezone.now()
        return (
            self.is_active and self.effective_from <= now and (not self.effective_until or self.effective_until >= now)
        )

    def calculate_total_cost(self, quantity, apply_bulk_discount=True):
        """
        Calculate total cost including setup fees and bulk discounts.

        Args:
            quantity: Number of units
            apply_bulk_discount: Whether to apply bulk discount if applicable

        Returns:
            dict: Detailed cost breakdown
        """
        # Ensure minimum charge
        billable_quantity = max(quantity, self.minimum_charge_units)

        # Base cost
        subtotal = self.base_price * billable_quantity

        # Bulk discount
        bulk_discount = Decimal("0")
        if (
            apply_bulk_discount
            and self.bulk_threshold
            and quantity >= self.bulk_threshold
            and self.bulk_discount_percentage > 0
        ):
            bulk_discount = subtotal * (self.bulk_discount_percentage / 100)

        # Final calculation
        total = self.setup_fee + subtotal - bulk_discount

        return {
            "quantity_requested": quantity,
            "quantity_billable": billable_quantity,
            "unit_price": self.base_price,
            "subtotal": subtotal,
            "setup_fee": self.setup_fee,
            "bulk_discount": bulk_discount,
            "total": total,
            "currency": self.currency,
        }


class BillingRecord(models.Model):
    """
    Individual billing transaction record with generic relation support.
    """

    history = HistoricalRecords()

    # Unique identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Generic relation to any billable object (InstrumentJob, InstrumentUsage, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    billable_object = GenericForeignKey("content_type", "object_id")

    # Billing details
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="billing_records")
    service_tier = models.ForeignKey(ServiceTier, on_delete=models.PROTECT, related_name="billing_records")
    service_price = models.ForeignKey(ServicePrice, on_delete=models.PROTECT, related_name="billing_records")

    # Quantities and calculations
    quantity = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    setup_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")

    # Status and workflow
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("billed", "Billed"),
        ("paid", "Paid"),
        ("disputed", "Disputed"),
        ("cancelled", "Cancelled"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Metadata
    billing_period_start = models.DateTimeField()
    billing_period_end = models.DateTimeField()
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Financial details
    cost_center = models.CharField(max_length=100, blank=True)
    funder = models.CharField(max_length=200, blank=True)

    # Timestamps and approvals
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_billing_records",
    )

    class Meta:
        app_label = "ccsc"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["billing_period_start", "billing_period_end"]),
            models.Index(fields=["cost_center"]),
        ]

    def __str__(self):
        obj_name = str(self.billable_object) if self.billable_object else "Unknown Object"
        return f"Billing Record: {obj_name} - {self.total_amount} {self.currency}"

    def approve(self, user):
        """Approve this billing record."""
        if self.status == "pending":
            self.status = "approved"
            self.approved_by = user
            self.approved_at = timezone.now()
            self.save()
            return True
        return False

    def can_be_modified(self):
        """Check if billing record can still be modified."""
        return self.status in ["pending", "disputed"]

    def get_cost_breakdown(self):
        """Get detailed cost breakdown."""
        return {
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "subtotal": self.subtotal,
            "setup_fee": self.setup_fee,
            "discount_amount": self.discount_amount,
            "tax_amount": self.tax_amount,
            "total_amount": self.total_amount,
            "currency": self.currency,
        }
