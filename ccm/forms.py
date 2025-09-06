from django import forms

from .models import Instrument, StorageObject, StoredReagent
from .widgets import Base64ImageField


class InstrumentAdminForm(forms.ModelForm):
    """Custom admin form for Instrument with base64 image handling."""

    image = Base64ImageField(
        required=False, help_text="Upload an image of the instrument (will be converted to base64)"
    )

    class Meta:
        model = Instrument
        fields = "__all__"


class StorageObjectAdminForm(forms.ModelForm):
    """Custom admin form for StorageObject with base64 image handling."""

    png_base64 = Base64ImageField(
        required=False, help_text="Upload an image of the storage location (will be converted to base64)"
    )

    class Meta:
        model = StorageObject
        fields = "__all__"


class StoredReagentAdminForm(forms.ModelForm):
    """Custom admin form for StoredReagent with base64 image handling."""

    png_base64 = Base64ImageField(
        required=False, help_text="Upload an image of the reagent (will be converted to base64)"
    )

    class Meta:
        model = StoredReagent
        fields = "__all__"
