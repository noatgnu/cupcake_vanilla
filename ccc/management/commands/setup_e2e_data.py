"""Management command to create idempotent seed data for E2E tests."""

import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    """Seed the database with predictable data for Playwright E2E tests.

    Safe to run multiple times; uses get_or_create throughout.
    """

    help = "Create seed data for E2E tests"

    def handle(self, *args, **options):
        admin = self._create_users()
        lab_group = self._create_lab_group(admin)
        self._create_device_token(admin)
        self._create_metadata_table(admin, lab_group)

        if apps.is_installed("ccm"):
            instrument = self._create_instrument(admin, lab_group)
            storage = self._create_storage(admin, lab_group)
            self._create_stored_reagent(admin, storage, lab_group)
            self._create_instrument_job(admin, instrument, lab_group)

        if apps.is_installed("ccrv"):
            protocol = self._create_protocol(admin, lab_group)
            self._create_session(admin, protocol, lab_group)

        if apps.is_installed("ccsc"):
            self._create_billing_data()

        if apps.is_installed("ccmc"):
            self._create_message_thread(admin)

        self.stdout.write(self.style.SUCCESS("E2E seed data created successfully"))

    def _create_users(self):
        """Create admin, testuser, and teststaff accounts."""
        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@cupcake.local",
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Admin",
                "last_name": "User",
            },
        )
        admin.set_password("admin")
        admin.save(update_fields=["password"])

        testuser, _ = User.objects.get_or_create(
            username="testuser",
            defaults={
                "email": "testuser@cupcake.local",
                "first_name": "Test",
                "last_name": "User",
            },
        )
        testuser.set_password("testuser123")
        testuser.save(update_fields=["password"])

        teststaff, _ = User.objects.get_or_create(
            username="teststaff",
            defaults={
                "email": "teststaff@cupcake.local",
                "is_staff": True,
                "first_name": "Test",
                "last_name": "Staff",
            },
        )
        teststaff.set_password("teststaff123")
        teststaff.save(update_fields=["password"])

        self.stdout.write("  Users: admin, testuser, teststaff")
        return admin

    def _create_lab_group(self, admin):
        """Create Test Lab group with all three users as members."""
        from ccc.models import LabGroup

        testuser = User.objects.get(username="testuser")
        teststaff = User.objects.get(username="teststaff")

        lab_group, _ = LabGroup.objects.get_or_create(
            name="Test Lab",
            defaults={
                "description": "Lab group for E2E testing",
                "creator": admin,
                "is_active": True,
            },
        )
        lab_group.members.add(admin, testuser, teststaff)
        self.stdout.write("  LabGroup: Test Lab")
        return lab_group

    def _create_device_token(self, admin):
        """Create a predictable device token for testuser."""
        from ccc.device_token.model import DeviceToken

        testuser = User.objects.get(username="testuser")
        if not DeviceToken.objects.filter(user=testuser, label="E2E Device").exists():
            DeviceToken.objects.create(
                user=testuser,
                label="E2E Device",
                token="e2e-device-token-fixed-for-testing-purposes-only-not-secret",
                permission=DeviceToken.PERMISSION_WRITE,
            )
        self.stdout.write("  DeviceToken: e2e-device-token")

    def _create_metadata_table(self, admin, lab_group):
        """Create E2E Table with 3 columns."""
        from ccv.models import MetadataColumn, MetadataTable

        testuser = User.objects.get(username="testuser")

        table, _ = MetadataTable.objects.get_or_create(
            name="E2E Table",
            defaults={
                "description": "Metadata table for E2E tests",
                "owner": testuser,
                "lab_group": lab_group,
                "sample_count": 3,
            },
        )

        column_definitions = [
            {"name": "Sample Name", "type": "characteristics", "column_position": 1},
            {"name": "Species", "type": "characteristics", "column_position": 2},
            {"name": "Tissue", "type": "characteristics", "column_position": 3},
        ]
        for col_def in column_definitions:
            MetadataColumn.objects.get_or_create(
                metadata_table=table,
                name=col_def["name"],
                defaults={
                    "type": col_def["type"],
                    "column_position": col_def["column_position"],
                },
            )

        self.stdout.write("  MetadataTable: E2E Table (3 columns)")
        return table

    def _create_instrument(self, admin, lab_group):
        """Create Test Mass Spec instrument accessible to Test Lab."""
        from ccm.models import Instrument, InstrumentPermission

        instrument, _ = Instrument.objects.get_or_create(
            instrument_name="Test Mass Spec",
            defaults={
                "user": admin,
                "enabled": True,
                "accepts_bookings": True,
                "instrument_description": "Mass spectrometer for E2E testing",
            },
        )
        testuser = User.objects.get(username="testuser")
        teststaff = User.objects.get(username="teststaff")
        for user in (admin, testuser, teststaff):
            InstrumentPermission.objects.get_or_create(
                user=user,
                instrument=instrument,
                defaults={"can_view": True, "can_book": True, "can_manage": user == admin},
            )
        self.stdout.write("  Instrument: Test Mass Spec")
        return instrument

    def _create_storage(self, admin, lab_group):
        """Create Test Freezer storage object accessible to Test Lab."""
        from ccm.models import StorageObject

        storage, _ = StorageObject.objects.get_or_create(
            object_name="Test Freezer",
            defaults={
                "object_type": "freezer",
                "object_description": "Freezer for E2E testing",
                "user": admin,
            },
        )
        storage.access_lab_groups.add(lab_group)
        self.stdout.write("  StorageObject: Test Freezer")
        return storage

    def _create_stored_reagent(self, admin, storage, lab_group):
        """Create Test Antibody reagent in Test Freezer with low-stock threshold."""
        from ccm.models import Reagent, StoredReagent

        reagent, _ = Reagent.objects.get_or_create(
            name="Test Antibody",
            defaults={"unit": "uL"},
        )
        stored, _ = StoredReagent.objects.get_or_create(
            reagent=reagent,
            storage_object=storage,
            defaults={
                "quantity": 100,
                "user": admin,
                "low_stock_threshold": 10,
                "notify_on_low_stock": True,
                "access_all": False,
            },
        )
        stored.access_lab_groups.add(lab_group)
        self.stdout.write("  StoredReagent: Test Antibody (qty=100, threshold=10)")

    def _create_instrument_job(self, admin, instrument, lab_group):
        """Create a pending instrument job for testuser."""
        from ccm.models import InstrumentJob

        testuser = User.objects.get(username="testuser")
        teststaff = User.objects.get(username="teststaff")

        job, created = InstrumentJob.objects.get_or_create(
            job_name="E2E Job",
            defaults={
                "user": testuser,
                "instrument": instrument,
                "lab_group": lab_group,
                "job_type": "analysis",
                "status": "pending",
                "sample_number": 3,
            },
        )
        if created:
            job.staff.add(teststaff)
        self.stdout.write("  InstrumentJob: E2E Job (pending)")

    def _create_protocol(self, admin, lab_group):
        """Create E2E Protocol with 2 sections and 3 steps."""
        from ccrv.models import ProtocolModel, ProtocolSection, ProtocolStep

        testuser = User.objects.get(username="testuser")

        protocol, _ = ProtocolModel.objects.get_or_create(
            protocol_title="E2E Protocol",
            defaults={
                "protocol_description": "Protocol for E2E testing",
                "owner": testuser,
                "lab_group": lab_group,
                "enabled": True,
            },
        )

        section1, _ = ProtocolSection.objects.get_or_create(
            protocol=protocol,
            section_description="Sample Preparation",
            defaults={"order": 1, "section_duration": 30},
        )
        section2, _ = ProtocolSection.objects.get_or_create(
            protocol=protocol,
            section_description="Instrument Setup",
            defaults={"order": 2, "section_duration": 15},
        )

        step1, _ = ProtocolStep.objects.get_or_create(
            step_section=section1,
            step_description="Prepare samples",
            defaults={"protocol": protocol, "step_duration": 10, "order": 1},
        )
        step2, _ = ProtocolStep.objects.get_or_create(
            step_section=section1,
            step_description="Centrifuge at 12000g",
            defaults={"protocol": protocol, "step_duration": 15, "order": 2, "previous_step": step1},
        )
        ProtocolStep.objects.get_or_create(
            step_section=section2,
            step_description="Calibrate instrument",
            defaults={"protocol": protocol, "step_duration": 10, "order": 1},
        )
        self.stdout.write("  Protocol: E2E Protocol (2 sections, 3 steps)")
        return protocol

    def _create_session(self, admin, protocol, lab_group):
        """Create E2E Session linked to E2E Protocol."""
        from ccrv.models import Session

        testuser = User.objects.get(username="testuser")

        session, _ = Session.objects.get_or_create(
            name="E2E Session",
            defaults={
                "unique_id": uuid.uuid4(),
                "owner": testuser,
                "lab_group": lab_group,
                "enabled": True,
            },
        )
        session.protocols.add(protocol)
        self.stdout.write("  Session: E2E Session")

    def _create_billing_data(self):
        """Create Standard service tier and Analysis billable item type."""
        from django.contrib.contenttypes.models import ContentType

        from ccsc.models import BillableItemType, ServiceTier

        ServiceTier.objects.get_or_create(
            tier_name="Standard",
            defaults={
                "description": "Standard service tier for E2E tests",
                "priority_level": 1,
                "is_active": True,
            },
        )
        user_ct = ContentType.objects.get_for_model(User)
        BillableItemType.objects.get_or_create(
            name="Analysis",
            defaults={
                "description": "Generic analysis billable item type for E2E tests",
                "content_type": user_ct,
                "default_billing_unit": "usage",
            },
        )
        self.stdout.write("  Billing: Standard tier, Analysis item type")

    def _create_message_thread(self, admin):
        """Create a message thread from admin to testuser with one reply."""
        from ccmc.models import Message, MessageThread, ThreadParticipant

        testuser = User.objects.get(username="testuser")

        thread, created = MessageThread.objects.get_or_create(
            title="E2E Test Thread",
            defaults={
                "description": "Message thread for E2E testing",
                "creator": admin,
            },
        )
        if created:
            ThreadParticipant.objects.get_or_create(thread=thread, user=admin)
            ThreadParticipant.objects.get_or_create(thread=thread, user=testuser)
            Message.objects.create(
                thread=thread,
                sender=admin,
                content="Hello testuser, this is an E2E test message.",
            )
            Message.objects.create(
                thread=thread,
                sender=testuser,
                content="Hello admin, this is a reply in the E2E test thread.",
            )
        self.stdout.write("  MessageThread: E2E Test Thread (2 messages)")
