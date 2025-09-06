"""
CCSC (Salted Caramel) Billing API Tests.

Tests for the actual API endpoints that are working.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from ccsc.models import BillableItemType, BillingRecord, ServicePrice, ServiceTier
from tests.factories import UserFactory

User = get_user_model()


class BillingAPITestCase(APITestCase):
    """Base test case with data for API testing."""

    def setUp(self):
        """Set up test data."""
        # Create users
        self.regular_user = UserFactory.create_user(username="regular_user")
        self.staff_user = UserFactory.create_user(username="staff_user", is_staff=True)
        self.admin_user = UserFactory.create_user(username="admin_user", is_staff=True, is_superuser=True)

        # Create service tier
        self.service_tier = ServiceTier.objects.create(
            tier_name="Academic",
            description="Academic research pricing",
            priority_level=1,
            features=["academic_discount", "flexible_scheduling"],
            max_concurrent_bookings=3,
            advance_booking_days=30,
            base_rate_multiplier=Decimal("0.8"),
            discount_percentage=Decimal("20.0"),
            is_active=True,
        )

        # Create content type
        self.content_type, _ = ContentType.objects.get_or_create(app_label="test", model="testmodel")

        # Create billable item type
        self.billable_item_type = BillableItemType.objects.create(
            name="Instrument Usage",
            description="Hourly instrument usage",
            content_type=self.content_type,
            default_billing_unit="hourly",
            requires_approval=True,
            is_active=True,
        )

        # Create service price
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


class ServiceTierAPITests(BillingAPITestCase):
    """Test ServiceTier API endpoints."""

    def test_list_service_tiers(self):
        """Test listing service tiers."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("servicetier-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        tier_data = response.data["results"][0]
        self.assertEqual(tier_data["tier_name"], "Academic")
        self.assertIn("features_display", tier_data)
        self.assertIn("active_prices_count", tier_data)

    def test_calculate_price_action(self):
        """Test the calculate_price custom action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("servicetier-calculate-price", kwargs={"pk": self.service_tier.pk})
        data = {"base_price": "100.00"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("final_price", response.data)

        # Academic tier: base_price * 0.8 * (1 - 0.2) = 100 * 0.8 * 0.8 = 64.00
        expected_price = Decimal("64.00")
        self.assertEqual(Decimal(response.data["final_price"]), expected_price)

    def test_active_tiers_action(self):
        """Test the active_tiers custom action."""
        # Create inactive tier
        ServiceTier.objects.create(tier_name="Inactive", is_active=False, base_rate_multiplier=Decimal("1.0"))

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("servicetier-active-tiers")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tier_names = [t["tier_name"] for t in response.data]
        self.assertIn("Academic", tier_names)
        self.assertNotIn("Inactive", tier_names)


class BillableItemTypeAPITests(BillingAPITestCase):
    """Test BillableItemType API endpoints."""

    def test_list_billable_item_types(self):
        """Test listing billable item types."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("billableitemtype-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        item_data = response.data["results"][0]
        self.assertEqual(item_data["name"], "Instrument Usage")
        self.assertEqual(item_data["default_billing_unit"], "hourly")

    def test_by_content_type_action(self):
        """Test the by_content_type custom action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("billableitemtype-by-content-type")
        response = self.client.get(url, {"content_type": self.content_type.pk})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0)
        self.assertEqual(response.data[0]["name"], "Instrument Usage")


class ServicePriceAPITests(BillingAPITestCase):
    """Test ServicePrice API endpoints."""

    def test_list_service_prices(self):
        """Test listing service prices."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("serviceprice-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        price_data = response.data["results"][0]
        self.assertEqual(price_data["base_price"], "100.00")
        self.assertEqual(price_data["billing_unit"], "hourly")

    def test_calculate_cost_action(self):
        """Test the calculate_cost custom action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("serviceprice-calculate-cost", kwargs={"pk": self.service_price.pk})
        data = {"quantity": 3}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify response contains expected fields
        expected_fields = ["quantity_requested", "quantity_billable", "unit_price", "total", "currency"]
        for field in expected_fields:
            self.assertIn(field, response.data)

        self.assertEqual(response.data["quantity_requested"], 3)
        self.assertEqual(response.data["currency"], "USD")


class BillingRecordAPITests(BillingAPITestCase):
    """Test BillingRecord API endpoints."""

    def setUp(self):
        """Set up test data including billing records."""
        super().setUp()

        # Create billing record
        self.billing_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=1,
            user=self.regular_user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("2.0"),
            unit_price=Decimal("100.00"),
            setup_fee=Decimal("50.00"),
            subtotal=Decimal("200.00"),
            total_amount=Decimal("250.00"),
            currency="USD",
            status="pending",
            billing_period_start=timezone.now() - timedelta(hours=2),
            billing_period_end=timezone.now(),
            description="Test billing record",
        )

    def test_list_billing_records(self):
        """Test listing billing records."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("billingrecord-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["status"], "pending")

    def test_summary_action(self):
        """Test the summary custom action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("billingrecord-summary")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include summary fields
        self.assertIn("total_records", response.data)
        self.assertIn("total_amount", response.data)
        self.assertIn("by_status", response.data)

    def test_user_can_only_see_own_records(self):
        """Test users can only see their own billing records."""
        # Create record for another user
        other_user = UserFactory.create_user(username="other_user")
        other_record = BillingRecord.objects.create(
            content_type=self.content_type,
            object_id=3,
            user=other_user,
            service_tier=self.service_tier,
            service_price=self.service_price,
            quantity=Decimal("1.0"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("150.00"),
            billing_period_start=timezone.now() - timedelta(hours=1),
            billing_period_end=timezone.now(),
            description="Other user record",
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("billingrecord-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see own record
        returned_ids = [r["id"] for r in response.data["results"]]
        self.assertIn(str(self.billing_record.pk), returned_ids)
        self.assertNotIn(str(other_record.pk), returned_ids)


class BillingPermissionTests(BillingAPITestCase):
    """Test API permissions."""

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated users cannot access endpoints."""
        url = reverse("servicetier-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_users_read_access(self):
        """Test regular users can read data."""
        self.client.force_authenticate(user=self.regular_user)

        # Can read service tiers
        url = reverse("servicetier-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Can read billing records (their own)
        url = reverse("billingrecord-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_write_permissions_restricted(self):
        """Test write permissions are properly restricted."""
        self.client.force_authenticate(user=self.regular_user)

        # Regular users cannot create service tiers
        url = reverse("servicetier-list")
        data = {"tier_name": "Test", "base_rate_multiplier": 1.0}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Regular users cannot create billing records
        url = reverse("billingrecord-list")
        data = {
            "content_type": self.content_type.pk,
            "object_id": 2,
            "service_tier": self.service_tier.pk,
            "service_price": self.service_price.pk,
            "quantity": 1.0,
            "billing_period_start": timezone.now().isoformat(),
            "billing_period_end": timezone.now().isoformat(),
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BillingCalculationTests(BillingAPITestCase):
    """Test billing calculations work correctly."""

    def test_service_tier_price_calculation(self):
        """Test service tier price calculation via API."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("servicetier-calculate-price", kwargs={"pk": self.service_tier.pk})

        test_cases = [
            {"base_price": "100.00", "expected": "64.00"},
            {"base_price": "200.00", "expected": "128.00"},
            {"base_price": "0.00", "expected": "0.00"},
        ]

        for case in test_cases:
            response = self.client.post(url, {"base_price": case["base_price"]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(Decimal(str(response.data["final_price"])), Decimal(case["expected"]))

    def test_service_price_cost_calculation(self):
        """Test service price cost calculation via API."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("serviceprice-calculate-cost", kwargs={"pk": self.service_price.pk})

        # Test different quantities
        test_cases = [
            {"quantity": 1, "below_bulk": True},
            {"quantity": 3, "below_bulk": True},
            {"quantity": 6, "below_bulk": False},  # Above bulk threshold
        ]

        for case in test_cases:
            response = self.client.post(url, {"quantity": case["quantity"]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Verify bulk discount logic
            if case["below_bulk"]:
                self.assertEqual(response.data.get("bulk_discount", 0), 0)
            else:
                self.assertGreater(response.data.get("bulk_discount", 0), 0)

    def test_minimum_charge_logic(self):
        """Test minimum charge units are applied."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("serviceprice-calculate-cost", kwargs={"pk": self.service_price.pk})

        # Test below minimum charge
        response = self.client.post(url, {"quantity": 0.5}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should bill for minimum units even though requested less
        self.assertEqual(response.data["quantity_requested"], 0.5)
        self.assertEqual(response.data["quantity_billable"], 1.0)  # Minimum is 1.0
