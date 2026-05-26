from rest_framework import serializers

from ccc.plugin.model import Plugin


class PluginSerializer(serializers.ModelSerializer):
    """Serializer for Plugin model."""

    class Meta:
        model = Plugin
        fields = [
            "id",
            "name",
            "display_name",
            "version",
            "description",
            "manifest_cache",
            "base_url",
            "is_active",
            "registered_at",
            "updated_at",
        ]
        read_only_fields = ["id", "registered_at", "updated_at"]
