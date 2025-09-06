"""
Tests for instrument usage booking permissions and session annotation linking.

Tests that instrument usage bookings require can_book permissions and that
session annotations can be properly linked to instrument usage bookings.
"""

import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from ccc.models import Annotation
from ccm.models import Instrument, InstrumentPermission, InstrumentUsage
from ccrv.models import InstrumentUsageSessionAnnotation, ProtocolModel, Session, SessionAnnotation
from tests.factories import UserFactory


class InstrumentUsagePermissionTestCase(TestCase):
    """Test instrument usage booking permission requirements."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.booker = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test HPLC System",
            instrument_description="High-performance liquid chromatography for sample analysis",
            user=self.owner,
        )

        # Create permissions
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.booker, can_view=True, can_book=True, can_manage=False
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

    def test_owner_can_create_bookings(self):
        """Test that instrument owner can create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.owner,
            time_started=timezone.now() + timedelta(hours=1),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Sample analysis run",
        )

        self.assertTrue(usage.user_can_create(self.owner))

    def test_staff_can_create_bookings(self):
        """Test that staff users can create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.staff_user,
            time_started=timezone.now() + timedelta(hours=1),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Staff maintenance booking",
        )

        self.assertTrue(usage.user_can_create(self.staff_user))

    def test_booker_can_create_bookings(self):
        """Test that users with can_book permission can create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.booker,
            time_started=timezone.now() + timedelta(hours=2),
            time_ended=timezone.now() + timedelta(hours=4),
            description="Research experiment",
        )

        self.assertTrue(usage.user_can_create(self.booker))

    def test_manager_can_create_bookings(self):
        """Test that users with can_manage permission can create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.manager,
            time_started=timezone.now() + timedelta(hours=3),
            time_ended=timezone.now() + timedelta(hours=5),
            description="System calibration",
        )

        self.assertTrue(usage.user_can_create(self.manager))

    def test_viewer_cannot_create_bookings(self):
        """Test that users with only view permission cannot create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.viewer,  # This shouldn't happen in practice, but test the method
            time_started=timezone.now() + timedelta(hours=1),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Unauthorized booking attempt",
        )

        self.assertFalse(usage.user_can_create(self.viewer))

    def test_other_user_cannot_create_bookings(self):
        """Test that users without permissions cannot create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.other_user,
            time_started=timezone.now() + timedelta(hours=1),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Unauthorized booking",
        )

        self.assertFalse(usage.user_can_create(self.other_user))

    def test_unauthenticated_user_cannot_create_bookings(self):
        """Test that unauthenticated users cannot create bookings."""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=None,
            time_started=timezone.now() + timedelta(hours=1),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Anonymous booking attempt",
        )

        self.assertFalse(usage.user_can_create(None))


class InstrumentUsageViewEditPermissionTestCase(TestCase):
    """Test viewing and editing permissions for instrument usage bookings."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.booking_user = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Mass Spectrometer",
            instrument_description="Advanced mass spectrometry system",
            user=self.owner,
        )

        # Create permissions
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.booking_user, can_view=True, can_book=True, can_manage=False
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        # Create instrument usage booking
        self.usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.booking_user,
            time_started=timezone.now(),
            time_ended=timezone.now() + timedelta(hours=2),
            description="Protein analysis experiment",
            usage_hours=2.0,
        )

    def test_booking_creator_can_view_and_edit(self):
        """Test that booking creator has full access to their booking."""
        self.assertTrue(self.usage.user_can_view(self.booking_user))
        self.assertTrue(self.usage.user_can_edit(self.booking_user))
        self.assertTrue(self.usage.user_can_delete(self.booking_user))

    def test_instrument_owner_can_view_and_edit(self):
        """Test that instrument owner can view and edit all bookings."""
        self.assertTrue(self.usage.user_can_view(self.owner))
        self.assertTrue(self.usage.user_can_edit(self.owner))
        self.assertTrue(self.usage.user_can_delete(self.owner))

    def test_manager_can_view_and_edit(self):
        """Test that users with manage permission can view and edit all bookings."""
        self.assertTrue(self.usage.user_can_view(self.manager))
        self.assertTrue(self.usage.user_can_edit(self.manager))
        self.assertTrue(self.usage.user_can_delete(self.manager))

    def test_viewer_can_view_but_not_edit(self):
        """Test that users with view permission can see but not modify bookings."""
        self.assertTrue(self.usage.user_can_view(self.viewer))
        self.assertFalse(self.usage.user_can_edit(self.viewer))
        self.assertFalse(self.usage.user_can_delete(self.viewer))

    def test_other_user_cannot_view_or_edit(self):
        """Test that users without permissions cannot access bookings."""
        self.assertFalse(self.usage.user_can_view(self.other_user))
        self.assertFalse(self.usage.user_can_edit(self.other_user))
        self.assertFalse(self.usage.user_can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access to all bookings."""
        self.assertTrue(self.usage.user_can_view(self.staff_user))
        self.assertTrue(self.usage.user_can_edit(self.staff_user))
        self.assertTrue(self.usage.user_can_delete(self.staff_user))


class InstrumentUsageSessionAnnotationTestCase(TestCase):
    """Test linking session annotations to instrument usage bookings."""

    def setUp(self):
        self.researcher = UserFactory.create_user()
        self.lab_manager = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test NMR Spectrometer",
            instrument_description="Nuclear magnetic resonance spectrometer",
            user=self.lab_manager,
        )

        # Give researcher booking permissions
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.researcher, can_view=True, can_book=True, can_manage=False
        )

        # Create protocol and session for the research experiment
        self.protocol = ProtocolModel.objects.create(
            protocol_title="NMR Sample Analysis Protocol",
            protocol_description="Standard protocol for NMR analysis",
            owner=self.researcher,
        )

        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            name="Protein Structure Analysis Session",
            owner=self.researcher,
            visibility="private",
        )
        self.session.protocols.add(self.protocol)

        # Create instrument usage booking
        self.usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.researcher,
            time_started=timezone.now(),
            time_ended=timezone.now() + timedelta(hours=4),
            description="NMR analysis of protein samples",
            usage_hours=4.0,
        )

        # Create session annotation with experimental data
        experiment_data = SimpleUploadedFile(
            "nmr_spectrum.csv", b"chemical_shift,intensity\n7.23,0.85\n7.45,0.92\n8.12,0.78", content_type="text/csv"
        )

        self.annotation = Annotation.objects.create(
            annotation="NMR spectrum data showing protein folding patterns",
            annotation_type="file",
            file=experiment_data,
            owner=self.researcher,
        )

        self.session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=self.annotation)

    def test_create_session_annotation_link(self):
        """Test creating a link between instrument usage and session annotation."""
        link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation, order=1
        )

        self.assertEqual(link.instrument_usage, self.usage)
        self.assertEqual(link.session_annotation, self.session_annotation)
        self.assertEqual(link.order, 1)

        # Test string representation
        expected_str = f"{self.session.name} - {self.instrument.instrument_name}"
        self.assertEqual(str(link), expected_str)

    def test_unique_constraint(self):
        """Test that each session annotation can only be linked once per instrument usage."""
        # Create first link
        InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation
        )

        # The unique_together constraint should be enforced at the database level
        # Here we just verify the constraint is properly defined
        self.assertEqual(
            InstrumentUsageSessionAnnotation._meta.unique_together, (("session_annotation", "instrument_usage"),)
        )

    def test_researcher_can_view_and_edit_link(self):
        """Test that researcher who created both booking and session can manage link."""
        link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation
        )

        self.assertTrue(link.can_view(self.researcher))
        self.assertTrue(link.can_edit(self.researcher))
        self.assertTrue(link.can_delete(self.researcher))

    def test_lab_manager_can_view_and_edit_link(self):
        """Test that lab manager (instrument owner) can manage links."""
        link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation
        )

        self.assertTrue(link.can_view(self.lab_manager))
        self.assertTrue(link.can_edit(self.lab_manager))
        self.assertTrue(link.can_delete(self.lab_manager))

    def test_other_user_cannot_access_link(self):
        """Test that other users cannot access the link."""
        link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation
        )

        self.assertFalse(link.can_view(self.other_user))
        self.assertFalse(link.can_edit(self.other_user))
        self.assertFalse(link.can_delete(self.other_user))

    def test_staff_has_full_access_to_link(self):
        """Test that staff users have full access to annotation links."""
        link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=self.usage, session_annotation=self.session_annotation
        )

        self.assertTrue(link.can_view(self.staff_user))
        self.assertTrue(link.can_edit(self.staff_user))
        self.assertTrue(link.can_delete(self.staff_user))


class InstrumentUsageWorkflowTestCase(TestCase):
    """Test complete workflows involving instrument usage and session annotations."""

    def setUp(self):
        self.facility_manager = UserFactory.create_user()
        self.postdoc = UserFactory.create_user()
        self.grad_student = UserFactory.create_user()
        self.external_collaborator = UserFactory.create_user()

        # Create high-end instrument
        self.lcms = Instrument.objects.create(
            instrument_name="Advanced LC-MS/MS System",
            instrument_description="Triple quadrupole liquid chromatography mass spectrometry",
            user=self.facility_manager,
        )

        # Set up hierarchical permissions
        InstrumentPermission.objects.create(
            instrument=self.lcms, user=self.postdoc, can_view=True, can_book=True, can_manage=True
        )

        InstrumentPermission.objects.create(
            instrument=self.lcms, user=self.grad_student, can_view=True, can_book=True, can_manage=False
        )

        # External collaborator gets limited access
        InstrumentPermission.objects.create(
            instrument=self.lcms,
            user=self.external_collaborator,
            can_view=True,
            can_book=False,  # Must be supervised
            can_manage=False,
        )

    def test_postdoc_booking_and_annotation_workflow(self):
        """Test complete workflow: postdoc books instrument and documents session."""
        # Postdoc creates booking for metabolomics experiment
        booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.postdoc,
            time_started=timezone.now(),
            time_ended=timezone.now() + timedelta(hours=6),
            description="Metabolomics analysis of cell culture samples",
            usage_hours=6.0,
        )

        # Verify booking permissions
        self.assertTrue(booking.user_can_create(self.postdoc))
        self.assertTrue(booking.user_can_view(self.postdoc))
        self.assertTrue(booking.user_can_edit(self.postdoc))

        # Create experimental session
        protocol = ProtocolModel.objects.create(
            protocol_title="Metabolomics LC-MS Analysis",
            protocol_description="Standard protocol for untargeted metabolomics",
            owner=self.postdoc,
        )

        session = Session.objects.create(
            unique_id=uuid.uuid4(),
            name="Cell Culture Metabolomics - Batch 1",
            owner=self.postdoc,
            visibility="protected",
        )
        session.protocols.add(protocol)
        session.editors.add(self.grad_student)  # Grad student can collaborate

        # Create session annotations with experimental results
        method_notes = Annotation.objects.create(
            annotation="Used extended gradient method with optimized ion source parameters",
            annotation_type="text",
            owner=self.postdoc,
        )

        results_file = SimpleUploadedFile(
            "metabolomics_results.mzML", b"fake mzML mass spectrometry data", content_type="application/octet-stream"
        )

        results_annotation = Annotation.objects.create(
            annotation="Raw mass spectrometry data from LC-MS run",
            annotation_type="file",
            file=results_file,
            owner=self.postdoc,
        )

        # Create session annotations
        method_session_annotation = SessionAnnotation.objects.create(session=session, annotation=method_notes)

        results_session_annotation = SessionAnnotation.objects.create(session=session, annotation=results_annotation)

        # Link session annotations to instrument booking
        method_link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=booking, session_annotation=method_session_annotation, order=1
        )

        results_link = InstrumentUsageSessionAnnotation.objects.create(
            instrument_usage=booking, session_annotation=results_session_annotation, order=2
        )

        # Verify all permissions work correctly
        self.assertTrue(method_link.can_view(self.postdoc))
        self.assertTrue(method_link.can_edit(self.postdoc))
        self.assertTrue(results_link.can_view(self.postdoc))
        self.assertTrue(results_link.can_edit(self.postdoc))

        # Facility manager should have oversight access
        self.assertTrue(booking.user_can_view(self.facility_manager))
        self.assertTrue(booking.user_can_edit(self.facility_manager))
        self.assertTrue(method_link.can_view(self.facility_manager))
        self.assertTrue(method_link.can_edit(self.facility_manager))

    def test_grad_student_booking_workflow(self):
        """Test grad student can book but has limited management access."""
        # Grad student books instrument
        booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.grad_student,
            time_started=timezone.now() + timedelta(hours=24),
            time_ended=timezone.now() + timedelta(hours=26),
            description="Preliminary compound identification",
            usage_hours=2.0,
        )

        # Verify booking permissions
        self.assertTrue(booking.user_can_create(self.grad_student))
        self.assertTrue(booking.user_can_view(self.grad_student))
        self.assertTrue(booking.user_can_edit(self.grad_student))

        # Postdoc (with manage rights) should also be able to edit
        self.assertTrue(booking.user_can_view(self.postdoc))
        self.assertTrue(booking.user_can_edit(self.postdoc))

    def test_external_collaborator_restrictions(self):
        """Test that external collaborators cannot book but can view."""
        # External collaborator should not be able to create bookings
        booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.external_collaborator,  # This shouldn't happen in practice
            time_started=timezone.now() + timedelta(hours=48),
            time_ended=timezone.now() + timedelta(hours=50),
            description="Collaborative analysis",
            usage_hours=2.0,
        )

        # Verify they don't have booking permission
        self.assertFalse(booking.user_can_create(self.external_collaborator))

        # But they should be able to view bookings (if they somehow exist)
        self.assertTrue(booking.user_can_view(self.external_collaborator))
        self.assertFalse(booking.user_can_edit(self.external_collaborator))

        # They should be able to view properly authorized bookings made by others
        postdoc_booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.postdoc,
            time_started=timezone.now() + timedelta(hours=72),
            time_ended=timezone.now() + timedelta(hours=74),
            description="Shared analysis for collaboration",
            usage_hours=2.0,
        )

        self.assertTrue(postdoc_booking.user_can_view(self.external_collaborator))
        self.assertFalse(postdoc_booking.user_can_edit(self.external_collaborator))

    def test_permission_changes_affect_existing_bookings(self):
        """Test that changing instrument permissions affects access to existing bookings."""
        # Create booking when grad student has booking rights
        booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.grad_student,
            time_started=timezone.now(),
            time_ended=timezone.now() + timedelta(hours=3),
            description="Analysis before permission change",
            usage_hours=3.0,
        )

        # Initially grad student can view their booking
        self.assertTrue(booking.user_can_view(self.grad_student))

        # Remove grad student's view permission
        grad_permission = InstrumentPermission.objects.get(instrument=self.lcms, user=self.grad_student)
        grad_permission.can_view = False
        grad_permission.save()

        # Now grad student should not be able to view even their own booking
        # (instrument permissions take precedence over booking creator status)
        self.assertFalse(booking.user_can_view(self.grad_student))

        # Restore view permission and add manage permission
        grad_permission.can_view = True
        grad_permission.can_manage = True
        grad_permission.save()

        # Now grad student should have edit access to all bookings, not just their own
        postdoc_booking = InstrumentUsage.objects.create(
            instrument=self.lcms,
            user=self.postdoc,
            time_started=timezone.now() + timedelta(hours=6),
            time_ended=timezone.now() + timedelta(hours=8),
            description="Another user's booking",
            usage_hours=2.0,
        )

        self.assertTrue(postdoc_booking.user_can_view(self.grad_student))
        self.assertTrue(postdoc_booking.user_can_edit(self.grad_student))  # Now has manage rights
