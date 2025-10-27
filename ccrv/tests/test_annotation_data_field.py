"""
Test annotation_data field functionality for creating annotations without file upload.
"""
import uuid

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase

from ccrv.models import Project, ProtocolModel, ProtocolStep, Session

User = get_user_model()


class SessionAnnotationDataFieldTest(APITestCase):
    """Test SessionAnnotation creation using annotation_data field."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass123", email="test@example.com")
        self.client.force_authenticate(user=self.user)

        self.project = Project.objects.create(project_name="Test Project", owner=self.user)

        self.session = Session.objects.create(name="Test Session", owner=self.user, unique_id=uuid.uuid4())

    def test_create_session_annotation_with_annotation_data(self):
        """Test creating SessionAnnotation with annotation_data only (no annotation field)."""
        data = {
            "session": self.session.id,
            "annotation_data": {"annotation": "This is a test text annotation", "annotation_type": "text"},
        }

        response = self.client.post("/api/v1/session-annotations/", data, format="json")

        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Data: {response.data}")

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            f"Expected 201, got {response.status_code}. Errors: {response.data}",
        )
        self.assertIn("id", response.data)
        self.assertEqual(response.data["annotation_text"], "This is a test text annotation")
        self.assertEqual(response.data["annotation_type"], "text")

    def test_create_session_annotation_with_audio_type(self):
        """Test creating SessionAnnotation with audio annotation type."""
        data = {
            "session": self.session.id,
            "annotation_data": {"annotation": "Audio note description", "annotation_type": "audio"},
        }

        response = self.client.post("/api/v1/session-annotations/", data, format="json")

        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Data: {response.data}")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["annotation_type"], "audio")

    def test_create_session_annotation_without_either_field(self):
        """Test that creating SessionAnnotation without annotation or annotation_data fails."""
        data = {"session": self.session.id}

        response = self.client.post("/api/v1/session-annotations/", data, format="json")

        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Data: {response.data}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class StepAnnotationDataFieldTest(APITestCase):
    """Test StepAnnotation creation using annotation_data field."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass123", email="test@example.com")
        self.client.force_authenticate(user=self.user)

        self.project = Project.objects.create(project_name="Test Project", owner=self.user)

        self.session = Session.objects.create(name="Test Session", owner=self.user, unique_id=uuid.uuid4())

        self.protocol = ProtocolModel.objects.create(
            protocol_title="Test Protocol", protocol_description="Test protocol for annotation testing", owner=self.user
        )

        self.step = ProtocolStep.objects.create(protocol=self.protocol, step_description="Test Step")

    def test_create_step_annotation_with_annotation_data(self):
        """Test creating StepAnnotation with annotation_data only."""
        data = {
            "session": self.session.id,
            "step": self.step.id,
            "annotation_data": {"annotation": "Step note: Temperature should be 37°C", "annotation_type": "text"},
        }

        response = self.client.post("/api/v1/step-annotations/", data, format="json")

        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Data: {response.data}")

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            f"Expected 201, got {response.status_code}. Errors: {response.data}",
        )
        self.assertIn("id", response.data)
        self.assertEqual(response.data["annotation_text"], "Step note: Temperature should be 37°C")
