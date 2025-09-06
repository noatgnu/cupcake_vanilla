"""
Tests for annotation permission inheritance system.

Tests that annotation access and edit permissions properly inherit from
the parent objects they are bound to (Instruments, StoredReagents, MaintenanceLogs).
"""

from django.contrib.auth.models import User
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


class InstrumentAnnotationPermissionTestCase(TestCase):
    """Test permission inheritance for instrument annotations."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument owned by owner
        self.instrument = Instrument.objects.create(
            instrument_name="Test HPLC",
            instrument_description="Test instrument for permission testing",
            user=self.owner,
        )

        # Create default folders and annotation
        self.instrument.create_default_folders()
        self.manuals_folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.owner)

        self.annotation = Annotation.objects.create(
            annotation="Instrument manual", annotation_type="document", folder=self.manuals_folder, owner=self.owner
        )

        self.instrument_annotation = InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=self.annotation, folder=self.manuals_folder
        )

    def test_owner_has_full_access(self):
        """Test that instrument owner has full access to annotations."""
        # Owner should have full access
        self.assertTrue(self.instrument_annotation.can_view(self.owner))
        self.assertTrue(self.instrument_annotation.can_edit(self.owner))
        self.assertTrue(self.instrument_annotation.can_delete(self.owner))

    def test_other_user_has_no_access(self):
        """Test that other users have no access to instrument annotations."""
        # Other user should have no access
        self.assertFalse(self.instrument_annotation.can_view(self.other_user))
        self.assertFalse(self.instrument_annotation.can_edit(self.other_user))
        self.assertFalse(self.instrument_annotation.can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access to all instrument annotations."""
        # Staff should have full access
        self.assertTrue(self.instrument_annotation.can_view(self.staff_user))
        self.assertTrue(self.instrument_annotation.can_edit(self.staff_user))
        self.assertTrue(self.instrument_annotation.can_delete(self.staff_user))

    def test_unauthenticated_user_has_no_access(self):
        """Test that unauthenticated users have no access."""
        # None/unauthenticated should have no access
        self.assertFalse(self.instrument_annotation.can_view(None))
        self.assertFalse(self.instrument_annotation.can_edit(None))
        self.assertFalse(self.instrument_annotation.can_delete(None))


class StoredReagentAnnotationPermissionTestCase(TestCase):
    """Test permission inheritance for stored reagent annotations with sharing."""

    def setUp(self):
        self.owner = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.shared_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create reagent and storage
        self.reagent = Reagent.objects.create(name="Test Buffer", unit="mL")
        self.storage = StorageObject.objects.create(object_name="Test Storage", object_type="fridge")

        # Create stored reagent owned by owner
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            quantity=100.0,
            user=self.owner,
            shareable=True,  # Enable sharing
        )

        # Add shared user to access list
        self.stored_reagent.access_users.add(self.shared_user)

        # Create default folders and annotation
        self.stored_reagent.create_default_folders()
        self.msds_folder = AnnotationFolder.objects.get(folder_name="MSDS", owner=self.owner)

        self.msds_annotation = Annotation.objects.create(
            annotation="Safety data sheet", annotation_type="document", folder=self.msds_folder, owner=self.owner
        )

        self.reagent_annotation = StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=self.msds_annotation, folder=self.msds_folder
        )

    def test_owner_has_full_access(self):
        """Test that reagent owner has full access to annotations."""
        # Owner should have full access
        self.assertTrue(self.reagent_annotation.can_view(self.owner))
        self.assertTrue(self.reagent_annotation.can_edit(self.owner))
        self.assertTrue(self.reagent_annotation.can_delete(self.owner))

    def test_shared_user_has_view_access_only(self):
        """Test that shared users have view access but not edit."""
        # Shared user should have view access but not edit (safety documents are read-only for shared users)
        self.assertTrue(self.reagent_annotation.can_view(self.shared_user))
        self.assertFalse(self.reagent_annotation.can_edit(self.shared_user))
        self.assertFalse(self.reagent_annotation.can_delete(self.shared_user))

    def test_other_user_has_no_access_when_not_shared(self):
        """Test that non-shared users have no access."""
        # Other user should have no access
        self.assertFalse(self.reagent_annotation.can_view(self.other_user))
        self.assertFalse(self.reagent_annotation.can_edit(self.other_user))
        self.assertFalse(self.reagent_annotation.can_delete(self.other_user))

    def test_access_all_provides_view_access(self):
        """Test that access_all flag provides view access to all users."""
        # Enable access for all
        self.stored_reagent.access_all = True
        self.stored_reagent.save()

        # Now other user should have view access
        self.assertTrue(self.reagent_annotation.can_view(self.other_user))
        self.assertFalse(self.reagent_annotation.can_edit(self.other_user))  # Still no edit
        self.assertFalse(self.reagent_annotation.can_delete(self.other_user))

    def test_non_shareable_reagent_blocks_access(self):
        """Test that non-shareable reagents block access even for shared users."""
        # Disable sharing
        self.stored_reagent.shareable = False
        self.stored_reagent.save()

        # Now shared user should have no access
        self.assertFalse(self.reagent_annotation.can_view(self.shared_user))
        self.assertFalse(self.reagent_annotation.can_edit(self.shared_user))
        self.assertFalse(self.reagent_annotation.can_delete(self.shared_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access regardless of sharing."""
        # Staff should have full access
        self.assertTrue(self.reagent_annotation.can_view(self.staff_user))
        self.assertTrue(self.reagent_annotation.can_edit(self.staff_user))
        self.assertTrue(self.reagent_annotation.can_delete(self.staff_user))


class MaintenanceLogAnnotationPermissionTestCase(TestCase):
    """Test permission inheritance for maintenance log annotations."""

    def setUp(self):
        self.instrument_owner = UserFactory.create_user()
        self.maintenance_person = UserFactory.create_user()
        self.other_user = UserFactory.create_user()
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        # Create instrument owned by instrument_owner
        self.instrument = Instrument.objects.create(
            instrument_name="Test Microscope",
            instrument_description="Test instrument for maintenance",
            user=self.instrument_owner,
        )

        # Create maintenance log by maintenance_person
        from django.utils import timezone

        self.maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Routine cleaning",
            created_by=self.maintenance_person,
        )

        # Create maintenance annotation
        self.maintenance_photo = SimpleUploadedFile("maintenance.jpg", b"fake photo content", content_type="image/jpeg")

        self.annotation = Annotation.objects.create(
            annotation="Maintenance completion photo",
            annotation_type="image",
            file=self.maintenance_photo,
            owner=self.maintenance_person,
        )

        self.maintenance_annotation = MaintenanceLogAnnotation.objects.create(
            maintenance_log=self.maintenance_log, annotation=self.annotation
        )

    def test_maintenance_creator_has_full_access(self):
        """Test that maintenance log creator has full access to annotations."""
        # Maintenance creator should have full access
        self.assertTrue(self.maintenance_annotation.can_view(self.maintenance_person))
        self.assertTrue(self.maintenance_annotation.can_edit(self.maintenance_person))
        self.assertTrue(self.maintenance_annotation.can_delete(self.maintenance_person))

    def test_instrument_owner_has_full_access(self):
        """Test that instrument owner has full access to maintenance annotations."""
        # Instrument owner should also have full access
        self.assertTrue(self.maintenance_annotation.can_view(self.instrument_owner))
        self.assertTrue(self.maintenance_annotation.can_edit(self.instrument_owner))
        self.assertTrue(self.maintenance_annotation.can_delete(self.instrument_owner))

    def test_other_user_has_no_access(self):
        """Test that other users have no access to maintenance annotations."""
        # Other user should have no access
        self.assertFalse(self.maintenance_annotation.can_view(self.other_user))
        self.assertFalse(self.maintenance_annotation.can_edit(self.other_user))
        self.assertFalse(self.maintenance_annotation.can_delete(self.other_user))

    def test_staff_has_full_access(self):
        """Test that staff users have full access to all maintenance annotations."""
        # Staff should have full access
        self.assertTrue(self.maintenance_annotation.can_view(self.staff_user))
        self.assertTrue(self.maintenance_annotation.can_edit(self.staff_user))
        self.assertTrue(self.maintenance_annotation.can_delete(self.staff_user))


class AnnotationPermissionConsistencyTestCase(TestCase):
    """Test that annotation permissions are consistent across all types."""

    def setUp(self):
        self.user1 = UserFactory.create_user()
        self.user2 = UserFactory.create_user()

        # Create instrument annotation
        self.instrument = Instrument.objects.create(instrument_name="Test Equipment", user=self.user1)
        self.instrument.create_default_folders()

        folder = AnnotationFolder.objects.get(folder_name="Manuals", owner=self.user1)
        annotation = Annotation.objects.create(
            annotation="Manual", annotation_type="document", folder=folder, owner=self.user1
        )
        self.instrument_annotation = InstrumentAnnotation.objects.create(
            instrument=self.instrument, annotation=annotation, folder=folder
        )

        # Create reagent annotation
        reagent = Reagent.objects.create(name="Test Chemical", unit="g")
        storage = StorageObject.objects.create(object_name="Lab Storage", object_type="shelf")
        self.stored_reagent = StoredReagent.objects.create(
            reagent=reagent, storage_object=storage, user=self.user1, shareable=False  # Not shared
        )
        self.stored_reagent.create_default_folders()

        msds_folder = AnnotationFolder.objects.get(folder_name="MSDS", owner=self.user1)
        msds_annotation = Annotation.objects.create(
            annotation="MSDS Document", annotation_type="document", folder=msds_folder, owner=self.user1
        )
        self.reagent_annotation = StoredReagentAnnotation.objects.create(
            stored_reagent=self.stored_reagent, annotation=msds_annotation, folder=msds_folder
        )

    def test_owner_consistency(self):
        """Test that owners have consistent access across all annotation types."""
        # User1 owns both objects, should have full access to both annotations
        self.assertTrue(self.instrument_annotation.can_view(self.user1))
        self.assertTrue(self.instrument_annotation.can_edit(self.user1))
        self.assertTrue(self.instrument_annotation.can_delete(self.user1))

        self.assertTrue(self.reagent_annotation.can_view(self.user1))
        self.assertTrue(self.reagent_annotation.can_edit(self.user1))
        self.assertTrue(self.reagent_annotation.can_delete(self.user1))

    def test_non_owner_consistency(self):
        """Test that non-owners have consistent access denial across annotation types."""
        # User2 doesn't own either object, should have no access to either annotation
        self.assertFalse(self.instrument_annotation.can_view(self.user2))
        self.assertFalse(self.instrument_annotation.can_edit(self.user2))
        self.assertFalse(self.instrument_annotation.can_delete(self.user2))

        self.assertFalse(self.reagent_annotation.can_view(self.user2))
        self.assertFalse(self.reagent_annotation.can_edit(self.user2))
        self.assertFalse(self.reagent_annotation.can_delete(self.user2))

    def test_permission_inheritance_reflects_parent_changes(self):
        """Test that annotation permissions update when parent object permissions change."""
        # Initially user2 has no access
        self.assertFalse(self.reagent_annotation.can_view(self.user2))

        # Enable sharing on stored reagent
        self.stored_reagent.shareable = True
        self.stored_reagent.access_all = True
        self.stored_reagent.save()

        # Now user2 should have view access to the annotation
        self.assertTrue(self.reagent_annotation.can_view(self.user2))
        self.assertFalse(self.reagent_annotation.can_edit(self.user2))  # Still no edit access
