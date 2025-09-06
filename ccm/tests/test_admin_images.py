import base64

from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.test import TestCase

from ..admin import InstrumentAdmin, StorageObjectAdmin, StoredReagentAdmin
from ..forms import InstrumentAdminForm, StorageObjectAdminForm, StoredReagentAdminForm
from ..models import Instrument, StorageObject, StoredReagent
from ..widgets import Base64ImageField


class AdminImageFunctionalityTestCase(TestCase):
    """Test cases for admin interface image functionality."""

    def setUp(self):
        self.user = User.objects.create_superuser("admin", "admin@test.com", "password")

        # Create sample base64 image data (minimal PNG)
        # This is a 1x1 transparent PNG
        png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
        self.sample_b64_image = f"data:image/png;base64,{base64.b64encode(png_data).decode('utf-8')}"

    def test_instrument_admin_image_preview(self):
        """Test that instrument admin displays image preview correctly."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument", image=self.sample_b64_image)

        admin_instance = InstrumentAdmin(Instrument, site)
        preview_html = admin_instance.image_preview(instrument)

        self.assertIn('<img src="data:image/png;base64,', preview_html)
        self.assertIn("max-width: 50px", preview_html)

    def test_instrument_admin_no_image(self):
        """Test instrument admin when no image is present."""
        instrument = Instrument.objects.create(instrument_name="Test Instrument")

        admin_instance = InstrumentAdmin(Instrument, site)
        preview_html = admin_instance.image_preview(instrument)

        self.assertEqual(preview_html, "No image")

    def test_storage_object_admin_image_preview(self):
        """Test that storage object admin displays image preview correctly."""
        storage = StorageObject.objects.create(object_name="Test Storage", png_base64=self.sample_b64_image)

        admin_instance = StorageObjectAdmin(StorageObject, site)
        preview_html = admin_instance.image_preview(storage)

        self.assertIn('<img src="data:image/png;base64,', preview_html)
        self.assertIn("max-width: 50px", preview_html)

    def test_stored_reagent_admin_image_preview(self):
        """Test that stored reagent admin displays image preview correctly."""
        reagent = StoredReagent.objects.create(png_base64=self.sample_b64_image)

        admin_instance = StoredReagentAdmin(StoredReagent, site)
        preview_html = admin_instance.image_preview(reagent)

        self.assertIn('<img src="data:image/png;base64,', preview_html)
        self.assertIn("max-width: 50px", preview_html)

    def test_base64_image_field_validation(self):
        """Test that Base64ImageField properly validates data."""
        field = Base64ImageField()

        # Test with valid base64 image
        result = field.to_python(self.sample_b64_image)
        self.assertEqual(result, self.sample_b64_image)

        # Test with None
        result = field.to_python(None)
        self.assertIsNone(result)

        # Test with empty string
        result = field.to_python("")
        self.assertIsNone(result)

    def test_instrument_admin_form_includes_image_field(self):
        """Test that InstrumentAdminForm includes the custom image field."""
        form = InstrumentAdminForm()
        self.assertIn("image", form.fields)
        self.assertIsInstance(form.fields["image"], Base64ImageField)

    def test_storage_object_admin_form_includes_image_field(self):
        """Test that StorageObjectAdminForm includes the custom image field."""
        form = StorageObjectAdminForm()
        self.assertIn("png_base64", form.fields)
        self.assertIsInstance(form.fields["png_base64"], Base64ImageField)

    def test_stored_reagent_admin_form_includes_image_field(self):
        """Test that StoredReagentAdminForm includes the custom image field."""
        form = StoredReagentAdminForm()
        self.assertIn("png_base64", form.fields)
        self.assertIsInstance(form.fields["png_base64"], Base64ImageField)

    def test_admin_list_display_includes_image_preview(self):
        """Test that admin list_display includes image_preview."""
        instrument_admin = InstrumentAdmin(Instrument, site)
        storage_admin = StorageObjectAdmin(StorageObject, site)
        stored_reagent_admin = StoredReagentAdmin(StoredReagent, site)

        self.assertIn("image_preview", instrument_admin.list_display)
        self.assertIn("image_preview", storage_admin.list_display)
        self.assertIn("image_preview", stored_reagent_admin.list_display)

    def test_admin_readonly_fields_includes_image_preview(self):
        """Test that admin readonly_fields includes image_preview."""
        instrument_admin = InstrumentAdmin(Instrument, site)
        storage_admin = StorageObjectAdmin(StorageObject, site)
        stored_reagent_admin = StoredReagentAdmin(StoredReagent, site)

        self.assertIn("image_preview", instrument_admin.readonly_fields)
        self.assertIn("image_preview", storage_admin.readonly_fields)
        self.assertIn("image_preview", stored_reagent_admin.readonly_fields)

    def test_admin_uses_custom_forms(self):
        """Test that admin classes use the custom forms."""
        instrument_admin = InstrumentAdmin(Instrument, site)
        storage_admin = StorageObjectAdmin(StorageObject, site)
        stored_reagent_admin = StoredReagentAdmin(StoredReagent, site)

        self.assertEqual(instrument_admin.form, InstrumentAdminForm)
        self.assertEqual(storage_admin.form, StorageObjectAdminForm)
        self.assertEqual(stored_reagent_admin.form, StoredReagentAdminForm)
