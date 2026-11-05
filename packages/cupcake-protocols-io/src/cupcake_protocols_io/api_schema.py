"""Request and response shapes of the protocols.io endpoints, for the OpenAPI schema."""

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from cupcake_protocols_io.serializers import ProtocolsIOExportSerializer, ProtocolsIORunSerializer


class SingleObjectSchema(AutoSchema):
    """Schema for views whose list action returns one object."""

    def _is_list_view(self, serializer=None):
        return False


class ImportByUrlSerializer(serializers.Serializer):
    """A protocols.io address or DOI link."""

    url = serializers.CharField()


class ImportFromAccountSerializer(serializers.Serializer):
    """The address, URI or id of a protocols.io protocol the user can open."""

    protocol = serializers.CharField()


class ProtocolExportRequestSerializer(serializers.Serializer):
    """The protocols.io protocol to export into."""

    target = serializers.CharField(help_text="Address, URI, id or GUID of the protocols.io protocol")
    scaling_factor = serializers.FloatField(default=1.0, help_text="Factor for scalable reagents")


class ExportQueuedSerializer(serializers.Serializer):
    """The queued export task."""

    task_id = serializers.UUIDField()
    message = serializers.CharField()


class SessionExportRequestSerializer(serializers.Serializer):
    """Which protocols of the session to export, and where."""

    protocols = serializers.ListField(
        child=serializers.IntegerField(), required=False, help_text="Every protocol of the session when omitted"
    )
    new_runs = serializers.BooleanField(default=False, help_text="Create new runs instead of updating earlier ones")
    folder = serializers.CharField(required=False, help_text="GUID of the protocols.io folder for new runs")
    session_url = serializers.URLField(required=False, help_text="Address of the session in Cupcake")


class ProtocolsNotExportedSerializer(serializers.Serializer):
    """Protocols that must be exported before the session."""

    error = serializers.CharField()
    protocols_not_exported = serializers.ListField(child=serializers.CharField())


class SessionExportStatusSerializer(serializers.Serializer):
    """How one protocol of the session would be exported."""

    protocol = serializers.IntegerField()
    protocol_title = serializers.CharField()
    protocol_export = ProtocolsIOExportSerializer(allow_null=True)
    varied_steps = serializers.IntegerField()
    run = ProtocolsIORunSerializer(allow_null=True)
    run_is_current = serializers.BooleanField()


class AccountStatusSerializer(serializers.Serializer):
    """Whether the user has a connected protocols.io account, and which one."""

    connected = serializers.BooleanField()
    username = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    connected_at = serializers.DateTimeField(required=False)
    last_used_at = serializers.DateTimeField(required=False, allow_null=True)


class ProtocolsIOErrorSerializer(serializers.Serializer):
    """An error, with the protocols.io message when the request to protocols.io failed."""

    error = serializers.CharField()
    detail = serializers.CharField(required=False)


class BrowsePageSerializer(serializers.Serializer):
    """Paging of a protocols.io listing."""

    page = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    total_results = serializers.IntegerField()
    has_next = serializers.BooleanField()


class WorkspaceSerializer(serializers.Serializer):
    """A protocols.io workspace."""

    uri = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)


class WorkspacePageSerializer(BrowsePageSerializer):
    """A page of the user's workspaces."""

    items = WorkspaceSerializer(many=True)


class WorkspaceReferenceSerializer(serializers.Serializer):
    """The workspace an item belongs to."""

    id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField(allow_blank=True)


class FolderEntrySerializer(serializers.Serializer):
    """A protocols.io folder."""

    kind = serializers.ChoiceField(choices=["folder"])
    title = serializers.CharField(allow_blank=True)
    guid = serializers.CharField(allow_blank=True)
    parent_guid = serializers.CharField(allow_null=True)
    has_subfolders = serializers.BooleanField()
    workspace = WorkspaceReferenceSerializer()


class ProtocolEntrySerializer(serializers.Serializer):
    """A protocols.io protocol."""

    kind = serializers.ChoiceField(choices=["protocol"])
    title = serializers.CharField(allow_blank=True)
    id = serializers.IntegerField(allow_null=True)
    uri = serializers.CharField(allow_blank=True)
    protocol_type = serializers.CharField()
    importable = serializers.BooleanField()
    last_modified = serializers.IntegerField(allow_null=True)
    workspace = WorkspaceReferenceSerializer()


class BrowseItemsPageSerializer(BrowsePageSerializer):
    """A page of folders and protocols."""

    items = PolymorphicProxySerializer(
        component_name="ProtocolsIOBrowseItem",
        serializers={"folder": FolderEntrySerializer, "protocol": ProtocolEntrySerializer},
        resource_type_field_name="kind",
        many=True,
    )
