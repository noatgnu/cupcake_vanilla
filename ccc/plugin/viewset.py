from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ccc.plugin.auth import PluginTokenAuthentication
from ccc.plugin.model import Plugin
from ccc.plugin.permissions import IsPluginAuthenticated
from ccc.plugin.serializer import PluginSerializer


def _broadcast_lifecycle(plugin: Plugin) -> None:
    """Push a lifecycle status change for a plugin to its global channel group."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"plugin__{plugin.id}__global",
        {
            "type": "plugin_lifecycle",
            "plugin_id": plugin.id,
            "plugin_name": plugin.name,
            "lifecycle_status": plugin.lifecycle_status,
            "progress_message": plugin.progress_message,
            "progress_data": plugin.progress_data,
        },
    )


class PluginViewSet(viewsets.ModelViewSet):
    """ViewSet for plugin registration and lifecycle management.

    Admin users register plugins via /api/v1/plugins/register/ and receive a
    startup token.  The token is stored in the plugin's environment file and
    used for all subsequent plugin-originated calls.

    Lifecycle:
      register/           (admin)         → lifecycle set to "installing"
      startup/            (plugin token)  → lifecycle set to "running"
      report-progress/    (plugin token)  → plugin self-reports any stage or progress
      push/               (plugin token)  → plugin broadcasts arbitrary runtime data
    """

    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_authenticators(self):
        """Prepend plugin token auth so plugin-token endpoints work without a user session."""
        return [PluginTokenAuthentication()] + super().get_authenticators()

    def get_permissions(self):
        """Map actions to their required permission classes."""
        if getattr(self, "action", None) in ("startup", "push", "report_progress"):
            return [IsPluginAuthenticated()]
        if self.action in ("destroy", "partial_update", "register", "reset_token"):
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        """Register a new plugin or update an existing one by name.

        Sets lifecycle_status to "installing" so the frontend immediately shows
        that setup is in progress.  Returns the full plugin record including the
        startup token, which the install script writes to the plugin's env file.
        """
        name = request.data.get("name")
        version = request.data.get("version")
        if not name or not version:
            return Response(
                {"error": "name and version are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plugin, created = Plugin.objects.update_or_create(
            name=name,
            defaults={
                "display_name": request.data.get("display_name", name),
                "version": version,
                "description": request.data.get("description", ""),
                "manifest_cache": request.data.get("manifest", {}),
                "base_url": request.data.get("base_url", ""),
                "is_active": True,
                "lifecycle_status": Plugin.LIFECYCLE_INSTALLING,
                "progress_message": "Installing",
            },
        )
        data = self.get_serializer(plugin).data
        if created:
            data["token"] = plugin._plain_token
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="startup")
    def startup(self, request):
        """Called by a plugin process on boot to announce its address and mark itself running.

        Authenticated with the plugin's own startup token (Plugin-Token header).
        Updates base_url, manifest_cache, and lifecycle_status for the calling plugin.
        Broadcasts a lifecycle update to all WebSocket subscribers.
        """
        plugin = request.auth
        update_fields = ["lifecycle_status", "progress_message", "updated_at"]

        base_url = request.data.get("base_url", "")
        manifest = request.data.get("manifest", {})

        if base_url:
            plugin.base_url = base_url
            update_fields.append("base_url")
        if manifest:
            plugin.manifest_cache = manifest
            update_fields.append("manifest_cache")

        plugin.lifecycle_status = Plugin.LIFECYCLE_RUNNING
        plugin.progress_message = "Running"
        plugin.save(update_fields=update_fields)

        _broadcast_lifecycle(plugin)

        return Response(self.get_serializer(plugin).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="report-progress")
    def report_progress(self, request):
        """Report the plugin's own lifecycle stage or operational progress.

        Authenticated with the plugin's own startup token (Plugin-Token header).
        The plugin calls this to communicate what it is doing — initialising
        data, running a migration, entering an error state, etc.  Each call
        broadcasts a lifecycle event so the frontend updates in real time.

        Body:
          lifecycle_status  - one of: installing, starting, running, stopped, error
          progress_message  - short human-readable description of the current stage
          progress_data     - optional dict with structured progress details
        """
        plugin = request.auth
        new_status = request.data.get("lifecycle_status")
        if new_status and new_status not in dict(Plugin.LIFECYCLE_CHOICES):
            return Response(
                {"error": f"Invalid lifecycle_status. Choices: {[c[0] for c in Plugin.LIFECYCLE_CHOICES]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_fields = ["updated_at"]
        if new_status:
            plugin.lifecycle_status = new_status
            update_fields.append("lifecycle_status")
        if "progress_message" in request.data:
            plugin.progress_message = request.data["progress_message"]
            update_fields.append("progress_message")
        if "progress_data" in request.data:
            plugin.progress_data = request.data["progress_data"]
            update_fields.append("progress_data")

        plugin.save(update_fields=update_fields)
        _broadcast_lifecycle(plugin)

        return Response(self.get_serializer(plugin).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="push")
    def push(self, request):
        """Broadcast an arbitrary payload from a running plugin to its subscribers.

        Authenticated with the plugin's own startup token (Plugin-Token header).
        Sends a plugin.message event to the plugin's global channel group so
        frontend components subscribed to this plugin receive the data.

        Body:
          payload  - dict with arbitrary data to forward to the frontend
        """
        plugin = request.auth
        payload = request.data.get("payload", {})

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"plugin__{plugin.id}__global",
            {
                "type": "plugin_message",
                "plugin_id": plugin.id,
                "plugin_name": plugin.name,
                "scope": "global",
                "payload": payload,
            },
        )
        return Response({"sent": True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reset-token")
    def reset_token(self, request, pk=None):
        """Regenerate the startup token for a plugin.

        Admin-only.  Use this after a SECRET_KEY rotation or if a token is
        compromised.  The new plain token is returned once; the plugin env
        file must be updated and the plugin service restarted.
        """
        plugin = self.get_object()
        plugin.token = ""
        plugin.save(update_fields=["token", "updated_at"])
        data = self.get_serializer(plugin).data
        data["token"] = plugin._plain_token
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request, pk=None):
        """Return the cached manifest for a plugin."""
        plugin = self.get_object()
        return Response(plugin.manifest_cache)

    @action(detail=True, methods=["post"], url_path="broadcast")
    def broadcast(self, request, pk=None):
        """Broadcast a message to all WebSocket subscribers of this plugin (admin only)."""
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
