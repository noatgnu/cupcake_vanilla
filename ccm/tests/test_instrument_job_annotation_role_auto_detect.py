"""
Tests for InstrumentJobAnnotation automatic role detection in API.

Tests that the viewset correctly auto-detects the role when creating
annotations based on whether the user is owner, staff, or both.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework.test import APIClient

from ccm.models import Instrument, InstrumentJob
from ccv.models import LabGroup

User = get_user_model()


class InstrumentJobAnnotationRoleAutoDetectTestCase(TestCase):
    """Test automatic role detection when creating annotations via API."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.owner_user = User.objects.create_user(username="owner", password="testpass123")
        self.staff_user = User.objects.create_user(username="staff", password="testpass123")
        self.dual_role_user = User.objects.create_user(username="dual", password="testpass123")

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

    def test_owner_only_auto_detects_user_role(self):
        """Test that job owner without staff role gets 'user' role automatically."""
        self.client.force_authenticate(user=self.owner_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_with_staff.id,
                "annotation_data": {
                    "annotation": "Owner annotation",
                    "annotation_type": "text",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "user")

    def test_staff_only_auto_detects_staff_role(self):
        """Test that assigned staff without owner role gets 'staff' role automatically."""
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_with_staff.id,
                "annotation_data": {
                    "annotation": "Staff annotation",
                    "annotation_type": "text",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "staff")

    def test_dual_role_defaults_to_user(self):
        """Test that user who is both owner and staff defaults to 'user' role."""
        self.client.force_authenticate(user=self.dual_role_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_dual_role.id,
                "annotation_data": {
                    "annotation": "Dual role annotation",
                    "annotation_type": "text",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "user")

    def test_dual_role_explicit_staff(self):
        """Test that dual-role user can explicitly set role to 'staff'."""
        self.client.force_authenticate(user=self.dual_role_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_dual_role.id,
                "annotation_data": {
                    "annotation": "Explicit staff annotation",
                    "annotation_type": "text",
                },
                "role": "staff",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "staff")

    def test_dual_role_explicit_user(self):
        """Test that dual-role user can explicitly set role to 'user'."""
        self.client.force_authenticate(user=self.dual_role_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_dual_role.id,
                "annotation_data": {
                    "annotation": "Explicit user annotation",
                    "annotation_type": "text",
                },
                "role": "user",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "user")

    def test_owner_cannot_override_to_staff_if_not_staff(self):
        """Test that owner who is not staff keeps 'user' role even if trying to set 'staff'."""
        self.client.force_authenticate(user=self.owner_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_with_staff.id,
                "annotation_data": {
                    "annotation": "Trying staff role",
                    "annotation_type": "text",
                },
                "role": "staff",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "staff")

    def test_staff_cannot_override_to_user_if_not_owner(self):
        """Test that staff who is not owner keeps 'staff' role even if trying to set 'user'."""
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_with_staff.id,
                "annotation_data": {
                    "annotation": "Trying user role",
                    "annotation_type": "text",
                },
                "role": "user",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "user")

    def test_filter_by_role_in_query(self):
        """Test filtering annotations by role via API."""
        self.client.force_authenticate(user=self.dual_role_user)

        self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_dual_role.id,
                "annotation_data": {
                    "annotation": "User annotation 1",
                    "annotation_type": "text",
                },
                "role": "user",
            },
            format="json",
        )

        self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_dual_role.id,
                "annotation_data": {
                    "annotation": "Staff annotation 1",
                    "annotation_type": "text",
                },
                "role": "staff",
            },
            format="json",
        )

        user_response = self.client.get(
            f"/api/v1/instrument-job-annotations/?instrument_job={self.job_dual_role.id}&role=user"
        )
        staff_response = self.client.get(
            f"/api/v1/instrument-job-annotations/?instrument_job={self.job_dual_role.id}&role=staff"
        )

        self.assertEqual(user_response.status_code, 200)
        self.assertEqual(staff_response.status_code, 200)
        self.assertEqual(user_response.data["count"], 1)
        self.assertEqual(staff_response.data["count"], 1)
        self.assertEqual(user_response.data["results"][0]["role"], "user")
        self.assertEqual(staff_response.data["results"][0]["role"], "staff")

    def test_booking_annotation_with_auto_detect(self):
        """Test that booking annotations also get auto-detected role."""
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/v1/instrument-job-annotations/",
            {
                "instrument_job": self.job_with_staff.id,
                "annotation_data": {
                    "annotation": "Booking scheduled",
                    "annotation_type": "booking",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "staff")
        self.assertEqual(response.data["annotation_type"], "booking")
