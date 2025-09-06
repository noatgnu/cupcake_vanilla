import base64

from django import forms
from django.forms.widgets import ClearableFileInput
from django.utils.html import format_html
from django.utils.safestring import mark_safe


class Base64ImageWidget(ClearableFileInput):
    """
    Custom widget for handling base64 encoded images in Django admin.

    This widget allows uploading image files that get converted to base64,
    and displays existing base64 images as actual images in the admin interface.
    """

    def format_value(self, value):
        """Display base64 image as an actual image if it exists."""
        if value and isinstance(value, str) and value.startswith("data:image/"):
            return value
        return None

    def render(self, name, value, attrs=None, renderer=None):
        """Render the widget with image preview if base64 data exists."""
        html = super().render(name, value, attrs, renderer)

        if value and isinstance(value, str) and value.startswith("data:image/"):
            # Display the current image
            image_html = format_html(
                '<div style="margin-bottom: 10px;">'
                "<p>Current image:</p>"
                '<img src="{}" style="max-width: 200px; max-height: 200px; border: 1px solid #ddd; padding: 5px;" />'
                "</div>",
                value,
            )
            html = image_html + html

        return mark_safe(html)


class Base64ImageField(forms.FileField):
    """
    Custom form field that converts uploaded images to base64.
    """

    widget = Base64ImageWidget

    def to_python(self, data):
        """Convert uploaded file to base64 string."""
        if data is None or data == "":
            return None

        # If it's already a base64 string, return as is
        if isinstance(data, str) and data.startswith("data:image/"):
            return data

        # Handle file upload
        file = super().to_python(data)
        if file is None:
            return None

        # Convert to base64
        try:
            file_content = file.read()
            file_b64 = base64.b64encode(file_content).decode("utf-8")

            # Determine MIME type based on file extension or content
            content_type = getattr(file, "content_type", "image/jpeg")
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"

            return f"data:{content_type};base64,{file_b64}"

        except Exception as e:
            raise forms.ValidationError(f"Error processing image: {str(e)}")
