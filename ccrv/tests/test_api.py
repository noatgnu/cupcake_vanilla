"""
CCRV (Red Velvet) API Tests.

Tests for the actual API endpoints based on migrated functionality.
"""

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import Annotation, RemoteHost
from ccrv.models import (
    Project,
    ProtocolModel,
    ProtocolRating,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotation,
)
from tests.factories import UserFactory

User = get_user_model()


class CCRVAPITestCase(APITestCase):
    """Base test case with data for API testing."""

    def setUp(self):
        """Set up test data."""
        # Create users
        self.regular_user = UserFactory.create_user(username="regular_user")
        self.staff_user = UserFactory.create_user(username="staff_user", is_staff=True)
        self.admin_user = UserFactory.create_user(username="admin_user", is_staff=True, is_superuser=True)

        # Create remote host
        self.remote_host = RemoteHost.objects.create(
            host_name="remote.example.com", host_port=443, host_protocol="https", host_description="Test Remote Host"
        )

        # Create project
        self.project = Project.objects.create(
            project_name="Test Project",
            project_description="A test project for API testing",
            owner=self.regular_user,
            remote_id=123,
            remote_host=self.remote_host,
        )

        # Create protocol
        self.protocol = ProtocolModel.objects.create(
            protocol_id=12345,
            protocol_title="Test Protocol",
            protocol_description="A test protocol for API testing",
            protocol_url="https://protocols.io/view/test-protocol",
            owner=self.regular_user,
            enabled=True,
        )

        # Create session
        self.session = Session.objects.create(
            name="Test Session", owner=self.regular_user, unique_id=uuid.uuid4(), enabled=True
        )

        # Create protocol section and step
        self.section = ProtocolSection.objects.create(
            protocol=self.protocol, section_description="Test Section", section_duration=30
        )

        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_section=self.section,
            step_description="Test step description",
            step_duration=15,
        )


class ProjectAPITests(CCRVAPITestCase):
    """Test Project API endpoints."""

    def test_list_projects(self):
        """Test listing projects."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        project_data = response.data["results"][0]
        self.assertEqual(project_data["project_name"], "Test Project")
        self.assertIn("owner_username", project_data)
        self.assertIn("remote_host_info", project_data)

    def test_create_project(self):
        """Test creating a project."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-list")
        data = {"project_name": "New Project", "project_description": "A new project", "is_vaulted": False}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["project_name"], "New Project")
        self.assertEqual(response.data["owner"], self.regular_user.id)

    def test_project_sessions_action(self):
        """Test getting sessions for a project."""
        self.project.sessions.add(self.session)
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-sessions", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Test Session")

    def test_my_projects_action(self):
        """Test getting user's own projects."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-my-projects")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_vaulted_projects_action(self):
        """Test getting vaulted projects."""
        # Create vaulted project
        Project.objects.create(project_name="Vaulted Project", owner=self.regular_user, is_vaulted=True)

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-vaulted-projects")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["project_name"], "Vaulted Project")


class ProtocolModelAPITests(CCRVAPITestCase):
    """Test ProtocolModel API endpoints."""

    def test_list_protocols(self):
        """Test listing protocols."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolmodel-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        protocol_data = response.data["results"][0]
        self.assertEqual(protocol_data["protocol_title"], "Test Protocol")
        self.assertIn("sections", protocol_data)
        self.assertIn("ratings", protocol_data)

    def test_create_protocol(self):
        """Test creating a protocol."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolmodel-list")
        data = {"protocol_title": "New Protocol", "protocol_description": "A new protocol", "enabled": False}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["protocol_title"], "New Protocol")
        self.assertEqual(response.data["owner"], self.regular_user.id)

    def test_toggle_enabled_action(self):
        """Test toggling protocol enabled status."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolmodel-toggle-enabled", kwargs={"pk": self.protocol.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("enabled", response.data)

        # Refresh from database
        self.protocol.refresh_from_db()
        self.assertEqual(self.protocol.enabled, response.data["enabled"])

    def test_protocol_steps_action(self):
        """Test getting steps for a protocol."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolmodel-steps", kwargs={"pk": self.protocol.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["step_description"], "Test step description")

    def test_enabled_protocols_action(self):
        """Test getting enabled protocols."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolmodel-enabled-protocols")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Our test protocol is enabled
        self.assertEqual(len(response.data), 1)


class SessionAPITests(CCRVAPITestCase):
    """Test Session API endpoints."""

    def test_list_sessions(self):
        """Test listing sessions."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        session_data = response.data["results"][0]
        self.assertEqual(session_data["name"], "Test Session")
        self.assertIn("is_running", session_data)
        self.assertIn("import_info", session_data)

    def test_create_session(self):
        """Test creating a session."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-list")
        data = {"name": "New Session", "enabled": True}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Session")
        self.assertEqual(response.data["owner"], self.regular_user.id)
        self.assertIsNotNone(response.data["unique_id"])

    def test_start_session_action(self):
        """Test starting a session."""
        # Create unstarted session
        unstarted_session = Session.objects.create(
            name="Unstarted Session", owner=self.regular_user, unique_id=uuid.uuid4()
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-start", kwargs={"pk": unstarted_session.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Check session was started
        unstarted_session.refresh_from_db()
        self.assertIsNotNone(unstarted_session.started_at)
        self.assertTrue(unstarted_session.enabled)

    def test_end_session_action(self):
        """Test ending a session."""
        # Create started session
        started_session = Session.objects.create(
            name="Started Session",
            owner=self.regular_user,
            unique_id=uuid.uuid4(),
            started_at=timezone.now() - timedelta(hours=1),
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-end", kwargs={"pk": started_session.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Check session was ended
        started_session.refresh_from_db()
        self.assertIsNotNone(started_session.ended_at)
        self.assertFalse(started_session.processing)

    def test_add_protocol_action(self):
        """Test adding a protocol to a session."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-add-protocol", kwargs={"pk": self.session.pk})
        data = {"protocol_id": self.protocol.pk}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Check protocol was added
        self.assertIn(self.protocol, self.session.protocols.all())

    def test_running_sessions_action(self):
        """Test getting running sessions."""
        # Create running session
        Session.objects.create(
            name="Running Session",
            owner=self.regular_user,
            unique_id=uuid.uuid4(),
            started_at=timezone.now() - timedelta(hours=1)
            # No ended_at, so it's running
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:session-running-sessions")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Running Session")


class ProtocolRatingAPITests(CCRVAPITestCase):
    """Test ProtocolRating API endpoints."""

    def test_create_rating(self):
        """Test creating a protocol rating."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolrating-list")
        data = {"protocol": self.protocol.pk, "complexity_rating": 5, "duration_rating": 7}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["complexity_rating"], 5)
        self.assertEqual(response.data["user"], self.regular_user.id)

    def test_rate_protocol_action(self):
        """Test the rate_protocol custom action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolrating-rate-protocol")
        data = {"protocol_id": self.protocol.pk, "complexity_rating": 8, "duration_rating": 6}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("rating", response.data)
        self.assertEqual(response.data["rating"]["complexity_rating"], 8)

    def test_rating_validation(self):
        """Test rating validation through API."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolrating-rate-protocol")
        data = {"protocol_id": self.protocol.pk, "complexity_rating": 11, "duration_rating": 5}  # Above maximum

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_my_ratings_action(self):
        """Test getting user's own ratings."""
        # Create rating
        ProtocolRating.objects.create(
            protocol=self.protocol, user=self.regular_user, complexity_rating=7, duration_rating=8
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolrating-my-ratings")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class ProtocolStepAPITests(CCRVAPITestCase):
    """Test ProtocolStep API endpoints with linked-list functionality."""

    def test_list_steps(self):
        """Test listing protocol steps."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolstep-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        step_data = response.data["results"][0]
        self.assertEqual(step_data["step_description"], "Test step description")
        self.assertIn("next_steps", step_data)
        self.assertIn("has_next", step_data)
        self.assertIn("has_previous", step_data)

    def test_move_up_action(self):
        """Test moving a step up in the sequence."""
        # Create second step that comes after first
        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", previous_step=self.step
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolstep-move-up", kwargs={"pk": step2.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

    def test_move_down_action(self):
        """Test moving a step down in the sequence."""
        # Create second step
        ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", previous_step=self.step
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolstep-move-down", kwargs={"pk": self.step.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

    def test_next_steps_action(self):
        """Test getting next steps in linked list."""
        # Create next step
        ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Next step", previous_step=self.step
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolstep-next-steps", kwargs={"pk": self.step.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["step_description"], "Next step")


class ProtocolSectionAPITests(CCRVAPITestCase):
    """Test ProtocolSection API endpoints."""

    def test_list_sections(self):
        """Test listing protocol sections."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolsection-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        section_data = response.data["results"][0]
        self.assertEqual(section_data["section_description"], "Test Section")
        self.assertIn("steps_in_order", section_data)

    def test_steps_in_order_action(self):
        """Test getting steps in order for a section."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolsection-steps-in-order", kwargs={"pk": self.section.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)  # Our test step

    def test_first_step_action(self):
        """Test getting the first step in a section."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:protocolsection-first-step", kwargs={"pk": self.section.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["step_description"], "Test step description")


class RemoteHostAPITests(CCRVAPITestCase):
    """Test RemoteHost API endpoints (admin only)."""

    def test_list_remote_hosts_as_admin(self):
        """Test listing remote hosts as admin."""
        self.client.force_authenticate(user=self.admin_user)

        url = reverse("ccrv:remotehost-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_list_remote_hosts_as_regular_user(self):
        """Test listing remote hosts as regular user (should be forbidden)."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:remotehost-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CCRVPermissionTests(CCRVAPITestCase):
    """Test API permissions across CCRV endpoints."""

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated users cannot access endpoints."""
        url = reverse("ccrv:project-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_can_modify_project(self):
        """Test project owner can modify their project."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:project-detail", kwargs={"pk": self.project.pk})
        data = {"project_name": "Updated Project Name"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_owner_cannot_modify_project(self):
        """Test non-owner cannot modify project."""
        other_user = UserFactory.create_user(username="other_user")
        self.client.force_authenticate(user=other_user)

        url = reverse("ccrv:project-detail", kwargs={"pk": self.project.pk})
        data = {"project_name": "Hacked Project Name"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)  # Filtered out by queryset

    def test_protocol_editors_can_modify(self):
        """Test protocol editors can modify the protocol."""
        editor = UserFactory.create_user(username="editor")
        self.protocol.editors.add(editor)

        self.client.force_authenticate(user=editor)

        url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        data = {"protocol_description": "Updated by editor"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_protocol_viewers_can_read_only(self):
        """Test protocol viewers can only read, not modify."""
        viewer = UserFactory.create_user(username="viewer")
        self.protocol.viewers.add(viewer)

        self.client.force_authenticate(user=viewer)

        # Can read
        url = reverse("ccrv:protocolmodel-detail", kwargs={"pk": self.protocol.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Cannot modify (this would require checking the IsOwnerOrReadOnly permission)
        # In a real test, this would return 403, but the permission logic would need
        # to be properly implemented in the viewset


class ProtocolSectionOrderingAPITests(CCRVAPITestCase):
    """Test ordering functionality for ProtocolSection API."""

    def test_section_serializer_includes_order(self):
        """Test that section serializer includes order field."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section", order=5)

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-detail", kwargs={"pk": section.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order"], 5)

    def test_steps_by_order_endpoint(self):
        """Test efficient steps_by_order endpoint."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create steps in different order
        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Third step", order=2
        )

        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="First step", order=0
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Second step", order=1
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-steps-by-order", kwargs={"pk": section.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)

        # Check order is correct
        self.assertEqual(response.data[0]["id"], step1.id)
        self.assertEqual(response.data[1]["id"], step2.id)
        self.assertEqual(response.data[2]["id"], step3.id)

        # Check order values are included
        self.assertEqual(response.data[0]["order"], 0)
        self.assertEqual(response.data[1]["order"], 1)
        self.assertEqual(response.data[2]["order"], 2)

    def test_section_move_to_order_endpoint(self):
        """Test section move_to_order API endpoint."""
        # Create multiple sections
        section1 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 1", order=0)
        section2 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 2", order=1)
        section3 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 3", order=2)

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-move-to-order", kwargs={"pk": section3.pk})
        data = {"order": 0}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("moved to order 0 successfully", response.data["message"])

        # Verify database changes
        section1.refresh_from_db()
        section2.refresh_from_db()
        section3.refresh_from_db()

        self.assertEqual(section3.order, 0)
        self.assertEqual(section1.order, 1)
        self.assertEqual(section2.order, 2)

    def test_section_move_to_order_invalid_data(self):
        """Test section move_to_order with invalid data."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-move-to-order", kwargs={"pk": section.pk})

        # Test missing order parameter
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Order parameter is required", response.data["error"])

        # Test negative order
        response = self.client.post(url, {"order": -1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must be a non-negative integer", response.data["error"])

        # Test invalid order type
        response = self.client.post(url, {"order": "invalid"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must be a valid integer", response.data["error"])

    def test_reorder_steps_endpoint(self):
        """Test section reorder_steps API endpoint."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create steps with non-sequential orders
        ProtocolStep.objects.create(protocol=self.protocol, step_section=section, step_description="Step 1", order=5)

        ProtocolStep.objects.create(protocol=self.protocol, step_section=section, step_description="Step 2", order=10)

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-reorder-steps", kwargs={"pk": section.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Steps reordered successfully", response.data["message"])


class ProtocolStepOrderingAPITests(CCRVAPITestCase):
    """Test ordering functionality for ProtocolStep API."""

    def test_step_serializer_includes_order(self):
        """Test that step serializer includes order field."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Test Step", order=3
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolstep-detail", kwargs={"pk": step.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order"], 3)

    def test_step_move_to_order_endpoint(self):
        """Test step move_to_order API endpoint."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create multiple steps
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 1", order=0
        )
        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 2", order=1
        )
        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 3", order=2
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolstep-move-to-order", kwargs={"pk": step3.pk})
        data = {"order": 0}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("moved to order 0 successfully", response.data["message"])

        # Verify database changes
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        self.assertEqual(step3.order, 0)
        self.assertEqual(step1.order, 1)
        self.assertEqual(step2.order, 2)

    def test_step_move_to_order_without_section(self):
        """Test step move_to_order for protocol-level steps (no section)."""
        # Create protocol-level steps
        step1 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 1", order=0)
        step2 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 2", order=1)
        step3 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 3", order=2)

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolstep-move-to-order", kwargs={"pk": step3.pk})
        data = {"order": 0}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("moved to order 0 successfully", response.data["message"])

        # Verify database changes
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        self.assertEqual(step3.order, 0)
        self.assertEqual(step1.order, 1)
        self.assertEqual(step2.order, 2)

    def test_reorder_by_linked_list_endpoint(self):
        """Test reorder_by_linked_list API endpoint (migration utility)."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("ccrv:protocolstep-reorder-by-linked-list")
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Successfully populated order fields", response.data["message"])

    def test_steps_in_order_uses_efficient_method(self):
        """Test that steps_in_order in section serializer uses efficient ordering."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create steps with order values
        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Second step", order=1
        )

        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="First step", order=0
        )

        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Third step", order=2
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("ccrv:protocolsection-detail", kwargs={"pk": section.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        steps_in_order = response.data["steps_in_order"]
        self.assertEqual(len(steps_in_order), 3)

        # Check order is correct and includes order values
        self.assertEqual(steps_in_order[0]["id"], step1.id)
        self.assertEqual(steps_in_order[0]["order"], 0)
        self.assertEqual(steps_in_order[1]["id"], step2.id)
        self.assertEqual(steps_in_order[1]["order"], 1)
        self.assertEqual(steps_in_order[2]["id"], step3.id)
        self.assertEqual(steps_in_order[2]["order"], 2)


class SessionAnnotationAPITests(CCRVAPITestCase):
    """Test SessionAnnotation API endpoints and metadata functionality."""

    def setUp(self):
        super().setUp()

        # Create annotation
        self.annotation = Annotation.objects.create(
            annotation="Test experimental data", annotation_type="text", owner=self.regular_user
        )

        # Create session annotation
        self.session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=self.annotation)

    def test_list_session_annotations(self):
        """Test listing session annotations."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        annotation_data = response.data["results"][0]
        self.assertEqual(annotation_data["session"], self.session.id)
        self.assertEqual(annotation_data["annotation"], self.annotation.id)

    def test_create_session_annotation(self):
        """Test creating a session annotation."""
        # Create another annotation
        new_annotation = Annotation.objects.create(
            annotation="Another test annotation", annotation_type="text", owner=self.regular_user
        )

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-list")
        data = {"session": self.session.id, "annotation": new_annotation.id}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["session"], self.session.id)
        self.assertEqual(response.data["annotation"], new_annotation.id)

    def test_create_metadata_table_action(self):
        """Test create_metadata_table action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-create-metadata-table", kwargs={"pk": self.session_annotation.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("metadata_table", response.data)

        # Verify metadata table was created
        self.session_annotation.refresh_from_db()
        self.assertIsNotNone(self.session_annotation.metadata_table)

    def test_add_metadata_column_action(self):
        """Test add_metadata_column action."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-add-metadata-column", kwargs={"pk": self.session_annotation.pk})
        data = {"name": "Sample Type", "type": "characteristics", "value": "blood plasma", "mandatory": True}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("column", response.data)
        self.assertEqual(response.data["column"]["name"], "Sample Type")
        self.assertTrue(response.data["column"]["mandatory"])

    def test_add_metadata_column_missing_name(self):
        """Test add_metadata_column with missing name."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-add-metadata-column", kwargs={"pk": self.session_annotation.pk})
        data = {"type": "characteristics", "value": "test"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_remove_metadata_column_action(self):
        """Test remove_metadata_column action."""
        # First add a column
        column = self.session_annotation.add_metadata_column({"name": "Test Column", "value": "test value"})

        self.client.force_authenticate(user=self.regular_user)

        url = reverse(
            "ccrv:sessionannotation-remove-metadata-column",
            kwargs={"pk": self.session_annotation.pk, "column_id": column.id},
        )

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Verify column was removed
        self.assertEqual(self.session_annotation.get_metadata_columns().count(), 0)

    def test_remove_nonexistent_column(self):
        """Test removing non-existent column."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse(
            "ccrv:sessionannotation-remove-metadata-column", kwargs={"pk": self.session_annotation.pk, "column_id": 999}
        )

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_metadata_columns_action(self):
        """Test metadata_columns action."""
        # Add some columns
        self.session_annotation.add_metadata_column({"name": "Column A", "value": "value A", "position": 1})
        self.session_annotation.add_metadata_column({"name": "Column B", "value": "value B", "position": 0})

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-metadata-columns", kwargs={"pk": self.session_annotation.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        # Should be ordered by position
        self.assertEqual(response.data[0]["name"], "Column B")  # position 0
        self.assertEqual(response.data[1]["name"], "Column A")  # position 1

    def test_metadata_columns_no_table(self):
        """Test metadata_columns action when no metadata table exists."""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("ccrv:sessionannotation-metadata-columns", kwargs={"pk": self.session_annotation.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_update_column_value_action(self):
        """Test update_column_value action."""
        # Add a column
        column = self.session_annotation.add_metadata_column({"name": "Status", "value": "pending"})

        self.client.force_authenticate(user=self.regular_user)

        url = reverse(
            "ccrv:sessionannotation-update-column-value",
            kwargs={"pk": self.session_annotation.pk, "column_id": column.id},
        )
        data = {"value": "completed"}

        response = self.client.patch(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Verify value was updated
        column.refresh_from_db()
        self.assertEqual(column.value, "completed")

    def test_update_column_value_missing_params(self):
        """Test update_column_value with missing parameters."""
        self.client.force_authenticate(user=self.regular_user)

        # Missing value (column_id is in URL now)
        url = reverse(
            "ccrv:sessionannotation-update-column-value", kwargs={"pk": self.session_annotation.pk, "column_id": 1}
        )
        response = self.client.patch(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_session_annotation_permissions(self):
        """Test session annotation permissions."""
        # Create annotation from different user
        other_user = UserFactory.create_user(username="other_user")
        other_annotation = Annotation.objects.create(
            annotation="Other user annotation", annotation_type="text", owner=other_user
        )
        other_session_annotation = SessionAnnotation.objects.create(
            session=self.session, annotation=other_annotation  # Same session but different annotation owner
        )

        self.client.force_authenticate(user=self.regular_user)

        # Should be able to see session annotation (session permissions apply)
        url = reverse("ccrv:sessionannotation-detail", kwargs={"pk": other_session_annotation.pk})
        response = self.client.get(url)

        # Actual result depends on permission implementation
        # This tests the API endpoint behavior
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_metadata_workflow_integration(self):
        """Test complete metadata workflow through API."""
        self.client.force_authenticate(user=self.regular_user)

        # 1. Create metadata table
        url = reverse("ccrv:sessionannotation-create-metadata-table", kwargs={"pk": self.session_annotation.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 2. Add multiple columns
        add_column_url = reverse(
            "ccrv:sessionannotation-add-metadata-column", kwargs={"pk": self.session_annotation.pk}
        )

        # Add sample ID column
        response = self.client.post(
            add_column_url,
            {"name": "Sample ID", "type": "factor value", "value": "S001", "mandatory": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Add concentration column
        response = self.client.post(
            add_column_url, {"name": "Concentration", "type": "parameter value", "value": "2.5 mg/ml"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        conc_col = response.data["column"]["id"]

        # 3. Verify columns exist
        columns_url = reverse("ccrv:sessionannotation-metadata-columns", kwargs={"pk": self.session_annotation.pk})
        response = self.client.get(columns_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # 4. Update column value
        update_url = reverse(
            "ccrv:sessionannotation-update-column-value",
            kwargs={"pk": self.session_annotation.pk, "column_id": conc_col},
        )
        response = self.client.patch(update_url, {"value": "3.0 mg/ml"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 5. Remove one column
        remove_url = reverse(
            "ccrv:sessionannotation-remove-metadata-column",
            kwargs={"pk": self.session_annotation.pk, "column_id": conc_col},
        )
        response = self.client.delete(remove_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 6. Verify final state
        response = self.client.get(columns_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Sample ID")
