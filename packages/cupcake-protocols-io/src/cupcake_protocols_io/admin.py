"""Admin pages for protocols.io accounts, exports and runs."""

from django.contrib import admin

from cupcake_protocols_io.models import ProtocolsIOAccount, ProtocolsIOExport, ProtocolsIORun


@admin.register(ProtocolsIOAccount)
class ProtocolsIOAccountAdmin(admin.ModelAdmin):
    """Admin interface for users' protocols.io accounts. Tokens are not shown."""

    list_display = ["user", "username", "name", "connected_at", "last_used_at"]
    search_fields = ["user__username", "username", "name"]
    fields = ["user", "username", "name", "connected_at", "updated_at", "last_used_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        """Accounts cannot be added from the admin."""
        return False


@admin.register(ProtocolsIOExport)
class ProtocolsIOExportAdmin(admin.ModelAdmin):
    """Admin interface for protocols.io protocols that Cupcake protocols were exported into."""

    list_display = ["protocol", "protocols_io_uri", "exported_by", "exported_at"]
    search_fields = ["protocol__protocol_title", "protocols_io_uri", "protocols_io_guid"]
    readonly_fields = [
        "protocol",
        "exported_by",
        "protocols_io_id",
        "protocols_io_guid",
        "protocols_io_uri",
        "protocols_io_url",
        "step_ids",
        "exported_at",
    ]

    def has_add_permission(self, request):
        """Exports cannot be added from the admin."""
        return False


@admin.register(ProtocolsIORun)
class ProtocolsIORunAdmin(admin.ModelAdmin):
    """Admin interface for protocols.io runs that Cupcake sessions were exported into."""

    list_display = ["session", "title", "record_guid", "exported_by", "exported_at"]
    search_fields = ["session__name", "title", "record_guid"]
    readonly_fields = [
        "session",
        "protocol",
        "protocol_export",
        "exported_by",
        "record_id",
        "record_guid",
        "item_id",
        "title",
        "step_map",
        "reference_comment_id",
        "created_at",
        "exported_at",
    ]

    def has_add_permission(self, request):
        """Runs cannot be added from the admin."""
        return False
