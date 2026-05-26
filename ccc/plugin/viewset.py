from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ccc.plugin.model import Plugin
from ccc.plugin.serializer import PluginSerializer


class PluginViewSet(viewsets.ModelViewSet):
    """ViewSet for plugin/addon registration and management.

    Plugins register by POSTing to /api/v1/plugins/register/.
    The integer id returned is the stable identifier for all subsequent calls.
    Staff users may update or delete plugins; any authenticated user can read.
    """

    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        """Staff required for mutations other than register."""
        if self.action in ("destroy", "partial_update"):
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        """Register or update a plugin. Returns the plugin record including its id."""
        name = request.data.get("name")
        version = request.data.get("version")
        if not name or not version:
            return Response({"error": "name and version are required"}, status=status.HTTP_400_BAD_REQUEST)

        plugin, _ = Plugin.objects.update_or_create(
            name=name,
            defaults={
                "display_name": request.data.get("display_name", name),
                "version": version,
                "description": request.data.get("description", ""),
                "manifest_cache": request.data.get("manifest", {}),
                "base_url": request.data.get("base_url", ""),
                "is_active": True,
            },
        )
        serializer = self.get_serializer(plugin)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request, pk=None):
        """Return the cached manifest for a plugin."""
        plugin = self.get_object()
        return Response(plugin.manifest_cache)

    @action(detail=True, methods=["post"], url_path="broadcast")
    def broadcast(self, request, pk=None):
        """Broadcast a message to all subscribers of this plugin's channel group."""
        plugin = self.get_object()
        payload = request.data.get("payload", {})
        scope = request.data.get("scope", "global")

        if scope == "global":
            group_name = f"plugin__{plugin.id}__global"
        elif scope == "user":
            user_id = request.data.get("user_id", request.user.id)
            group_name = f"plugin__{plugin.id}__user_{user_id}"
        elif scope == "lab_group":
            lab_group_id = request.data.get("lab_group_id")
            if not lab_group_id:
                return Response(
                    {"error": "lab_group_id required for lab_group scope"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            group_name = f"plugin__{plugin.id}__lab_group_{lab_group_id}"
        else:
            return Response(
                {"error": "scope must be global, user, or lab_group"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "plugin_message",
                "plugin_id": plugin.id,
                "plugin_name": plugin.name,
                "scope": scope,
                "payload": payload,
            },
        )
        return Response({"sent": True, "group": group_name})
