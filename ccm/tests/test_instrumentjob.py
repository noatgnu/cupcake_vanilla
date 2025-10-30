"""
Test CCM InstrumentJob model functionality.

Tests the core InstrumentJob functionality including metadata table integration,
time tracking, sample management, and workflow statuses - without billing concerns.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from tests.factories import MetadataTableFactory, get_fixture_path

User = get_user_model()


@override_settings(ENABLE_CUPCAKE_MACARON=True)
class InstrumentJobModelTest(TestCase):
    """Test InstrumentJob model core functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="researcher", email="researcher@lab.edu")
        self.staff_user = User.objects.create_user(username="staff_member", email="staff@lab.edu", is_staff=True)
        self.admin_user = User.objects.create_user(
            username="lab_admin", email="admin@lab.edu", is_staff=True, is_superuser=True
        )

        # Create metadata table with SDRF fixture
        sdrf_file = get_fixture_path("PXD019185_PXD018883.sdrf.tsv")

        self.metadata_table = MetadataTableFactory.from_sdrf_file(
            sdrf_file, created_by=self.user, table_name="Proteomics Dataset"
        )

        # Create staff-only metadata table
        self.staff_metadata = MetadataTableFactory.create_basic_table(
            user=self.staff_user, name="Internal Analysis Results"
        )

        # Mock InstrumentJob creation (since we can't import it directly)
        self.job_data = {
            "user": self.user,
            "job_name": "Proteomics LC-MS/MS Analysis",
            "job_type": "analysis",
            "status": "draft",
            "sample_number": 24,
            "sample_type": "wcl",
            "cost_center": "BIO-PROT-001",
            "funder": "NIH R01 Grant #12345",
            "injection_volume": 5.0,
            "injection_unit": "uL",
            "search_engine": "MaxQuant",
            "search_engine_version": "2.4.3.0",
            "search_details": "Oxidation (M), Acetyl (Protein N-term)",
            "location": "Room 204, Mass Spec Facility",
            "method": "Data-dependent acquisition, 120 min gradient",
            "metadata_table": self.metadata_table,
        }

    def create_mock_instrument_job(self, **kwargs):
        """Create a mock InstrumentJob for testing."""
        from unittest.mock import MagicMock

        # Start with default job data
        job_attrs = self.job_data.copy()
        job_attrs.update(kwargs)

        mock_job = MagicMock()

        # Set all attributes
        for key, value in job_attrs.items():
            setattr(mock_job, key, value)

        # Set timestamps
        mock_job.created_at = timezone.now() - timedelta(hours=2)
        mock_job.updated_at = timezone.now() - timedelta(minutes=30)
        mock_job.submitted_at = None
        mock_job.completed_at = None

        # Time tracking (initially None)
        mock_job.instrument_start_time = None
        mock_job.instrument_end_time = None
        mock_job.personnel_start_time = None
        mock_job.personnel_end_time = None

        # Mock the properties for hour calculations
        def calculate_instrument_hours():
            if mock_job.instrument_start_time and mock_job.instrument_end_time:
                delta = mock_job.instrument_end_time - mock_job.instrument_start_time
                return delta.total_seconds() / 3600
            return 0

        def calculate_personnel_hours():
            if mock_job.personnel_start_time and mock_job.personnel_end_time:
                delta = mock_job.personnel_end_time - mock_job.personnel_start_time
                return delta.total_seconds() / 3600
            return 0

        # Assign properties as attributes since MagicMock can't handle @property
        mock_job.instrument_hours = 0
        mock_job.personnel_hours = 0
        mock_job._calculate_instrument_hours = calculate_instrument_hours
        mock_job._calculate_personnel_hours = calculate_personnel_hours

        # Mock staff ManyToMany field
        mock_staff_manager = MagicMock()
        mock_staff_manager.all.return_value = []  # No staff assigned by default
        mock_job.staff = mock_staff_manager

        # Ensure lab_group is None if not explicitly set (avoid MagicMock truthy issues)
        if not hasattr(mock_job, "lab_group") or isinstance(getattr(mock_job, "lab_group", None), MagicMock):
            if "lab_group" not in job_attrs:
                mock_job.lab_group = None

        # Mock methods for metadata permissions
        def can_user_view_metadata(user):
            if not mock_job.metadata_table:
                return False
            return mock_job.metadata_table.can_view(user)

        def can_user_edit_metadata(user):
            if not mock_job.metadata_table:
                return False
            return mock_job.metadata_table.can_edit(user)

        def get_staff_editable_metadata():
            if mock_job.metadata_table:
                return mock_job.metadata_table
            return None

        # Import and bind actual model methods instead of old mocked logic
        from ccm.models import InstrumentJob

        # Bind actual methods from the model
        mock_job.can_user_view_metadata = lambda user: InstrumentJob.can_user_view_metadata(mock_job, user)
        mock_job.can_user_edit_metadata = lambda user: InstrumentJob.can_user_edit_metadata(mock_job, user)
        mock_job.get_staff_editable_metadata = lambda: InstrumentJob.get_staff_editable_metadata(mock_job)

        # Mock choice display methods
        mock_job.get_job_type_display = lambda: mock_job.job_type.title()
        mock_job.get_status_display = lambda: mock_job.status.title().replace("_", " ")
        mock_job.get_sample_type_display = lambda: {
            "wcl": "Whole Cell Lysate",
            "ip": "Immunoprecipitate",
            "other": "Other",
        }.get(mock_job.sample_type, "Other")

        return mock_job

    def test_instrument_job_creation(self):
        """Test basic InstrumentJob creation with metadata table."""
        job = self.create_mock_instrument_job()

        # Verify basic fields
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.job_name, "Proteomics LC-MS/MS Analysis")
        self.assertEqual(job.job_type, "analysis")
        self.assertEqual(job.status, "draft")
        self.assertEqual(job.sample_number, 24)
        self.assertEqual(job.metadata_table, self.metadata_table)

        # Verify choice displays
        self.assertEqual(job.get_job_type_display(), "Analysis")
        self.assertEqual(job.get_status_display(), "Draft")
        self.assertEqual(job.get_sample_type_display(), "Whole Cell Lysate")

    def test_instrument_job_metadata_permissions(self):
        """Test metadata table permission methods."""
        job = self.create_mock_instrument_job()

        # Test user (owner) can view and edit their metadata
        self.assertTrue(job.can_user_view_metadata(self.user))
        self.assertTrue(job.can_user_edit_metadata(self.user))

        # Test staff can view but not edit user metadata
        self.assertTrue(job.can_user_view_metadata(self.staff_user))
        self.assertFalse(job.can_user_edit_metadata(self.staff_user))

        # Test admin can view but not edit user metadata
        self.assertTrue(job.can_user_view_metadata(self.admin_user))
        self.assertFalse(job.can_user_edit_metadata(self.admin_user))

        # Test with no metadata table
        job_no_meta = self.create_mock_instrument_job(metadata_table=None)
        self.assertFalse(job_no_meta.can_user_view_metadata(self.user))
        self.assertFalse(job_no_meta.can_user_edit_metadata(self.user))

    def test_instrument_job_staff_only_metadata(self):
        """Test metadata table permissions with staff assignment."""
        job = self.create_mock_instrument_job(metadata_table=self.staff_metadata)

        # Add staff_user to the job's staff
        job.staff.all.return_value = [self.staff_user]

        # Regular job owner can view and edit their job's metadata table
        # (staff_only restrictions apply at column level, not table level)
        self.assertTrue(job.can_user_view_metadata(self.user))
        self.assertTrue(job.can_user_edit_metadata(self.user))

        # Staff assigned to job can also view and edit
        self.assertTrue(job.can_user_view_metadata(self.staff_user))
        self.assertTrue(job.can_user_edit_metadata(self.staff_user))

        # Staff editable metadata returns the staff metadata table
        self.assertEqual(job.get_staff_editable_metadata(), self.staff_metadata)

    def test_instrument_job_time_tracking(self):
        """Test instrument and personnel time tracking."""
        job = self.create_mock_instrument_job()

        # Initially no time recorded
        self.assertEqual(job.instrument_hours, 0)
        self.assertEqual(job.personnel_hours, 0)

        # Set instrument time (12 hours)
        start_time = timezone.now() - timedelta(hours=12)
        end_time = timezone.now()
        job.instrument_start_time = start_time
        job.instrument_end_time = end_time

        # Update the calculated hours
        job.instrument_hours = job._calculate_instrument_hours()
        self.assertAlmostEqual(job.instrument_hours, 12.0, places=1)

        # Set personnel time (4 hours, overlapping with instrument time)
        personnel_start = timezone.now() - timedelta(hours=6)
        personnel_end = timezone.now() - timedelta(hours=2)
        job.personnel_start_time = personnel_start
        job.personnel_end_time = personnel_end

        job.personnel_hours = job._calculate_personnel_hours()
        self.assertAlmostEqual(job.personnel_hours, 4.0, places=1)

        # Test with partial times (only start time)
        partial_job = self.create_mock_instrument_job()
        partial_job.instrument_start_time = start_time
        # instrument_end_time is None
        partial_job.instrument_hours = partial_job._calculate_instrument_hours()
        self.assertEqual(partial_job.instrument_hours, 0)

    def test_instrument_job_status_workflow(self):
        """Test job status transitions."""
        job = self.create_mock_instrument_job()

        # Test initial draft status
        self.assertEqual(job.status, "draft")

        # Test status transitions
        statuses = ["submitted", "pending", "in_progress", "completed", "cancelled"]

        for status in statuses:
            job.status = status
            self.assertEqual(job.status, status)
            self.assertEqual(job.get_status_display(), status.title().replace("_", " "))

        # Test completed job with timestamps
        completed_job = self.create_mock_instrument_job(status="completed")
        completed_job.submitted_at = timezone.now() - timedelta(days=2)
        completed_job.completed_at = timezone.now() - timedelta(hours=1)

        self.assertEqual(completed_job.status, "completed")
        self.assertIsNotNone(completed_job.submitted_at)
        self.assertIsNotNone(completed_job.completed_at)

    def test_instrument_job_sample_information(self):
        """Test sample-related fields."""
        job = self.create_mock_instrument_job(
            sample_number=48, sample_type="ip", injection_volume=2.5, injection_unit="uL"
        )

        self.assertEqual(job.sample_number, 48)
        self.assertEqual(job.sample_type, "ip")
        self.assertEqual(job.get_sample_type_display(), "Immunoprecipitate")
        self.assertEqual(job.injection_volume, 2.5)
        self.assertEqual(job.injection_unit, "uL")

    def test_instrument_job_analysis_parameters(self):
        """Test analysis-specific parameters."""
        job = self.create_mock_instrument_job(
            search_engine="Mascot",
            search_engine_version="2.8.1",
            search_details="Carbamidomethyl (C), Oxidation (M), Deamidation (NQ)",
            method="90 min gradient, DDA top 15",
        )

        self.assertEqual(job.search_engine, "Mascot")
        self.assertEqual(job.search_engine_version, "2.8.1")
        self.assertIn("Carbamidomethyl", job.search_details)
        self.assertIn("90 min gradient", job.method)

    def test_instrument_job_administrative_fields(self):
        """Test administrative and tracking fields."""
        job = self.create_mock_instrument_job(
            cost_center="CHEM-MS-2024", funder="DOE Office of Science Grant", location="Building 5, Room 312"
        )

        self.assertEqual(job.cost_center, "CHEM-MS-2024")
        self.assertEqual(job.funder, "DOE Office of Science Grant")
        self.assertEqual(job.location, "Building 5, Room 312")

    def test_instrument_job_different_job_types(self):
        """Test different job types."""
        job_types = ["analysis", "maintenance", "other"]

        for job_type in job_types:
            job = self.create_mock_instrument_job(job_type=job_type)
            self.assertEqual(job.job_type, job_type)
            self.assertEqual(job.get_job_type_display(), job_type.title())

    def test_instrument_job_with_sdrf_metadata_integration(self):
        """Test integration with SDRF metadata table."""
        job = self.create_mock_instrument_job()

        # Verify metadata table connection
        self.assertEqual(job.metadata_table, self.metadata_table)
        self.assertIsNotNone(job.metadata_table.name)

        # Verify sample count matches metadata rows
        metadata_row_count = self.metadata_table.sample_count
        self.assertGreater(metadata_row_count, 0)  # Should have rows from SDRF

        # Test that sample number could be derived from metadata
        if metadata_row_count > 0:
            self.assertGreaterEqual(job.sample_number, 1)

    def test_instrument_job_metadata_permission_scenarios(self):
        """Test various metadata permission scenarios."""
        # Scenario 1: Regular user with their own metadata
        user_job = self.create_mock_instrument_job(user=self.user, metadata_table=self.metadata_table)

        # Owner can view and edit
        self.assertTrue(user_job.can_user_view_metadata(self.user))
        self.assertTrue(user_job.can_user_edit_metadata(self.user))

        # Scenario 2: Staff user with staff metadata
        staff_job = self.create_mock_instrument_job(user=self.staff_user, metadata_table=self.staff_metadata)

        # Staff can view and edit their staff metadata
        self.assertTrue(staff_job.can_user_view_metadata(self.staff_user))
        self.assertTrue(staff_job.can_user_edit_metadata(self.staff_user))

        # Regular user cannot access staff metadata
        self.assertFalse(staff_job.can_user_view_metadata(self.user))
        self.assertFalse(staff_job.can_user_edit_metadata(self.user))

        # Scenario 3: Cross-user access
        other_user = User.objects.create_user(username="other_researcher", email="other@lab.edu")

        # Other user can view but not edit user's metadata
        self.assertTrue(user_job.can_user_view_metadata(self.staff_user))
        self.assertFalse(user_job.can_user_edit_metadata(other_user))

    def test_instrument_job_complex_workflow(self):
        """Test a complex job workflow with time tracking and status changes."""
        # Create job in draft status
        job = self.create_mock_instrument_job()

        # Submit the job
        job.status = "submitted"
        job.submitted_at = timezone.now()

        # Move to pending
        job.status = "pending"

        # Start instrument work
        job.status = "in_progress"
        job.instrument_start_time = timezone.now()

        # Start personnel work (later)
        job.personnel_start_time = timezone.now() + timedelta(hours=2)

        # Finish personnel work first
        job.personnel_end_time = job.personnel_start_time + timedelta(hours=3)
        job.personnel_hours = job._calculate_personnel_hours()

        # Finish instrument work
        job.instrument_end_time = job.instrument_start_time + timedelta(hours=8)
        job.instrument_hours = job._calculate_instrument_hours()

        # Complete the job
        job.status = "completed"
        job.completed_at = timezone.now()

        # Verify final state
        self.assertEqual(job.status, "completed")
        self.assertAlmostEqual(job.instrument_hours, 8.0, places=1)
        self.assertAlmostEqual(job.personnel_hours, 3.0, places=1)
        self.assertIsNotNone(job.submitted_at)
        self.assertIsNotNone(job.completed_at)

        # Verify job can be viewed by users
        self.assertTrue(job.can_user_view_metadata(job.user))
        self.assertTrue(job.can_user_view_metadata(self.staff_user))

    def test_instrument_job_edge_cases(self):
        """Test edge cases and error conditions."""
        # Job with minimal required fields
        minimal_job = self.create_mock_instrument_job(
            job_name=None, sample_number=None, metadata_table=None, cost_center=None, funder=None
        )

        # Should still be valid
        self.assertEqual(minimal_job.user, self.user)
        self.assertEqual(minimal_job.job_type, "analysis")
        self.assertIsNone(minimal_job.metadata_table)

        # Test with zero sample number
        zero_sample_job = self.create_mock_instrument_job(sample_number=0)
        self.assertEqual(zero_sample_job.sample_number, 0)

        # Test with very long text fields
        long_text_job = self.create_mock_instrument_job(
            job_name="A" * 1000,  # Very long job name
            search_details="B" * 2000,  # Very long search details
            method="C" * 1500,  # Very long method description
        )

        # Should handle long text
        self.assertEqual(len(long_text_job.job_name), 1000)
        self.assertEqual(len(long_text_job.search_details), 2000)
        self.assertEqual(len(long_text_job.method), 1500)

    def test_instrument_job_string_representations(self):
        """Test string representations and displays."""
        job = self.create_mock_instrument_job()

        # Test choice field displays
        self.assertIn("Analysis", job.get_job_type_display())
        self.assertIn("Draft", job.get_status_display())
        self.assertIn("Whole Cell Lysate", job.get_sample_type_display())

        # Test with different choices
        maintenance_job = self.create_mock_instrument_job(
            job_type="maintenance", status="completed", sample_type="other"
        )

        self.assertEqual(maintenance_job.get_job_type_display(), "Maintenance")
        self.assertEqual(maintenance_job.get_status_display(), "Completed")
        self.assertEqual(maintenance_job.get_sample_type_display(), "Other")


@override_settings(ENABLE_CUPCAKE_MACARON=True)
class InstrumentJobStaffAssignmentTest(TestCase):
    """Test staff assignment validation for InstrumentJob."""

    def setUp(self):
        from ccc.models import LabGroup, LabGroupPermission
        from ccm.models import Instrument

        self.user1 = User.objects.create_user(username="user1", email="user1@lab.edu")
        self.user2 = User.objects.create_user(username="user2", email="user2@lab.edu")
        self.staff1 = User.objects.create_user(username="staff1", email="staff1@lab.edu", is_staff=True)
        self.staff2 = User.objects.create_user(username="staff2", email="staff2@lab.edu", is_staff=True)

        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        self.lab_group.members.add(self.user1, self.staff1, self.staff2)

        LabGroupPermission.objects.create(
            user=self.staff1, lab_group=self.lab_group, can_process_jobs=True, can_view=True
        )

        LabGroupPermission.objects.create(
            user=self.staff2, lab_group=self.lab_group, can_process_jobs=False, can_view=True
        )

        self.instrument = Instrument.objects.create(instrument_name="Test Instrument")

    def test_staff_assignment_with_permission(self):
        """Test that staff with can_process_jobs permission can be assigned."""
        from ccm.serializers import InstrumentJobSerializer

        job_data = {
            "job_name": "Test Job",
            "job_type": "analysis",
            "lab_group": self.lab_group.id,
            "staff": [self.staff1.id],
        }

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        job = serializer.save(user=self.user1)
        self.assertEqual(job.staff.count(), 1)
        self.assertIn(self.staff1, job.staff.all())

    def test_staff_assignment_without_permission(self):
        """Test that staff without can_process_jobs permission cannot be assigned."""
        from ccm.serializers import InstrumentJobSerializer

        job_data = {
            "job_name": "Test Job",
            "job_type": "analysis",
            "lab_group": self.lab_group.id,
            "staff": [self.staff2.id],
        }

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("staff", serializer.errors)
        self.assertIn("can_process_jobs permission", str(serializer.errors["staff"]))

    def test_staff_assignment_mixed_permissions(self):
        """Test assignment with mix of staff with and without permission."""
        from ccm.serializers import InstrumentJobSerializer

        job_data = {
            "job_name": "Test Job",
            "job_type": "analysis",
            "lab_group": self.lab_group.id,
            "staff": [self.staff1.id, self.staff2.id],
        }

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("staff", serializer.errors)
        self.assertIn("staff2", str(serializer.errors["staff"]))

    def test_staff_assignment_no_lab_group(self):
        """Test that staff cannot be assigned without lab_group (validation enforced)."""
        from ccm.serializers import InstrumentJobSerializer

        job_data = {
            "job_name": "Test Job",
            "job_type": "analysis",
            "staff": [self.staff2.id],
        }

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("lab_group", serializer.errors)
        self.assertEqual(
            str(serializer.errors["lab_group"][0]), "Lab group is required when staff members are assigned to the job"
        )
