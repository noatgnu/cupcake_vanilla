"""Automatic billing of staff time, instrument time and reagent cost."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APITestCase

from ccm.models import Instrument, InstrumentJob, InstrumentUsage, Reagent, ReagentAction, StorageObject, StoredReagent
from ccsc.models import BillableItemType, BillingRecord, ServicePrice
from ccsc.signals import get_user_service_tier, item_type_for


def price(kind, amount):
    """Price a kind for the Basic tier."""
    return ServicePrice.objects.create(
        billable_item_type=item_type_for(kind),
        service_tier=get_user_service_tier(None),
        base_price=Decimal(amount),
        billing_unit=BillableItemType.objects.get(kind=kind).default_billing_unit,
        effective_from=timezone.now() - timedelta(days=1),
    )


def records(kind):
    """The billing records of a kind."""
    return BillingRecord.objects.filter(service_price__billable_item_type__kind=kind)


class BillableKindTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("researcher", password="pw")
        self.instrument = Instrument.objects.create(instrument_name="Orbitrap", user=self.user)
        price(BillableItemType.STAFF_TIME, "80.00")
        price(BillableItemType.INSTRUMENT_TIME, "120.00")
        price(BillableItemType.REAGENT_COST, "2.50")

    def test_a_finished_approved_booking_is_billed_as_instrument_time(self):
        start = timezone.now() - timedelta(hours=3)
        InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=start,
            time_ended=start + timedelta(hours=2),
            usage_hours=2,
            approved=True,
        )
        record = records(BillableItemType.INSTRUMENT_TIME).get()
        self.assertEqual(record.quantity, Decimal("2"))
        self.assertEqual(record.subtotal, Decimal("240.00"))

    def test_a_completed_job_is_billed_as_staff_time_and_instrument_time(self):
        start = timezone.now() - timedelta(hours=6)
        job = InstrumentJob.objects.create(
            user=self.user,
            instrument=self.instrument,
            job_name="Phosphoproteome",
            personnel_start_time=start,
            personnel_end_time=start + timedelta(hours=1, minutes=30),
            instrument_start_time=start,
            instrument_end_time=start + timedelta(hours=4),
        )
        self.assertFalse(BillingRecord.objects.exists())
        job.status = "completed"
        job.completed_at = timezone.now()
        job.save()
        self.assertEqual(records(BillableItemType.STAFF_TIME).get().quantity, Decimal("1.5"))
        self.assertEqual(records(BillableItemType.INSTRUMENT_TIME).get().quantity, Decimal("4"))
        job.save()
        self.assertEqual(BillingRecord.objects.count(), 2)

    def test_reserving_a_reagent_is_billed_as_reagent_cost_and_unbilled_when_deleted(self):
        reagent = Reagent.objects.create(name="Trypsin", unit="mg")
        location = StorageObject.objects.create(object_name="Freezer", object_type="freezer", user=self.user)
        stored = StoredReagent.objects.create(reagent=reagent, storage_object=location, quantity=10, user=self.user)
        ReagentAction.objects.create(reagent=stored, action_type="add", quantity=5, user=self.user)
        self.assertFalse(records(BillableItemType.REAGENT_COST).exists())
        reservation = ReagentAction.objects.create(reagent=stored, action_type="reserve", quantity=3, user=self.user)
        record = records(BillableItemType.REAGENT_COST).get()
        self.assertEqual(record.subtotal, Decimal("7.50"))
        self.assertIn("Trypsin, 3 mg", record.description)
        reservation.delete()
        self.assertFalse(records(BillableItemType.REAGENT_COST).exists())


class BillableKindApiTests(APITestCase):
    def test_staff_create_an_item_type_by_its_kind(self):
        staff = User.objects.create_user("billing-staff", password="pw", is_staff=True)
        self.client.force_authenticate(staff)
        response = self.client.post(
            "/api/v1/billable-item-types/",
            {"name": "Mass spectrometer time", "kind": "instrument_time", "default_billing_unit": "hourly"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["kind_display"], "Instrument time")
