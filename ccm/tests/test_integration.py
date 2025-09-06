"""
Integration tests for CUPCAKE Macaron (CCM)
Tests complete workflows and cross-model interactions
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from ccc.models import Annotation, AnnotationFolder
from ccm.models import (
    ExternalContact,
    ExternalContactDetails,
    Instrument,
    InstrumentUsage,
    MaintenanceLog,
    Reagent,
    ReagentAction,
    StorageObject,
    StoredReagent,
    SupportInformation,
)


class LabWorkflowIntegrationTest(TestCase):
    """Test complete lab workflow scenarios"""

    def setUp(self):
        self.lab_manager = User.objects.create_user(
            username="lab_manager", email="manager@lab.com", password="manager123"
        )

        self.researcher = User.objects.create_user(
            username="researcher", email="researcher@lab.com", password="researcher123"
        )

    def test_complete_instrument_lifecycle(self):
        """Test complete instrument setup and usage lifecycle"""

        # 1. Create vendor contact information
        vendor_email = ExternalContactDetails.objects.create(
            contact_method_alt_name="Sales Email", contact_type="email", contact_value="sales@microscope-corp.com"
        )

        vendor_phone = ExternalContactDetails.objects.create(
            contact_method_alt_name="Support Phone", contact_type="phone", contact_value="+1-555-MICRO"
        )

        vendor_contact = ExternalContact.objects.create(contact_name="MicroScope Corp Support", user=self.lab_manager)
        vendor_contact.contact_details.add(vendor_email, vendor_phone)

        # 2. Create support information
        support_info = SupportInformation.objects.create(
            vendor_name="MicroScope Corp",
            manufacturer_name="Precision Instruments",
            serial_number="PSI-2024-001",
            maintenance_frequency_days=90,  # Quarterly maintenance
            warranty_start_date=timezone.now().date() - timedelta(days=30),
            warranty_end_date=timezone.now().date() + timedelta(days=335),  # ~11 months
        )
        support_info.vendor_contacts.add(vendor_contact)

        # 3. Create instrument
        instrument = Instrument.objects.create(
            instrument_name="High-Resolution Microscope",
            instrument_description="Advanced imaging system for cellular research",
            enabled=True,
            accepts_bookings=True,
            max_days_ahead_pre_approval=7,
            max_days_within_usage_pre_approval=1,
            user=self.lab_manager,
        )
        instrument.support_information.add(support_info)

        # 4. Create default folders
        instrument.create_default_folders()

        # 5. Add manual to instrument folder
        manual_folder = AnnotationFolder.objects.filter(folder_name="Manuals", owner=self.lab_manager).first()

        manual = Annotation.objects.create(
            annotation="User manual for high-resolution microscope",
            annotation_type="file",
            folder=manual_folder,
            resource_type="file",
            visibility="private",
            owner=self.lab_manager,
        )

        # 6. Schedule maintenance
        scheduled_maintenance = MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_date=timezone.now() + timedelta(days=30),
            maintenance_type="routine",
            status="requested",
            maintenance_description="Quarterly calibration and cleaning",
            created_by=self.lab_manager,
        )

        # 7. Record instrument usage
        usage_session = InstrumentUsage.objects.create(
            instrument=instrument,
            user=self.researcher,
            time_started=timezone.now() - timedelta(hours=2),
            time_ended=timezone.now() - timedelta(hours=1),
            description="Cell imaging experiment for Project Alpha",
            approved=True,
            approved_by=self.lab_manager,
        )

        # 8. Test warranty check
        warranty_alert = instrument.check_warranty_expiration(days_threshold=365)

        # 9. Test maintenance check
        maintenance_alert = instrument.check_upcoming_maintenance(days_threshold=45)

        # Assertions
        self.assertEqual(instrument.instrument_name, "High-Resolution Microscope")
        self.assertTrue(instrument.enabled)
        self.assertEqual(vendor_contact.contact_details.count(), 2)
        self.assertTrue(AnnotationFolder.objects.filter(folder_name="Manuals").exists())
        self.assertEqual(manual.folder, manual_folder)
        self.assertEqual(scheduled_maintenance.instrument, instrument)
        self.assertEqual(usage_session.instrument, instrument)
        self.assertTrue(warranty_alert)  # Should trigger within 11 months
        self.assertFalse(maintenance_alert)  # Maintenance not due for 30+ days

    def test_complete_inventory_workflow(self):
        """Test complete reagent inventory management workflow"""

        # 1. Create storage hierarchy
        main_lab = StorageObject.objects.create(object_name="Main Laboratory", object_type="room")

        cold_storage = StorageObject.objects.create(
            object_name="Cold Storage Area", object_type="room", stored_at=main_lab
        )

        reagent_fridge = StorageObject.objects.create(
            object_name="Reagent Refrigerator A", object_type="fridge", stored_at=cold_storage, user=self.lab_manager
        )

        # 2. Create reagents
        dapi_reagent = Reagent.objects.create(name="DAPI Nuclear Stain", unit="ml")

        pbs_reagent = Reagent.objects.create(name="Phosphate Buffered Saline", unit="L")

        # 3. Add reagents to inventory
        dapi_stock = StoredReagent.objects.create(
            reagent=dapi_reagent,
            storage_object=reagent_fridge,
            quantity=10.0,
            notes="Fresh batch, received 2024-08-30",
            user=self.lab_manager,
            expiration_date=timezone.now().date() + timedelta(days=365),
            low_stock_threshold=2.0,
            notify_on_low_stock=True,
            shareable=True,
        )

        pbs_stock = StoredReagent.objects.create(
            reagent=pbs_reagent,
            storage_object=reagent_fridge,
            quantity=2.0,
            user=self.lab_manager,
            expiration_date=timezone.now().date() + timedelta(days=180),
            low_stock_threshold=0.5,
            notify_on_low_stock=True,
            shareable=True,
        )

        # 4. Researcher reserves reagents
        dapi_reservation = ReagentAction.objects.create(
            reagent=dapi_stock,
            action_type="reserve",
            quantity=1.0,
            user=self.researcher,
            notes="Reserved for cell imaging experiment",
        )

        ReagentAction.objects.create(
            reagent=pbs_stock,
            action_type="reserve",
            quantity=0.2,
            user=self.researcher,
            notes="Buffer for cell preparation",
        )

        # 5. Subscribe to reagent notifications
        from ccm.models import ReagentSubscription

        dapi_subscription = ReagentSubscription.objects.create(
            user=self.researcher, stored_reagent=dapi_stock, notify_on_low_stock=True, notify_on_expiry=True
        )

        # Assertions
        self.assertEqual(reagent_fridge.stored_at, cold_storage)
        self.assertEqual(cold_storage.stored_at, main_lab)
        self.assertEqual(dapi_stock.quantity, 10.0)
        self.assertEqual(pbs_stock.quantity, 2.0)
        self.assertEqual(dapi_stock.reagent_actions.count(), 1)
        self.assertEqual(pbs_stock.reagent_actions.count(), 1)
        self.assertEqual(dapi_reservation.quantity, 1.0)
        self.assertEqual(dapi_subscription.stored_reagent, dapi_stock)
        self.assertTrue(dapi_stock.shareable)
        self.assertTrue(pbs_stock.notify_on_low_stock)

    def test_cross_model_relationships(self):
        """Test relationships between different CCM models"""

        # Create linked ecosystem
        instrument = Instrument.objects.create(
            instrument_name="Automated Liquid Handler", enabled=True, user=self.lab_manager
        )

        storage = StorageObject.objects.create(object_name="Reagent Deck", object_type="shelf", user=self.lab_manager)

        reagent = Reagent.objects.create(name="PCR Master Mix", unit="ml")

        stored_reagent = StoredReagent.objects.create(
            reagent=reagent, storage_object=storage, quantity=50.0, user=self.lab_manager
        )

        # Create usage session that involves reagent consumption
        usage = InstrumentUsage.objects.create(
            instrument=instrument,
            user=self.researcher,
            time_started=timezone.now() - timedelta(hours=3),
            time_ended=timezone.now() - timedelta(hours=1),
            description="PCR setup using liquid handler",
            approved=True,
        )

        # Record reagent consumption during usage
        reagent_consumption = ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type="reserve",
            quantity=5.0,
            user=self.researcher,
            notes=f"Used during instrument session {usage.id}",
        )

        # Create maintenance that affects both instrument and reagents
        maintenance = MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_date=timezone.now(),
            maintenance_type="routine",
            status="completed",
            maintenance_description="Cleaned reagent lines and calibrated pipettes",
            created_by=self.lab_manager,
        )

        # Test relationships
        self.assertEqual(usage.instrument, instrument)
        self.assertEqual(reagent_consumption.reagent, stored_reagent)
        self.assertEqual(maintenance.instrument, instrument)
        self.assertEqual(stored_reagent.storage_object, storage)

        # Test model counts
        self.assertEqual(Instrument.objects.count(), 1)
        self.assertEqual(StorageObject.objects.count(), 1)
        self.assertEqual(StoredReagent.objects.count(), 1)
        self.assertEqual(InstrumentUsage.objects.count(), 1)
        self.assertEqual(ReagentAction.objects.count(), 1)
        self.assertEqual(MaintenanceLog.objects.count(), 1)
