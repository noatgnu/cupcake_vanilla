"""
Tests for CCRV session and step annotation permission inheritance.

Tests that session and step annotation permissions properly inherit from
the parent Session objects using AbstractResource permission methods.
"""

import uuid

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ccc.models import Annotation, AnnotationFolder
from ccrv.models import (
    ProtocolModel,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotation,
    SessionAnnotationFolder,
    StepAnnotation,
)
from tests.factories import UserFactory


class SessionAnnotationPermissionTestCase(TestCase):
    """Test permission inheritance for session annotations."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.editor = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create protocol
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol", protocol_description="Protocol for permission testing", owner=self.owner
        )

        # Create session owned by owner
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(), name="Permission Test Session", owner=self.owner, visibility="private"
        )
        self.session.protocols.add(self.protocol)

        # Add editor and viewer permissions
        self.session.editors.add(self.editor)
        self.session.viewers.add(self.viewer)

        # Create session annotation
        self.annotation = Annotation.objects.create(
            annotation="Session started at 2 PM", annotation_type="text", owner=self.owner
        )

        self.session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=self.annotation)

    def test_owner_has_full_access(self):
        """Test that session owner has full access to annotations."""
        # Owner should have full access
        self.assertTrue(self.session_annotation.can_view(self.owner))
        self.assertTrue(self.session_annotation.can_edit(self.owner))
        self.assertTrue(self.session_annotation.can_delete(self.owner))

    def test_editor_has_edit_access(self):
        """Test that session editors have edit access to annotations."""
        # Editor should have edit access
        self.assertTrue(self.session_annotation.can_view(self.editor))
        self.assertTrue(self.session_annotation.can_edit(self.editor))
        self.assertTrue(self.session_annotation.can_delete(self.editor))

    def test_viewer_has_view_only_access(self):
        """Test that session viewers have view-only access to annotations."""
        # Viewer should have view access but not edit
        self.assertTrue(self.session_annotation.can_view(self.viewer))
        self.assertFalse(self.session_annotation.can_edit(self.viewer))
        self.assertFalse(self.session_annotation.can_delete(self.viewer))

    def test_other_user_has_no_access(self):
        """Test that other users have no access to private session annotations."""
        # Other user should have no access
        self.assertFalse(self.session_annotation.can_view(self.other_user))
        self.assertFalse(self.session_annotation.can_edit(self.other_user))
        self.assertFalse(self.session_annotation.can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access to all session annotations."""
        # Staff should have full access
        self.assertTrue(self.session_annotation.can_view(self.staff_user))
        self.assertTrue(self.session_annotation.can_edit(self.staff_user))
        self.assertTrue(self.session_annotation.can_delete(self.staff_user))

    def test_public_session_allows_view_access(self):
        """Test that public sessions allow view access to all users."""
        # Make session public
        self.session.visibility = "public"
        self.session.save()

        # Now other user should have view access
        self.assertTrue(self.session_annotation.can_view(self.other_user))
        self.assertFalse(self.session_annotation.can_edit(self.other_user))  # Still no edit
        self.assertFalse(self.session_annotation.can_delete(self.other_user))


class StepAnnotationPermissionTestCase(TestCase):
    """Test permission inheritance for step annotations."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.collaborator = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create protocol components
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Step Test Protocol",
            protocol_description="Protocol for step annotation testing",
            owner=self.owner,
        )

        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        self.step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Mix reagents thoroughly"
        )

        # Create session with collaborator access
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(), name="Step Annotation Session", owner=self.owner, visibility="protected"
        )
        self.session.protocols.add(self.protocol)
        self.session.editors.add(self.collaborator)

        # Create step annotation with file
        step_photo = SimpleUploadedFile("step_complete.jpg", b"fake step completion photo", content_type="image/jpeg")

        self.annotation = Annotation.objects.create(
            annotation="Step completed successfully", annotation_type="image", file=step_photo, owner=self.owner
        )

        self.step_annotation = StepAnnotation.objects.create(
            session=self.session, step=self.step, annotation=self.annotation
        )

    def test_session_owner_has_full_access(self):
        """Test that session owner has full access to step annotations."""
        # Session owner should have full access
        self.assertTrue(self.step_annotation.can_view(self.owner))
        self.assertTrue(self.step_annotation.can_edit(self.owner))
        self.assertTrue(self.step_annotation.can_delete(self.owner))

    def test_session_collaborator_has_edit_access(self):
        """Test that session collaborators have edit access to step annotations."""
        # Session collaborator should have edit access
        self.assertTrue(self.step_annotation.can_view(self.collaborator))
        self.assertTrue(self.step_annotation.can_edit(self.collaborator))
        self.assertTrue(self.step_annotation.can_delete(self.collaborator))

    def test_other_user_has_no_access(self):
        """Test that other users have no access to step annotations."""
        # Other user should have no access
        self.assertFalse(self.step_annotation.can_view(self.other_user))
        self.assertFalse(self.step_annotation.can_edit(self.other_user))
        self.assertFalse(self.step_annotation.can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access to all step annotations."""
        # Staff should have full access
        self.assertTrue(self.step_annotation.can_view(self.staff_user))
        self.assertTrue(self.step_annotation.can_edit(self.staff_user))
        self.assertTrue(self.step_annotation.can_delete(self.staff_user))


class SessionAnnotationFolderPermissionTestCase(TestCase):
    """Test permission inheritance for session annotation folders."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.editor = UserFactory.create_user()
        self.other_user = UserFactory.create_user()

        # Create session
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(), name="Folder Test Session", owner=self.owner, visibility="private"
        )
        self.session.editors.add(self.editor)

        # Create session-specific folder
        self.folder = AnnotationFolder.objects.create(folder_name="Session Documents", owner=self.owner)

        self.session_folder = SessionAnnotationFolder.objects.create(session=self.session, folder=self.folder)

    def test_session_owner_can_manage_folders(self):
        """Test that session owner can manage session folders."""
        # Session owner should have full access to folders
        self.assertTrue(self.session_folder.can_view(self.owner))
        self.assertTrue(self.session_folder.can_edit(self.owner))
        self.assertTrue(self.session_folder.can_delete(self.owner))

    def test_session_editor_can_manage_folders(self):
        """Test that session editors can manage session folders."""
        # Session editor should have full access to folders
        self.assertTrue(self.session_folder.can_view(self.editor))
        self.assertTrue(self.session_folder.can_edit(self.editor))
        self.assertTrue(self.session_folder.can_delete(self.editor))

    def test_other_user_cannot_access_folders(self):
        """Test that other users cannot access private session folders."""
        # Other user should have no access to folders
        self.assertFalse(self.session_folder.can_view(self.other_user))
        self.assertFalse(self.session_folder.can_edit(self.other_user))
        self.assertFalse(self.session_folder.can_delete(self.other_user))


class SessionAnnotationWorkflowPermissionTestCase(TestCase):
    """Test permission workflow for complete session annotation scenarios."""

    def setUp(self):
        self.lab_leader = UserFactory.create_user()
        self.researcher = UserFactory.create_user()
        self.student = UserFactory.create_user()
        self.external = UserFactory.create_user()

        # Create protocol by lab leader
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Lab Protocol v2.0", protocol_description="Standard lab protocol", owner=self.lab_leader
        )

        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Sample Preparation")

        self.step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Prepare sample buffer"
        )

        self.step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Mix with reagents"
        )

        # Create research session with different permission levels
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            name="Research Session Alpha",
            owner=self.researcher,  # Researcher owns the session
            visibility="protected",
        )
        self.session.protocols.add(self.protocol)
        self.session.editors.add(self.lab_leader)  # Lab leader can edit
        self.session.viewers.add(self.student)  # Student can view

    def test_session_owner_workflow(self):
        """Test complete annotation workflow for session owner."""
        # Researcher (session owner) creates session annotation
        session_note = Annotation.objects.create(
            annotation="Session started with fresh reagents", annotation_type="text", owner=self.researcher
        )

        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=session_note)

        # Researcher creates step annotations
        step_note = Annotation.objects.create(
            annotation="Buffer preparation went smoothly", annotation_type="text", owner=self.researcher
        )

        step_annotation = StepAnnotation.objects.create(session=self.session, step=self.step1, annotation=step_note)

        # Researcher should have full access to all annotations
        self.assertTrue(session_annotation.can_view(self.researcher))
        self.assertTrue(session_annotation.can_edit(self.researcher))
        self.assertTrue(session_annotation.can_delete(self.researcher))

        self.assertTrue(step_annotation.can_view(self.researcher))
        self.assertTrue(step_annotation.can_edit(self.researcher))
        self.assertTrue(step_annotation.can_delete(self.researcher))

    def test_lab_leader_oversight(self):
        """Test that lab leader can oversee and edit all session annotations."""
        # Create annotations by researcher
        annotation = Annotation.objects.create(
            annotation="Preliminary results look promising", annotation_type="text", owner=self.researcher
        )

        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # Lab leader should be able to view and edit (has editor access)
        self.assertTrue(session_annotation.can_view(self.lab_leader))
        self.assertTrue(session_annotation.can_edit(self.lab_leader))
        self.assertTrue(session_annotation.can_delete(self.lab_leader))

    def test_student_view_only_access(self):
        """Test that student has view-only access to session annotations."""
        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Method validation complete", annotation_type="text", owner=self.researcher
        )

        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # Student should have view access but not edit
        self.assertTrue(session_annotation.can_view(self.student))
        self.assertFalse(session_annotation.can_edit(self.student))
        self.assertFalse(session_annotation.can_delete(self.student))

    def test_external_user_blocked(self):
        """Test that external users have no access to protected session annotations."""
        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Confidential research data", annotation_type="text", owner=self.researcher
        )

        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # External user should have no access
        self.assertFalse(session_annotation.can_view(self.external))
        self.assertFalse(session_annotation.can_edit(self.external))
        self.assertFalse(session_annotation.can_delete(self.external))

    def test_permission_changes_propagate(self):
        """Test that changes to session permissions affect annotation access."""
        # Create annotation
        annotation = Annotation.objects.create(annotation="Test data", annotation_type="text", owner=self.researcher)

        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # Initially external user has no access
        self.assertFalse(session_annotation.can_view(self.external))

        # Add external user as viewer
        self.session.viewers.add(self.external)

        # Now external user should have view access
        self.assertTrue(session_annotation.can_view(self.external))
        self.assertFalse(session_annotation.can_edit(self.external))

        # Promote to editor
        self.session.viewers.remove(self.external)
        self.session.editors.add(self.external)

        # Now should have edit access
        self.assertTrue(session_annotation.can_view(self.external))
        self.assertTrue(session_annotation.can_edit(self.external))
        self.assertTrue(session_annotation.can_delete(self.external))
