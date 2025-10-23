"""
Tests for the granular instrument permission system.

Tests that the InstrumentPermission model provides proper access control
for instruments, maintenance logs, and their annotations.
"""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from ccc.models import Annotation, AnnotationFolder
from ccm.models import Instrument, InstrumentAnnotation, InstrumentPermission, MaintenanceLog, MaintenanceLogAnnotation
from tests.factories import UserFactory


class InstrumentPermissionModelTestCase(TestCase):
    """Test the InstrumentPermission model itself."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.booker = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.other_user = UserFactory.create_user()

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test HPLC System",
            instrument_description="High-performance liquid chromatography",
            user=self.owner,
        )

    def test_permission_creation(self):
        """Test basic permission creation and string representation."""
        permission = InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        self.assertEqual(permission.instrument, self.instrument)
        self.assertEqual(permission.user, self.viewer)
        self.assertTrue(permission.can_view)
        self.assertFalse(permission.can_book)
        self.assertFalse(permission.can_manage)

        # Test string representation
        expected_str = f"{self.viewer.username} - {self.instrument.instrument_name} (view)"
        self.assertEqual(str(permission), expected_str)

    def test_multiple_permissions_string(self):
        """Test string representation with multiple permissions."""
        permission = InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

        expected_str = f"{self.manager.username} - {self.instrument.instrument_name} (view, book, manage)"
        self.assertEqual(str(permission), expected_str)

    def test_no_permissions_string(self):
        """Test string representation with no permissions."""
        permission = InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.other_user, can_view=False, can_book=False, can_manage=False
        )

        expected_str = f"{self.other_user.username} - {self.instrument.instrument_name} (no permissions)"
        self.assertEqual(str(permission), expected_str)

    def test_unique_constraint(self):
        """Test that each user can have only one permission per instrument."""
        # Create first permission
        InstrumentPermission.objects.create(instrument=self.instrument, user=self.viewer, can_view=True)

        # Creating another permission for same user/instrument should work due to unique constraint
        # but will be prevented at the application level
        # Let's test that the unique_together constraint is properly set
        self.assertEqual(InstrumentPermission._meta.unique_together, (("user", "instrument"),))


class InstrumentPermissionMethodsTestCase(TestCase):
    """Test instrument permission checking methods."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.booker = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Microscope",
            instrument_description="Advanced fluorescence microscopy",
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

    def test_owner_has_all_permissions(self):
        """Test that instrument owner has all permissions."""
        self.assertTrue(self.instrument.user_can_view(self.owner))
        self.assertTrue(self.instrument.user_can_book(self.owner))
        self.assertTrue(self.instrument.user_can_manage(self.owner))

    def test_staff_has_all_permissions(self):
        """Test that staff users have all permissions."""
        self.assertTrue(self.instrument.user_can_view(self.staff_user))
        self.assertTrue(self.instrument.user_can_book(self.staff_user))
        self.assertTrue(self.instrument.user_can_manage(self.staff_user))

    def test_viewer_permissions(self):
        """Test viewer-only permissions."""
        self.assertTrue(self.instrument.user_can_view(self.viewer))
        self.assertFalse(self.instrument.user_can_book(self.viewer))
        self.assertFalse(self.instrument.user_can_manage(self.viewer))

    def test_booker_permissions(self):
        """Test booking permissions."""
        self.assertTrue(self.instrument.user_can_view(self.booker))
        self.assertTrue(self.instrument.user_can_book(self.booker))
        self.assertFalse(self.instrument.user_can_manage(self.booker))

    def test_manager_permissions(self):
        """Test management permissions."""
        self.assertTrue(self.instrument.user_can_view(self.manager))
        self.assertTrue(self.instrument.user_can_book(self.manager))
        self.assertTrue(self.instrument.user_can_manage(self.manager))

    def test_other_user_no_permissions(self):
        """Test that users without explicit permissions have no access."""
        self.assertFalse(self.instrument.user_can_view(self.other_user))
        self.assertFalse(self.instrument.user_can_book(self.other_user))
        self.assertFalse(self.instrument.user_can_manage(self.other_user))

    def test_unauthenticated_user_no_permissions(self):
        """Test that unauthenticated users have no access."""
        self.assertFalse(self.instrument.user_can_view(None))
        self.assertFalse(self.instrument.user_can_book(None))
        self.assertFalse(self.instrument.user_can_manage(None))


class MaintenanceLogPermissionTestCase(TestCase):
    """Test that maintenance logs inherit instrument permissions."""

    def setUp(self):
        self.instrument_owner = UserFactory.create_user()
        self.maintenance_person = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Centrifuge",
            instrument_description="High-speed centrifuge for sample preparation",
            user=self.instrument_owner,
        )

        # Give viewer permission to view instrument
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        # Create maintenance log
        self.maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Monthly cleaning and calibration",
            created_by=self.maintenance_person,
        )

    def test_maintenance_creator_has_full_access(self):
        """Test that maintenance log creator has full access."""
        self.assertTrue(self.maintenance_log.user_can_view(self.maintenance_person))
        self.assertTrue(self.maintenance_log.user_can_edit(self.maintenance_person))
        self.assertTrue(self.maintenance_log.user_can_delete(self.maintenance_person))

    def test_instrument_owner_has_full_access(self):
        """Test that instrument owner has full access to maintenance logs."""
        self.assertTrue(self.maintenance_log.user_can_view(self.instrument_owner))
        self.assertTrue(self.maintenance_log.user_can_edit(self.instrument_owner))
        self.assertTrue(self.maintenance_log.user_can_delete(self.instrument_owner))

    def test_viewer_has_no_access_to_maintenance(self):
        """Test that instrument viewers cannot see maintenance logs."""
        self.assertFalse(self.maintenance_log.user_can_view(self.viewer))
        self.assertFalse(self.maintenance_log.user_can_edit(self.viewer))
        self.assertFalse(self.maintenance_log.user_can_delete(self.viewer))

    def test_other_user_no_access(self):
        """Test that other users have no access."""
        self.assertFalse(self.maintenance_log.user_can_view(self.other_user))
        self.assertFalse(self.maintenance_log.user_can_edit(self.other_user))
        self.assertFalse(self.maintenance_log.user_can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access."""
        self.assertTrue(self.maintenance_log.user_can_view(self.staff_user))
        self.assertTrue(self.maintenance_log.user_can_edit(self.staff_user))
        self.assertTrue(self.maintenance_log.user_can_delete(self.staff_user))


class InstrumentAnnotationPermissionTestCase(TestCase):
    """Test that instrument annotations inherit instrument permissions."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Spectrometer", instrument_description="Mass spectrometry system", user=self.owner
        )

        # Create permissions
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        # Create default folders and annotation
        self.instrument.create_default_folders()
        self.manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.owner)

        self.annotation = Annotation.objects.create(
            annotation="Instrument operating manual v2.1",
            annotation_type="document",
            folder=self.manuals_folder,
            owner=self.owner,
        )

        self.instrument_annotation = InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=self.annotation, folder=self.manuals_folder
        )

    def test_owner_has_full_access(self):
        """Test that instrument owner has full access to annotations."""
        self.assertTrue(self.instrument_annotation.can_view(self.owner))
        self.assertTrue(self.instrument_annotation.can_edit(self.owner))
        self.assertTrue(self.instrument_annotation.can_delete(self.owner))

    def test_manager_has_full_access(self):
        """Test that users with manage permissions have full access."""
        self.assertTrue(self.instrument_annotation.can_view(self.manager))
        self.assertTrue(self.instrument_annotation.can_edit(self.manager))
        self.assertTrue(self.instrument_annotation.can_delete(self.manager))

    def test_viewer_has_view_access_only(self):
        """Test that users with view permissions can only view."""
        self.assertTrue(self.instrument_annotation.can_view(self.viewer))
        self.assertFalse(self.instrument_annotation.can_edit(self.viewer))
        self.assertFalse(self.instrument_annotation.can_delete(self.viewer))

    def test_other_user_no_access(self):
        """Test that other users have no access."""
        self.assertFalse(self.instrument_annotation.can_view(self.other_user))
        self.assertFalse(self.instrument_annotation.can_edit(self.other_user))
        self.assertFalse(self.instrument_annotation.can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access."""
        self.assertTrue(self.instrument_annotation.can_view(self.staff_user))
        self.assertTrue(self.instrument_annotation.can_edit(self.staff_user))
        self.assertTrue(self.instrument_annotation.can_delete(self.staff_user))


class MaintenanceLogAnnotationPermissionTestCase(TestCase):
    """Test that maintenance log annotations inherit instrument permissions through maintenance logs."""

    def setUp(self):
        self.instrument_owner = UserFactory.create_user()
        self.maintenance_tech = UserFactory.create_user()
        self.manager = UserFactory.create_user()
        self.viewer = UserFactory.create_user()
        self.other_user = UserFactory.create_user()

        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name="Test Analyzer",
            instrument_description="Chemical analysis equipment",
            user=self.instrument_owner,
        )

        # Create permissions
        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.manager, can_view=True, can_book=True, can_manage=True
        )

        InstrumentPermission.objects.create(
            instrument=self.instrument, user=self.viewer, can_view=True, can_book=False, can_manage=False
        )

        # Create maintenance log
        self.maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="emergency",
            status="completed",
            maintenance_description="Emergency repair after malfunction",
            created_by=self.maintenance_tech,
        )

        # Create maintenance annotation
        maintenance_photo = SimpleUploadedFile(
            "repair_photo.jpg", b"fake repair completion photo", content_type="image/jpeg"
        )

        self.annotation = Annotation.objects.create(
            annotation="Repair completion photo showing fixed component",
            annotation_type="image",
            file=maintenance_photo,
            owner=self.maintenance_tech,
        )

        self.maintenance_annotation = MaintenanceLogAnnotation.objects.create(
            maintenance_log=self.maintenance_log, annotation=self.annotation
        )

    def test_maintenance_creator_has_full_access(self):
        """Test that maintenance log creator has full access to annotations."""
        self.assertTrue(self.maintenance_annotation.can_view(self.maintenance_tech))
        self.assertTrue(self.maintenance_annotation.can_edit(self.maintenance_tech))
        self.assertTrue(self.maintenance_annotation.can_delete(self.maintenance_tech))

    def test_instrument_owner_has_full_access(self):
        """Test that instrument owner has full access to maintenance annotations."""
        self.assertTrue(self.maintenance_annotation.can_view(self.instrument_owner))
        self.assertTrue(self.maintenance_annotation.can_edit(self.instrument_owner))
        self.assertTrue(self.maintenance_annotation.can_delete(self.instrument_owner))

    def test_manager_has_edit_access(self):
        """Test that users with manage permissions can edit maintenance annotations."""
        self.assertTrue(self.maintenance_annotation.can_view(self.manager))
        self.assertTrue(self.maintenance_annotation.can_edit(self.manager))
        self.assertTrue(self.maintenance_annotation.can_delete(self.manager))

    def test_viewer_has_no_access_to_maintenance_annotations(self):
        """Test that users with view permissions cannot access maintenance annotations."""
        self.assertFalse(self.maintenance_annotation.can_view(self.viewer))
        self.assertFalse(self.maintenance_annotation.can_edit(self.viewer))
        self.assertFalse(self.maintenance_annotation.can_delete(self.viewer))

    def test_other_user_no_access(self):
        """Test that other users have no access to maintenance annotations."""
        self.assertFalse(self.maintenance_annotation.can_view(self.other_user))
        self.assertFalse(self.maintenance_annotation.can_edit(self.other_user))
        self.assertFalse(self.maintenance_annotation.can_delete(self.other_user))


class InstrumentPermissionWorkflowTestCase(TestCase):
    """Test complete permission workflows with realistic scenarios."""

    def setUp(self):
        # Create users representing different roles
        self.lab_head = UserFactory.create_user()
        self.postdoc = UserFactory.create_user()
        self.grad_student = UserFactory.create_user()
        self.undergrad = UserFactory.create_user()
        self.external_user = UserFactory.create_user()

        # Create core facility instrument
        self.core_instrument = Instrument.objects.create(
            instrument_name="Core Facility LCMS",
            instrument_description="Shared liquid chromatography mass spectrometry system",
            user=self.lab_head,  # Lab head owns the instrument
        )

        # Set up realistic permissions
        # Postdoc can manage the instrument
        InstrumentPermission.objects.create(
            instrument=self.core_instrument, user=self.postdoc, can_view=True, can_book=True, can_manage=True
        )

        # Grad student can book and use
        InstrumentPermission.objects.create(
            instrument=self.core_instrument, user=self.grad_student, can_view=True, can_book=True, can_manage=False
        )

        # Undergrad can only view (must be supervised)
        InstrumentPermission.objects.create(
            instrument=self.core_instrument, user=self.undergrad, can_view=True, can_book=False, can_manage=False
        )

    def test_lab_head_oversight(self):
        """Test that lab head (owner) has complete oversight."""
        # Lab head should have all permissions
        self.assertTrue(self.core_instrument.user_can_view(self.lab_head))
        self.assertTrue(self.core_instrument.user_can_book(self.lab_head))
        self.assertTrue(self.core_instrument.user_can_manage(self.lab_head))

        # Create maintenance log as lab head
        maintenance = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="pending",
            maintenance_description="Annual calibration and service",
            created_by=self.lab_head,
        )

        # Lab head should have full access to maintenance
        self.assertTrue(maintenance.user_can_view(self.lab_head))
        self.assertTrue(maintenance.user_can_edit(self.lab_head))
        self.assertTrue(maintenance.user_can_delete(self.lab_head))

    def test_postdoc_management_workflow(self):
        """Test postdoc management capabilities."""
        # Postdoc should have management access
        self.assertTrue(self.core_instrument.user_can_view(self.postdoc))
        self.assertTrue(self.core_instrument.user_can_book(self.postdoc))
        self.assertTrue(self.core_instrument.user_can_manage(self.postdoc))

        # Postdoc creates maintenance log
        maintenance = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Weekly cleaning and prep",
            created_by=self.postdoc,
        )

        # Postdoc should have full access to their maintenance logs
        self.assertTrue(maintenance.user_can_view(self.postdoc))
        self.assertTrue(maintenance.user_can_edit(self.postdoc))
        self.assertTrue(maintenance.user_can_delete(self.postdoc))

        # Grad student (without manage permission) cannot view maintenance logs
        self.assertFalse(maintenance.user_can_view(self.grad_student))
        self.assertFalse(maintenance.user_can_edit(self.grad_student))
        self.assertFalse(maintenance.user_can_delete(self.grad_student))

    def test_grad_student_booking_workflow(self):
        """Test grad student booking and usage workflow."""
        # Grad student can book but not manage
        self.assertTrue(self.core_instrument.user_can_view(self.grad_student))
        self.assertTrue(self.core_instrument.user_can_book(self.grad_student))
        self.assertFalse(self.core_instrument.user_can_manage(self.grad_student))

        # Grad student creates maintenance report (like usage notes)
        usage_log = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="other",
            status="completed",
            maintenance_description="Sample run completed, no issues observed",
            created_by=self.grad_student,
        )

        # Grad student should have full access to their own logs
        self.assertTrue(usage_log.user_can_view(self.grad_student))
        self.assertTrue(usage_log.user_can_edit(self.grad_student))
        self.assertTrue(usage_log.user_can_delete(self.grad_student))

        # But postdoc (with management rights) should also have edit access
        self.assertTrue(usage_log.user_can_view(self.postdoc))
        self.assertTrue(usage_log.user_can_edit(self.postdoc))  # Can edit because has manage permission
        self.assertTrue(usage_log.user_can_delete(self.postdoc))

    def test_undergrad_view_only_workflow(self):
        """Test undergrad view-only access."""
        # Undergrad can only view, not book or manage
        self.assertTrue(self.core_instrument.user_can_view(self.undergrad))
        self.assertFalse(self.core_instrument.user_can_book(self.undergrad))
        self.assertFalse(self.core_instrument.user_can_manage(self.undergrad))

        # Create maintenance by grad student
        maintenance = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Daily startup and calibration check",
            created_by=self.grad_student,
        )

        # Undergrad (without manage permission) cannot view maintenance logs
        self.assertFalse(maintenance.user_can_view(self.undergrad))
        self.assertFalse(maintenance.user_can_edit(self.undergrad))
        self.assertFalse(maintenance.user_can_delete(self.undergrad))

    def test_external_user_blocked(self):
        """Test that external users have no access."""
        # External user should have no access
        self.assertFalse(self.core_instrument.user_can_view(self.external_user))
        self.assertFalse(self.core_instrument.user_can_book(self.external_user))
        self.assertFalse(self.core_instrument.user_can_manage(self.external_user))

        # Create maintenance log
        maintenance = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Service technician visit",
            created_by=self.lab_head,
        )

        # External user should have no access to maintenance logs
        self.assertFalse(maintenance.user_can_view(self.external_user))
        self.assertFalse(maintenance.user_can_edit(self.external_user))
        self.assertFalse(maintenance.user_can_delete(self.external_user))

    def test_permission_changes_propagate(self):
        """Test that changing permissions affects access to existing content."""
        # Create maintenance log when undergrad has only view access
        maintenance = MaintenanceLog.objects.create(
            instrument=self.core_instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="pending",
            maintenance_description="Scheduled maintenance",
            created_by=self.postdoc,
        )

        # Initially undergrad cannot view (only has view permission, not manage)
        self.assertFalse(maintenance.user_can_view(self.undergrad))
        self.assertFalse(maintenance.user_can_edit(self.undergrad))

        # Grant manage permission
        undergrad_permission = InstrumentPermission.objects.get(instrument=self.core_instrument, user=self.undergrad)
        undergrad_permission.can_manage = True
        undergrad_permission.save()

        # Now undergrad should have full access
        self.assertTrue(maintenance.user_can_view(self.undergrad))
        self.assertTrue(maintenance.user_can_edit(self.undergrad))
        self.assertTrue(maintenance.user_can_delete(self.undergrad))

        # Remove manage permission
        undergrad_permission.can_manage = False
        undergrad_permission.save()

        # Now undergrad should have no access again
        self.assertFalse(maintenance.user_can_view(self.undergrad))
        self.assertFalse(maintenance.user_can_edit(self.undergrad))
