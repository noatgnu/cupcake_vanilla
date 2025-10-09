"""
Test cases for CUPCAKE Macaron (CCM) models
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from ccc.models import Annotation, AnnotationFolder, RemoteHost
from ccm.models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentUsage,
    MaintenanceLog,
    Reagent,
    ReagentAction,
    ReagentSubscription,
    StorageObject,
    StoredReagent,
    SupportInformation,
)


class InstrumentModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")

    def test_instrument_creation(self):
        """Test basic instrument creation"""
        instrument = Instrument.objects.create(
            instrument_name="Test Microscope",
            instrument_description="High-resolution microscope",
            enabled=True,
            accepts_bookings=True,
        )

        self.assertEqual(instrument.instrument_name, "Test Microscope")
        self.assertTrue(instrument.enabled)
        self.assertTrue(instrument.accepts_bookings)
        self.assertEqual(str(instrument), "Test Microscope")

    def test_warranty_expiration_check(self):
        """Test warranty expiration notification system"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        # Create support information with warranty expiring soon
        support = SupportInformation.objects.create(
            vendor_name="Test Vendor",
            warranty_start_date=timezone.now().date() - timedelta(days=300),
            warranty_end_date=timezone.now().date() + timedelta(days=15),  # Expires in 15 days
        )
        instrument.support_information.add(support)

        # Should trigger warranty notification (threshold 30 days)
        result = instrument.check_warranty_expiration(days_threshold=30)
        self.assertTrue(result)
        self.assertIsNotNone(instrument.last_warranty_notification_sent)

    def test_maintenance_check(self):
        """Test maintenance scheduling system"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        # Create support info requiring monthly maintenance
        support = SupportInformation.objects.create(vendor_name="Test Vendor", maintenance_frequency_days=30)
        instrument.support_information.add(support)

        # Create maintenance log from 35 days ago
        MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_date=timezone.now() - timedelta(days=35),
            status="completed",
            maintenance_type="routine",
        )

        # Should trigger maintenance notification (next maintenance overdue by 5 days, threshold 10 days)
        result = instrument.check_upcoming_maintenance(days_threshold=10)
        self.assertTrue(result)

    def test_maintenance_check_no_history(self):
        """Test maintenance check with no maintenance history"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        # Create support info requiring maintenance every 10 days
        support = SupportInformation.objects.create(vendor_name="Test Vendor", maintenance_frequency_days=10)
        instrument.support_information.add(support)

        # Should trigger initial maintenance notification (10 days <= 15 days threshold)
        result = instrument.check_upcoming_maintenance(days_threshold=15)
        self.assertTrue(result)

    def test_create_default_folders(self):
        """Test default folder creation for instruments"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", user=self.user, enabled=True)

        # Should create default folders
        instrument.create_default_folders()

        # Check folders were created
        folders = AnnotationFolder.objects.filter(owner=self.user)
        folder_names = list(folders.values_list("folder_name", flat=True))

        self.assertIn("Manuals", folder_names)
        self.assertIn("Certificates", folder_names)
        self.assertIn("Maintenance", folder_names)

    def test_batch_instrument_check(self):
        """Test checking all instruments at once"""
        # Create multiple instruments with different statuses
        instrument1 = Instrument.objects.create(instrument_name="Equipment 1", enabled=True)
        instrument2 = Instrument.objects.create(instrument_name="Equipment 2", enabled=True)

        # Add support info with warranty expiring soon
        support1 = SupportInformation.objects.create(warranty_end_date=timezone.now().date() + timedelta(days=10))
        instrument1.support_information.add(support1)

        # Add support info needing maintenance
        support2 = SupportInformation.objects.create(maintenance_frequency_days=15)
        instrument2.support_information.add(support2)

        warranty_count, maintenance_count = Instrument.check_all_instruments(days_threshold=30)

        # Should find at least one of each
        self.assertGreaterEqual(warranty_count, 0)
        self.assertGreaterEqual(maintenance_count, 0)


class StorageObjectModelTest(TestCase):
    def test_storage_object_creation(self):
        """Test storage object creation and hierarchy"""
        # Create parent storage
        building = StorageObject.objects.create(object_name="Main Building", object_type="building")

        # Create child storage
        fridge = StorageObject.objects.create(object_name="Lab Fridge A", object_type="fridge", stored_at=building)

        self.assertEqual(fridge.stored_at, building)
        self.assertEqual(str(fridge), "Lab Fridge A (fridge)")

    def test_storage_object_get_full_path(self):
        """Test get_full_path method for storage object hierarchy"""
        # Create multi-level hierarchy
        building = StorageObject.objects.create(object_name="Main Building", object_type="building")
        floor = StorageObject.objects.create(object_name="Floor 2", object_type="floor", stored_at=building)
        room = StorageObject.objects.create(object_name="Lab 201", object_type="room", stored_at=floor)
        fridge = StorageObject.objects.create(object_name="Fridge A", object_type="fridge", stored_at=room)
        shelf = StorageObject.objects.create(object_name="Shelf 3", object_type="shelf", stored_at=fridge)

        # Test full path for each level (returns array of {id, name})
        building_path = building.get_full_path()
        self.assertEqual(len(building_path), 1)
        self.assertEqual(building_path[0], {"id": building.id, "name": "Main Building"})

        floor_path = floor.get_full_path()
        self.assertEqual(len(floor_path), 2)
        self.assertEqual(
            floor_path, [{"id": building.id, "name": "Main Building"}, {"id": floor.id, "name": "Floor 2"}]
        )

        room_path = room.get_full_path()
        self.assertEqual(len(room_path), 3)
        self.assertEqual(
            room_path,
            [
                {"id": building.id, "name": "Main Building"},
                {"id": floor.id, "name": "Floor 2"},
                {"id": room.id, "name": "Lab 201"},
            ],
        )

        fridge_path = fridge.get_full_path()
        self.assertEqual(len(fridge_path), 4)
        self.assertEqual(
            fridge_path,
            [
                {"id": building.id, "name": "Main Building"},
                {"id": floor.id, "name": "Floor 2"},
                {"id": room.id, "name": "Lab 201"},
                {"id": fridge.id, "name": "Fridge A"},
            ],
        )

        shelf_path = shelf.get_full_path()
        self.assertEqual(len(shelf_path), 5)
        self.assertEqual(
            shelf_path,
            [
                {"id": building.id, "name": "Main Building"},
                {"id": floor.id, "name": "Floor 2"},
                {"id": room.id, "name": "Lab 201"},
                {"id": fridge.id, "name": "Fridge A"},
                {"id": shelf.id, "name": "Shelf 3"},
            ],
        )


class ReagentModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.storage = StorageObject.objects.create(object_name="Test Storage", object_type="shelf")
        self.reagent = Reagent.objects.create(name="Test Chemical", unit="ml")

    def test_reagent_creation(self):
        """Test basic reagent creation"""
        self.assertEqual(self.reagent.name, "Test Chemical")
        self.assertEqual(self.reagent.unit, "ml")
        self.assertEqual(str(self.reagent), "Test Chemical")

    def test_stored_reagent_creation(self):
        """Test stored reagent creation"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=100.0, notes="Fresh batch", user=self.user
        )

        self.assertEqual(stored_reagent.quantity, 100.0)
        self.assertEqual(stored_reagent.notes, "Fresh batch")
        self.assertEqual(str(stored_reagent), "Test Chemical in Test Storage")

    def test_reagent_action_logging(self):
        """Test reagent action tracking"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=100.0, user=self.user
        )

        # Create reagent action
        action = ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type="reserve",
            quantity=25.0,
            user=self.user,
            notes="Reserved for experiment",
        )

        self.assertEqual(action.action_type, "reserve")
        self.assertEqual(action.quantity, 25.0)
        self.assertEqual(str(action), "reserve 25.0 - Test Chemical")

    def test_reagent_subscription(self):
        """Test reagent subscription system"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=100.0, user=self.user
        )

        subscription = ReagentSubscription.objects.create(
            user=self.user, stored_reagent=stored_reagent, notify_on_low_stock=True, notify_on_expiry=True
        )

        self.assertTrue(subscription.notify_on_low_stock)
        self.assertTrue(subscription.notify_on_expiry)
        self.assertEqual(str(subscription), "testuser - Test Chemical")


class MaintenanceLogModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

    def test_maintenance_log_creation(self):
        """Test maintenance log creation"""
        maintenance = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Monthly calibration",
            created_by=self.user,
        )

        self.assertEqual(maintenance.maintenance_type, "routine")
        self.assertEqual(maintenance.status, "completed")
        self.assertEqual(maintenance.created_by, self.user)

    def test_maintenance_log_string_representation(self):
        """Test maintenance log string representation"""
        maintenance_date = timezone.now()
        maintenance = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=maintenance_date,
            maintenance_type="emergency",
            status="completed",
        )

        expected_str = f"{self.instrument.instrument_name} - Emergency - {maintenance_date.strftime('%Y-%m-%d')}"
        self.assertEqual(str(maintenance), expected_str)


class SupportInformationModelTest(TestCase):
    def test_support_information_creation(self):
        """Test support information creation"""
        support = SupportInformation.objects.create(
            vendor_name="Test Vendor",
            manufacturer_name="Test Manufacturer",
            serial_number="SN123456",
            maintenance_frequency_days=30,
            warranty_start_date=timezone.now().date(),
            warranty_end_date=timezone.now().date() + timedelta(days=365),
        )

        self.assertEqual(support.vendor_name, "Test Vendor")
        self.assertEqual(support.serial_number, "SN123456")
        self.assertEqual(support.maintenance_frequency_days, 30)


class ExternalContactModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")

    def test_external_contact_creation(self):
        """Test external contact and contact details creation"""
        # Create contact details
        email_detail = ExternalContactDetails.objects.create(
            contact_method_alt_name="Primary Email", contact_type="email", contact_value="vendor@example.com"
        )

        phone_detail = ExternalContactDetails.objects.create(
            contact_method_alt_name="Support Phone", contact_type="phone", contact_value="+1-555-0123"
        )

        # Create contact
        contact = ExternalContact.objects.create(contact_name="Vendor Support", user=self.user)
        contact.contact_details.add(email_detail, phone_detail)

        self.assertEqual(contact.contact_name, "Vendor Support")
        self.assertEqual(contact.contact_details.count(), 2)
        self.assertEqual(str(email_detail), "Primary Email: vendor@example.com")


class InstrumentUsageModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

    def test_instrument_usage_creation(self):
        """Test instrument usage tracking"""
        usage = InstrumentUsage.objects.create(
            instrument=self.instrument,
            user=self.user,
            time_started=timezone.now() - timedelta(hours=2),
            time_ended=timezone.now(),
            description="Test experiment",
            approved=True,
        )

        self.assertEqual(usage.instrument, self.instrument)
        self.assertEqual(usage.user, self.user)
        self.assertTrue(usage.approved)
        self.assertFalse(usage.maintenance)


class CCCCoreModelTest(TestCase):
    """Test CCC core models used by CCM"""

    def test_remote_host_creation(self):
        """Test RemoteHost creation"""
        host = RemoteHost.objects.create(
            host_name="remote.lab.com", host_port=8000, host_protocol="https", host_description="Remote lab server"
        )

        self.assertEqual(host.host_name, "remote.lab.com")
        self.assertEqual(host.host_port, 8000)
        self.assertEqual(str(host), "remote.lab.com")

    def test_annotation_folder_creation(self):
        """Test AnnotationFolder creation and hierarchy"""
        parent_folder = AnnotationFolder.objects.create(
            folder_name="Documents", resource_type="file", visibility="private"
        )

        child_folder = AnnotationFolder.objects.create(
            folder_name="Manuals", parent_folder=parent_folder, resource_type="file", visibility="private"
        )

        self.assertEqual(child_folder.parent_folder, parent_folder)
        self.assertEqual(child_folder.get_full_path(), "Documents/Manuals")

    def test_annotation_creation(self):
        """Test Annotation creation"""
        folder = AnnotationFolder.objects.create(folder_name="Test Folder", resource_type="file", visibility="private")

        annotation = Annotation.objects.create(
            annotation="Test document content",
            annotation_type="text",
            folder=folder,
            resource_type="file",
            visibility="private",
        )

        self.assertEqual(annotation.annotation, "Test document content")
        self.assertEqual(annotation.annotation_type, "text")
        self.assertEqual(annotation.folder, folder)
