"""
Test CCM API serializers and viewsets.

Tests the REST API functionality for instrument management, jobs, usage tracking,
and maintenance functionality.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from ccm.models import (
    Instrument,
    InstrumentAnnotation,
    InstrumentJob,
    InstrumentPermission,
    InstrumentUsage,
    MaintenanceLog,
    MaintenanceLogAnnotation,
    Reagent,
    StorageObject,
    StoredReagent,
    StoredReagentAnnotation,
)
from ccm.serializers import (
    InstrumentAnnotationSerializer,
    InstrumentJobSerializer,
    InstrumentPermissionSerializer,
    InstrumentSerializer,
    MaintenanceLogAnnotationSerializer,
    ReagentSerializer,
    StorageObjectSerializer,
    StoredReagentAnnotationSerializer,
)

User = get_user_model()


class CCMSerializerTests(TestCase):
    """Test CCM model serializers."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

    def test_instrument_serializer(self):
        """Test InstrumentSerializer."""
        instrument_data = {
            "instrument_name": "LC-MS/MS System",
            "instrument_description": "High-resolution mass spectrometer",
            "enabled": True,
            "accepts_bookings": True,
            "user": self.user.id,
        }

        serializer = InstrumentSerializer(data=instrument_data)
        self.assertTrue(serializer.is_valid())

        instrument = serializer.save()
        self.assertEqual(instrument.instrument_name, "LC-MS/MS System")
        self.assertEqual(instrument.user, self.user)
        self.assertTrue(instrument.enabled)

    def test_instrument_serializer_validation(self):
        """Test InstrumentSerializer validation."""
        # Test empty instrument name
        instrument_data = {"instrument_name": "", "enabled": True}

        serializer = InstrumentSerializer(data=instrument_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("instrument_name", serializer.errors)

    def test_instrument_job_serializer(self):
        """Test InstrumentJobSerializer."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        job_data = {
            "instrument": instrument.id,
            "job_type": "analysis",
            "job_name": "Proteomics Analysis",
            "status": "draft",
            "sample_number": 24,
            "sample_type": "wcl",
            "user": self.user.id,
        }

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertTrue(serializer.is_valid())

        job = serializer.save()
        self.assertEqual(job.job_name, "Proteomics Analysis")
        self.assertEqual(job.sample_number, 24)
        self.assertEqual(job.user, self.user)

    def test_instrument_job_serializer_validation(self):
        """Test InstrumentJobSerializer validation."""
        # Test invalid sample number
        job_data = {"job_type": "analysis", "sample_number": -5, "user": self.user.id}  # Invalid negative number

        serializer = InstrumentJobSerializer(data=job_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("sample_number", serializer.errors)

    def test_storage_object_serializer(self):
        """Test StorageObjectSerializer."""
        storage_data = {
            "object_type": "freezer",
            "object_name": "Freezer A",
            "object_description": "Main storage freezer",
            "can_delete": True,
        }

        serializer = StorageObjectSerializer(data=storage_data)
        self.assertTrue(serializer.is_valid())

        storage = serializer.save()
        self.assertEqual(storage.object_name, "Freezer A")
        self.assertEqual(storage.object_type, "freezer")
        self.assertEqual(storage.object_description, "Main storage freezer")

    def test_reagent_serializer(self):
        """Test ReagentSerializer."""
        reagent_data = {"name": "Trypsin", "unit": "mg"}

        serializer = ReagentSerializer(data=reagent_data)
        self.assertTrue(serializer.is_valid())

        reagent = serializer.save()
        self.assertEqual(reagent.name, "Trypsin")
        self.assertEqual(reagent.unit, "mg")

    def test_instrument_annotation_serializer(self):
        """Test InstrumentAnnotationSerializer."""
        from ccc.models import Annotation, AnnotationFolder

        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Test instrument annotation", annotation_type="text", owner=self.user
        )

        # Create annotation folder
        folder = AnnotationFolder.objects.create(folder_name="Manuals")

        annotation_data = {"instrument": instrument.id, "annotation": annotation.id, "folder": folder.id}

        serializer = InstrumentAnnotationSerializer(data=annotation_data)
        self.assertTrue(serializer.is_valid())

        instrument_annotation = serializer.save()
        self.assertEqual(instrument_annotation.instrument, instrument)
        self.assertEqual(instrument_annotation.annotation, annotation)
        self.assertEqual(instrument_annotation.folder, folder)

    def test_stored_reagent_annotation_serializer(self):
        """Test StoredReagentAnnotationSerializer."""
        from ccc.models import Annotation, AnnotationFolder

        reagent = Reagent.objects.create(name="Test Reagent", unit="mg")
        stored_reagent = StoredReagent.objects.create(reagent=reagent, quantity=100.0, user=self.user)

        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Test stored reagent annotation", annotation_type="text", owner=self.user
        )

        # Create annotation folder
        folder = AnnotationFolder.objects.create(folder_name="MSDS")

        annotation_data = {"stored_reagent": stored_reagent.id, "annotation": annotation.id, "folder": folder.id}

        serializer = StoredReagentAnnotationSerializer(data=annotation_data)
        self.assertTrue(serializer.is_valid())

        stored_reagent_annotation = serializer.save()
        self.assertEqual(stored_reagent_annotation.stored_reagent, stored_reagent)
        self.assertEqual(stored_reagent_annotation.annotation, annotation)
        self.assertEqual(stored_reagent_annotation.folder, folder)

    def test_maintenance_log_annotation_serializer(self):
        """Test MaintenanceLogAnnotationSerializer."""
        from ccc.models import Annotation

        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)
        maintenance_log = MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_type="routine",
            maintenance_description="Test maintenance",
            created_by=self.user,
            maintenance_date=timezone.now(),
        )

        # Create annotation
        annotation = Annotation.objects.create(
            annotation="Test maintenance log annotation", annotation_type="text", owner=self.user
        )

        annotation_data = {"maintenance_log": maintenance_log.id, "annotation": annotation.id, "order": 1}

        serializer = MaintenanceLogAnnotationSerializer(data=annotation_data)
        self.assertTrue(serializer.is_valid())

        maintenance_log_annotation = serializer.save()
        self.assertEqual(maintenance_log_annotation.maintenance_log, maintenance_log)
        self.assertEqual(maintenance_log_annotation.annotation, annotation)
        self.assertEqual(maintenance_log_annotation.order, 1)

    def test_instrument_permission_serializer(self):
        """Test InstrumentPermissionSerializer."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        permission_data = {
            "instrument": instrument.id,
            "user": self.user.id,
            "can_view": True,
            "can_book": True,
            "can_manage": False,
        }

        serializer = InstrumentPermissionSerializer(data=permission_data)
        self.assertTrue(serializer.is_valid())

        permission = serializer.save()
        self.assertEqual(permission.instrument, instrument)
        self.assertEqual(permission.user, self.user)
        self.assertTrue(permission.can_view)
        self.assertTrue(permission.can_book)
        self.assertFalse(permission.can_manage)


class CCMViewSetTests(APITestCase):
    """Test CCM API viewsets."""

    def _get_results_from_response(self, response):
        """Helper to get results from potentially paginated API response."""
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def _get_count_from_response(self, response):
        """Helper to get count from potentially paginated API response."""
        if isinstance(response.data, dict) and "results" in response.data:
            return len(response.data["results"])
        return len(response.data)

    def setUp(self):
        # Clean up any existing test data to ensure test isolation
        Instrument.objects.all().delete()
        InstrumentJob.objects.all().delete()
        InstrumentUsage.objects.all().delete()
        MaintenanceLog.objects.all().delete()
        StorageObject.objects.all().delete()
        Reagent.objects.all().delete()
        StoredReagent.objects.all().delete()
        InstrumentAnnotation.objects.all().delete()
        StoredReagentAnnotation.objects.all().delete()
        MaintenanceLogAnnotation.objects.all().delete()
        InstrumentPermission.objects.all().delete()

        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.staff_user = User.objects.create_user(
            username="staffuser", email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_authenticate(user=self.user)

    def test_instrument_list_create(self):
        """Test instrument list and create endpoints."""
        # Get initial count
        url = "/api/v1/instruments/"
        initial_response = self.client.get(url)
        initial_count = self._get_count_from_response(initial_response)

        # Test create
        data = {
            "instrument_name": "New LC-MS",
            "instrument_description": "Brand new instrument",
            "enabled": True,
            "accepts_bookings": True,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["instrument_name"], "New LC-MS")

        # Test list - should have one more item
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        final_count = self._get_count_from_response(response)
        self.assertEqual(final_count, initial_count + 1)

    def test_instrument_permissions(self):
        """Test instrument access permissions."""
        # Create instrument owned by different user
        other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="testpass123")

        Instrument.objects.create(
            instrument_name="Private Instrument", user=other_user, enabled=True, is_vaulted=True  # Private to owner
        )

        # Regular user should not see private instrument
        url = "/api/v1/instruments/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 0)

        # Staff user should see all instruments
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)

    def test_instrument_job_workflow(self):
        """Test instrument job workflow actions."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        # Create job
        url = "/api/v1/instrument-jobs/"
        job_data = {
            "instrument": instrument.id,
            "job_type": "analysis",
            "job_name": "Test Analysis",
            "status": "draft",
            "sample_number": 10,
        }

        response = self.client.post(url, job_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job_id = response.data["id"]

        # Submit job
        submit_url = f"/api/v1/instrument-jobs/{job_id}/submit/"
        response = self.client.post(submit_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["job"]["status"], "submitted")

        # Complete job
        complete_url = f"/api/v1/instrument-jobs/{job_id}/complete/"
        response = self.client.post(complete_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["job"]["status"], "completed")

    def test_instrument_job_my_jobs(self):
        """Test my_jobs endpoint for instrument jobs."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        # Create a job for current user
        InstrumentJob.objects.create(instrument=instrument, user=self.user, job_name="My Test Job", job_type="analysis")

        # Create a job for another user
        other_user = User.objects.create_user(username="otheruser", password="testpass123")
        InstrumentJob.objects.create(
            instrument=instrument, user=other_user, job_name="Other User Job", job_type="analysis"
        )

        # Test my_jobs endpoint
        url = "/api/v1/instrument-jobs/my_jobs/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
        results = self._get_results_from_response(response)
        self.assertEqual(results[0]["job_name"], "My Test Job")

    def test_storage_object_list(self):
        """Test storage object list endpoint."""
        StorageObject.objects.create(object_name="Test Freezer", object_type="freezer", user=self.user)

        url = "/api/v1/storage-objects/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
        results = self._get_results_from_response(response)
        self.assertEqual(results[0]["object_name"], "Test Freezer")

    def test_reagent_list_filter(self):
        """Test reagent list and filtering."""
        # Create reagents
        Reagent.objects.create(name="Trypsin", unit="mg")
        Reagent.objects.create(name="DTT", unit="mL")

        url = "/api/v1/reagents/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 2)

        # Test filtering by unit
        response = self.client.get(url, {"unit": "mg"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
        results = self._get_results_from_response(response)
        self.assertEqual(results[0]["name"], "Trypsin")

    def test_available_instruments(self):
        """Test available instruments endpoint."""
        # Create available instrument
        Instrument.objects.create(
            instrument_name="Available Instrument",
            enabled=True,
            accepts_bookings=True,
            is_vaulted=False,
            user=self.user,
        )

        # Create unavailable instrument
        Instrument.objects.create(
            instrument_name="Unavailable Instrument",
            enabled=False,
            accepts_bookings=False,
            is_vaulted=True,
            user=self.user,
        )

        url = "/api/v1/instruments/?enabled=true&is_vaulted=false"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
        results = self._get_results_from_response(response)
        self.assertEqual(results[0]["instrument_name"], "Available Instrument")

    def test_instrument_usage_my_usage(self):
        """Test my_usage endpoint for instrument usage."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument")

        # Create usage record for current user
        InstrumentUsage.objects.create(
            instrument=instrument, user=self.user, description="Analysis run", time_started=timezone.now()
        )

        # Create usage record for another user
        other_user = User.objects.create_user(username="otheruser", password="testpass123")
        InstrumentUsage.objects.create(
            instrument=instrument,
            user=other_user,
            description="Maintenance work",
            maintenance=True,
            time_started=timezone.now(),
        )

        url = "/api/v1/instrument-usage/my_usage/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
        results = self._get_results_from_response(response)
        self.assertEqual(results[0]["description"], "Analysis run")

    def test_maintenance_log_staff_only(self):
        """Test that maintenance logs are only accessible to staff."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument")

        MaintenanceLog.objects.create(
            instrument=instrument,
            maintenance_type="routine",
            maintenance_description="Regular maintenance",
            created_by=self.staff_user,
            maintenance_date=timezone.now(),
        )

        # Regular user should not see maintenance logs
        url = "/api/v1/maintenance-logs/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 0)

        # Staff user should see maintenance logs
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._get_count_from_response(response), 1)
