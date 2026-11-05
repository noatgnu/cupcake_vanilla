"""Deleting a session removes the annotations and files only it used."""

import tempfile
import uuid
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import Annotation, AnnotationFolder
from ccm.models import Instrument, InstrumentUsage
from ccrv.models import (
    InstrumentUsageStepAnnotation,
    ProtocolModel,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotation,
    StepAnnotation,
)
from tests.factories import UserFactory

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class SessionDeletionTests(APITestCase):
    def setUp(self):
        self.owner = UserFactory.create_user(username="owner")
        protocol = ProtocolModel.objects.create(protocol_title="Protocol", owner=self.owner)
        section = ProtocolSection.objects.create(protocol=protocol, section_description="Section")
        self.step = ProtocolStep.objects.create(protocol=protocol, step_section=section, step_description="Step")
        self.session = Session.objects.create(name="Session", owner=self.owner, unique_id=uuid.uuid4())
        self.session.protocols.add(protocol)
        self.client.force_authenticate(user=self.owner)

    def annotation(self, text, with_file=False):
        annotation = Annotation.objects.create(annotation=text, annotation_type="file", owner=self.owner)
        if with_file:
            annotation.file = SimpleUploadedFile(f"{text}.txt", b"recording")
            annotation.save()
        return annotation

    def delete_session(self):
        response = self.client.delete(reverse("ccrv:session-detail", kwargs={"pk": self.session.pk}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_annotations_and_files_of_the_session_are_deleted(self):
        step_note = self.annotation("step note", with_file=True)
        session_note = self.annotation("session note")
        StepAnnotation.objects.create(session=self.session, step=self.step, annotation=step_note)
        SessionAnnotation.objects.create(session=self.session, annotation=session_note)
        file_path = Path(step_note.file.path)
        self.assertTrue(file_path.exists())

        self.delete_session()

        self.assertFalse(Annotation.objects.filter(pk__in=[step_note.pk, session_note.pk]).exists())
        self.assertFalse(file_path.exists())

    def test_annotations_still_used_elsewhere_are_kept(self):
        shared = self.annotation("shared note", with_file=True)
        StepAnnotation.objects.create(session=self.session, step=self.step, annotation=shared)
        other_session = Session.objects.create(name="Other", owner=self.owner, unique_id=uuid.uuid4())
        StepAnnotation.objects.create(session=other_session, step=self.step, annotation=shared)

        self.delete_session()

        self.assertTrue(Annotation.objects.filter(pk=shared.pk).exists())
        self.assertTrue(Path(shared.file.path).exists())

    def test_annotations_filed_in_a_folder_are_kept(self):
        folder = AnnotationFolder.objects.create(folder_name="My recordings", owner=self.owner)
        filed = self.annotation("filed recording", with_file=True)
        filed.folder = folder
        filed.save()
        SessionAnnotation.objects.create(session=self.session, annotation=filed)

        self.delete_session()

        self.assertTrue(Annotation.objects.filter(pk=filed.pk).exists())
        self.assertTrue(Path(filed.file.path).exists())

    def test_bookings_linked_from_the_session_are_kept(self):
        booking_note = self.annotation("booking")
        step_annotation = StepAnnotation.objects.create(session=self.session, step=self.step, annotation=booking_note)
        instrument = Instrument.objects.create(instrument_name="LC-MS", user=self.owner)
        booking = InstrumentUsage.objects.create(instrument=instrument, user=self.owner)
        InstrumentUsageStepAnnotation.objects.create(step_annotation=step_annotation, instrument_usage=booking)

        self.delete_session()

        self.assertTrue(InstrumentUsage.objects.filter(pk=booking.pk).exists())
        self.assertFalse(Annotation.objects.filter(pk=booking_note.pk).exists())
