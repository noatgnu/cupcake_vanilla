"""Instrument permissions listed to staff, instrument owners, managers and the users the permissions belong to."""

from django.contrib.auth.models import User
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccm.models import Instrument, InstrumentPermission


class InstrumentPermissionListTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.manager = User.objects.create_user(username="manager")
        self.booker = User.objects.create_user(username="booker")
        self.other = User.objects.create_user(username="other")
        self.staff = User.objects.create_user(username="staff", is_staff=True)
        self.instrument = Instrument.objects.create(instrument_name="Orbitrap", user=self.owner)
        self.other_instrument = Instrument.objects.create(instrument_name="Exploris", user=self.other)
        self.manage = InstrumentPermission.objects.create(
            user=self.manager, instrument=self.instrument, can_view=True, can_manage=True
        )
        self.book = InstrumentPermission.objects.create(
            user=self.booker, instrument=self.instrument, can_view=True, can_book=True
        )
        self.elsewhere = InstrumentPermission.objects.create(
            user=self.booker, instrument=self.other_instrument, can_view=True
        )
        self.unrelated = InstrumentPermission.objects.create(
            user=self.other, instrument=self.other_instrument, can_view=True, can_book=True
        )

    def listed(self, as_user, **params):
        self.client.force_authenticate(user=as_user)
        response = self.client.get(reverse("ccm:instrumentpermission-list"), params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["id"] for row in response.data["results"]}

    def test_users_see_their_own_permissions(self):
        self.assertEqual(self.listed(self.booker), {self.book.id, self.elsewhere.id})

    def test_bookable_instruments_of_a_user(self):
        self.assertEqual(self.listed(self.booker, can_book="true"), {self.book.id})

    def test_permission_of_a_user_on_one_instrument(self):
        self.assertEqual(self.listed(self.booker, instrument=self.instrument.id, user=self.booker.id), {self.book.id})

    def test_managers_and_owners_see_every_permission_of_their_instrument(self):
        expected = {self.manage.id, self.book.id}
        self.assertEqual(self.listed(self.manager, instrument=self.instrument.id), expected)
        self.assertEqual(self.listed(self.owner, instrument=self.instrument.id), expected)

    def test_permissions_on_other_instruments_stay_hidden(self):
        self.assertNotIn(self.unrelated.id, self.listed(self.booker))
        self.assertNotIn(self.unrelated.id, self.listed(self.manager))

    def test_staff_see_all_permissions(self):
        self.assertEqual(self.listed(self.staff), {self.manage.id, self.book.id, self.elsewhere.id, self.unrelated.id})
