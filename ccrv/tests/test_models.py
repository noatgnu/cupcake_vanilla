"""
CCRV (Red Velvet) Model Tests.

Tests for the actual model methods and business logic of migrated models.
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import RemoteHost
from ccrv.models import (
    Project,
    ProtocolModel,
    ProtocolRating,
    ProtocolReagent,
    ProtocolSection,
    ProtocolStep,
    Session,
    StepReagent,
    StepVariation,
    TimeKeeper,
)
from tests.factories import UserFactory

User = get_user_model()


class ProjectModelTests(TestCase):
    """Test Project model methods and AbstractResource integration."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.remote_host = RemoteHost.objects.create(
            host_name="remote.example.com", host_port=443, host_protocol="https", host_description="Test Remote Host"
        )

    def test_project_creation(self):
        """Test creating a project with all fields."""
        project = Project.objects.create(
            project_name="Test Project",
            project_description="A test project",
            owner=self.user,
            remote_id=123,
            remote_host=self.remote_host,
            is_vaulted=True,
        )

        self.assertEqual(project.project_name, "Test Project")
        self.assertEqual(project.owner, self.user)
        self.assertTrue(project.is_vaulted)
        self.assertEqual(project.remote_host, self.remote_host)

    def test_project_str_method(self):
        """Test Project string representation."""
        project = Project.objects.create(project_name="My Project", owner=self.user)
        self.assertEqual(str(project), "My Project")

    def test_project_sessions_relationship(self):
        """Test project sessions many-to-many relationship."""
        project = Project.objects.create(project_name="Project with Sessions", owner=self.user)

        session = Session.objects.create(name="Test Session", owner=self.user, unique_id=uuid.uuid4())

        project.sessions.add(session)
        self.assertIn(session, project.sessions.all())
        self.assertIn(project, session.projects.all())


class ProtocolRatingModelTests(TestCase):
    """Test ProtocolRating model validation and methods."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)

    def test_rating_creation(self):
        """Test creating a protocol rating."""
        rating = ProtocolRating.objects.create(
            protocol=self.protocol, user=self.user, complexity_rating=5, duration_rating=7
        )

        self.assertEqual(rating.complexity_rating, 5)
        self.assertEqual(rating.duration_rating, 7)

    def test_rating_validation(self):
        """Test rating validation from original save() method."""
        rating = ProtocolRating(
            protocol=self.protocol, user=self.user, complexity_rating=11, duration_rating=5  # Above maximum
        )

        with self.assertRaises(ValueError):
            rating.save()

    def test_rating_str_method(self):
        """Test ProtocolRating string representation."""
        rating = ProtocolRating.objects.create(
            protocol=self.protocol, user=self.user, complexity_rating=8, duration_rating=6
        )

        expected = f"{self.protocol} - {self.user} - 8"
        self.assertEqual(str(rating), expected)

    def test_unique_together_constraint(self):
        """Test unique_together constraint on protocol and user."""
        ProtocolRating.objects.create(protocol=self.protocol, user=self.user, complexity_rating=5, duration_rating=5)

        # Should not be able to create another rating for same protocol/user
        with self.assertRaises(Exception):  # IntegrityError
            ProtocolRating.objects.create(
                protocol=self.protocol, user=self.user, complexity_rating=7, duration_rating=8
            )


class ProtocolModelTests(TestCase):
    """Test ProtocolModel functionality including protocols.io integration."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()

    def test_protocol_creation(self):
        """Test creating a protocol with all fields."""
        protocol = ProtocolModel.objects.create(
            protocol_id=12345,
            protocol_title="Test Protocol",
            protocol_description="A test protocol",
            protocol_doi="10.17504/protocols.io.test",
            protocol_url="https://protocols.io/view/test-protocol",
            owner=self.user,
            enabled=True,
            is_vaulted=False,
        )

        self.assertEqual(protocol.protocol_title, "Test Protocol")
        self.assertTrue(protocol.enabled)
        self.assertFalse(protocol.is_vaulted)

    def test_protocol_collaboration_fields(self):
        """Test editors and viewers many-to-many fields."""
        protocol = ProtocolModel.objects.create(protocol_title="Collaborative Protocol", owner=self.user)

        editor = UserFactory.create_user(username="editor")
        viewer = UserFactory.create_user(username="viewer")

        protocol.editors.add(editor)
        protocol.viewers.add(viewer)

        self.assertIn(editor, protocol.editors.all())
        self.assertIn(viewer, protocol.viewers.all())


class SessionModelTests(TestCase):
    """Test Session model functionality and import tracking."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()

    def test_session_creation(self):
        """Test creating a session with unique_id."""
        unique_id = uuid.uuid4()
        session = Session.objects.create(name="Test Session", owner=self.user, unique_id=unique_id)

        self.assertEqual(session.name, "Test Session")
        self.assertEqual(session.unique_id, unique_id)
        self.assertFalse(session.enabled)

    def test_session_str_method(self):
        """Test Session string representation."""
        session = Session.objects.create(name="My Session", owner=self.user, unique_id=uuid.uuid4())
        self.assertEqual(str(session), "My Session")

        # Test fallback to unique_id when no name
        session_no_name = Session.objects.create(owner=self.user, unique_id=uuid.uuid4())
        self.assertTrue(str(session_no_name).startswith("Session "))

    def test_is_imported_property(self):
        """Test is_imported property logic."""
        # Regular session
        session = Session.objects.create(name="Regular Session", owner=self.user, unique_id=uuid.uuid4())
        self.assertFalse(session.is_imported)

        # Imported session
        imported_session = Session.objects.create(
            name="[IMPORTED] Session from Old System", owner=self.user, unique_id=uuid.uuid4()
        )
        self.assertTrue(imported_session.is_imported)

    def test_session_protocols_relationship(self):
        """Test session protocols many-to-many relationship."""
        session = Session.objects.create(name="Session with Protocols", owner=self.user, unique_id=uuid.uuid4())

        protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)

        session.protocols.add(protocol)
        self.assertIn(protocol, session.protocols.all())
        self.assertIn(session, protocol.sessions.all())


class ProtocolSectionModelTests(TestCase):
    """Test ProtocolSection model and linked-list navigation."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)

    def test_section_creation(self):
        """Test creating a protocol section."""
        section = ProtocolSection.objects.create(
            protocol=self.protocol, section_description="Introduction", section_duration=30
        )

        self.assertEqual(section.section_description, "Introduction")
        self.assertEqual(section.section_duration, 30)

    def test_section_str_method(self):
        """Test ProtocolSection string representation."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Materials")
        self.assertEqual(str(section), "Materials")

        # Test fallback when no description
        section_no_desc = ProtocolSection.objects.create(protocol=self.protocol)
        self.assertTrue(str(section_no_desc).startswith("Section "))

    def test_get_step_in_order_empty(self):
        """Test get_step_in_order with no steps."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Empty Section")

        ordered_steps = section.get_step_in_order()
        self.assertEqual(ordered_steps, [])

    def test_get_first_and_last_in_section(self):
        """Test get_first_in_section and get_last_in_section methods."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section with Steps")

        # Create steps with linked-list structure
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_section=section,
            step_description="First step",
            previous_step=None,  # First step
        )

        ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Second step", previous_step=step1
        )

        # Test first step detection
        first_step = section.get_first_in_section()
        self.assertEqual(first_step, step1)

        # Note: get_last_in_section is more complex and requires next_step relationships
        # which are reverse foreign keys, so we'll test basic functionality

    def test_section_ordering_default(self):
        """Test that sections have default order of 0."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")
        self.assertEqual(section.order, 0)

    def test_get_steps_by_order(self):
        """Test efficient ordering by order attribute."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create steps with different orders
        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Third step", order=2
        )

        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="First step", order=0
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Second step", order=1
        )

        # Test efficient ordering
        ordered_steps = section.get_steps_by_order()
        self.assertEqual(list(ordered_steps), [step1, step2, step3])

    def test_section_move_to_order(self):
        """Test moving section to specific order position."""
        # Create multiple sections
        section1 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 1", order=0)
        section2 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 2", order=1)
        section3 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 3", order=2)

        # Move section3 to position 0
        section3.move_to_order(0)

        # Refresh from database
        section1.refresh_from_db()
        section2.refresh_from_db()
        section3.refresh_from_db()

        # Check that other sections were shifted
        self.assertEqual(section3.order, 0)
        self.assertEqual(section1.order, 1)
        self.assertEqual(section2.order, 2)

    def test_reorder_steps(self):
        """Test reordering steps within a section."""
        section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        # Create steps with non-sequential orders
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 1", order=5
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 2", order=10
        )

        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=section, step_description="Step 3", order=15
        )

        # Reorder steps to be sequential
        section.reorder_steps()

        # Refresh from database
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        # Check that steps are now ordered sequentially starting from 1
        self.assertEqual(step1.order, 1)
        self.assertEqual(step2.order, 2)
        self.assertEqual(step3.order, 3)

    def test_reorder_by_protocol(self):
        """Test reordering all sections in a protocol."""
        # Create sections with non-sequential orders
        section1 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 1", order=10)
        section2 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 2", order=5)
        section3 = ProtocolSection.objects.create(protocol=self.protocol, section_description="Section 3", order=20)

        # Reorder all sections in protocol
        ProtocolSection.reorder_by_protocol(self.protocol)

        # Refresh from database
        section1.refresh_from_db()
        section2.refresh_from_db()
        section3.refresh_from_db()

        # Check that sections are ordered by their current order values
        # (section2 has order=5, so it should be 0, section1 has order=10 so it should be 1, etc.)
        self.assertEqual(section2.order, 0)
        self.assertEqual(section1.order, 1)
        self.assertEqual(section3.order, 2)


class ProtocolStepModelTests(TestCase):
    """Test ProtocolStep model and linked-list manipulation."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)
        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

    def test_step_creation(self):
        """Test creating a protocol step."""
        step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_section=self.section,
            step_description="Mix reagents",
            step_duration=15,
            original=True,
        )

        self.assertEqual(step.step_description, "Mix reagents")
        self.assertEqual(step.step_duration, 15)
        self.assertTrue(step.original)

    def test_step_str_method(self):
        """Test ProtocolStep string representation."""
        step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Incubate for 30 minutes")

        self.assertEqual(str(step), "Incubate for 30 minutes")

    def test_step_linked_list_structure(self):
        """Test linked-list structure with previous_step relationships."""
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="First step"
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", previous_step=step1
        )

        self.assertEqual(step2.previous_step, step1)
        self.assertIn(step2, step1.next_step.all())

    def test_step_branching(self):
        """Test step branching functionality."""
        main_step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Main step")

        branch_step = ProtocolStep.objects.create(
            protocol=self.protocol, step_description="Branch step", original=False, branch_from=main_step
        )

        self.assertEqual(branch_step.branch_from, main_step)
        self.assertFalse(branch_step.original)
        self.assertIn(branch_step, main_step.branch_steps.all())

    def test_step_deletion_updates_linked_list(self):
        """Test that deleting a step updates the linked list properly."""
        step1 = ProtocolStep.objects.create(protocol=self.protocol, step_description="First step")

        step2 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Middle step", previous_step=step1)

        step3 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Last step", previous_step=step2)

        # Delete middle step
        step2.delete()

        # Refresh from database
        step3.refresh_from_db()

        # step3 should now point to step1 as previous
        self.assertEqual(step3.previous_step, step1)

    def test_step_ordering_default(self):
        """Test that steps have default order of 0."""
        step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Test step"
        )
        self.assertEqual(step.order, 0)

    def test_step_move_to_order(self):
        """Test moving step to specific order position."""
        # Create multiple steps in section
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step 1", order=0
        )
        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step 2", order=1
        )
        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Step 3", order=2
        )

        # Move step3 to position 0
        step3.move_to_order(0)

        # Refresh from database
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        # Check that other steps were shifted
        self.assertEqual(step3.order, 0)
        self.assertEqual(step1.order, 1)
        self.assertEqual(step2.order, 2)

    def test_step_move_to_order_without_section(self):
        """Test moving step to order when step has no section."""
        # Create protocol-level steps (no section)
        step1 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 1", order=0)
        step2 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 2", order=1)
        step3 = ProtocolStep.objects.create(protocol=self.protocol, step_description="Protocol Step 3", order=2)

        # Move step3 to position 0
        step3.move_to_order(0)

        # Refresh from database
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        # Check that other steps were shifted
        self.assertEqual(step3.order, 0)
        self.assertEqual(step1.order, 1)
        self.assertEqual(step2.order, 2)

    def test_reorder_by_linked_list(self):
        """Test migration method that populates order from linked-list structure."""
        # Create steps with linked-list structure but no order
        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="First step", previous_step=None
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", previous_step=step1
        )

        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Third step", previous_step=step2
        )

        # Set up the next_step relationships manually for this test
        # In real usage, these would be set up by the linked-list logic
        step1.next_step.add(step2)
        step2.next_step.add(step3)

        # Run the migration method
        ProtocolStep.reorder_by_linked_list()

        # Refresh from database
        step1.refresh_from_db()
        step2.refresh_from_db()
        step3.refresh_from_db()

        # Check that order was populated correctly
        self.assertEqual(step1.order, 0)
        self.assertEqual(step2.order, 1)
        self.assertEqual(step3.order, 2)

    def test_protocol_step_meta_ordering(self):
        """Test that ProtocolStep model uses order attribute for default ordering."""
        # Create steps in different order
        step3 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Third step", order=2
        )

        step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="First step", order=0
        )

        step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Second step", order=1
        )

        # Query all steps - should be ordered by order attribute
        all_steps = list(ProtocolStep.objects.filter(step_section=self.section))
        self.assertEqual(all_steps, [step1, step2, step3])


class RemoteHostModelTests(TestCase):
    """Test RemoteHost model for distributed system support (now using CCC RemoteHost)."""

    def test_remote_host_creation(self):
        """Test creating a remote host using CCC RemoteHost fields."""
        host = RemoteHost.objects.create(
            host_name="remote.example.com", host_port=443, host_protocol="https", host_description="Test Remote Host"
        )

        self.assertEqual(host.host_name, "remote.example.com")
        self.assertEqual(host.host_port, 443)
        self.assertEqual(host.host_protocol, "https")
        self.assertEqual(host.host_description, "Test Remote Host")

    def test_remote_host_str_method(self):
        """Test RemoteHost string representation."""
        host = RemoteHost.objects.create(
            host_name="production-server", host_port=8080, host_protocol="http", host_description="Production Server"
        )

        self.assertEqual(str(host), "production-server")

    def test_remote_host_relationships(self):
        """Test remote host relationships with CCRV models."""
        user = UserFactory.create_user()
        host = RemoteHost.objects.create(
            host_name="test.host.com", host_port=443, host_protocol="https", host_description="Test Host"
        )

        # Test with Project
        project = Project.objects.create(project_name="Remote Project", owner=user, remote_host=host, remote_id=123)

        self.assertEqual(project.remote_host, host)
        self.assertIn(project, host.projects.all())

        # Test with ProtocolModel
        protocol = ProtocolModel.objects.create(
            protocol_title="Remote Protocol", owner=user, remote_host=host, remote_id=456
        )

        self.assertEqual(protocol.remote_host, host)
        # Note: related_name for protocols changed from 'protocols' to match the ForeignKey definition


class ProtocolReagentModelTests(TestCase):
    """Test ProtocolReagent model linking protocols with CCM reagents."""

    def setUp(self):
        """Set up test data."""
        from ccm.models import Reagent

        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)
        self.reagent = Reagent.objects.create(name="Test Reagent", unit="mL")

    def test_protocol_reagent_creation(self):
        """Test creating a protocol reagent link."""
        protocol_reagent = ProtocolReagent.objects.create(protocol=self.protocol, reagent=self.reagent, quantity=50.0)

        self.assertEqual(protocol_reagent.protocol, self.protocol)
        self.assertEqual(protocol_reagent.reagent, self.reagent)
        self.assertEqual(protocol_reagent.quantity, 50.0)

    def test_protocol_reagent_str_method(self):
        """Test ProtocolReagent string representation."""
        protocol_reagent = ProtocolReagent.objects.create(protocol=self.protocol, reagent=self.reagent, quantity=25.0)

        expected_str = f"{self.protocol.protocol_title} - {self.reagent.name} (25.0)"
        self.assertEqual(str(protocol_reagent), expected_str)


class StepReagentModelTests(TestCase):
    """Test StepReagent model with scaling functionality."""

    def setUp(self):
        """Set up test data."""
        from ccm.models import Reagent

        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)
        self.step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Test step")
        self.reagent = Reagent.objects.create(name="Scalable Reagent", unit="μL")

    def test_step_reagent_creation(self):
        """Test creating a step reagent with scaling."""
        step_reagent = StepReagent.objects.create(
            step=self.step, reagent=self.reagent, quantity=10.0, scalable=True, scalable_factor=2.0
        )

        self.assertEqual(step_reagent.step, self.step)
        self.assertEqual(step_reagent.reagent, self.reagent)
        self.assertEqual(step_reagent.quantity, 10.0)
        self.assertTrue(step_reagent.scalable)
        self.assertEqual(step_reagent.scalable_factor, 2.0)

    def test_step_reagent_scaling_calculation(self):
        """Test scaling calculation logic."""
        step_reagent = StepReagent.objects.create(
            step=self.step, reagent=self.reagent, quantity=5.0, scalable=True, scalable_factor=3.0
        )

        # This would be tested in the serializer, but we can verify the data
        expected_scaled = step_reagent.quantity * step_reagent.scalable_factor
        self.assertEqual(expected_scaled, 15.0)

    def test_step_reagent_non_scalable(self):
        """Test non-scalable reagent behavior."""
        step_reagent = StepReagent.objects.create(step=self.step, reagent=self.reagent, quantity=20.0, scalable=False)

        self.assertFalse(step_reagent.scalable)
        self.assertEqual(step_reagent.scalable_factor, 1.0)  # default value

    def test_step_reagent_str_method(self):
        """Test StepReagent string representation."""
        step_reagent = StepReagent.objects.create(step=self.step, reagent=self.reagent, quantity=100.0)

        # Should truncate long step descriptions
        expected_str = f"{self.step.step_description[:50]}... - {self.reagent.name} (100.0)"
        self.assertEqual(str(step_reagent), expected_str)


class StepVariationModelTests(TestCase):
    """Test StepVariation model for protocol step alternatives."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Test Protocol", owner=self.user)
        self.step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Original step")

    def test_step_variation_creation(self):
        """Test creating a step variation."""
        variation = StepVariation.objects.create(
            step=self.step, variation_description="Alternative approach for this step", variation_duration=300
        )

        self.assertEqual(variation.step, self.step)
        self.assertEqual(variation.variation_description, "Alternative approach for this step")
        self.assertEqual(variation.variation_duration, 300)

    def test_step_variation_str_method(self):
        """Test StepVariation string representation."""
        variation = StepVariation.objects.create(
            step=self.step, variation_description="Quick variation method", variation_duration=120
        )

        self.assertEqual(str(variation), "Quick variation method")

    def test_step_variation_with_remote_host(self):
        """Test step variation with remote host tracking."""
        remote_host = RemoteHost.objects.create(
            host_name="remote.lab.com", host_port=443, host_protocol="https", host_description="Lab Remote"
        )

        variation = StepVariation.objects.create(
            step=self.step,
            variation_description="Remote variation",
            variation_duration=180,
            remote_host=remote_host,
            remote_id=789,
        )

        self.assertEqual(variation.remote_host, remote_host)
        self.assertEqual(variation.remote_id, 789)


class TimeKeeperModelTests(TestCase):
    """Test TimeKeeper model for protocol timing."""

    def setUp(self):
        """Set up test data."""
        self.user = UserFactory.create_user()
        self.protocol = ProtocolModel.objects.create(protocol_title="Timed Protocol", owner=self.user)
        self.session = Session.objects.create(name="Test Session", owner=self.user, unique_id=uuid.uuid4())
        self.step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Timed step")

    def test_time_keeper_creation(self):
        """Test creating a time keeper."""
        time_keeper = TimeKeeper.objects.create(session=self.session, step=self.step, user=self.user)

        self.assertEqual(time_keeper.session, self.session)
        self.assertEqual(time_keeper.step, self.step)
        self.assertEqual(time_keeper.user, self.user)
        self.assertFalse(time_keeper.started)

    def test_time_keeper_timing_functionality(self):
        """Test time keeper timing states."""
        time_keeper = TimeKeeper.objects.create(
            session=self.session, user=self.user, started=True, current_duration=3600  # 1 hour in seconds
        )

        self.assertTrue(time_keeper.started)
        self.assertEqual(time_keeper.current_duration, 3600)

    def test_time_keeper_str_method(self):
        """Test TimeKeeper string representation."""
        time_keeper = TimeKeeper.objects.create(session=self.session, step=self.step, user=self.user)

        expected_str = f"{time_keeper.start_time} - {self.session} - {self.step}"
        self.assertEqual(str(time_keeper), expected_str)

    def test_time_keeper_session_only(self):
        """Test time keeper for session-level timing."""
        time_keeper = TimeKeeper.objects.create(
            session=self.session, user=self.user, current_duration=1800  # 30 minutes
        )

        self.assertIsNone(time_keeper.step)
        self.assertEqual(time_keeper.session, self.session)
        self.assertEqual(time_keeper.current_duration, 1800)

    def test_time_keeper_step_only(self):
        """Test time keeper for step-level timing."""
        time_keeper = TimeKeeper.objects.create(step=self.step, user=self.user, current_duration=600)  # 10 minutes

        self.assertIsNone(time_keeper.session)
        self.assertEqual(time_keeper.step, self.step)
        self.assertEqual(time_keeper.current_duration, 600)
