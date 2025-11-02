"""
Tests for InstrumentJobAnnotation role field functionality.

Tests that annotations can be correctly categorized as 'user' or 'staff'
and that users who are both owner and staff can have separate annotations.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import Annotation
from ccm.models import Instrument, InstrumentJob, InstrumentJobAnnotation
from ccv.models import LabGroup

User = get_user_model()


class InstrumentJobAnnotationRoleTestCase(TestCase):
    """Test role field functionality for InstrumentJobAnnotation."""

    def setUp(self):
        """Set up test data."""
        self.owner_user = User.objects.create_user(username="owner", password="testpass123")
        self.staff_user = User.objects.create_user(username="staff", password="testpass123")
        self.dual_role_user = User.objects.create_user(username="dual", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")

        self.lab_group = LabGroup.objects.create(
            name="Test Lab",
            description="Test lab group",
            creator=self.owner_user,
        )
        self.lab_group.members.add(self.owner_user, self.staff_user, self.dual_role_user)

        self.instrument = Instrument.objects.create(
            instrument_name="Test LCMS",
            user=self.owner_user,
        )

        self.job_owner_only = InstrumentJob.objects.create(
            user=self.owner_user,
            instrument=self.instrument,
            lab_group=self.lab_group,
            job_name="Owner Only Job",
            job_type="lcms",
            status="submitted",
        )

        self.job_with_staff = InstrumentJob.objects.create(
            user=self.owner_user,
            instrument=self.instrument,
            lab_group=self.lab_group,
            job_name="Job With Staff",
            job_type="lcms",
            status="submitted",
        )
        self.job_with_staff.staff.add(self.staff_user)

        self.job_dual_role = InstrumentJob.objects.create(
            user=self.dual_role_user,
            instrument=self.instrument,
            lab_group=self.lab_group,
            job_name="Dual Role Job",
            job_type="lcms",
            status="submitted",
        )
        self.job_dual_role.staff.add(self.dual_role_user)

    def test_default_role_is_user(self):
        """Test that default role is 'user' when not specified."""
        annotation = Annotation.objects.create(
            annotation="Test annotation",
            annotation_type="text",
            owner=self.owner_user,
        )

        job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_owner_only,
            annotation=annotation,
        )

        self.assertEqual(job_annotation.role, "user")

    def test_create_user_role_annotation(self):
        """Test creating annotation with explicit user role."""
        annotation = Annotation.objects.create(
            annotation="User annotation",
            annotation_type="text",
            owner=self.owner_user,
        )

        job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_owner_only,
            annotation=annotation,
            role="user",
        )

        self.assertEqual(job_annotation.role, "user")

    def test_create_staff_role_annotation(self):
        """Test creating annotation with explicit staff role."""
        annotation = Annotation.objects.create(
            annotation="Staff annotation",
            annotation_type="text",
            owner=self.staff_user,
        )

        job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_with_staff,
            annotation=annotation,
            role="staff",
        )

        self.assertEqual(job_annotation.role, "staff")

    def test_dual_role_user_can_create_both_types(self):
        """Test that user who is both owner and staff can create both types of annotations."""
        user_annotation = Annotation.objects.create(
            annotation="As owner",
            annotation_type="text",
            owner=self.dual_role_user,
        )

        staff_annotation = Annotation.objects.create(
            annotation="As staff",
            annotation_type="text",
            owner=self.dual_role_user,
        )

        user_job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_dual_role,
            annotation=user_annotation,
            role="user",
        )

        staff_job_annotation = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_dual_role,
            annotation=staff_annotation,
            role="staff",
        )

        self.assertEqual(user_job_annotation.role, "user")
        self.assertEqual(staff_job_annotation.role, "staff")
        self.assertEqual(user_job_annotation.annotation.owner, staff_job_annotation.annotation.owner)

    def test_filter_by_user_role(self):
        """Test filtering annotations by user role."""
        user_annotation = Annotation.objects.create(
            annotation="User note",
            annotation_type="text",
            owner=self.dual_role_user,
        )

        staff_annotation = Annotation.objects.create(
            annotation="Staff note",
            annotation_type="text",
            owner=self.dual_role_user,
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_dual_role,
            annotation=user_annotation,
            role="user",
        )

        InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_dual_role,
            annotation=staff_annotation,
            role="staff",
        )

        user_annotations = InstrumentJobAnnotation.objects.filter(instrument_job=self.job_dual_role, role="user")

        staff_annotations = InstrumentJobAnnotation.objects.filter(instrument_job=self.job_dual_role, role="staff")

        self.assertEqual(user_annotations.count(), 1)
        self.assertEqual(staff_annotations.count(), 1)
        self.assertEqual(user_annotations.first().annotation.annotation, "User note")
        self.assertEqual(staff_annotations.first().annotation.annotation, "Staff note")

    def test_role_choices(self):
        """Test that only valid role choices are accepted."""
        annotation = Annotation.objects.create(
            annotation="Test",
            annotation_type="text",
            owner=self.owner_user,
        )

        valid_job_annotation = InstrumentJobAnnotation(
            instrument_job=self.job_owner_only,
            annotation=annotation,
            role="user",
        )

        valid_job_annotation.full_clean()

        invalid_job_annotation = InstrumentJobAnnotation(
            instrument_job=self.job_owner_only,
            annotation=annotation,
            role="invalid_role",
        )

        with self.assertRaises(Exception):
            invalid_job_annotation.full_clean()

    def test_multiple_annotations_same_job_different_roles(self):
        """Test that same job can have multiple annotations with different roles."""
        for i in range(3):
            user_annotation = Annotation.objects.create(
                annotation=f"User note {i}",
                annotation_type="text",
                owner=self.dual_role_user,
            )
            InstrumentJobAnnotation.objects.create(
                instrument_job=self.job_dual_role,
                annotation=user_annotation,
                role="user",
            )

        for i in range(2):
            staff_annotation = Annotation.objects.create(
                annotation=f"Staff note {i}",
                annotation_type="text",
                owner=self.dual_role_user,
            )
            InstrumentJobAnnotation.objects.create(
                instrument_job=self.job_dual_role,
                annotation=staff_annotation,
                role="staff",
            )

        all_annotations = InstrumentJobAnnotation.objects.filter(instrument_job=self.job_dual_role)
        user_annotations = all_annotations.filter(role="user")
        staff_annotations = all_annotations.filter(role="staff")

        self.assertEqual(all_annotations.count(), 5)
        self.assertEqual(user_annotations.count(), 3)
        self.assertEqual(staff_annotations.count(), 2)

    def test_booking_annotation_with_role(self):
        """Test that booking annotations can have role field."""
        booking_annotation = Annotation.objects.create(
            annotation="Booking details",
            annotation_type="booking",
            owner=self.dual_role_user,
        )

        user_booking = InstrumentJobAnnotation.objects.create(
            instrument_job=self.job_dual_role,
            annotation=booking_annotation,
            role="user",
        )

        self.assertEqual(user_booking.role, "user")
        self.assertEqual(user_booking.annotation.annotation_type, "booking")
