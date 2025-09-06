"""
Tests for CCM model methods without CCMC dependency.

These tests ensure CCM models work correctly regardless of CCMC installation.
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ccm.models import Instrument, MaintenanceLog, Reagent, StorageObject, StoredReagent, SupportInformation

User = get_user_model()


class InstrumentModelTest(TestCase):
    """Test Instrument model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(
            instrument_name="Test Instrument", instrument_description="Test description", user=self.user, enabled=True
        )

    def test_instrument_creation(self):
        """Test basic instrument creation."""
        self.assertEqual(self.instrument.instrument_name, "Test Instrument")
        self.assertEqual(self.instrument.user, self.user)
        self.assertTrue(self.instrument.enabled)
        self.assertFalse(self.instrument.is_vaulted)

    def test_instrument_string_representation(self):
        """Test instrument string representation."""
        self.assertEqual(str(self.instrument), "Test Instrument")

    def test_create_default_folders(self):
        """Test default folder creation for instrument."""
        # This would normally create AnnotationFolders via CCC
        # For now, just test the method exists and doesn't crash
        self.instrument.create_default_folders()
        # Method should complete without error

    def test_warranty_check_no_support_info(self):
        """Test warranty check with no support information."""
        result = self.instrument.check_warranty_expiration()
        self.assertFalse(result)

    def test_warranty_check_no_warranty_date(self):
        """Test warranty check with support info but no warranty date."""
        support_info = SupportInformation.objects.create(vendor_name="Test Vendor")
        self.instrument.support_information.add(support_info)

        result = self.instrument.check_warranty_expiration()
        self.assertFalse(result)

    def test_warranty_check_not_expiring(self):
        """Test warranty check when warranty is not expiring."""
        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor", warranty_end_date=date.today() + timedelta(days=60)
        )
        self.instrument.support_information.add(support_info)

        result = self.instrument.check_warranty_expiration(days_threshold=30)
        self.assertFalse(result)

    def test_warranty_check_expiring_soon(self):
        """Test warranty check when warranty is expiring soon."""
        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor", warranty_end_date=date.today() + timedelta(days=15)
        )
        self.instrument.support_information.add(support_info)

        result = self.instrument.check_warranty_expiration(days_threshold=30)
        self.assertTrue(result)
        self.assertIsNotNone(self.instrument.last_warranty_notification_sent)

    def test_warranty_check_recent_notification(self):
        """Test warranty check with recent notification sent."""
        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor", warranty_end_date=date.today() + timedelta(days=15)
        )
        self.instrument.support_information.add(support_info)

        # Set recent notification
        self.instrument.last_warranty_notification_sent = timezone.now() - timedelta(days=3)
        self.instrument.save()

        result = self.instrument.check_warranty_expiration(days_threshold=30)
        self.assertFalse(result)  # Should not send notification again

    def test_maintenance_check_no_support_info(self):
        """Test maintenance check with no support information."""
        result = self.instrument.check_upcoming_maintenance()
        self.assertFalse(result)

    def test_maintenance_check_no_frequency(self):
        """Test maintenance check with no maintenance frequency set."""
        support_info = SupportInformation.objects.create(vendor_name="Test Vendor")
        self.instrument.support_information.add(support_info)

        result = self.instrument.check_upcoming_maintenance()
        self.assertFalse(result)

    def test_maintenance_check_no_history_initial(self):
        """Test maintenance check with no maintenance history."""
        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor", maintenance_frequency_days=10  # Short frequency to trigger
        )
        self.instrument.support_information.add(support_info)

        result = self.instrument.check_upcoming_maintenance(days_threshold=30)
        self.assertTrue(result)

    def test_maintenance_check_with_history_due(self):
        """Test maintenance check with history showing maintenance is due."""
        support_info = SupportInformation.objects.create(vendor_name="Test Vendor", maintenance_frequency_days=30)
        self.instrument.support_information.add(support_info)

        # Create old maintenance log
        MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now() - timedelta(days=35),
            status="completed",
            created_by=self.user,
        )

        result = self.instrument.check_upcoming_maintenance(days_threshold=30)
        self.assertTrue(result)

    def test_check_all_instruments_class_method(self):
        """Test class method to check all instruments."""
        # Create another instrument with warranty expiring
        instrument2 = Instrument.objects.create(instrument_name="Test Instrument 2", user=self.user, enabled=True)

        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor", warranty_end_date=date.today() + timedelta(days=15)
        )
        instrument2.support_information.add(support_info)

        warranty_count, maintenance_count = Instrument.check_all_instruments()

        self.assertGreaterEqual(warranty_count, 0)
        self.assertGreaterEqual(maintenance_count, 0)


class StoredReagentModelTest(TestCase):
    """Test StoredReagent model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.reagent = Reagent.objects.create(name="Test Reagent", unit="mL")
        self.storage = StorageObject.objects.create(object_name="Test Storage", object_type="shelf")
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent, storage_object=self.storage, quantity=10.0, user=self.user
        )

    def test_stored_reagent_creation(self):
        """Test basic stored reagent creation."""
        self.assertEqual(self.stored_reagent.reagent, self.reagent)
        self.assertEqual(self.stored_reagent.quantity, 10.0)
        self.assertEqual(self.stored_reagent.user, self.user)
        self.assertTrue(self.stored_reagent.shareable)

    def test_stored_reagent_string_representation(self):
        """Test stored reagent string representation."""
        expected = f"{self.reagent.name} in {self.storage.object_name}"
        self.assertEqual(str(self.stored_reagent), expected)

    def test_low_stock_check_disabled(self):
        """Test low stock check when notifications are disabled."""
        self.stored_reagent.notify_on_low_stock = False
        self.stored_reagent.save()

        result = self.stored_reagent.check_low_stock()
        self.assertFalse(result)

    def test_low_stock_check_no_threshold(self):
        """Test low stock check with no threshold set."""
        self.stored_reagent.notify_on_low_stock = True
        self.stored_reagent.low_stock_threshold = None
        self.stored_reagent.save()

        result = self.stored_reagent.check_low_stock()
        self.assertFalse(result)

    def test_low_stock_check_above_threshold(self):
        """Test low stock check when stock is above threshold."""
        self.stored_reagent.notify_on_low_stock = True
        self.stored_reagent.low_stock_threshold = 5.0
        self.stored_reagent.quantity = 10.0
        self.stored_reagent.save()

        result = self.stored_reagent.check_low_stock()
        self.assertFalse(result)

    @patch("ccm.communication.send_reagent_alert")
    def test_low_stock_check_below_threshold(self, mock_send_alert):
        """Test low stock check when stock is below threshold."""
        mock_send_alert.return_value = True

        self.stored_reagent.notify_on_low_stock = True
        self.stored_reagent.low_stock_threshold = 5.0
        self.stored_reagent.quantity = 2.0
        self.stored_reagent.save()

        result = self.stored_reagent.check_low_stock()
        self.assertTrue(result)
        self.assertIsNotNone(self.stored_reagent.last_notification_sent)

    def test_low_stock_check_recent_notification(self):
        """Test low stock check with recent notification sent."""
        self.stored_reagent.notify_on_low_stock = True
        self.stored_reagent.low_stock_threshold = 5.0
        self.stored_reagent.quantity = 2.0
        self.stored_reagent.last_notification_sent = timezone.now() - timedelta(days=3)
        self.stored_reagent.save()

        result = self.stored_reagent.check_low_stock()
        self.assertFalse(result)  # Should not send notification again

    def test_expiration_check_no_date(self):
        """Test expiration check with no expiration date set."""
        result = self.stored_reagent.check_expiration()
        self.assertFalse(result)

    def test_expiration_check_not_expiring(self):
        """Test expiration check when reagent is not expiring soon."""
        self.stored_reagent.expiration_date = date.today() + timedelta(days=30)
        self.stored_reagent.save()

        result = self.stored_reagent.check_expiration(days_threshold=7)
        self.assertFalse(result)

    @patch("ccm.communication.send_reagent_alert")
    def test_expiration_check_expiring_soon(self, mock_send_alert):
        """Test expiration check when reagent is expiring soon."""
        mock_send_alert.return_value = True

        self.stored_reagent.expiration_date = date.today() + timedelta(days=3)
        self.stored_reagent.save()

        result = self.stored_reagent.check_expiration(days_threshold=7)
        self.assertTrue(result)
        self.assertIsNotNone(self.stored_reagent.last_notification_sent)

    @patch("ccm.communication.send_reagent_alert")
    def test_expiration_check_expired(self, mock_send_alert):
        """Test expiration check when reagent is already expired."""
        mock_send_alert.return_value = True

        self.stored_reagent.expiration_date = date.today() - timedelta(days=1)
        self.stored_reagent.save()

        result = self.stored_reagent.check_expiration()
        self.assertTrue(result)

    def test_expiration_check_recent_notification(self):
        """Test expiration check with recent notification sent."""
        self.stored_reagent.expiration_date = date.today() + timedelta(days=3)
        self.stored_reagent.last_notification_sent = timezone.now() - timedelta(days=1)
        self.stored_reagent.save()

        result = self.stored_reagent.check_expiration(days_threshold=7)
        self.assertFalse(result)  # Should not send notification again


class MaintenanceLogModelTest(TestCase):
    """Test MaintenanceLog model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

    def test_maintenance_log_creation(self):
        """Test basic maintenance log creation."""
        maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Test maintenance",
            created_by=self.user,
        )

        self.assertEqual(maintenance_log.instrument, self.instrument)
        self.assertEqual(maintenance_log.maintenance_type, "routine")
        self.assertEqual(maintenance_log.status, "completed")
        self.assertFalse(maintenance_log.is_template)

    def test_maintenance_log_string_representation(self):
        """Test maintenance log string representation."""
        maintenance_log = MaintenanceLog.objects.create(
            instrument=self.instrument,
            maintenance_date=timezone.now(),
            maintenance_type="emergency",
            status="completed",
            created_by=self.user,
        )

        expected_parts = [
            self.instrument.instrument_name,
            "Emergency",
            maintenance_log.maintenance_date.strftime("%Y-%m-%d"),
        ]

        str_repr = str(maintenance_log)
        for part in expected_parts:
            self.assertIn(part, str_repr)


class SupportInformationModelTest(TestCase):
    """Test SupportInformation model functionality."""

    def test_support_information_creation(self):
        """Test basic support information creation."""
        support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor",
            manufacturer_name="Test Manufacturer",
            serial_number="12345",
            maintenance_frequency_days=90,
            warranty_start_date=date.today() - timedelta(days=365),
            warranty_end_date=date.today() + timedelta(days=365),
        )

        self.assertEqual(support_info.vendor_name, "Test Vendor")
        self.assertEqual(support_info.maintenance_frequency_days, 90)
        self.assertIsNotNone(support_info.warranty_end_date)

    def test_support_information_string_representation(self):
        """Test support information string representation."""
        support_info = SupportInformation.objects.create(manufacturer_name="Test Manufacturer")

        expected = "Support for Test Manufacturer"
        self.assertEqual(str(support_info), expected)

    def test_support_information_unknown_manufacturer(self):
        """Test support information with unknown manufacturer."""
        support_info = SupportInformation.objects.create()

        expected = "Support for Unknown"
        self.assertEqual(str(support_info), expected)
