"""Changes to protocols, sessions and their contents by owners and editors, and protocol ratings."""

import uuid

from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import Annotation, AnnotationFolder, LabGroup
from ccm.models import Instrument, InstrumentJob, InstrumentUsage, Reagent
from ccrv.models import (
    InstrumentUsageStepAnnotation,
    ProtocolModel,
    ProtocolRating,
    ProtocolReagent,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotationFolder,
    StepAnnotation,
    StepReagent,
    StepVariation,
)
from tests.factories import UserFactory


class OwnerEditorTestCase(APITestCase):
    def setUp(self):
        self.owner = UserFactory.create_user(username="owner")
        self.editor = UserFactory.create_user(username="editor")
        self.viewer = UserFactory.create_user(username="viewer")
        self.member = UserFactory.create_user(username="member")
        self.stranger = UserFactory.create_user(username="stranger")
        self.staff = UserFactory.create_user(username="staff", is_staff=True)
        lab_group = LabGroup.objects.create(name="Lab", creator=self.owner)
        lab_group.members.add(self.member)

        self.protocol = ProtocolModel.objects.create(
            protocol_title="Protocol", owner=self.owner, lab_group=lab_group, enabled=True
        )
        self.protocol.editors.add(self.editor)
        self.protocol.viewers.add(self.viewer)
        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section")
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step", step_duration=10
        )
        self.reagent = Reagent.objects.create(name="Trypsin", unit="ug")
        self.protocol_reagent = ProtocolReagent.objects.create(protocol=self.protocol, reagent=self.reagent, quantity=1)
        self.step_reagent = StepReagent.objects.create(step=self.step, reagent=self.reagent, quantity=1, scalable=True)

        self.session = Session.objects.create(name="Session", owner=self.owner, unique_id=uuid.uuid4())
        self.session.editors.add(self.editor)
        self.session.viewers.add(self.viewer)
        self.session.protocols.add(self.protocol)

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client


class ProtocolAndSessionTests(OwnerEditorTestCase):
    def test_staff_open_and_change_any_protocol_and_session(self):
        client = self.as_user(self.staff)
        protocol_url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        session_url = reverse("ccrv:session-detail", kwargs={"pk": self.session.pk})
        self.assertEqual(client.get(protocol_url).status_code, status.HTTP_200_OK)
        self.assertEqual(client.get(session_url).status_code, status.HTTP_200_OK)
        self.assertEqual(client.patch(session_url, {"name": "Renamed"}, format="json").status_code, 200)

    def test_viewers_cannot_change_the_session(self):
        session_url = reverse("ccrv:session-detail", kwargs={"pk": self.session.pk})
        response = self.as_user(self.viewer).patch(session_url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SessionMemberProtocolViewTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        self.session_viewer = UserFactory.create_user(username="session_viewer")
        self.session.viewers.add(self.session_viewer)

    def test_session_members_view_the_protocol_and_its_contents(self):
        client = self.as_user(self.session_viewer)
        protocol_url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        self.assertEqual(client.get(protocol_url).status_code, status.HTTP_200_OK)
        listed = client.get(reverse("ccrv:protocolmodel-list"), {"limit": 10}).data["results"]
        self.assertIn(self.protocol.pk, [p["id"] for p in listed])
        step_url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        section_url = reverse("ccrv:protocolsection-detail", kwargs={"pk": self.section.pk})
        self.assertEqual(client.get(step_url).status_code, status.HTTP_200_OK)
        self.assertEqual(client.get(section_url).status_code, status.HTTP_200_OK)

    def test_session_members_only_view_the_protocol(self):
        client = self.as_user(self.session_viewer)
        protocol_url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        step_url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        self.assertEqual(client.patch(protocol_url, {"protocol_title": "x"}, format="json").status_code, 403)
        self.assertEqual(client.patch(step_url, {"step_description": "x"}, format="json").status_code, 403)

    def test_session_members_rate_the_protocol(self):
        url = reverse("ccrv:protocolrating-rate-protocol")
        body = {"protocol_id": self.protocol.pk, "complexity_rating": 3, "duration_rating": 4}
        self.assertEqual(self.as_user(self.session_viewer).post(url, body, format="json").status_code, 201)

    def test_members_removed_from_the_session_lose_the_protocol(self):
        self.session.viewers.remove(self.session_viewer)
        protocol_url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        self.assertEqual(self.as_user(self.session_viewer).get(protocol_url).status_code, 404)

    def test_strangers_still_cannot_view_the_protocol(self):
        protocol_url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        self.assertEqual(self.as_user(self.stranger).get(protocol_url).status_code, 404)


class ReorderByLinkedListTests(OwnerEditorTestCase):
    def reorder_as(self, user):
        self.step.order = 7
        self.step.save(update_fields=["order"])
        self.as_user(user).post(reverse("ccrv:protocolstep-reorder-by-linked-list"))
        self.step.refresh_from_db()
        return self.step.order

    def test_owners_and_editors_reorder_their_protocols(self):
        self.assertEqual(self.reorder_as(self.owner), 0)
        self.assertEqual(self.reorder_as(self.editor), 0)

    def test_staff_reorder_every_protocol(self):
        self.assertEqual(self.reorder_as(self.staff), 0)

    def test_viewers_and_others_leave_the_protocol_untouched(self):
        for user in (self.viewer, self.member, self.stranger):
            self.assertEqual(self.reorder_as(user), 7, user.username)


class ProtocolContentTests(OwnerEditorTestCase):
    def test_viewers_and_lab_group_members_cannot_change_steps(self):
        url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        for user in (self.viewer, self.member):
            response = self.as_user(user).patch(url, {"step_description": "changed"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, user.username)
            move = self.as_user(user).post(reverse("ccrv:protocolstep-move-up", kwargs={"pk": self.step.pk}))
            self.assertEqual(move.status_code, status.HTTP_403_FORBIDDEN, user.username)

    def test_staff_change_steps_of_any_protocol(self):
        url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        response = self.as_user(self.staff).patch(url, {"step_description": "staff"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewers_can_still_read_steps(self):
        url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        self.assertEqual(self.as_user(self.viewer).get(url).status_code, status.HTTP_200_OK)

    def test_editors_change_steps_and_sections(self):
        step_url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        section_url = reverse("ccrv:protocolsection-detail", kwargs={"pk": self.section.pk})
        client = self.as_user(self.editor)
        self.assertEqual(client.patch(step_url, {"step_description": "new"}, format="json").status_code, 200)
        self.assertEqual(client.patch(section_url, {"section_description": "new"}, format="json").status_code, 200)

    def test_adding_a_section_needs_the_owner_or_an_editor(self):
        url = reverse("ccrv:protocolsection-list")
        body = {"protocol": self.protocol.pk, "section_description": "New", "section_duration": 5}
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.editor).post(url, body, format="json").status_code, 201)

    def test_protocol_reagents_are_changed_by_owners_and_editors_only(self):
        url = reverse("ccrv:protocolreagent-detail", kwargs={"pk": self.protocol_reagent.pk})
        self.assertEqual(self.as_user(self.viewer).patch(url, {"quantity": 2}, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.viewer).delete(url).status_code, 403)
        self.assertEqual(self.as_user(self.editor).patch(url, {"quantity": 2}, format="json").status_code, 200)

    def test_reagents_follow_protocol_visibility(self):
        session_viewer = UserFactory.create_user(username="session_viewer")
        self.session.viewers.add(session_viewer)
        lists = (
            (reverse("ccrv:protocolreagent-list"), self.protocol_reagent.pk),
            (reverse("ccrv:stepreagent-list"), self.step_reagent.pk),
        )
        for url, pk in lists:
            for user in (self.owner, self.editor, self.viewer, self.member, session_viewer, self.staff):
                ids = [r["id"] for r in self.as_user(user).get(url, {"limit": 10}).data["results"]]
                self.assertIn(pk, ids, f"{url} {user.username}")
            ids = [r["id"] for r in self.as_user(self.stranger).get(url, {"limit": 10}).data["results"]]
            self.assertNotIn(pk, ids, url)

    def test_bulk_adding_reagents_needs_the_owner_or_an_editor(self):
        url = reverse("ccrv:protocolreagent-bulk-add-reagents")
        body = {"protocol_id": self.protocol.pk, "reagents": [{"reagent_id": self.reagent.pk, "quantity": 1}]}
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.editor).post(url, body, format="json").status_code, 201)

    def test_step_reagents_are_scaled_by_owners_and_editors_only(self):
        scaling = reverse("ccrv:stepreagent-update-scaling", kwargs={"pk": self.step_reagent.pk})
        bulk = reverse("ccrv:stepreagent-bulk-scale-reagents")
        body = {"step_id": self.step.pk, "scale_factor": 2}
        self.assertEqual(self.as_user(self.viewer).post(scaling, {"scalable_factor": 2}).status_code, 403)
        self.assertEqual(self.as_user(self.viewer).post(bulk, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.editor).post(scaling, {"scalable_factor": 2}).status_code, 200)
        self.assertEqual(self.as_user(self.editor).post(bulk, body, format="json").status_code, 200)


class SessionAnnotationWriteTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        annotation = Annotation.objects.create(annotation="note", annotation_type="text", owner=self.owner)
        self.step_annotation = StepAnnotation.objects.create(
            session=self.session, step=self.step, annotation=annotation
        )

    def scratch_as(self, user):
        url = reverse("ccrv:stepannotation-detail", kwargs={"pk": self.step_annotation.pk})
        return self.as_user(user).patch(url, {"annotation_data": {"scratched": True}}, format="json")

    def test_viewers_cannot_scratch_annotations(self):
        self.assertIn(self.scratch_as(self.viewer).status_code, (403, 404))
        self.step_annotation.annotation.refresh_from_db()
        self.assertFalse(self.step_annotation.annotation.scratched)

    def test_editors_can_scratch_annotations(self):
        self.assertEqual(self.scratch_as(self.editor).status_code, status.HTTP_200_OK)
        self.step_annotation.annotation.refresh_from_db()
        self.assertTrue(self.step_annotation.annotation.scratched)

    def test_staff_scratch_annotations_of_any_session(self):
        self.assertEqual(self.scratch_as(self.staff).status_code, status.HTTP_200_OK)

    def test_deleting_an_annotation_needs_the_session_owner_or_an_editor(self):
        url = reverse("ccrv:stepannotation-detail", kwargs={"pk": self.step_annotation.pk})
        self.assertEqual(self.as_user(self.viewer).delete(url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(StepAnnotation.objects.filter(pk=self.step_annotation.pk).exists())
        self.assertEqual(self.as_user(self.editor).delete(url).status_code, status.HTTP_204_NO_CONTENT)

    def test_annotation_permissions_follow_the_session_owner_and_editors(self):
        self.assertTrue(self.step_annotation.can_edit(self.editor))
        self.assertTrue(self.step_annotation.can_delete(self.editor))
        self.assertFalse(self.step_annotation.can_edit(self.viewer))
        self.assertFalse(self.step_annotation.can_delete(self.viewer))

    def test_annotating_a_session_needs_the_owner_or_an_editor(self):
        url = reverse("ccrv:stepannotation-list")
        body = {
            "session": self.session.pk,
            "step": self.step.pk,
            "annotation_data": {"annotation": "note", "annotation_type": "text"},
        }
        before = Annotation.objects.count()
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(Annotation.objects.count(), before)
        self.assertEqual(self.as_user(self.editor).post(url, body, format="json").status_code, 201)


class RatingTests(OwnerEditorTestCase):
    def rate_as(self, user):
        url = reverse("ccrv:protocolrating-rate-protocol")
        body = {"protocol_id": self.protocol.pk, "complexity_rating": 3, "duration_rating": 4}
        return self.as_user(user).post(url, body, format="json")

    def test_users_who_can_view_the_protocol_can_rate_it(self):
        for user in (self.owner, self.editor, self.viewer, self.member):
            self.assertIn(self.rate_as(user).status_code, (200, 201), user.username)

    def test_users_who_cannot_view_the_protocol_cannot_rate_it(self):
        self.assertEqual(self.rate_as(self.stranger).status_code, status.HTTP_403_FORBIDDEN)
        response = self.as_user(self.stranger).post(
            reverse("ccrv:protocolrating-list"),
            {"protocol": self.protocol.pk, "complexity_rating": 3, "duration_rating": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ProtocolRating.objects.filter(user=self.stranger).exists())

    def test_ratings_outside_0_to_10_are_rejected(self):
        response = self.as_user(self.viewer).post(
            reverse("ccrv:protocolrating-list"),
            {"protocol": self.protocol.pk, "complexity_rating": 11, "duration_rating": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_the_rater_deletes_a_rating(self):
        rating = ProtocolRating.objects.create(
            protocol=self.protocol, user=self.viewer, complexity_rating=2, duration_rating=2
        )
        url = reverse("ccrv:protocolrating-detail", kwargs={"pk": rating.pk})
        self.assertEqual(self.as_user(self.owner).delete(url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(ProtocolRating.objects.filter(pk=rating.pk).exists())
        self.assertEqual(self.as_user(self.viewer).delete(url).status_code, status.HTTP_204_NO_CONTENT)

    def test_only_the_rater_changes_a_rating(self):
        rating = ProtocolRating.objects.create(
            protocol=self.protocol, user=self.viewer, complexity_rating=2, duration_rating=2
        )
        url = reverse("ccrv:protocolrating-detail", kwargs={"pk": rating.pk})
        response = self.as_user(self.owner).patch(url, {"complexity_rating": 9}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.as_user(self.viewer).patch(url, {"complexity_rating": 5}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rating.refresh_from_db()
        self.assertEqual(rating.complexity_rating, 5)

    def test_staff_delete_any_rating(self):
        rating = ProtocolRating.objects.create(
            protocol=self.protocol, user=self.viewer, complexity_rating=2, duration_rating=2
        )
        url = reverse("ccrv:protocolrating-detail", kwargs={"pk": rating.pk})
        self.assertEqual(self.as_user(self.staff).delete(url).status_code, status.HTTP_204_NO_CONTENT)

    def test_each_user_keeps_one_rating_per_protocol(self):
        self.rate_as(self.viewer)
        url = reverse("ccrv:protocolrating-rate-protocol")
        body = {"protocol_id": self.protocol.pk, "complexity_rating": 7, "duration_rating": 7}
        self.as_user(self.viewer).post(url, body, format="json")
        ratings = ProtocolRating.objects.filter(protocol=self.protocol, user=self.viewer)
        self.assertEqual(ratings.count(), 1)
        self.assertEqual(ratings.get().complexity_rating, 7)


class StepVariationTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        self.variation = StepVariation.objects.create(
            step=self.step, session=self.session, variation_description="Longer", variation_duration=20
        )

    def test_variations_follow_session_visibility(self):
        url = reverse("ccrv:stepvariation-list")
        for user in (self.owner, self.editor, self.viewer, self.staff):
            ids = [v["id"] for v in self.as_user(user).get(url, {"limit": 10}).data["results"]]
            self.assertIn(self.variation.pk, ids, user.username)
        for user in (self.member, self.stranger):
            ids = [v["id"] for v in self.as_user(user).get(url, {"limit": 10}).data["results"]]
            self.assertNotIn(self.variation.pk, ids, user.username)

    def test_variations_without_a_session_follow_protocol_visibility(self):
        variation = StepVariation.objects.create(step=self.step, variation_description="Plain", variation_duration=5)
        url = reverse("ccrv:stepvariation-list")
        ids = [v["id"] for v in self.as_user(self.member).get(url, {"limit": 10}).data["results"]]
        self.assertIn(variation.pk, ids)
        ids = [v["id"] for v in self.as_user(self.stranger).get(url, {"limit": 10}).data["results"]]
        self.assertNotIn(variation.pk, ids)

    def test_session_viewers_cannot_change_variations(self):
        url = reverse("ccrv:stepvariation-detail", kwargs={"pk": self.variation.pk})
        response = self.as_user(self.viewer).patch(url, {"variation_duration": 30}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.as_user(self.viewer).delete(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_session_editors_change_variations(self):
        url = reverse("ccrv:stepvariation-detail", kwargs={"pk": self.variation.pk})
        response = self.as_user(self.editor).patch(url, {"variation_duration": 30}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_adding_a_variation_needs_the_session_owner_or_an_editor(self):
        url = reverse("ccrv:stepvariation-list")
        body = {
            "step": self.step.pk,
            "session": self.session.pk,
            "variation_description": "Shorter",
            "variation_duration": 5,
        }
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.editor).post(url, body, format="json").status_code, 201)


class SessionFolderTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        folder = AnnotationFolder.objects.create(folder_name="Images", owner=self.owner)
        self.session_folder = SessionAnnotationFolder.objects.create(session=self.session, folder=folder)

    def test_session_members_see_the_folders(self):
        url = reverse("ccrv:sessionannotationfolder-list")
        for user in (self.owner, self.editor, self.viewer, self.staff):
            ids = [f["id"] for f in self.as_user(user).get(url, {"session": self.session.pk}).data["results"]]
            self.assertIn(self.session_folder.pk, ids, user.username)
        ids = [f["id"] for f in self.as_user(self.stranger).get(url).data["results"]]
        self.assertNotIn(self.session_folder.pk, ids)

    def test_viewers_cannot_remove_folders(self):
        url = reverse("ccrv:sessionannotationfolder-detail", kwargs={"pk": self.session_folder.pk})
        self.assertEqual(self.as_user(self.viewer).delete(url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.as_user(self.editor).delete(url).status_code, status.HTTP_204_NO_CONTENT)


class StepBookingTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        self.instrument_owner = UserFactory.create_user(username="instrument_owner")
        self.job_staff = UserFactory.create_user(username="job_staff")
        self.facility_member = UserFactory.create_user(username="facility_member")
        facility = LabGroup.objects.create(name="Facility", creator=self.instrument_owner)
        facility.members.add(self.facility_member)
        instrument = Instrument.objects.create(instrument_name="LC-MS", user=self.instrument_owner)
        self.booking = InstrumentUsage.objects.create(instrument=instrument, user=self.instrument_owner)
        job = InstrumentJob.objects.create(
            instrument=instrument,
            instrument_usage=self.booking,
            user=self.owner,
            lab_group=facility,
            job_name="Run",
            job_type="analysis",
            status="submitted",
        )
        job.staff.add(self.job_staff)
        annotation = Annotation.objects.create(annotation="Booking", annotation_type="booking", owner=self.owner)
        self.step_annotation = StepAnnotation.objects.create(
            session=self.session, step=self.step, annotation=annotation
        )
        self.link = InstrumentUsageStepAnnotation.objects.create(
            step_annotation=self.step_annotation, instrument_usage=self.booking
        )

    def linked_ids(self, user):
        response = self.as_user(user).get(reverse("ccrv:instrumentusagestepannotation-list"), {"limit": 10})
        return [link["id"] for link in response.data["results"]]

    def test_booking_rules_keep_the_link_visible_outside_the_session(self):
        for user in (self.instrument_owner, self.job_staff, self.facility_member, self.viewer):
            self.assertIn(self.link.pk, self.linked_ids(user), user.username)
        self.assertNotIn(self.link.pk, self.linked_ids(self.stranger))

    def test_deleting_the_annotation_keeps_a_booking_the_user_cannot_delete(self):
        url = reverse("ccrv:stepannotation-detail", kwargs={"pk": self.step_annotation.pk})
        self.assertEqual(self.as_user(self.editor).delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(InstrumentUsage.objects.filter(pk=self.booking.pk).exists())

    def test_deleting_the_annotation_removes_a_booking_the_user_can_delete(self):
        self.booking.user = self.owner
        self.booking.save(update_fields=["user"])
        self.booking.instrument.instrument_permissions.create(user=self.owner, can_book=True)
        url = reverse("ccrv:stepannotation-detail", kwargs={"pk": self.step_annotation.pk})
        self.assertEqual(self.as_user(self.owner).delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(InstrumentUsage.objects.filter(pk=self.booking.pk).exists())


class PublicSessionTests(OwnerEditorTestCase):
    def setUp(self):
        super().setUp()
        self.session.enabled = True
        self.session.save(update_fields=["enabled"])
        annotation = Annotation.objects.create(annotation="note", annotation_type="text", owner=self.owner)
        self.step_annotation = StepAnnotation.objects.create(
            session=self.session, step=self.step, annotation=annotation
        )

    def get(self, name, params=None, **kwargs):
        return self.as_user(self.stranger).get(reverse(f"ccrv:{name}", kwargs=kwargs or None), params)

    def ids(self, response):
        return [row["id"] for row in response.data["results"]]

    def open_by_link(self):
        return self.get("session-list", {"unique_id": str(self.session.unique_id), "limit": 1})

    def test_anyone_with_the_link_opens_what_the_session_page_shows(self):
        self.assertEqual(self.ids(self.open_by_link()), [self.session.pk])
        self.assertEqual(self.get("session-detail", pk=self.session.pk).status_code, status.HTTP_200_OK)
        self.assertEqual(self.get("protocolmodel-detail", pk=self.protocol.pk).status_code, status.HTTP_200_OK)
        self.assertIn(self.section.pk, self.ids(self.get("protocolsection-list", {"protocol": self.protocol.pk})))
        self.assertIn(self.step.pk, self.ids(self.get("protocolstep-list", {"protocol": self.protocol.pk})))
        self.assertIn(self.step_reagent.pk, self.ids(self.get("stepreagent-list", {"step": self.step.pk})))
        annotations = self.get("stepannotation-list", {"session": self.session.pk})
        self.assertIn(self.step_annotation.pk, self.ids(annotations))
        self.assertTrue(self.step_annotation.annotation.can_view(self.stranger))
        self.assertEqual(self.get("session-get-export-url", pk=self.session.pk).status_code, status.HTTP_200_OK)

    def test_guessed_ids_without_the_link_find_nothing(self):
        self.assertEqual(self.get("session-detail", pk=self.session.pk).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.get("protocolmodel-detail", pk=self.protocol.pk).status_code, status.HTTP_404_NOT_FOUND)
        annotations = self.get("stepannotation-list", {"session": self.session.pk})
        self.assertNotIn(self.step_annotation.pk, self.ids(annotations))
        self.assertFalse(self.step_annotation.annotation.can_view(self.stranger))

    def test_making_the_session_private_revokes_the_link(self):
        self.open_by_link()
        self.session.enabled = False
        self.session.save(update_fields=["enabled"])
        self.session.enabled = True
        self.session.save(update_fields=["enabled"])
        self.assertEqual(self.get("session-detail", pk=self.session.pk).status_code, status.HTTP_404_NOT_FOUND)

    def test_members_are_not_recorded_as_link_users(self):
        self.as_user(self.viewer).get(reverse("ccrv:session-list"), {"unique_id": str(self.session.unique_id)})
        self.assertFalse(self.session.link_unlocked_by.filter(pk=self.viewer.pk).exists())

    def test_public_sessions_are_not_listed(self):
        self.open_by_link()
        self.assertNotIn(self.session.pk, self.ids(self.get("session-list", {"limit": 10})))
        self.assertNotIn(self.protocol.pk, self.ids(self.get("protocolmodel-list", {"limit": 10})))
        self.assertNotIn(self.step.pk, self.ids(self.get("protocolstep-list", {"limit": 10})))
        self.assertNotIn(self.step_annotation.pk, self.ids(self.get("stepannotation-list", {"limit": 10})))

    def test_only_the_session_page_actions_are_public(self):
        self.open_by_link()
        self.assertEqual(self.get("session-folders", pk=self.session.pk).status_code, status.HTTP_403_FORBIDDEN)

    def test_public_sessions_are_read_only(self):
        self.open_by_link()
        client = self.as_user(self.stranger)
        session_url = reverse("ccrv:session-detail", kwargs={"pk": self.session.pk})
        step_url = reverse("ccrv:protocolstep-detail", kwargs={"pk": self.step.pk})
        annotation_url = reverse("ccrv:stepannotation-detail", kwargs={"pk": self.step_annotation.pk})
        self.assertEqual(client.patch(session_url, {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(client.patch(step_url, {"step_description": "x"}, format="json").status_code, 403)
        self.assertEqual(client.delete(annotation_url).status_code, status.HTTP_403_FORBIDDEN)

    def test_private_sessions_stay_closed(self):
        self.session.enabled = False
        self.session.save(update_fields=["enabled"])
        self.assertEqual(self.get("session-detail", pk=self.session.pk).status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(
            self.step_annotation.pk, self.ids(self.get("stepannotation-list", {"session": self.session.pk}))
        )
