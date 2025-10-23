"""
Tests for CCM annotation relationship models.

Tests the annotation systems for Instruments, StoredReagents, and MaintenanceLogs,
including default folder creation, file uploads, and validation constraints.
"""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ccc.models import Annotation, AnnotationFolder
from ccm.models import (
    Instrument,
    InstrumentAnnotation,
    MaintenanceLog,
    MaintenanceLogAnnotation,
    Reagent,
    StorageObject,
    StoredReagent,
    StoredReagentAnnotation,
)
from tests.factories import UserFactory


class InstrumentAnnotationTestCase(TestCase):
    """Test InstrumentAnnotation model with predefined folder structure."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test HPLC", instrument_description="Test instrument for annotations", user=self.user
        )

    def test_instrument_default_folder_creation(self):
        """Test that instruments create default folders on creation."""
        # Create default folders
        self.instrument.create_default_folders()

        # Verify folders were created
        folders = AnnotationFolder.objects.filter(owner=self.user)
        folder_names = list(folders.values_list("folder_name", flat=True))

        self.assertIn("Manuals", folder_names)
        self.assertIn("Certificates", folder_names)
        self.assertIn("Maintenance", folder_names)
        self.assertEqual(folders.count(), 3)

    def test_instrument_annotation_with_manual_folder(self):
        """Test attaching annotation to instrument via Manuals folder."""
        # Create default folders
        self.instrument.create_default_folders()
        manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.user)

        # Create annotation with file
        manual_file = SimpleUploadedFile(
            "instrument_manual.pdf", b"fake PDF content for instrument manual", content_type="application/pdf"
        )

        annotation = Annotation.objects.create(
            annotation="Instrument operation manual",
            annotation_type="document",
            file=manual_file,
            folder=manuals_folder,
            owner=self.user,
        )

        # Link annotation to instrument via folder
        instrument_annotation = InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=annotation, folder=manuals_folder, order=1
        )

        # Verify relationships
        self.assertEqual(instrument_annotation.instrument, self.instrument)
        self.assertEqual(instrument_annotation.annotation, annotation)
        self.assertEqual(instrument_annotation.folder, manuals_folder)

        # Test reverse relationships
        self.assertEqual(self.instrument.instrument_annotations.count(), 1)
        self.assertEqual(annotation.instrument_attachments.count(), 1)
        self.assertEqual(manuals_folder.instrument_annotations.count(), 1)

    def test_instrument_annotation_with_certificates_folder(self):
        """Test attaching annotation to instrument via Certificates folder."""
        # Create default folders
        self.instrument.create_default_folders()
        certificates_folder = AnnotationFolder.objects.get(folder_name="Certificates", owner=self.user)

        # Create annotation with image
        cert_image = SimpleUploadedFile(
            "calibration_cert.jpg", b"fake image content for calibration certificate", content_type="image/jpeg"
        )

        annotation = Annotation.objects.create(
            annotation="Calibration certificate",
            annotation_type="image",
            file=cert_image,
            folder=certificates_folder,
            owner=self.user,
        )

        # Link annotation to instrument
        InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=annotation, folder=certificates_folder
        )

        # Verify file upload
        self.assertTrue(annotation.file)
        self.assertTrue(
            annotation.file.name.startswith("annotations/calibration_cert") and annotation.file.name.endswith(".jpg")
        )

    def test_instrument_multiple_annotations_same_folder(self):
        """Test multiple annotations in same folder with ordering."""
        # Create default folders
        self.instrument.create_default_folders()
        maintenance_folder = AnnotationFolder.objects.get(folder_name="Maintenance", owner=self.user)

        # Create multiple maintenance annotations
        annotations = []
        for i in range(3):
            annotation = Annotation.objects.create(
                annotation=f"Maintenance log entry {i+1}",
                annotation_type="text",
                folder=maintenance_folder,
                owner=self.user,
            )
            annotations.append(annotation)

            InstrumentAnnotation.objects.create(
                instrument=self.instrument, annotation=annotation, folder=maintenance_folder, order=i + 1
            )

        # Verify ordering
        instrument_annotations = self.instrument.instrument_annotations.all()
        self.assertEqual(instrument_annotations.count(), 3)

        for i, ia in enumerate(instrument_annotations):
            self.assertEqual(ia.order, i + 1)
            self.assertEqual(ia.annotation, annotations[i])

    def test_instrument_folder_isolation(self):
        """Test that different instruments can have separate folder structures."""
        # Create second instrument
        instrument2 = Instrument.objects.create(
            instrument_name="Test Microscope", instrument_description="Second test instrument", user=self.user
        )

        # Both create default folders
        self.instrument.create_default_folders()
        instrument2.create_default_folders()

        # Should not duplicate folders (both use same user)
        folders = AnnotationFolder.objects.filter(owner=self.user)
        self.assertEqual(folders.count(), 3)  # Still only 3 folders total

        # Both instruments can use the same folders
        manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.user)

        # Create annotations for both instruments
        annotation1 = Annotation.objects.create(
            annotation="HPLC manual", annotation_type="document", folder=manuals_folder, owner=self.user
        )

        annotation2 = Annotation.objects.create(
            annotation="Microscope manual", annotation_type="document", folder=manuals_folder, owner=self.user
        )

        # Link to respective instruments
        InstrumentAnnotation.objects.create(instrument=self.instrument, annotation=annotation1, folder=manuals_folder)
        InstrumentAnnotation.objects.create(instrument=instrument2, annotation=annotation2, folder=manuals_folder)

        # Verify isolation
        hplc_annotations = self.instrument.instrument_annotations.all()
        microscope_annotations = instrument2.instrument_annotations.all()

        self.assertEqual(hplc_annotations.count(), 1)
        self.assertEqual(microscope_annotations.count(), 1)
        self.assertNotEqual(hplc_annotations.first().annotation, microscope_annotations.first().annotation)

    def test_instrument_folder_validation(self):
        """Test that instruments reject annotations in invalid folders."""
        # Create default folders
        self.instrument.create_default_folders()

        # Create invalid folder
        invalid_folder = AnnotationFolder.objects.create(folder_name="Invalid Folder", owner=self.user)

        annotation = Annotation.objects.create(
            annotation="Test annotation", annotation_type="text", folder=invalid_folder, owner=self.user
        )

        # Try to link to instrument - should fail validation
        with self.assertRaises(ValidationError):
            InstrumentAnnotation.objects.create(
                instrument=self.instrument, annotation=annotation, folder=invalid_folder
            )


class StoredReagentAnnotationTestCase(TestCase):
    """Test StoredReagentAnnotation model with MSDS/Certificates/Manuals folders."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create reagent and storage
        self.reagent = Reagent.objects.create(name="Test Buffer", unit="mL")

        self.storage = StorageObject.objects.create(
            object_name="Fridge A", object_type="fridge", object_description="Chemical storage fridge"
        )

        # Create stored reagent
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=100.0, user=self.user
        )

    def test_stored_reagent_default_folder_creation(self):
        """Test that stored reagents create default folders."""
        # Create default folders
        self.stored_reagent.create_default_folders()

        # Verify folders were created
        folders = AnnotationFolder.objects.filter(owner=self.user)
        folder_names = list(folders.values_list("folder_name", flat=True))

        self.assertIn("MSDS", folder_names)
        self.assertIn("Certificates", folder_names)
        self.assertIn("Manuals", folder_names)
        self.assertEqual(folders.count(), 3)

    def test_stored_reagent_msds_annotation(self):
        """Test attaching MSDS document to stored reagent."""
        # Create default folders
        self.stored_reagent.create_default_folders()
        msds_folder = AnnotationFolder.objects.get(folder_name="MSDS", owner=self.user)

        # Create MSDS document
        msds_file = SimpleUploadedFile("buffer_msds.pdf", b"fake MSDS document content", content_type="application/pdf")

        annotation = Annotation.objects.create(
            annotation="Safety data sheet for test buffer",
            annotation_type="document",
            file=msds_file,
            folder=msds_folder,
            owner=self.user,
        )

        # Link to stored reagent
        reagent_annotation = StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=annotation, folder=msds_folder
        )

        # Verify relationships
        self.assertEqual(reagent_annotation.stored_reagent, self.stored_reagent)
        self.assertEqual(reagent_annotation.annotation, annotation)
        self.assertEqual(reagent_annotation.folder, msds_folder)

        # Test reverse relationships
        self.assertEqual(self.stored_reagent.stored_reagent_annotations.count(), 1)
        self.assertEqual(annotation.stored_reagent_attachments.count(), 1)

    def test_stored_reagent_certificates_with_images(self):
        """Test attaching certificate images to stored reagent."""
        # Create default folders
        self.stored_reagent.create_default_folders()
        certificates_folder = AnnotationFolder.objects.get(folder_name="Certificates", owner=self.user)

        # Create certificate image
        cert_image = SimpleUploadedFile(
            "purity_certificate.png", b"fake certificate image content", content_type="image/png"
        )

        annotation = Annotation.objects.create(
            annotation="Purity certificate",
            annotation_type="image",
            file=cert_image,
            folder=certificates_folder,
            owner=self.user,
        )

        # Link to stored reagent
        StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=annotation, folder=certificates_folder
        )

        # Verify file upload
        self.assertTrue(annotation.file)
        self.assertTrue(
            annotation.file.name.startswith("annotations/purity_certificate") and annotation.file.name.endswith(".png")
        )

    def test_stored_reagent_manual_text_annotation(self):
        """Test attaching text manual to stored reagent."""
        # Create default folders
        self.stored_reagent.create_default_folders()
        manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.user)

        # Create text annotation
        annotation = Annotation.objects.create(
            annotation="Buffer preparation protocol: Mix 10mL distilled water with 1g powder. Store at 4°C.",
            annotation_type="text",
            folder=manuals_folder,
            owner=self.user,
        )

        # Link to stored reagent
        StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=annotation, folder=manuals_folder
        )

        # Verify text content
        self.assertIn("Buffer preparation protocol", annotation.annotation)
        self.assertEqual(annotation.annotation_type, "text")

    def test_stored_reagent_folder_validation(self):
        """Test that stored reagents reject annotations in invalid folders."""
        # Create default folders
        self.stored_reagent.create_default_folders()

        # Create invalid folder
        invalid_folder = AnnotationFolder.objects.create(folder_name="Invalid Storage Folder", owner=self.user)

        annotation = Annotation.objects.create(
            annotation="Test reagent annotation", annotation_type="text", folder=invalid_folder, owner=self.user
        )

        # Try to link to stored reagent - should fail validation
        with self.assertRaises(ValidationError):
            StoredReagentAnnotation.objects.create(
                stored_reagent=self.stored_reagent, annotation=annotation, folder=invalid_folder
            )


class MaintenanceLogAnnotationTestCase(TestCase):
    """Test MaintenanceLogAnnotation model for direct annotation attachment."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Centrifuge",
            instrument_description="Centrifuge for maintenance testing",
            user=self.user,
        )

        # Create maintenance log
        from django.utils import timezone

        self.maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Routine cleaning and calibration",
            maintenance_notes="All components checked and working properly",
            created_by=self.user,
        )

    def test_direct_maintenance_log_annotation(self):
        """Test direct annotation attachment to maintenance log."""
        # Create annotation with file
        maintenance_photo = SimpleUploadedFile(
            "maintenance_complete.jpg", b"fake photo of completed maintenance", content_type="image/jpeg"
        )

        annotation = Annotation.objects.create(
            annotation="Photo of cleaned centrifuge components",
            annotation_type="image",
            file=maintenance_photo,
            owner=self.user,
        )

        # Attach directly to maintenance log
        log_annotation = MaintenanceLogAnnotation.objects.create(
            maintenance_log=self.maintenance_log, annotation=annotation, order=1
        )

        # Verify relationships
        self.assertEqual(log_annotation.maintenance_log, self.maintenance_log)
        self.assertEqual(log_annotation.annotation, annotation)

        # Test reverse relationships
        self.assertEqual(self.maintenance_log.maintenance_log_annotations.count(), 1)
        self.assertEqual(annotation.maintenance_log_attachments.count(), 1)

    def test_maintenance_log_multiple_annotations(self):
        """Test multiple annotations on single maintenance log with ordering."""
        # Create multiple annotations
        annotations = []

        # Before photo
        before_photo = SimpleUploadedFile("before.jpg", b"before photo", content_type="image/jpeg")
        annotation1 = Annotation.objects.create(
            annotation="Before maintenance photo", annotation_type="image", file=before_photo, owner=self.user
        )
        annotations.append(annotation1)

        # Text notes
        annotation2 = Annotation.objects.create(
            annotation="Replaced worn belt and cleaned all surfaces", annotation_type="text", owner=self.user
        )
        annotations.append(annotation2)

        # After photo
        after_photo = SimpleUploadedFile("after.jpg", b"after photo", content_type="image/jpeg")
        annotation3 = Annotation.objects.create(
            annotation="After maintenance photo", annotation_type="image", file=after_photo, owner=self.user
        )
        annotations.append(annotation3)

        # Attach all to maintenance log with ordering
        for i, annotation in enumerate(annotations):
            MaintenanceLogAnnotation.objects.create(
                maintenance_log=self.maintenance_log, annotation=annotation, order=i + 1
            )

        # Verify ordering
        log_annotations = self.maintenance_log.maintenance_log_annotations.all()
        self.assertEqual(log_annotations.count(), 3)

        for i, la in enumerate(log_annotations):
            self.assertEqual(la.order, i + 1)
            self.assertEqual(la.annotation, annotations[i])

    def test_maintenance_log_with_folder_organization(self):
        """Test maintenance log using both direct annotations and folder organization."""
        # Create folder for this maintenance log
        maintenance_folder = AnnotationFolder.objects.create(
            folder_name=f"Maintenance {self.maintenance_log.id}", owner=self.user
        )

        # Set folder on maintenance log
        self.maintenance_log.annotation_folder = maintenance_folder
        self.maintenance_log.save()

        # Create annotation in folder
        Annotation.objects.create(
            annotation="Detailed maintenance report",
            annotation_type="document",
            folder=maintenance_folder,
            owner=self.user,
        )

        # Also create direct annotation
        direct_annotation = Annotation.objects.create(
            annotation="Quick maintenance note", annotation_type="text", owner=self.user
        )

        # Link direct annotation
        MaintenanceLogAnnotation.objects.create(maintenance_log=self.maintenance_log, annotation=direct_annotation)

        # Verify both approaches work
        self.assertEqual(self.maintenance_log.maintenance_log_annotations.count(), 1)  # Direct
        self.assertEqual(maintenance_folder.annotations.count(), 1)  # Via folder
        self.assertEqual(self.maintenance_log.annotation_folder, maintenance_folder)

    def test_maintenance_log_annotation_uniqueness(self):
        """Test unique constraint for maintenance log annotations."""
        annotation = Annotation.objects.create(
            annotation="Unique maintenance note", annotation_type="text", owner=self.user
        )

        # First attachment should work
        MaintenanceLogAnnotation.objects.create(maintenance_log=self.maintenance_log, annotation=annotation)

        # Duplicate attachment should fail
        with self.assertRaises(Exception):  # IntegrityError for unique constraint
            MaintenanceLogAnnotation.objects.create(maintenance_log=self.maintenance_log, annotation=annotation)


class IntegratedCCMAnnotationWorkflowTestCase(TestCase):
    """Test integrated workflow combining all CCM annotation types."""

    def setUp(self):
        self.user = UserFactory.create_user()

        # Create complete lab setup
        self.instrument = Instrument.objects.create(
            instrument_name="Lab HPLC System", instrument_description="Main HPLC for analytical work", user=self.user
        )

        self.reagent = Reagent.objects.create(name="HPLC Grade Water", unit="L")

        self.storage = StorageObject.objects.create(
            object_name="Chemical Storage Room A", object_type="room", object_description="Main chemical storage room"
        )

        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=20.0, user=self.user
        )

    def test_complete_ccm_annotation_workflow(self):
        """Test complete workflow with instrument manuals, reagent MSDS, and maintenance logs."""
        # 1. Set up instrument with manual
        self.instrument.create_default_folders()
        manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.user)

        instrument_manual = Annotation.objects.create(
            annotation="HPLC operation and maintenance manual",
            annotation_type="document",
            folder=manuals_folder,
            owner=self.user,
        )

        InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=instrument_manual, folder=manuals_folder
        )

        # 2. Set up stored reagent with MSDS
        self.stored_reagent.create_default_folders()
        msds_folder = AnnotationFolder.objects.get(folder_name="MSDS", owner=self.user)

        reagent_msds = Annotation.objects.create(
            annotation="Safety data sheet for HPLC grade water",
            annotation_type="document",
            folder=msds_folder,
            owner=self.user,
        )

        StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=reagent_msds, folder=msds_folder
        )

        # 3. Create maintenance log with photos
        from django.utils import timezone

        maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Monthly maintenance and cleaning",
            created_by=self.user,
        )

        maintenance_photo = SimpleUploadedFile(
            "monthly_maintenance.jpg", b"maintenance completion photo", content_type="image/jpeg"
        )

        maintenance_annotation = Annotation.objects.create(
            annotation="Monthly maintenance completed successfully",
            annotation_type="image",
            file=maintenance_photo,
            owner=self.user,
        )

        MaintenanceLogAnnotation.objects.create(maintenance_log=maintenance_log, annotation=maintenance_annotation)

        # Verify complete workflow
        # Instrument has manual
        self.assertEqual(self.instrument.instrument_annotations.count(), 1)

        # Stored reagent has MSDS
        self.assertEqual(self.stored_reagent.stored_reagent_annotations.count(), 1)

        # Maintenance log has photo
        self.assertEqual(maintenance_log.maintenance_log_annotations.count(), 1)

        # All folders created correctly (Instrument: Manuals, Certificates, Maintenance; StoredReagent: MSDS, Certificates, Manuals)
        # Since both create "Manuals" and "Certificates", we have: Manuals, Certificates, Maintenance, MSDS = 4 unique folders
        self.assertEqual(AnnotationFolder.objects.filter(owner=self.user).count(), 4)

        # Files uploaded properly
        self.assertTrue(maintenance_annotation.file)
        self.assertTrue(maintenance_annotation.file.name.endswith(".jpg"))

    def test_ccm_annotation_permission_isolation(self):
        """Test that different users have isolated annotation spaces."""
        # Create second user
        user2 = UserFactory.create_user()

        # User 1 creates instrument with folders
        self.instrument.create_default_folders()

        # User 2 creates their own instrument
        instrument2 = Instrument.objects.create(
            instrument_name="User 2 HPLC", instrument_description="Second user's instrument", user=user2
        )
        instrument2.create_default_folders()

        # Verify folder isolation
        user1_folders = AnnotationFolder.objects.filter(owner=self.user)
        user2_folders = AnnotationFolder.objects.filter(owner=user2)

        # User 1 should have at least the 3 instrument folders
        # May have more if other resources created folders
        self.assertGreaterEqual(user1_folders.count(), 3)
        self.assertEqual(user2_folders.count(), 3)

        # User 2 should have exactly the instrument folders
        user2_folder_names = set(user2_folders.values_list("folder_name", flat=True))
        self.assertEqual(user2_folder_names, {"Manuals", "Certificates", "Maintenance"})

        # User 1 should have at least the instrument folders
        user1_folder_names = set(user1_folders.values_list("folder_name", flat=True))
        self.assertTrue({"Manuals", "Certificates", "Maintenance"}.issubset(user1_folder_names))
