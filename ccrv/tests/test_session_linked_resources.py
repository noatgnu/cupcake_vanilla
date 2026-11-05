"""Bookings and reagent bookings shown on the session page, read through the session they are linked from."""

import uuid

from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import Annotation, SiteConfig
from ccm.models import Instrument, InstrumentUsage, Reagent, ReagentAction, StorageObject, StoredReagent
from ccrv.models import (
    InstrumentUsageStepAnnotation,
    ProtocolModel,
    ProtocolSection,
    ProtocolStep,
    Session,
    StepAnnotation,
    StepReagent,
)
from tests.factories import UserFactory


class SessionLinkedResourceTests(APITestCase):
    def setUp(self):
        self.owner = UserFactory.create_user(username="owner")
        self.viewer = UserFactory.create_user(username="viewer")
        self.stranger = UserFactory.create_user(username="stranger")
        self.facility = UserFactory.create_user(username="facility")

        protocol = ProtocolModel.objects.create(protocol_title="Protocol", owner=self.owner)
        section = ProtocolSection.objects.create(protocol=protocol, section_description="Section")
        self.step = ProtocolStep.objects.create(protocol=protocol, step_section=section, step_description="Step")
        self.session = Session.objects.create(name="Session", owner=self.owner, unique_id=uuid.uuid4())
        self.session.viewers.add(self.viewer)
        self.session.protocols.add(protocol)

        self.instrument = Instrument.objects.create(instrument_name="LC-MS", user=self.facility)
        self.booking = InstrumentUsage.objects.create(instrument=self.instrument, user=self.owner)
        annotation = Annotation.objects.create(annotation="Booking", annotation_type="booking", owner=self.owner)
        step_annotation = StepAnnotation.objects.create(session=self.session, step=self.step, annotation=annotation)
        InstrumentUsageStepAnnotation.objects.create(step_annotation=step_annotation, instrument_usage=self.booking)

        storage = StorageObject.objects.create(object_name="Freezer", user=self.facility)
        reagent = Reagent.objects.create(name="Trypsin", unit="ug")
        self.stored_reagent = StoredReagent.objects.create(
            reagent=reagent, storage_object=storage, quantity=10, user=self.facility
        )
        self.action = ReagentAction.objects.create(
            reagent=self.stored_reagent, user=self.owner, action_type="reserve", quantity=1, session=self.session
        )

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def reads(self, user):
        client = self.as_user(user)
        return {
            "booking": client.get(reverse("ccm:instrumentusage-detail", kwargs={"pk": self.booking.pk})).status_code,
            "instrument": client.get(reverse("ccm:instrument-detail", kwargs={"pk": self.instrument.pk})).status_code,
            "stored_reagent": client.get(
                reverse("ccm:storedreagent-detail", kwargs={"pk": self.stored_reagent.pk})
            ).status_code,
            "actions": [
                row["id"]
                for row in client.get(reverse("ccm:reagentaction-list"), {"session": self.session.pk}).data["results"]
            ],
        }

    def test_session_members_read_what_the_session_page_shows(self):
        reads = self.reads(self.viewer)
        self.assertEqual(reads["booking"], status.HTTP_200_OK)
        self.assertEqual(reads["instrument"], status.HTTP_200_OK)
        self.assertEqual(reads["stored_reagent"], status.HTTP_200_OK)
        self.assertEqual(reads["actions"], [self.action.pk])

    def test_a_public_session_without_the_link_gives_nothing(self):
        self.session.enabled = True
        self.session.save(update_fields=["enabled"])
        reads = self.reads(self.stranger)
        self.assertEqual(reads["booking"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(reads["actions"], [])

    def test_others_cannot_read_them_through_a_private_session(self):
        reads = self.reads(self.stranger)
        self.assertEqual(reads["booking"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(reads["instrument"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(reads["stored_reagent"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(reads["actions"], [])

    def test_anyone_with_the_link_reads_them_through_a_public_session(self):
        self.session.enabled = True
        self.session.save(update_fields=["enabled"])
        self.as_user(self.stranger).get(reverse("ccrv:session-list"), {"unique_id": str(self.session.unique_id)})
        reads = self.reads(self.stranger)
        self.assertEqual(reads["booking"], status.HTTP_200_OK)
        self.assertEqual(reads["instrument"], status.HTTP_200_OK)
        self.assertEqual(reads["stored_reagent"], status.HTTP_200_OK)
        self.assertEqual(reads["actions"], [self.action.pk])

    def test_disabled_linked_instruments_stay_hidden(self):
        Instrument.objects.filter(pk=self.instrument.pk).update(enabled=False)
        reads = self.reads(self.viewer)
        self.assertEqual(reads["instrument"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(reads["booking"], status.HTTP_200_OK)

    def test_linked_resources_are_not_listed_or_changed(self):
        client = self.as_user(self.viewer)
        listed = [row["id"] for row in client.get(reverse("ccm:instrumentusage-list"), {"limit": 10}).data["results"]]
        self.assertNotIn(self.booking.pk, listed)
        booking_url = reverse("ccm:instrumentusage-detail", kwargs={"pk": self.booking.pk})
        self.assertEqual(client.patch(booking_url, {"description": "x"}, format="json").status_code, 404)
        action_url = reverse("ccm:reagentaction-detail", kwargs={"pk": self.action.pk})
        self.assertEqual(client.delete(action_url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(ReagentAction.objects.filter(pk=self.action.pk).exists())


class ReagentBookingDeletionTests(SessionLinkedResourceTests):
    def delete_as(self, user):
        return self.as_user(user).delete(reverse("ccm:reagentaction-detail", kwargs={"pk": self.action.pk}))

    def test_the_booker_deletes_within_the_window(self):
        self.assertEqual(self.delete_as(self.owner).status_code, status.HTTP_204_NO_CONTENT)

    def test_the_booking_stays_after_the_window(self):
        SiteConfig.objects.update_or_create(defaults={"booking_deletion_window_minutes": 5})
        ReagentAction.objects.filter(pk=self.action.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=10)
        )
        self.assertEqual(self.delete_as(self.owner).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(ReagentAction.objects.filter(pk=self.action.pk).exists())


class StepReagentBookingTests(SessionLinkedResourceTests):
    def setUp(self):
        super().setUp()
        self.step_reagent = StepReagent.objects.create(step=self.step, reagent=self.stored_reagent.reagent, quantity=1)
        self.alternative = StoredReagent.objects.create(
            reagent=Reagent.objects.create(name="Trypsin 10x", unit="ug"),
            storage_object=self.stored_reagent.storage_object,
            quantity=5,
            user=self.owner,
        )

    def book(self, user, stored_reagent, step_reagent):
        body = {
            "action_type": "reserve",
            "reagent": stored_reagent.pk,
            "quantity": 1,
            "session": self.session.pk,
            "step": self.step.pk,
            "step_reagent": step_reagent.pk,
        }
        return self.as_user(user).post(reverse("ccm:reagentaction-list"), body, format="json")

    def test_an_alternative_reagent_is_booked_for_the_step_reagent(self):
        response = self.book(self.owner, self.alternative, self.step_reagent)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["step_reagent"], self.step_reagent.pk)

    def test_a_step_reagent_is_booked_several_times(self):
        self.assertEqual(self.book(self.owner, self.alternative, self.step_reagent).status_code, 201)
        self.assertEqual(self.book(self.owner, self.alternative, self.step_reagent).status_code, 201)
        self.assertEqual(ReagentAction.objects.filter(step_reagent=self.step_reagent).count(), 2)

    def test_the_step_reagent_must_be_in_the_step(self):
        other_step = ProtocolStep.objects.create(
            protocol=self.step.protocol, step_section=self.step.step_section, step_description="Other"
        )
        other = StepReagent.objects.create(step=other_step, reagent=self.stored_reagent.reagent, quantity=1)
        self.assertEqual(self.book(self.owner, self.alternative, other).status_code, status.HTTP_400_BAD_REQUEST)

    def test_stored_reagents_without_access_cannot_be_booked(self):
        response = self.book(self.viewer, self.stored_reagent, self.step_reagent)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
