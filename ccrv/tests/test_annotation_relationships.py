"""
Tests for CCRV annotation relationship models.

Tests the junction models that connect Sessions, ProtocolSteps, and AnnotationFolders
to CCC Annotations, including file upload functionality.
"""

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


class SessionAnnotationTestCase(TestCase):
    """Test SessionAnnotation model for session-level annotations."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create protocol components
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol", protocol_description="Test protocol for annotations", owner=self.user
        )

        # Create session
        import uuid

        self.session = Session.objects.create(unique_id=uuid.uuid4(), name="Test Session", owner=self.user)
        self.session.protocols.add(self.protocol)

    def test_create_session_annotation(self):
        """Test creating annotation attached to session."""
        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Session started at 9 AM", annotation_type="text", owner=self.user
        )

        # Attach annotation to session
        session_annotation = SessionAnnotation.objects.create(session=self.session, annotation=annotation, order=1)

        # Verify relationship
        self.assertEqual(session_annotation.session, self.session)
        self.assertEqual(session_annotation.annotation, annotation)
        self.assertEqual(session_annotation.order, 1)

        # Test reverse relationships
        self.assertEqual(self.session.session_annotations.count(), 1)
        self.assertEqual(annotation.session_attachments.count(), 1)

    def test_session_annotation_with_file(self):
        """Test session annotation with file upload."""
        # Create file annotation
        test_file = SimpleUploadedFile(
            "session_notes.txt", b"Session experimental notes content", content_type="text/plain"
        )

        annotation = Annotation.objects.create(
            annotation="Session experimental notes", annotation_type="file", file=test_file, owner=self.user
        )

        # Attach to session
        SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # Verify file attachment
        self.assertTrue(annotation.file)
        # Django adds random suffix to prevent collisions, so check if base name is present
        self.assertTrue(
            annotation.file.name.startswith("annotations/session_notes") and annotation.file.name.endswith(".txt")
        )

        # Verify session attachment
        self.assertEqual(self.session.session_annotations.count(), 1)

    def test_session_annotation_ordering(self):
        """Test ordering of annotations within session."""
        # Create multiple annotations
        annotations = []
        for i in range(3):
            annotation = Annotation.objects.create(
                annotation=f"Session note {i+1}", annotation_type="text", owner=self.user
            )
            annotations.append(annotation)

            SessionAnnotation.objects.create(session=self.session, annotation=annotation, order=i + 1)

        # Verify ordering
        session_annotations = self.session.session_annotations.all()
        self.assertEqual(session_annotations.count(), 3)

        for i, sa in enumerate(session_annotations):
            self.assertEqual(sa.order, i + 1)
            self.assertEqual(sa.annotation, annotations[i])

    def test_session_annotation_uniqueness(self):
        """Test that same annotation cannot be attached to session twice."""
        annotation = Annotation.objects.create(annotation="Unique note", annotation_type="text", owner=self.user)

        # First attachment should work
        SessionAnnotation.objects.create(session=self.session, annotation=annotation)

        # Second attachment should fail
        with self.assertRaises(Exception):  # IntegrityError for unique constraint
            SessionAnnotation.objects.create(session=self.session, annotation=annotation)


class StepAnnotationTestCase(TestCase):
    """Test StepAnnotation model for step-specific annotations within sessions."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create protocol components
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol", protocol_description="Test protocol for step annotations", owner=self.user
        )

        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Test Section")

        self.step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Mix reagents thoroughly"
        )

        # Create two sessions
        import uuid

        self.session_a = Session.objects.create(unique_id=uuid.uuid4(), name="Session A", owner=self.user)
        self.session_b = Session.objects.create(unique_id=uuid.uuid4(), name="Session B", owner=self.user)

        for session in [self.session_a, self.session_b]:
            session.protocols.add(self.protocol)

    def test_create_step_annotation(self):
        """Test creating annotation attached to step within session."""
        annotation = Annotation.objects.create(
            annotation="Step completed successfully", annotation_type="text", owner=self.user
        )

        step_annotation = StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation)

        # Verify relationship
        self.assertEqual(step_annotation.session, self.session_a)
        self.assertEqual(step_annotation.step, self.step)
        self.assertEqual(step_annotation.annotation, annotation)

        # Test reverse relationships
        self.assertEqual(self.session_a.step_annotations.count(), 1)
        self.assertEqual(self.step.step_annotations.count(), 1)
        self.assertEqual(annotation.step_attachments.count(), 1)

    def test_session_isolation_for_step_annotations(self):
        """Test that same step can have different annotations in different sessions."""
        # Session A annotation for the step
        annotation_a = Annotation.objects.create(
            annotation="Session A: Step completed at 10:30 AM", annotation_type="text", owner=self.user
        )

        StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation_a)

        # Session B annotation for the same step
        annotation_b = Annotation.objects.create(
            annotation="Session B: Step failed, retrying with higher temperature",
            annotation_type="text",
            owner=self.user,
        )

        StepAnnotation.objects.create(session=self.session_b, step=self.step, annotation=annotation_b)

        # Verify isolation - each session has different annotation for same step
        session_a_annotations = self.session_a.step_annotations.filter(step=self.step)
        session_b_annotations = self.session_b.step_annotations.filter(step=self.step)

        self.assertEqual(session_a_annotations.count(), 1)
        self.assertEqual(session_b_annotations.count(), 1)

        self.assertEqual(session_a_annotations.first().annotation.annotation, "Session A: Step completed at 10:30 AM")
        self.assertEqual(
            session_b_annotations.first().annotation.annotation,
            "Session B: Step failed, retrying with higher temperature",
        )

    def test_step_annotation_with_image_upload(self):
        """Test step annotation with image file upload."""
        # Create simple 1x1 PNG image data (minimal valid PNG)
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        test_image = SimpleUploadedFile("step_result.png", png_data, content_type="image/png")

        annotation = Annotation.objects.create(
            annotation="Step result image", annotation_type="image", file=test_image, owner=self.user
        )

        StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation)

        # Verify image attachment
        self.assertTrue(annotation.file)
        # Django adds random suffix to prevent collisions, so check if base name is present
        self.assertTrue(
            annotation.file.name.startswith("annotations/step_result") and annotation.file.name.endswith(".png")
        )
        self.assertEqual(annotation.annotation_type, "image")

        # Verify step attachment
        step_annotations = self.session_a.step_annotations.filter(step=self.step)
        self.assertEqual(step_annotations.count(), 1)

    def test_step_annotation_uniqueness(self):
        """Test unique constraint for session-step-annotation combination."""
        annotation = Annotation.objects.create(annotation="Unique step note", annotation_type="text", owner=self.user)

        # First attachment should work
        StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation)

        # Duplicate attachment to same session-step should fail
        with self.assertRaises(Exception):
            StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation)

    def test_multiple_annotations_per_step_in_session(self):
        """Test multiple different annotations for same step in same session."""
        # Create multiple annotations for the same step in same session
        annotations = []
        for i in range(3):
            annotation = Annotation.objects.create(
                annotation=f"Step observation {i+1}", annotation_type="text", owner=self.user
            )
            annotations.append(annotation)

            StepAnnotation.objects.create(session=self.session_a, step=self.step, annotation=annotation, order=i + 1)

        # Verify all annotations attached
        step_annotations = self.session_a.step_annotations.filter(step=self.step)
        self.assertEqual(step_annotations.count(), 3)

        # Verify ordering
        for i, sa in enumerate(step_annotations):
            self.assertEqual(sa.order, i + 1)


class SessionAnnotationFolderTestCase(TestCase):
    """Test SessionAnnotationFolder model for session-specific folder organization."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create session
        import uuid

        self.session = Session.objects.create(unique_id=uuid.uuid4(), name="Test Session with Folders", owner=self.user)

    def test_create_session_annotation_folder(self):
        """Test creating folder attached to session."""
        folder = AnnotationFolder.objects.create(folder_name="Session A Documents", owner=self.user)

        session_folder = SessionAnnotationFolder.objects.create(session=self.session, folder=folder)

        # Verify relationship
        self.assertEqual(session_folder.session, self.session)
        self.assertEqual(session_folder.folder, folder)

        # Test reverse relationships
        self.assertEqual(self.session.session_annotation_folders.count(), 1)
        self.assertEqual(folder.session_attachments.count(), 1)

    def test_session_folder_with_nested_annotations(self):
        """Test session folder containing annotations with files."""
        # Create session-specific folder
        folder = AnnotationFolder.objects.create(folder_name="Experimental Images", owner=self.user)

        SessionAnnotationFolder.objects.create(session=self.session, folder=folder)

        # Add annotations to the folder
        test_file = SimpleUploadedFile("experiment_photo.jpg", b"fake jpeg content", content_type="image/jpeg")

        annotation = Annotation.objects.create(
            annotation="Lab setup photo", annotation_type="image", file=test_file, folder=folder, owner=self.user
        )

        # Verify folder contains annotation
        self.assertEqual(folder.annotations.count(), 1)
        self.assertEqual(folder.annotations.first(), annotation)

        # Verify folder is attached to session
        self.assertEqual(self.session.session_annotation_folders.count(), 1)

    def test_hierarchical_session_folders(self):
        """Test nested folder structure within session."""
        # Create parent folder
        parent_folder = AnnotationFolder.objects.create(folder_name="Session Data", owner=self.user)

        # Create child folder
        child_folder = AnnotationFolder.objects.create(
            folder_name="Images", parent_folder=parent_folder, owner=self.user
        )

        # Attach both to session
        SessionAnnotationFolder.objects.create(session=self.session, folder=parent_folder, order=1)

        SessionAnnotationFolder.objects.create(session=self.session, folder=child_folder, order=2)

        # Verify hierarchy
        self.assertEqual(child_folder.parent_folder, parent_folder)
        self.assertEqual(parent_folder.child_folders.count(), 1)

        # Verify session attachment
        self.assertEqual(self.session.session_annotation_folders.count(), 2)

    def test_session_folder_uniqueness(self):
        """Test that same folder cannot be attached to session twice."""
        folder = AnnotationFolder.objects.create(folder_name="Unique Folder", owner=self.user)

        # First attachment should work
        SessionAnnotationFolder.objects.create(session=self.session, folder=folder)

        # Duplicate attachment should fail
        with self.assertRaises(Exception):
            SessionAnnotationFolder.objects.create(session=self.session, folder=folder)


class IntegratedAnnotationWorkflowTestCase(TestCase):
    """Test integrated workflow combining all annotation relationship types."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create protocol
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Complete Protocol",
            protocol_description="Full protocol for integrated testing",
            owner=self.user,
        )

        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Preparation")

        self.step1 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Prepare reagents"
        )

        self.step2 = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="Mix and incubate"
        )

        # Create session
        import uuid

        self.session = Session.objects.create(unique_id=uuid.uuid4(), name="Complete Workflow Session", owner=self.user)
        self.session.protocols.add(self.protocol)

    def test_complete_annotation_workflow(self):
        """Test complete workflow with session folders, session notes, and step annotations."""
        # 1. Create session-specific folder structure
        main_folder = AnnotationFolder.objects.create(folder_name="Session Documentation", owner=self.user)

        images_folder = AnnotationFolder.objects.create(
            folder_name="Step Images", parent_folder=main_folder, owner=self.user
        )

        SessionAnnotationFolder.objects.create(session=self.session, folder=main_folder)

        SessionAnnotationFolder.objects.create(session=self.session, folder=images_folder)

        # 2. Add session-level general notes
        session_note = Annotation.objects.create(
            annotation="Experiment started at 2 PM, ambient temp 22°C",
            annotation_type="text",
            folder=main_folder,
            owner=self.user,
        )

        SessionAnnotation.objects.create(session=self.session, annotation=session_note)

        # 3. Add step-specific annotations with files
        step1_image = SimpleUploadedFile("reagent_prep.jpg", b"fake reagent image data", content_type="image/jpeg")

        step1_annotation = Annotation.objects.create(
            annotation="Reagent preparation complete",
            annotation_type="image",
            file=step1_image,
            folder=images_folder,
            owner=self.user,
        )

        StepAnnotation.objects.create(session=self.session, step=self.step1, annotation=step1_annotation)

        # Step 2 text annotation
        step2_annotation = Annotation.objects.create(
            annotation="Incubation temperature maintained at 37°C", annotation_type="text", owner=self.user
        )

        StepAnnotation.objects.create(session=self.session, step=self.step2, annotation=step2_annotation)

        # Verify complete workflow
        # Session has folders
        self.assertEqual(self.session.session_annotation_folders.count(), 2)

        # Session has general notes
        self.assertEqual(self.session.session_annotations.count(), 1)

        # Steps have specific annotations
        self.assertEqual(self.session.step_annotations.count(), 2)

        # Folders contain appropriate annotations
        self.assertEqual(main_folder.annotations.count(), 1)
        self.assertEqual(images_folder.annotations.count(), 1)

        # Files are properly uploaded
        step1_annotation.refresh_from_db()
        self.assertTrue(step1_annotation.file)
        # Django adds random suffix to prevent collisions, so check if base name is present
        self.assertTrue(
            step1_annotation.file.name.startswith("annotations/reagent_prep")
            and step1_annotation.file.name.endswith(".jpg")
        )

    def test_session_isolation_in_workflow(self):
        """Test that two sessions executing same protocol have isolated annotation spaces."""
        # Create second session
        import uuid

        session2 = Session.objects.create(unique_id=uuid.uuid4(), name="Second Session", owner=self.user)
        session2.protocols.add(self.protocol)

        # Both sessions annotate the same step
        for i, session in enumerate([self.session, session2], 1):
            annotation = Annotation.objects.create(
                annotation=f"Session {i} completed step 1", annotation_type="text", owner=self.user
            )

            StepAnnotation.objects.create(session=session, step=self.step1, annotation=annotation)

        # Verify isolation
        session1_annotations = self.session.step_annotations.filter(step=self.step1)
        session2_annotations = session2.step_annotations.filter(step=self.step1)

        self.assertEqual(session1_annotations.count(), 1)
        self.assertEqual(session2_annotations.count(), 1)

        self.assertNotEqual(
            session1_annotations.first().annotation.annotation, session2_annotations.first().annotation.annotation
        )
