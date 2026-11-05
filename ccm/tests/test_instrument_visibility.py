"""Instrument visibility: disabled instruments for staff only, enabled ones by owner and view, book and manage permissions."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APITestCase

from ccm.models import Instrument, InstrumentPermission, InstrumentUsage

User = get_user_model()


class InstrumentVisibilityTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", "staff@test.com", "pw", is_staff=True)
        self.viewer = User.objects.create_user("viewer", "viewer@test.com", "pw")
        self.booker = User.objects.create_user("booker", "booker@test.com", "pw")
        self.manager = User.objects.create_user("manager", "manager@test.com", "pw")
        self.stranger = User.objects.create_user("stranger", "stranger@test.com", "pw")
        self.instrument = Instrument.objects.create(instrument_name="LC-MS", user=self.staff)
        InstrumentPermission.objects.create(instrument=self.instrument, user=self.viewer, can_view=True)
        InstrumentPermission.objects.create(instrument=self.instrument, user=self.booker, can_view=True, can_book=True)
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )
        self.booking = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.booker,
            time_started=timezone.now() + timedelta(days=1),
            time_ended=timezone.now() + timedelta(days=1, hours=2),
        )

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def listed(self, user, name):
        response = self.as_user(user).get(reverse(f"ccm:{name}-list"), {"limit": 10})
        return [row["id"] for row in response.data["results"]]

    def test_enabled_instruments_follow_view_permission(self):
        for user in (self.viewer, self.booker, self.manager, self.staff):
            self.assertIn(self.instrument.pk, self.listed(user, "instrument"), user.username)
        self.assertNotIn(self.instrument.pk, self.listed(self.stranger, "instrument"))

    def test_disabled_instruments_are_seen_by_staff_only(self):
        Instrument.objects.filter(pk=self.instrument.pk).update(enabled=False)
        self.assertIn(self.instrument.pk, self.listed(self.staff, "instrument"))
        for user in (self.viewer, self.booker, self.manager):
            self.assertNotIn(self.instrument.pk, self.listed(user, "instrument"), user.username)
            self.assertNotIn(self.booking.pk, self.listed(user, "instrumentusage"), user.username)

    def test_bookings_are_seen_by_those_who_can_view_the_instrument(self):
        for user in (self.viewer, self.booker, self.manager):
            self.assertIn(self.booking.pk, self.listed(user, "instrumentusage"), user.username)
        self.assertNotIn(self.booking.pk, self.listed(self.stranger, "instrumentusage"))

    def test_booking_needs_book_permission(self):
        url = reverse("ccm:instrumentusage-list")
        body = {
            "instrument": self.instrument.pk,
            "time_started": (timezone.now() + timedelta(days=2)).isoformat(),
            "time_ended": (timezone.now() + timedelta(days=2, hours=1)).isoformat(),
        }
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.booker).post(url, body, format="json").status_code, 201)

    def test_bookings_are_changed_by_the_booker_and_managers_only(self):
        url = reverse("ccm:instrumentusage-detail", kwargs={"pk": self.booking.pk})
        self.assertEqual(self.as_user(self.viewer).patch(url, {"description": "x"}, format="json").status_code, 404)
        self.assertEqual(self.as_user(self.manager).patch(url, {"description": "m"}, format="json").status_code, 200)
        self.assertEqual(self.as_user(self.booker).patch(url, {"description": "b"}, format="json").status_code, 200)
