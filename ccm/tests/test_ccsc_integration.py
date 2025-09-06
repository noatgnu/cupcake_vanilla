"""
Test CCM and CCSC integration, specifically InstrumentJob with MetadataTable billing.

Tests the billing integration between CCM InstrumentJob models and CCSC billing
system, including metadata table processing and related billing scenarios.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone

from ccsc.models import BillableItemType, BillingRecord, ServicePrice, ServiceTier
from ccv.models import MetadataTable
from tests.factories import MetadataTableFactory, get_fixture_path

User = get_user_model()


@override_settings(ENABLE_CUPCAKE_MACARON=True, ENABLE_CUPCAKE_SALTED_CARAMEL=True)
class InstrumentJobMetadataBillingTest(TestCase):
    """Test InstrumentJob billing with MetadataTable integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="researcher", email="researcher@lab.edu")

        # Load SDRF test fixture for metadata table
        sdrf_file_path = get_fixture_path("PXD019185_PXD018883.sdrf.tsv")

        # Create metadata table using SDRF fixture
        self.metadata_table = MetadataTableFactory.from_sdrf_file(
            sdrf_file_path, created_by=self.user, table_name="Proteomics Analysis Dataset"
        )

        # Set up billing tiers and pricing
        self.academic_tier = ServiceTier.objects.create(
            tier_name="Academic", base_rate_multiplier=Decimal("0.8"), discount_percentage=Decimal("10.0")
        )

        # Billing for InstrumentJob
        job_ct = ContentType.objects.get_for_model(self.metadata_table.__class__)

        # Mock content type for InstrumentJob since we can't import it directly in tests
        self.job_billable = BillableItemType.objects.create(
            name="Proteomics Analysis Job",
            content_type=job_ct,  # Using MetadataTable CT as proxy
            default_billing_unit="sample",
            requires_approval=True,
        )

        self.job_price = ServicePrice.objects.create(
            billable_item_type=self.job_billable,
            service_tier=self.academic_tier,
            base_price=Decimal("25.0"),
            billing_unit="sample",
            setup_fee=Decimal("100.0"),
            bulk_threshold=50,
            bulk_discount_percentage=Decimal("15.0"),
        )

        # Billing for metadata processing
        metadata_ct = ContentType.objects.get_for_model(MetadataTable)
        self.metadata_billable = BillableItemType.objects.create(
            name="Metadata Processing", content_type=metadata_ct, default_billing_unit="sample"
        )

        self.metadata_price = ServicePrice.objects.create(
            billable_item_type=self.metadata_billable,
            service_tier=self.academic_tier,
            base_price=Decimal("5.0"),
            billing_unit="sample",
        )

    def create_mock_instrument_job(self, with_metadata=True):
        """Create a mock InstrumentJob for testing."""
        from unittest.mock import MagicMock

        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.user = self.user
        mock_job.job_name = "Proteomics LC-MS/MS Analysis"
        mock_job.job_type = "analysis"
        mock_job.get_job_type_display.return_value = "Analysis"
        mock_job.status = "completed"
        mock_job.sample_number = 24  # From SDRF fixture
        mock_job.cost_center = "BIO-PROT-001"
        mock_job.funder = "NIH R01 Grant"
        mock_job.created_at = timezone.now() - timezone.timedelta(hours=2)
        mock_job.completed_at = timezone.now()

        # Time tracking
        mock_job.instrument_hours = 12.0
        mock_job.personnel_hours = 4.0
        mock_job.instrument_start_time = timezone.now() - timezone.timedelta(hours=16)
        mock_job.instrument_end_time = timezone.now() - timezone.timedelta(hours=4)
        mock_job.personnel_start_time = timezone.now() - timezone.timedelta(hours=6)
        mock_job.personnel_end_time = timezone.now() - timezone.timedelta(hours=2)

        # Metadata table relationship
        if with_metadata:
            mock_job.metadata_table = self.metadata_table
            # Mock permission methods
            mock_job.can_user_view_metadata.return_value = True
            mock_job.can_user_edit_metadata.return_value = False
            mock_job.get_staff_editable_metadata.return_value = self.metadata_table
        else:
            mock_job.metadata_table = None
            mock_job.can_user_view_metadata.return_value = False
            mock_job.can_user_edit_metadata.return_value = False
            mock_job.get_staff_editable_metadata.return_value = None

        return mock_job

    def test_instrument_job_with_metadata_billing_creation(self):
        """Test billing record creation for InstrumentJob with metadata table."""
        mock_job = self.create_mock_instrument_job(with_metadata=True)

        # Create billing record for the job
        billing_record = BillingRecord.objects.create(
            billable_object=self.metadata_table,  # Using metadata table as billable object
            user=self.user,
            service_tier=self.academic_tier,
            service_price=self.job_price,
            quantity=Decimal(str(mock_job.sample_number)),
            unit_price=self.job_price.base_price,
            setup_fee=self.job_price.setup_fee,
            subtotal=self.job_price.base_price * mock_job.sample_number,
            total_amount=(self.job_price.base_price * mock_job.sample_number) + self.job_price.setup_fee,
            billing_period_start=mock_job.created_at,
            billing_period_end=mock_job.completed_at,
            description=f"Proteomics analysis job: {mock_job.job_name} with {mock_job.sample_number} samples",
            cost_center=mock_job.cost_center,
            funder=mock_job.funder,
        )

        # Verify billing record details
        self.assertEqual(billing_record.billable_object, self.metadata_table)
        self.assertEqual(billing_record.quantity, Decimal("24"))  # Sample count from SDRF
        self.assertEqual(billing_record.cost_center, "BIO-PROT-001")
        self.assertEqual(billing_record.funder, "NIH R01 Grant")
        self.assertIn("Proteomics analysis", billing_record.description)

        # Verify cost calculation
        expected_subtotal = Decimal("25.0") * 24  # 600.0
        expected_total = expected_subtotal + Decimal("100.0")  # 700.0
        self.assertEqual(billing_record.subtotal, expected_subtotal)
        self.assertEqual(billing_record.total_amount, expected_total)

        # Apply tier pricing
        tier_adjusted = self.academic_tier.calculate_price(billing_record.total_amount)
        # 700 * 0.8 = 560, then 560 * 0.1 discount = 56, final = 504
        expected_final = Decimal("504.00")
        self.assertEqual(tier_adjusted, expected_final)

    def test_instrument_job_metadata_permission_billing(self):
        """Test billing based on metadata table permissions."""
        mock_job = self.create_mock_instrument_job(with_metadata=True)

        # Test user can view metadata
        self.assertTrue(mock_job.can_user_view_metadata(self.user))

        # Create billing for metadata access
        metadata_billing = BillingRecord.objects.create(
            billable_object=self.metadata_table,
            user=self.user,
            service_tier=self.academic_tier,
            service_price=self.metadata_price,
            quantity=Decimal(str(self.metadata_table.sample_count)),
            unit_price=self.metadata_price.base_price,
            subtotal=self.metadata_price.base_price * self.metadata_table.sample_count,
            total_amount=self.metadata_price.base_price * self.metadata_table.sample_count,
            billing_period_start=timezone.now(),
            billing_period_end=timezone.now(),
            description="Metadata table access for proteomics analysis",
        )

        # Verify metadata billing
        sample_count = self.metadata_table.sample_count
        self.assertEqual(metadata_billing.quantity, Decimal(str(sample_count)))
        self.assertEqual(metadata_billing.unit_price, Decimal("5.0"))
        self.assertIn("Metadata table access", metadata_billing.description)

    def test_instrument_job_staff_only_metadata_billing(self):
        """Test billing for staff-only metadata tables."""
        # Create staff-only metadata table
        staff_metadata = MetadataTableFactory.create_basic_table(user=self.user, name="Staff Internal Analysis Results")

        # Create internal tier for staff processing
        internal_tier = ServiceTier.objects.create(
            tier_name="Internal",
            base_rate_multiplier=Decimal("0.3"),  # 30% of regular rate
            discount_percentage=Decimal("0"),
        )

        # Mock job with staff metadata
        mock_job = self.create_mock_instrument_job(with_metadata=False)
        mock_job.metadata_table = staff_metadata
        mock_job.can_user_view_metadata.return_value = False  # Regular user cannot view
        mock_job.get_staff_editable_metadata.return_value = staff_metadata

        # Create billing for staff processing
        staff_billing = BillingRecord.objects.create(
            billable_object=staff_metadata,
            user=self.user,
            service_tier=internal_tier,
            service_price=self.metadata_price,
            quantity=Decimal("1.0"),  # Flat rate for staff processing
            unit_price=self.metadata_price.base_price,
            subtotal=self.metadata_price.base_price,
            total_amount=self.metadata_price.base_price,
            billing_period_start=timezone.now(),
            billing_period_end=timezone.now(),
            description="Internal staff metadata processing",
        )

        # Verify internal pricing applied
        internal_cost = internal_tier.calculate_price(staff_billing.total_amount)
        expected_internal = staff_billing.total_amount * Decimal("0.3")  # 30% rate
        self.assertEqual(internal_cost, expected_internal)
        self.assertIn("Internal staff", staff_billing.description)

    def test_instrument_job_bulk_sample_billing(self):
        """Test bulk billing for large sample jobs."""
        # Create mock job with large sample count
        mock_job = self.create_mock_instrument_job(with_metadata=True)
        mock_job.sample_number = 75  # Above bulk threshold of 50

        # Calculate cost with bulk discount
        cost_breakdown = self.job_price.calculate_total_cost(Decimal("75"))

        # Verify bulk discount applied
        expected_subtotal = Decimal("25.0") * 75  # 1875.0
        expected_discount = expected_subtotal * Decimal("0.15")  # 281.25
        expected_total = Decimal("100.0") + expected_subtotal - expected_discount  # 1693.75

        self.assertEqual(cost_breakdown["subtotal"], expected_subtotal)
        self.assertEqual(cost_breakdown["bulk_discount"], expected_discount)
        self.assertEqual(cost_breakdown["total"], expected_total)

        # Create actual billing record
        bulk_billing = BillingRecord.objects.create(
            billable_object=self.metadata_table,
            user=self.user,
            service_tier=self.academic_tier,
            service_price=self.job_price,
            quantity=Decimal("75"),
            unit_price=self.job_price.base_price,
            setup_fee=cost_breakdown["setup_fee"],
            subtotal=cost_breakdown["subtotal"],
            discount_amount=cost_breakdown["bulk_discount"],
            total_amount=cost_breakdown["total"],
            billing_period_start=mock_job.created_at,
            billing_period_end=mock_job.completed_at,
            description=f"Bulk proteomics analysis: {mock_job.sample_number} samples with bulk discount",
            cost_center=mock_job.cost_center,
        )

        self.assertEqual(bulk_billing.discount_amount, expected_discount)
        self.assertEqual(bulk_billing.total_amount, expected_total)
        self.assertIn("bulk discount", bulk_billing.description)

    def test_instrument_job_time_based_billing(self):
        """Test billing based on instrument and personnel hours."""
        mock_job = self.create_mock_instrument_job(with_metadata=True)

        # Create hourly billing for instrument time
        hourly_billable = BillableItemType.objects.create(
            name="Instrument Time",
            content_type=ContentType.objects.get_for_model(MetadataTable),
            default_billing_unit="hourly",
        )

        hourly_price = ServicePrice.objects.create(
            billable_item_type=hourly_billable,
            service_tier=self.academic_tier,
            base_price=Decimal("150.0"),  # Per hour
            billing_unit="hourly",
            minimum_charge_units=Decimal("1.0"),
        )

        # Bill for instrument hours
        instrument_billing = BillingRecord.objects.create(
            billable_object=self.metadata_table,
            user=self.user,
            service_tier=self.academic_tier,
            service_price=hourly_price,
            quantity=Decimal(str(mock_job.instrument_hours)),
            unit_price=hourly_price.base_price,
            subtotal=hourly_price.base_price * Decimal(str(mock_job.instrument_hours)),
            total_amount=hourly_price.base_price * Decimal(str(mock_job.instrument_hours)),
            billing_period_start=mock_job.instrument_start_time,
            billing_period_end=mock_job.instrument_end_time,
            description=f"Instrument usage: {mock_job.instrument_hours} hours",
            cost_center=mock_job.cost_center,
        )

        # Verify hourly billing
        expected_total = Decimal("150.0") * Decimal("12.0")  # 1800.0
        self.assertEqual(instrument_billing.quantity, Decimal("12.0"))
        self.assertEqual(instrument_billing.total_amount, expected_total)
        self.assertIn("Instrument usage", instrument_billing.description)

        # Personnel time billing (lower rate)
        personnel_price = ServicePrice.objects.create(
            billable_item_type=hourly_billable,
            service_tier=self.academic_tier,
            base_price=Decimal("75.0"),  # Per hour for personnel
            billing_unit="hourly",
        )

        personnel_billing = BillingRecord.objects.create(
            billable_object=self.metadata_table,
            user=self.user,
            service_tier=self.academic_tier,
            service_price=personnel_price,
            quantity=Decimal(str(mock_job.personnel_hours)),
            unit_price=personnel_price.base_price,
            subtotal=personnel_price.base_price * Decimal(str(mock_job.personnel_hours)),
            total_amount=personnel_price.base_price * Decimal(str(mock_job.personnel_hours)),
            billing_period_start=mock_job.personnel_start_time,
            billing_period_end=mock_job.personnel_end_time,
            description=f"Personnel time: {mock_job.personnel_hours} hours",
            cost_center=mock_job.cost_center,
        )

        # Verify personnel billing
        personnel_total = Decimal("75.0") * Decimal("4.0")  # 300.0
        self.assertEqual(personnel_billing.total_amount, personnel_total)

    def test_instrument_job_without_metadata_billing(self):
        """Test billing for InstrumentJob without metadata table."""
        mock_job = self.create_mock_instrument_job(with_metadata=False)

        # Create flat rate billing for jobs without metadata
        flat_billable = BillableItemType.objects.create(
            name="Basic Analysis Job",
            content_type=ContentType.objects.get_for_model(User),  # Using User as proxy
            default_billing_unit="flat",
        )

        flat_price = ServicePrice.objects.create(
            billable_item_type=flat_billable,
            service_tier=self.academic_tier,
            base_price=Decimal("500.0"),  # Flat rate
            billing_unit="flat",
        )

        # Create billing record
        flat_billing = BillingRecord.objects.create(
            billable_object=self.user,  # No metadata table, bill to user
            user=self.user,
            service_tier=self.academic_tier,
            service_price=flat_price,
            quantity=Decimal("1.0"),
            unit_price=flat_price.base_price,
            subtotal=flat_price.base_price,
            total_amount=flat_price.base_price,
            billing_period_start=mock_job.created_at,
            billing_period_end=mock_job.completed_at,
            description=f"Basic analysis job: {mock_job.job_name}",
            cost_center=mock_job.cost_center,
            funder=mock_job.funder,
        )

        # Verify flat rate billing
        self.assertEqual(flat_billing.billable_object, self.user)
        self.assertEqual(flat_billing.quantity, Decimal("1.0"))
        self.assertEqual(flat_billing.total_amount, Decimal("500.0"))
        self.assertIsNone(mock_job.metadata_table)

    def test_instrument_job_approval_workflow_with_metadata(self):
        """Test approval workflow for jobs with metadata requirements."""
        mock_job = self.create_mock_instrument_job(with_metadata=True)

        # Create admin user for approvals
        admin_user = User.objects.create_user(username="lab_admin", email="admin@lab.edu")

        # Create billing record requiring approval
        approval_billing = BillingRecord.objects.create(
            billable_object=self.metadata_table,
            user=self.user,
            service_tier=self.academic_tier,
            service_price=self.job_price,
            quantity=Decimal(str(mock_job.sample_number)),
            unit_price=self.job_price.base_price,
            setup_fee=self.job_price.setup_fee,
            subtotal=self.job_price.base_price * mock_job.sample_number,
            total_amount=(self.job_price.base_price * mock_job.sample_number) + self.job_price.setup_fee,
            billing_period_start=mock_job.created_at,
            billing_period_end=mock_job.completed_at,
            description="Proteomics job requiring approval due to metadata complexity",
            status="pending",
        )

        # Verify initial pending state
        self.assertEqual(approval_billing.status, "pending")
        self.assertTrue(approval_billing.can_be_modified())
        self.assertTrue(self.job_billable.requires_approval)

        # Approve the billing
        success = approval_billing.approve(admin_user)
        self.assertTrue(success)
        self.assertEqual(approval_billing.status, "approved")
        self.assertEqual(approval_billing.approved_by, admin_user)
        self.assertIsNotNone(approval_billing.approved_at)

        # Verify cannot approve twice
        second_approval = approval_billing.approve(admin_user)
        self.assertFalse(second_approval)
