"""Who can approve instrument bookings through the API."""

from datetime import timedelta

from django.utils import timezone

from rest_framework.test import APITestCase

from ccm.models import Instrument, InstrumentPermission, InstrumentUsage
from tests.factories import UserFactory

URL = "/api/v1/instrument-usage/"


class BookingApprovalTests(APITestCase):
    def setUp(self):
        self.owner = UserFactory.create_user()
        self.booker = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.instrument = Instrument.objects.create(
            instrument_name="Orbitrap", user=self.owner, accepts_bookings=True, max_days_ahead_pre_approval=1
        )
        InstrumentPermission.objects.create(instrument=self.instrument, user=self.booker, can_view=True, can_book=True)
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

    def book(self, days_ahead, **extra):
        start = timezone.now() + timedelta(days=days_ahead)
        self.client.force_authenticate(self.booker)
        return self.client.post(
            URL,
            {
                "instrument": self.instrument.id,
                "time_started": start,
                "time_ended": start + timedelta(hours=2),
                **extra,
            },
            format="json",
        )

    def test_a_booker_cannot_approve_a_booking_that_needs_approval(self):
        response = self.book(3, approved=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(InstrumentUsage.objects.get(id=response.data["id"]).approved)

    def test_a_booking_within_the_pre_approval_limits_is_approved_without_review(self):
        response = self.book(0)
        self.assertTrue(InstrumentUsage.objects.get(id=response.data["id"]).approved)

    def test_a_booker_cannot_approve_their_own_booking_by_editing_it(self):
        usage_id = self.book(3).data["id"]
        response = self.client.patch(f"{URL}{usage_id}/", {"approved": True, "description": "please"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        usage = InstrumentUsage.objects.get(id=usage_id)
        self.assertFalse(usage.approved)
        self.assertEqual(usage.description, "please")

    def test_a_manager_approves_and_is_recorded_as_approving(self):
        usage_id = self.book(3).data["id"]
        self.client.force_authenticate(self.manager)
        response = self.client.patch(f"{URL}{usage_id}/", {"approved": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        usage = InstrumentUsage.objects.get(id=usage_id)
        self.assertTrue(usage.approved)
        self.assertEqual(usage.approved_by, self.manager)

    def test_editing_the_description_keeps_the_managers_approval(self):
        usage_id = self.book(3).data["id"]
        self.client.force_authenticate(self.manager)
        self.client.patch(f"{URL}{usage_id}/", {"approved": True}, format="json")
        self.client.force_authenticate(self.booker)
        self.client.patch(f"{URL}{usage_id}/", {"description": "twelve samples"}, format="json")
        self.assertTrue(InstrumentUsage.objects.get(id=usage_id).approved)

    def test_moving_an_approved_booking_needs_approval_again(self):
        usage_id = self.book(3).data["id"]
        self.client.force_authenticate(self.manager)
        self.client.patch(f"{URL}{usage_id}/", {"approved": True}, format="json")
        self.client.force_authenticate(self.booker)
        start = timezone.now() + timedelta(days=4)
        response = self.client.patch(
            f"{URL}{usage_id}/", {"time_started": start, "time_ended": start + timedelta(hours=2)}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        usage = InstrumentUsage.objects.get(id=usage_id)
        self.assertFalse(usage.approved)
        self.assertIsNone(usage.approved_by)

    def test_approved_by_cannot_be_set_by_the_client(self):
        response = self.book(3, approved_by=self.manager.id)
        self.assertIsNone(InstrumentUsage.objects.get(id=response.data["id"]).approved_by)
