"""
Tests for StorageObject lab group access permission inheritance.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from ccc.models import LabGroup
from ccm.models import StorageObject

User = get_user_model()


class StorageObjectLabGroupAccessTestCase(TestCase):
    """Test lab group access inheritance for storage objects."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.user3 = User.objects.create_user("user3", "user3@test.com", "password")
        self.creator = User.objects.create_user("creator", "creator@test.com", "password")

        self.lab_group1 = LabGroup.objects.create(name="Lab Group 1", creator=self.creator)
        self.lab_group1.members.add(self.user1)

        self.lab_group2 = LabGroup.objects.create(name="Lab Group 2", creator=self.creator)
        self.lab_group2.members.add(self.user2)

    def test_direct_lab_group_access(self):
        """Test that user can access storage object with direct lab group access."""
        storage_obj = StorageObject.objects.create(object_name="Root Storage", object_type="freezer", user=self.creator)
        storage_obj.access_lab_groups.add(self.lab_group1)

        self.assertTrue(storage_obj.can_access(self.user1))
        self.assertFalse(storage_obj.can_access(self.user2))
        self.assertTrue(storage_obj.can_access(self.creator))

    def test_inherited_lab_group_access_from_parent(self):
        """Test that child storage objects inherit lab group access from parent."""
        parent = StorageObject.objects.create(object_name="Parent Freezer", object_type="freezer", user=self.creator)
        parent.access_lab_groups.add(self.lab_group1)

        child = StorageObject.objects.create(
            object_name="Child Shelf", object_type="shelf", stored_at=parent, user=self.creator
        )

        self.assertTrue(child.can_access(self.user1))
        self.assertFalse(child.can_access(self.user2))

    def test_inherited_lab_group_access_from_grandparent(self):
        """Test that access inherits through multiple levels."""
        grandparent = StorageObject.objects.create(object_name="Freezer Room", object_type="room", user=self.creator)
        grandparent.access_lab_groups.add(self.lab_group1)

        parent = StorageObject.objects.create(
            object_name="Freezer", object_type="freezer", stored_at=grandparent, user=self.creator
        )

        child = StorageObject.objects.create(
            object_name="Shelf", object_type="shelf", stored_at=parent, user=self.creator
        )

        self.assertTrue(child.can_access(self.user1))
        self.assertFalse(child.can_access(self.user2))

    def test_combined_lab_group_access(self):
        """Test that child can have additional lab groups beyond parent's."""
        parent = StorageObject.objects.create(object_name="Parent", object_type="freezer", user=self.creator)
        parent.access_lab_groups.add(self.lab_group1)

        child = StorageObject.objects.create(
            object_name="Child", object_type="shelf", stored_at=parent, user=self.creator
        )
        child.access_lab_groups.add(self.lab_group2)

        self.assertTrue(child.can_access(self.user1))
        self.assertTrue(child.can_access(self.user2))
        self.assertFalse(child.can_access(self.user3))

    def test_get_all_accessible_lab_groups(self):
        """Test that get_all_accessible_lab_groups returns inherited groups."""
        parent = StorageObject.objects.create(object_name="Parent", object_type="freezer", user=self.creator)
        parent.access_lab_groups.add(self.lab_group1)

        child = StorageObject.objects.create(
            object_name="Child", object_type="shelf", stored_at=parent, user=self.creator
        )
        child.access_lab_groups.add(self.lab_group2)

        accessible_groups = child.get_all_accessible_lab_groups()
        self.assertEqual(accessible_groups.count(), 2)
        self.assertIn(self.lab_group1, accessible_groups)
        self.assertIn(self.lab_group2, accessible_groups)

    def test_owner_always_has_access(self):
        """Test that owner always has access regardless of lab groups."""
        storage_obj = StorageObject.objects.create(object_name="Storage", object_type="freezer", user=self.user1)

        self.assertTrue(storage_obj.can_access(self.user1))
        self.assertFalse(storage_obj.can_access(self.user2))

    def test_staff_always_has_access(self):
        """Test that staff users always have access."""
        staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

        storage_obj = StorageObject.objects.create(object_name="Storage", object_type="freezer", user=self.user1)

        self.assertTrue(storage_obj.can_access(staff_user))
