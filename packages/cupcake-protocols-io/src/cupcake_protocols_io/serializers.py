"""Serializers for protocols.io accounts, exports and runs."""

from rest_framework import serializers

from cupcake_protocols_io.models import ProtocolsIOAccount, ProtocolsIOExport, ProtocolsIORun


class ProtocolsIOAccountSerializer(serializers.ModelSerializer):
    """Connection status of a user's protocols.io account, without the token."""

    class Meta:
        model = ProtocolsIOAccount
        fields = ["username", "name", "connected_at", "last_used_at"]
        read_only_fields = fields


class ProtocolsIOExportSerializer(serializers.ModelSerializer):
    """A protocols.io protocol that a Cupcake protocol was exported into."""

    exported_by_username = serializers.CharField(source="exported_by.username", read_only=True, default=None)

    class Meta:
        model = ProtocolsIOExport
        fields = [
            "id",
            "protocol",
            "session",
            "variation_hash",
            "exported_by",
            "exported_by_username",
            "protocols_io_id",
            "protocols_io_guid",
            "protocols_io_uri",
            "protocols_io_url",
            "step_ids",
            "exported_at",
        ]
        read_only_fields = fields


class ProtocolsIORunSerializer(serializers.ModelSerializer):
    """A protocols.io run that a Cupcake session was exported into."""

    protocol_title = serializers.CharField(source="protocol.protocol_title", read_only=True)
    exported_by_username = serializers.CharField(source="exported_by.username", read_only=True, default=None)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    record_url = serializers.CharField(read_only=True)

    class Meta:
        model = ProtocolsIORun
        fields = [
            "id",
            "session",
            "protocol",
            "protocol_title",
            "protocol_export",
            "exported_by",
            "exported_by_username",
            "record_id",
            "record_guid",
            "record_url",
            "item_id",
            "title",
            "comment_count",
            "created_at",
            "exported_at",
        ]
        read_only_fields = fields


class ProtocolsIOConnectSerializer(serializers.Serializer):
    """protocols.io access token to connect."""

    access_token = serializers.CharField(write_only=True, trim_whitespace=True)
