"""
CCRV (Red Velvet) Integration Tests.

Tests for integration with the broader CUPCAKE system and AbstractResource.
"""

import uuid
from unittest import skip
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import RemoteHost
from ccrv.models import Project, ProtocolModel, ProtocolRating, ProtocolSection, ProtocolStep, Session
from tests.factories import UserFactory

User = get_user_model()


class AbstractResourceIntegrationTests(TestCase):
    """Test integration with AbstractResource from CCC."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.other_user = UserFactory.create_user(username="other_user")

    def test_project_owner_field_integration(self):
        """Test Project integrates properly with AbstractResource owner field."""
        project = Project.objects.create(
            project_name="Test Project", project_description="Testing AbstractResource integration", owner=self.user
        )

        # Test owner field from AbstractResource
        self.assertEqual(project.owner, self.user)

        # Test timestamps from AbstractResource
        self.assertIsNotNone(project.created_at)
        self.assertIsNotNone(project.updated_at)

    def test_protocol_owner_field_integration(self):
        """Test ProtocolModel integrates properly with AbstractResource."""
        protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol", protocol_description="Testing AbstractResource integration", owner=self.user
        )

        # Test owner field from AbstractResource
        self.assertEqual(protocol.owner, self.user)

        # Test original collaboration fields still work
        protocol.editors.add(self.other_user)
        self.assertIn(self.other_user, protocol.editors.all())

    def test_session_owner_field_integration(self):
        """Test Session integrates properly with AbstractResource."""
        session = Session.objects.create(name="Test Session", owner=self.user, unique_id=uuid.uuid4())

        # Test owner field from AbstractResource
        self.assertEqual(session.owner, self.user)

        # Test original fields still work
        self.assertIsNotNone(session.unique_id)
        self.assertFalse(session.enabled)  # Default value

    def test_abstractresource_queryset_filtering(self):
        """Test that AbstractResource queryset filtering would work."""
        # Create projects for different users
        user1_project = Project.objects.create(project_name="User 1 Project", owner=self.user)

        user2_project = Project.objects.create(project_name="User 2 Project", owner=self.other_user)

        # Test filtering by owner (simulating what permissions would do)
        user1_projects = Project.objects.filter(owner=self.user)
        user2_projects = Project.objects.filter(owner=self.other_user)

        self.assertIn(user1_project, user1_projects)
        self.assertNotIn(user2_project, user1_projects)
        self.assertIn(user2_project, user2_projects)
        self.assertNotIn(user1_project, user2_projects)


class DistributedSystemIntegrationTests(TestCase):
    """Test integration with distributed system features."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.remote_host = RemoteHost.objects.create(
            host_name="remote.example.com",
            host_port=443,
            host_protocol="https",
            host_description="Remote Host for testing",
        )

    def test_project_remote_integration(self):
        """Test Project integration with remote system."""
        project = Project.objects.create(
            project_name="Remote Project", owner=self.user, remote_id=12345, remote_host=self.remote_host
        )

        self.assertEqual(project.remote_id, 12345)
        self.assertEqual(project.remote_host, self.remote_host)

        # Test reverse relationship
        self.assertIn(project, self.remote_host.projects.all())

    def test_protocol_remote_integration(self):
        """Test ProtocolModel integration with remote system."""
        protocol = ProtocolModel.objects.create(
            protocol_title="Remote Protocol", owner=self.user, remote_id=67890, remote_host=self.remote_host
        )

        self.assertEqual(protocol.remote_id, 67890)
        self.assertEqual(protocol.remote_host, self.remote_host)

        # Test reverse relationship
        self.assertIn(protocol, self.remote_host.protocols.all())

    def test_vaulting_system_integration(self):
        """Test vaulting system integration for imported data."""
        # Create vaulted project (imported)
        vaulted_project = Project.objects.create(
            project_name="[IMPORTED] Project from Remote",
            owner=self.user,
            is_vaulted=True,
            remote_id=999,
            remote_host=self.remote_host,
        )

        self.assertTrue(vaulted_project.is_vaulted)

        # Create vaulted protocol
        vaulted_protocol = ProtocolModel.objects.create(
            protocol_title="[IMPORTED] Protocol from Remote",
            owner=self.user,
            is_vaulted=True,
            remote_id=888,
            remote_host=self.remote_host,
        )

        self.assertTrue(vaulted_protocol.is_vaulted)

        # Test filtering vaulted items
        vaulted_projects = Project.objects.filter(is_vaulted=True)
        vaulted_protocols = ProtocolModel.objects.filter(is_vaulted=True)

        self.assertIn(vaulted_project, vaulted_projects)
        self.assertIn(vaulted_protocol, vaulted_protocols)


class ProtocolsIOIntegrationTests(TestCase):
    """Test protocols.io integration functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()

    @skip("Skipping protocols.io integration test as requested")
    @patch("requests.get")
    def test_create_protocol_from_url_success(self, mock_get):
        """Test successful protocol import from protocols.io."""
        # Mock the initial page request
        mock_initial_response = Mock()
        mock_initial_response.content = """
        <html>
        <head>
        <meta property="og:url" content="https://protocols.io/view/test-protocol-abc123" />
        </head>
        </html>
        """

        # Mock the API response
        mock_api_response = Mock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "protocol": {
                "id": 12345,
                "created_on": 1640995200,  # Unix timestamp
                "doi": "10.17504/protocols.io.test",
                "title": "Test Protocol from protocols.io",
                "description": "A test protocol imported from protocols.io",
            }
        }

        # Configure mock to return different responses for different URLs
        def mock_get_side_effect(url, headers=None):
            if "protocols.io/api/v3" in url:
                return mock_api_response
            else:
                return mock_initial_response

        mock_get.side_effect = mock_get_side_effect

        # Test the import
        with patch("ccrv.models.settings.PROTOCOLS_IO_ACCESS_TOKEN", "test-token"):
            protocol = ProtocolModel.create_protocol_from_url("https://protocols.io/view/test-protocol")

        self.assertIsNotNone(protocol)
        self.assertEqual(protocol.protocol_title, "Test Protocol from protocols.io")
        self.assertEqual(protocol.protocol_id, 12345)

    @skip("Skipping protocols.io integration test as requested")
    @patch("requests.get")
    def test_create_protocol_from_url_failure(self, mock_get):
        """Test failed protocol import from protocols.io."""
        # Mock failed API response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        # Test the import failure
        with self.assertRaises(ValueError):
            ProtocolModel.create_protocol_from_url("https://protocols.io/view/nonexistent")


class SessionImportTrackingTests(TestCase):
    """Test session import tracking functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()

    def test_is_imported_property(self):
        """Test session import detection."""
        # Regular session
        regular_session = Session.objects.create(name="Regular Session", owner=self.user, unique_id=uuid.uuid4())

        # Imported session
        imported_session = Session.objects.create(
            name="[IMPORTED] Session from Old System", owner=self.user, unique_id=uuid.uuid4()
        )

        self.assertFalse(regular_session.is_imported)
        self.assertTrue(imported_session.is_imported)

    def test_import_source_info_property(self):
        """Test import source info property."""
        session = Session.objects.create(name="[IMPORTED] Test Session", owner=self.user, unique_id=uuid.uuid4())

        # Since ImportedObject might not exist in this context,
        # the property should return None gracefully
        import_info = session.import_source_info
        self.assertIsNone(import_info)  # Should handle missing dependency gracefully


class LinkedListNavigationTests(TestCase):
    """Test complex linked-list navigation functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Navigation Test Protocol", owner=self.user)
        self.section = ProtocolSection.objects.create(
            protocol=self.protocol, section_description="Navigation Test Section"
        )

    def test_complex_step_sequence(self):
        """Test complex step sequence with linked-list navigation."""
        # Create a sequence of steps: step1 -> step2 -> step3
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="First step", previous_step=None
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", previous_step=step1
        )

        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Third step", previous_step=step2
        )

        # Test forward navigation
        self.assertIn(step2, step1.next_step.all())
        self.assertIn(step3, step2.next_step.all())

        # Test backward navigation
        self.assertEqual(step2.previous_step, step1)
        self.assertEqual(step3.previous_step, step2)

        # Test section navigation methods
        first_step = self.section.get_first_in_section()
        self.assertEqual(first_step, step1)

        # Test ordered step retrieval
        ordered_steps = self.section.get_step_in_order()
        expected_order = [step1, step2, step3]
        self.assertEqual(ordered_steps, expected_order)

    def test_step_branching_scenario(self):
        """Test step branching functionality."""
        main_step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Main protocol step"
        )

        # Create branch step
        branch_step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_section=self.section,
            step_description="Alternative branch step",
            original=False,
            branch_from=main_step,
        )

        self.assertEqual(branch_step.branch_from, main_step)
        self.assertFalse(branch_step.original)
        self.assertIn(branch_step, main_step.branch_steps.all())

    def test_step_deletion_chain_update(self):
        """Test that step deletion properly updates the linked list."""
        # Create chain: A -> B -> C
        stepA = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step A"
        )

        stepB = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step B", previous_step=stepA
        )

        stepC = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step C", previous_step=stepB
        )

        # Delete middle step B
        stepB.delete()

        # Refresh stepC from database
        stepC.refresh_from_db()

        # stepC should now point to stepA
        self.assertEqual(stepC.previous_step, stepA)
        self.assertIn(stepC, stepA.next_step.all())


class RatingAggregationTests(TestCase):
    """Test rating aggregation functionality."""

    def setUp(self):
        """Set up test data."""
        self.user1 = UserFactory.create_user(username="user1")
        self.user2 = UserFactory.create_user(username="user2")
        self.user3 = UserFactory.create_user(username="user3")

        self.protocol = ProtocolModel.objects.create(protocol_title="Rated Protocol", owner=self.user1)

    def test_protocol_rating_aggregation(self):
        """Test protocol rating aggregation calculations."""
        # Create multiple ratings
        ProtocolRating.objects.create(protocol=self.protocol, user=self.user1, complexity_rating=5, duration_rating=6)

        ProtocolRating.objects.create(protocol=self.protocol, user=self.user2, complexity_rating=7, duration_rating=8)

        ProtocolRating.objects.create(protocol=self.protocol, user=self.user3, complexity_rating=3, duration_rating=4)

        # Calculate averages (should be done in serializer)
        ratings = self.protocol.ratings.all()
        avg_complexity = sum(r.complexity_rating for r in ratings) / ratings.count()
        avg_duration = sum(r.duration_rating for r in ratings) / ratings.count()

        self.assertEqual(avg_complexity, 5.0)  # (5+7+3)/3
        self.assertEqual(avg_duration, 6.0)  # (6+8+4)/3

    def test_protocol_with_no_ratings(self):
        """Test protocol with no ratings handles gracefully."""
        protocol_no_ratings = ProtocolModel.objects.create(protocol_title="Unrated Protocol", owner=self.user1)

        ratings = protocol_no_ratings.ratings.all()
        self.assertEqual(ratings.count(), 0)

        # Should handle division by zero gracefully in serializer


class ProtocolOrderingTests(TestCase):
    """Test protocol step ordering functionality during import."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()

    def test_protocol_step_order_assignment(self):
        """Test that protocol steps get proper order values after import simulation."""
        # Create a protocol similar to what would come from protocols.io
        protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol with Steps", protocol_description="Testing step ordering", owner=self.user
        )

        # Create steps in linked-list structure (simulating protocols.io import)
        step1 = ProtocolStep.objects.create(
            protocol=protocol, step_description="First step", previous_step=None, order=0  # Initially no order assigned
        )

        step2 = ProtocolStep.objects.create(
            protocol=protocol,
            step_description="Second step",
            previous_step=step1,
            order=0,  # Initially no order assigned
        )

        step3 = ProtocolStep.objects.create(
            protocol=protocol,
            step_description="Third step",
            previous_step=step2,
            order=0,  # Initially no order assigned
        )

        # Simulate the order assignment that happens after protocols.io import
        root_steps = ProtocolStep.objects.filter(
            protocol=protocol, step_section__isnull=True, previous_step__isnull=True
        )

        order = 0
        for root_step in root_steps:
            order = ProtocolStep._traverse_and_order(root_step, order)

        # Verify that steps now have proper order values
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        self.assertEqual(step1.order, 0)
        self.assertEqual(step2.order, 1)
        self.assertEqual(step3.order, 2)

    def test_protocol_step_order_with_sections(self):
        """Test that protocol steps get proper order values within sections."""
        protocol = ProtocolModel.objects.create(protocol_title="Test Protocol with Sections", owner=self.user)

        # Create a section
        section = ProtocolSection.objects.create(protocol=protocol, section_description="Test Section")

        # Create steps within the section
        section_step1 = ProtocolStep.objects.create(
            protocol=protocol, step_section=section, step_description="Section step 1", previous_step=None, order=0
        )

        section_step2 = ProtocolStep.objects.create(
            protocol=protocol,
            step_section=section,
            step_description="Section step 2",
            previous_step=section_step1,
            order=0,
        )

        # Also create a root step (no section)
        root_step = ProtocolStep.objects.create(
            protocol=protocol, step_description="Root step", previous_step=None, order=0
        )

        # Simulate the order assignment for both root steps and section steps
        # Handle root steps first
        root_steps = ProtocolStep.objects.filter(
            protocol=protocol, step_section__isnull=True, previous_step__isnull=True
        )

        order = 0
        for root_step in root_steps:
            order = ProtocolStep._traverse_and_order(root_step, order)

        # Handle sections
        sections = protocol.sections.all().order_by("id")
        for section in sections:
            section_root_steps = ProtocolStep.objects.filter(step_section=section, previous_step__isnull=True)

            section_order = 0
            for root_step in section_root_steps:
                section_order = ProtocolStep._traverse_and_order(root_step, section_order, section_context=True)

        # Verify order assignment
        root_step.refresh_from_db()
        section_step1.refresh_from_db()
        section_step2.refresh_from_db()

        self.assertEqual(root_step.order, 0)  # Root step gets order 0
        self.assertEqual(section_step1.order, 0)  # Section step 1 gets order 0 within section
        self.assertEqual(section_step2.order, 1)  # Section step 2 gets order 1 within section

    def test_empty_protocol_order_assignment(self):
        """Test that empty protocols handle order assignment gracefully."""
        protocol = ProtocolModel.objects.create(protocol_title="Empty Protocol", owner=self.user)

        # Simulate order assignment on empty protocol (should not crash)
        root_steps = ProtocolStep.objects.filter(
            protocol=protocol, step_section__isnull=True, previous_step__isnull=True
        )

        order = 0
        for root_step in root_steps:
            order = ProtocolStep._traverse_and_order(root_step, order)

        # Should complete without error
        self.assertEqual(order, 0)  # No steps processed
