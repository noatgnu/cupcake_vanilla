"""
CCSC (Salted Caramel) Billing Model Tests.

Tests for the actual model methods and business logic.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ccsc.models import BillableItemType, BillingRecord, ServicePrice, ServiceTier
from tests.factories import UserFactory

User = get_user_model()


class ServiceTierModelTests(TestCase):
    """Test ServiceTier model methods."""

    def test_calculate_price_method(self):
        """Test ServiceTier.calculate_price method."""
        tier = ServiceTier.objects.create(
            tier_name="Academic", base_rate_multiplier=Decimal("0.8"), discount_percentage=Decimal("20.0")
        )

        base_price = Decimal("100.00")
        result = tier.calculate_price(base_price)

        # Academic tier: 100 * 0.8 = 80, then 80 - (80 * 0.2) = 64
        expected = Decimal("64.00")
        self.assertEqual(result, expected)

    def test_str_method(self):
        """Test ServiceTier string representation."""
        tier = ServiceTier.objects.create(tier_name="Premium", base_rate_multiplier=Decimal("1.5"))

        self.assertEqual(str(tier), "Premium")

    def test_features_default(self):
        """Test features field defaults to empty list."""
        tier = ServiceTier.objects.create(tier_name="Basic", base_rate_multiplier=Decimal("1.0"))

        self.assertEqual(tier.features, [])

    def test_validation_constraints(self):
        """Test model validation constraints."""
        tier = ServiceTier(
            tier_name="Test",
            base_rate_multiplier=Decimal("0.05"),  # Below minimum
            discount_percentage=Decimal("150.0"),  # Above maximum
        )

        with self.assertRaises(ValidationError):
            tier.full_clean()


class BillableItemTypeModelTests(TestCase):
    """Test BillableItemType model methods."""

    def setUp(self):
        """Set up test data."""
        self.content_type = ContentType.objects.get_or_create(app_label="test", model="testmodel")[0]

    def test_str_method(self):
        """Test BillableItemType string representation."""
        item_type = BillableItemType.objects.create(
            name="Instrument Usage", content_type=self.content_type, default_billing_unit="hourly"
        )

        expected = "Instrument Usage (Per Hour)"
        self.assertEqual(str(item_type), expected)

    def test_billing_unit_choices(self):
        """Test billing unit choices are available."""
        choices = dict(BillableItemType.BILLING_UNIT_CHOICES)

        self.assertIn("hourly", choices)
        self.assertIn("daily", choices)
        self.assertIn("usage", choices)
        self.assertIn("sample", choices)
        self.assertIn("flat", choices)
        self.assertIn("custom", choices)


class ServicePriceModelTests(TestCase):
    """Test ServicePrice model methods."""

    def setUp(self):
        """Set up test data."""
        self.content_type = ContentType.objects.get_or_create(app_label="test", model="testmodel")[0]

        self.service_tier = ServiceTier.objects.create(
            tier_name="Academic", base_rate_multiplier=Decimal("0.8"), discount_percentage=Decimal("20.0")
        )

        self.billable_item_type = BillableItemType.objects.create(
            name="Instrument Usage", content_type=self.content_type, default_billing_unit="hourly"
        )

        self.service_price = ServicePrice.objects.create(
            billable_item_type=self.billable_item_type,
            service_tier=self.service_tier,
            base_price=Decimal("100.00"),
            currency="USD",
            billing_unit="hourly",
            minimum_charge_units=Decimal("1.0"),
            setup_fee=Decimal("50.00"),
            bulk_threshold=5,
            bulk_discount_percentage=Decimal("15.0"),
            effective_from=timezone.now() - timedelta(days=1),
            is_active=True,
        )

    def test_str_method(self):
        """Test ServicePrice string representation."""
        expected = "Instrument Usage - Academic: 100.00 USD"
        self.assertEqual(str(self.service_price), expected)

    def test_is_current_method(self):
        """Test is_current method."""
        # Current price should be active
        self.assertTrue(self.service_price.is_current())

        # Future price should not be current
        future_price = ServicePrice.objects.create(
            billable_item_type=self.billable_item_type,
            service_tier=self.service_tier,
            base_price=Decimal("120.00"),
            billing_unit="hourly",
            effective_from=timezone.now() + timedelta(days=1),
            is_active=True,
        )
        self.assertFalse(future_price.is_current())

        # Expired price should not be current
        expired_price = ServicePrice.objects.create(
            billable_item_type=self.billable_item_type,
            service_tier=self.service_tier,
            base_price=Decimal("80.00"),
            billing_unit="hourly",
            effective_from=timezone.now() - timedelta(days=30),
            effective_until=timezone.now() - timedelta(days=1),
            is_active=True,
        )
        self.assertFalse(expired_price.is_current())

    def test_calculate_total_cost_method(self):
        """Test calculate_total_cost method."""
        result = self.service_price.calculate_total_cost(3)

        # Check all expected fields are present
        expected_fields = [
            "quantity_requested",
            "quantity_billable",
            "unit_price",
            "subtotal",
            "setup_fee",
            "bulk_discount",
            "total",
            "currency",
        ]

        for field in expected_fields:
            self.assertIn(field, result)

        self.assertEqual(result["quantity_requested"], 3)
        self.assertEqual(result["quantity_billable"], 3)  # Above minimum
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["setup_fee"], Decimal("50.00"))

        # No bulk discount for quantity below threshold
        self.assertEqual(result["bulk_discount"], Decimal("0"))

    def test_bulk_discount_application(self):
        """Test bulk discount is applied when threshold is met."""
        # Below threshold - no bulk discount
        result_below = self.service_price.calculate_total_cost(3)
        self.assertEqual(result_below["bulk_discount"], Decimal("0"))

        # Above threshold - bulk discount applied
        result_above = self.service_price.calculate_total_cost(6)
        self.assertGreater(result_above["bulk_discount"], Decimal("0"))

    def test_minimum_charge_units(self):
        """Test minimum charge units are respected."""
        # Test below minimum
        result = self.service_price.calculate_total_cost(Decimal("0.5"))

        self.assertEqual(result["quantity_requested"], Decimal("0.5"))
        self.assertEqual(result["quantity_billable"], Decimal("1.0"))  # Minimum


class BillingRecordModelTests(TestCase):
    """Test BillingRecord model methods."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.admin_user = UserFactory.create_user(is_staff=True, is_superuser=True)

        self.content_type = ContentType.objects.get_or_create(app_label="test", model="testmodel")[0]

        self.service_tier = ServiceTier.objects.create(
            tier_name="Academic", base_rate_multiplier=Decimal("0.8"), discount_percentage=Decimal("20.0")
        )

        self.billable_item_type = BillableItemType.objects.create(
            name="Instrument Usage", content_type=self.content_type, default_billing_unit="hourly"
        )

        self.service_price = ServicePrice.objects.create(
            billable_item_type=self.billable_item_type,
            service_tier=self.service_tier,
            base_price=Decimal("100.00"),
            currency="USD",
            billing_unit="hourly",
            effective_from=timezone.now() - timedelta(days=1),
            is_active=True,
        )

    def test_str_method(self):
        """Test BillingRecord string representation handles missing objects."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("2.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            billing_period_start=timezone.now() - timedelta(hours=2),
            billing_period_end=timezone.now(),
        )

        # The str method will raise an exception when trying to access billable_object
        # because the content type doesn't correspond to an actual model class
        with self.assertRaises(AttributeError):
            str(billing_record)

    def test_approve_method(self):
        """Test approve method."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
            status="pending",
        )

        success = billing_record.approve(self.admin_user)

        self.assertTrue(success)
        self.assertEqual(billing_record.status, "approved")
        self.assertEqual(billing_record.approved_by, self.admin_user)
        self.assertIsNotNone(billing_record.approved_at)

    def test_approve_already_approved(self):
        """Test approve method on already approved record."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
            status="approved",
            approved_by=self.admin_user,
            approved_at=timezone.now(),
        )

        success = billing_record.approve(self.admin_user)

        # Should return False since already approved
        self.assertFalse(success)

    def test_can_be_modified_method(self):
        """Test can_be_modified method."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
            status="pending",
        )

        # Pending record should be modifiable
        self.assertTrue(billing_record.can_be_modified())

        # Approved record should not be modifiable
        billing_record.status = "approved"
        billing_record.save()
        self.assertFalse(billing_record.can_be_modified())

        # Disputed record should be modifiable
        billing_record.status = "disputed"
        billing_record.save()
        self.assertTrue(billing_record.can_be_modified())

    def test_get_cost_breakdown_method(self):
        """Test get_cost_breakdown method."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("2.0"),
            unit_price=Decimal("100.00"),
            setup_fee=Decimal("50.00"),
            subtotal=Decimal("200.00"),
            discount_amount=Decimal("20.00"),
            tax_amount=Decimal("30.00"),
            total_amount=Decimal("260.00"),
            currency="USD",
            billing_period_start=timezone.now() - timedelta(hours=2),
            billing_period_end=timezone.now(),
        )

        breakdown = billing_record.get_cost_breakdown()

        expected_fields = [
            "quantity",
            "unit_price",
            "subtotal",
            "setup_fee",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "currency",
        ]

        for field in expected_fields:
            self.assertIn(field, breakdown)

        self.assertEqual(breakdown["currency"], "USD")
        self.assertEqual(breakdown["total_amount"], Decimal("260.00"))
        self.assertEqual(breakdown["setup_fee"], Decimal("50.00"))

    def test_uuid_primary_key(self):
        """Test billing record uses UUID as primary key."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
        )

        # Should be a UUID string
        self.assertIsInstance(str(billing_record.pk), str)
        # UUID should be 36 characters long (including hyphens)
        self.assertEqual(len(str(billing_record.pk)), 36)

    def test_generic_foreign_key(self):
        """Test generic foreign key functionality."""
        billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=123,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
        )

        self.assertEqual(billing_record.content_type, self.content_type)
        self.assertEqual(billing_record.object_id, 123)

        # Testing that accessing billable_object with non-existent model raises expected exception
        with self.assertRaises(AttributeError):
            _ = billing_record.billable_object

    def test_status_choices(self):
        """Test status choices are available."""
        choices = dict(BillingRecord.STATUS_CHOICES)

        expected_statuses = ["pending", "approved", "billed", "paid", "disputed", "cancelled"]

        for status in expected_statuses:
            self.assertIn(status, choices)

    def test_ordering(self):
        """Test default ordering by created_at descending."""
        # Create multiple records with slight time differences
        record1 = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
        )

        record2 = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=2,
            user=self.user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
        )

        # Get all records - should be ordered by created_at descending
        records = list(BillingRecord.objects.all())

        # record2 was created after record1, so should come first
        self.assertEqual(records[0].pk, record2.pk)
        self.assertEqual(records[1].pk, record1.pk)
