"""
Test cases for CUPCAKE Macaron (CCM) admin interfaces
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from ccm.models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    MaintenanceLog,
    Reagent,
    StorageObject,
    StoredReagent,
    SupportInformation,
)


class CCMAdminTest(TestCase):
    def setUp(self):
        # Create admin user
        self.admin_user = User.objects.create_superuser(username="admin", email="admin@test.com", password="admin123")

        # Create regular user
        self.user = User.objects.create_user(username="testuser", password="testpass123")

        self.client = Client()
        self.client.login(username="admin", password="admin123")

    def test_instrument_admin_access(self):
        """Test instrument admin interface access"""
        # Create test instrument
        instrument = Instrument.objects.create(
            instrument_name="Test Microscope", instrument_description="Testing admin interface", enabled=True
        )

        # Test admin list view
        response = self.client.get("/admin/ccm/instrument/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Microscope")

        # Test admin detail view
        response = self.client.get(f"/admin/ccm/instrument/{instrument.id}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Microscope")

    def test_instrument_admin_filtering(self):
        """Test instrument admin filtering functionality"""
        # Create instruments with different statuses
        Instrument.objects.create(instrument_name="Enabled Instrument", enabled=True, accepts_bookings=True)

        Instrument.objects.create(instrument_name="Disabled Instrument", enabled=False, accepts_bookings=False)

        # Test filtering by enabled status
        response = self.client.get("/admin/ccm/instrument/?enabled__exact=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enabled Instrument")
        self.assertNotContains(response, "Disabled Instrument")

    def test_storage_object_admin_access(self):
        """Test storage object admin interface"""
        StorageObject.objects.create(
            object_name="Test Fridge", object_type="fridge", object_description="Testing storage admin"
        )

        response = self.client.get("/admin/ccm/storageobject/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Fridge")

    def test_reagent_admin_access(self):
        """Test reagent admin interface"""
        Reagent.objects.create(name="Test Chemical", unit="ml")

        response = self.client.get("/admin/ccm/reagent/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Chemical")

    def test_stored_reagent_admin_access(self):
        """Test stored reagent admin interface"""
        reagent = Reagent.objects.create(name="Test Chemical", unit="ml")
        storage = StorageObject.objects.create(object_name="Test Storage", object_type="shelf")

        StoredReagent.objects.create(reagent=reagent, storage_object=storage, quantity=100.0, user=self.user)

        response = self.client.get("/admin/ccm/storedreagent/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Chemical")

    def test_maintenance_log_admin_access(self):
        """Test maintenance log admin interface"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Test maintenance",
            created_by=self.user,
        )

        response = self.client.get("/admin/ccm/maintenancelog/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Equipment")

    def test_maintenance_log_admin_date_hierarchy(self):
        """Test maintenance log date hierarchy in admin"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        # Create maintenance logs from different months
        MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_date=timezone.now() - timedelta(days=60),
            maintenance_type="routine",
            status="completed",
        )

        MaintenanceLog.objects.create(
            instrument=instrument, maintenance_date=timezone.now(), maintenance_type="routine", status="completed"
        )

        response = self.client.get("/admin/ccm/maintenancelog/")
        self.assertEqual(response.status_code, 200)

        # Check that date hierarchy is present
        self.assertContains(response, str(timezone.now().year))

    def test_support_information_admin_access(self):
        """Test support information admin interface"""
        SupportInformation.objects.create(
            vendor_name="Test Vendor", manufacturer_name="Test Manufacturer", serial_number="SN123456"
        )

        response = self.client.get("/admin/ccm/supportinformation/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Vendor")

    def test_external_contact_admin_access(self):
        """Test external contact admin interface"""
        ExternalContact.objects.create(contact_name="Test Contact", user=self.user)

        response = self.client.get("/admin/ccm/externalcontact/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Contact")

    def test_external_contact_details_admin_access(self):
        """Test external contact details admin interface"""
        ExternalContactDetails.objects.create(
            contact_method_alt_name="Primary Email", contact_type="email", contact_value="test@example.com"
        )

        response = self.client.get("/admin/ccm/externalcontactdetails/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Primary Email")

    def test_admin_search_functionality(self):
        """Test admin search functionality"""
        # Create instruments with searchable content
        Instrument.objects.create(
            instrument_name="Unique Microscope Model X", instrument_description="Special equipment for testing"
        )

        # Test search in instrument admin
        response = self.client.get("/admin/ccm/instrument/?q=Unique")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unique Microscope")

    def test_admin_readonly_fields(self):
        """Test that readonly fields are properly configured"""
        instrument = Instrument.objects.create(instrument_name="Test Equipment", enabled=True)

        response = self.client.get(f"/admin/ccm/instrument/{instrument.id}/change/")
        self.assertEqual(response.status_code, 200)

        # Check that created_at and updated_at are present (readonly)
        self.assertContains(response, "Created at")
        self.assertContains(response, "Updated at")

    def test_non_admin_user_access_denied(self):
        """Test that non-admin users cannot access admin interfaces"""
        # Login as regular user
        self.client.logout()
        self.client.login(username="testuser", password="testpass123")

        # Try to access admin
        response = self.client.get("/admin/ccm/instrument/")

        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])

    def test_admin_bulk_actions(self):
        """Test admin bulk actions if any are configured"""
        # Create multiple instruments
        instruments = []
        for i in range(3):
            instrument = Instrument.objects.create(instrument_name=f"Test Instrument {i}", enabled=True)
            instruments.append(instrument)

        response = self.client.get("/admin/ccm/instrument/")
        self.assertEqual(response.status_code, 200)

        # Check that all instruments are listed
        for instrument in instruments:
            self.assertContains(response, instrument.instrument_name)
