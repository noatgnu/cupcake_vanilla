"""
Test script to verify annotation_data field works correctly.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from rest_framework.test import force_authenticate

from ccm.models import AnnotationFolder, Instrument
from ccm.serializers import InstrumentAnnotationSerializer
from ccrv.models import Project, Session
from ccrv.serializers import SessionAnnotationSerializer

User = get_user_model()


def test_session_annotation_with_annotation_data():
    """Test creating SessionAnnotation with annotation_data only."""
    print("\n=== Testing SessionAnnotation with annotation_data ===")

    # Setup
    user = User.objects.first()
    if not user:
        user = User.objects.create_user(username="testuser", password="testpass")

    Project.objects.create(project_name="Test Project", owner=user)

    session = Session.objects.create(name="Test Session", owner=user)

    # Create request context
    factory = RequestFactory()
    request = factory.post("/api/session-annotations/")
    request.user = user
    force_authenticate(request, user=user)

    # Test data with annotation_data only (NO annotation field)
    data = {
        "session": session.id,
        "annotation_data": {"annotation": "This is a test text annotation", "annotation_type": "text"},
    }

    print(f"Request data: {data}")

    # Create serializer
    serializer = SessionAnnotationSerializer(data=data, context={"request": request})

    # Validate
    if serializer.is_valid():
        print("✓ Serializer is valid")
        session_annotation = serializer.save()
        print(f"✓ SessionAnnotation created with ID: {session_annotation.id}")
        print(f"✓ Annotation text: {session_annotation.annotation.annotation}")
        print(f"✓ Annotation type: {session_annotation.annotation.annotation_type}")
        return True
    else:
        print("✗ Serializer validation failed!")
        print(f"Errors: {serializer.errors}")
        return False


def test_instrument_annotation_with_annotation_data():
    """Test creating InstrumentAnnotation with annotation_data only."""
    print("\n=== Testing InstrumentAnnotation with annotation_data ===")

    # Setup
    user = User.objects.first()
    if not user:
        user = User.objects.create_user(username="testuser", password="testpass")

    instrument = Instrument.objects.first()
    if not instrument:
        print("✗ No instrument found in database. Creating one...")
        instrument = Instrument.objects.create(instrument_name="Test Instrument", owner=user)

    folder = AnnotationFolder.objects.filter(folder_name="Manuals").first()
    if not folder:
        print("✗ No folder found. Creating one...")
        folder = AnnotationFolder.objects.create(folder_name="Manuals")

    # Create request context
    factory = RequestFactory()
    request = factory.post("/api/instrument-annotations/")
    request.user = user
    force_authenticate(request, user=user)

    # Test data with annotation_data only (NO annotation field)
    data = {
        "instrument": instrument.id,
        "folder": folder.id,
        "annotation_data": {"annotation": "This is a test instrument manual", "annotation_type": "text"},
    }

    print(f"Request data: {data}")

    # Create serializer
    serializer = InstrumentAnnotationSerializer(data=data, context={"request": request})

    # Validate
    if serializer.is_valid():
        print("✓ Serializer is valid")
        instrument_annotation = serializer.save()
        print(f"✓ InstrumentAnnotation created with ID: {instrument_annotation.id}")
        print(f"✓ Annotation text: {instrument_annotation.annotation.annotation}")
        print(f"✓ Annotation type: {instrument_annotation.annotation.annotation_type}")
        return True
    else:
        print("✗ Serializer validation failed!")
        print(f"Errors: {serializer.errors}")
        return False


if __name__ == "__main__":
    print("Testing annotation_data field implementation...")

    result1 = test_session_annotation_with_annotation_data()
    result2 = test_instrument_annotation_with_annotation_data()

    print("\n" + "=" * 50)
    if result1 and result2:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ TESTS FAILED")
        if not result1:
            print("  - SessionAnnotation test failed")
        if not result2:
            print("  - InstrumentAnnotation test failed")
    print("=" * 50)
