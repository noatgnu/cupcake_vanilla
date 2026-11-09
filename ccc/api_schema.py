"""Request and response shapes of the CUPCAKE Core custom actions, for the OpenAPI schema."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension, OpenApiSerializerExtension
from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from .plugin.model import Plugin
from .plugin.serializer import PluginSerializer
from .serializers import AccountMergeRequestSerializer
from .serializers import AdminPasswordResetSerializer as BaseAdminPasswordResetSerializer
from .serializers import (
    AnnotationFolderSerializer,
    AnnotationSerializer,
    InstalledAppSerializer,
    LabGroupReferenceSerializer,
    UserOrcidProfileSerializer,
    UserSerializer,
    WhisperModelSerializer,
)


class DeviceTokenScheme(OpenApiAuthenticationExtension):
    """Describes DeviceTokenAuthentication, used by registered devices such as the mobile apps."""

    target_class = "ccc.device_token.auth.DeviceTokenAuthentication"
    name = "deviceToken"

    def get_security_definition(self, auto_schema):
        """Header-based token: Authorization: DeviceToken <token>."""
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": 'Device token, sent as "Authorization: DeviceToken <token>"',
        }


class PluginTokenScheme(OpenApiAuthenticationExtension):
    """Describes PluginTokenAuthentication, used by plugin processes for their own calls."""

    target_class = "ccc.plugin.auth.PluginTokenAuthentication"
    name = "pluginToken"

    def get_security_definition(self, auto_schema):
        """Header-based token: Plugin-Token <token>."""
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Plugin-Token",
            "description": "Startup token issued when the plugin was registered",
        }


class FieldErrorsSerializer(serializers.Serializer):
    """Validation errors of a request: each invalid field maps to its messages."""


class FieldErrorsScheme(OpenApiSerializerExtension):
    """Describes FieldErrorsSerializer as a map of field names to lists of messages."""

    target_class = "ccc.api_schema.FieldErrorsSerializer"

    def map_serializer(self, auto_schema, direction):
        """Object whose keys are field names, or non_field_errors, with lists of messages."""
        return {
            "type": "object",
            "description": "Validation errors per field; non_field_errors holds errors about the whole request",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        }


class ErrorSerializer(serializers.Serializer):
    """Error body returned by custom actions."""

    error = serializers.CharField()


class DetailSerializer(serializers.Serializer):
    """Error body in the form DRF uses for its own errors."""

    detail = serializers.CharField()


class CommandOutputSerializer(serializers.Serializer):
    """Output of a command run on the appliance by one of its root helper services."""

    output = serializers.CharField(allow_blank=True)


class StorageConfigSerializer(serializers.Serializer):
    """External storage settings; which fields apply depends on mountType."""

    mountType = serializers.ChoiceField(choices=["usb", "nfs", "smb"])
    label = serializers.CharField(required=False, help_text="Filesystem label of the USB drive (usb)")
    fsType = serializers.CharField(required=False, help_text="Filesystem type, or auto (usb)")
    host = serializers.CharField(required=False, help_text="Server name or address (nfs, smb)")
    share = serializers.CharField(required=False, help_text="Exported path or share name (nfs, smb)")
    username = serializers.CharField(required=False, help_text="SMB username")
    password = serializers.CharField(required=False, help_text="SMB password")


class StorageStatusConfigSerializer(StorageConfigSerializer):
    """Saved storage settings as returned by storage-status, without the password.

    Empty when storage was never configured.
    """

    mountType = serializers.ChoiceField(choices=["usb", "nfs", "smb"], required=False)
    password = None


class StorageStatusSerializer(serializers.Serializer):
    """Whether external storage is mounted, and the saved storage settings."""

    mounted = serializers.BooleanField()
    mount_point = serializers.CharField()
    device = serializers.CharField(allow_blank=True)
    fs_type = serializers.CharField(allow_blank=True)
    config = StorageStatusConfigSerializer()


class ApplyStorageSerializer(serializers.Serializer):
    """Storage settings to save and mount."""

    config = StorageConfigSerializer()


class BlockDeviceSerializer(serializers.Serializer):
    """A partition on a USB drive."""

    name = serializers.CharField(help_text="Device path, for example /dev/sda1")
    label = serializers.CharField(allow_blank=True)
    size = serializers.CharField(allow_blank=True)
    fs_type = serializers.CharField()


class BlockDevicesSerializer(serializers.Serializer):
    """USB partitions that carry a filesystem."""

    devices = BlockDeviceSerializer(many=True)


class RunBackupSerializer(serializers.Serializer):
    """Backup to run and where to write it."""

    backup_type = serializers.ChoiceField(choices=["database", "media", "full"])
    destination = serializers.CharField(help_text="Absolute path under /mnt/cupcake-data/ or /opt/cupcake/backups")


class WifiInterfacesSerializer(serializers.Serializer):
    """Wireless network interfaces of the appliance."""

    interfaces = serializers.ListField(child=serializers.CharField())


class WifiConfigSerializer(serializers.Serializer):
    """Wi-Fi settings; which fields apply depends on authType and eapMethod."""

    ssid = serializers.CharField(max_length=32)
    interfaceName = serializers.CharField()
    authType = serializers.ChoiceField(choices=["wpa2-personal", "wpa2-enterprise"])
    password = serializers.CharField(required=False, help_text="wpa2-personal, or PEAP/TTLS")
    eapMethod = serializers.ChoiceField(choices=["peap", "ttls", "tls"], required=False)
    identity = serializers.CharField(required=False)
    anonymousIdentity = serializers.CharField(required=False)
    phase2Auth = serializers.ChoiceField(choices=["mschapv2", "pap", "chap"], required=False)
    caCertFilename = serializers.CharField(required=False, help_text="Name returned by upload-wifi-cert")
    clientCertFilename = serializers.CharField(required=False, help_text="EAP-TLS; name returned by upload-wifi-cert")
    clientKeyFilename = serializers.CharField(required=False, help_text="EAP-TLS; name returned by upload-wifi-cert")


class WifiStatusConfigSerializer(WifiConfigSerializer):
    """Saved Wi-Fi settings as returned by wifi-status, without the password."""

    password = None


class WifiStatusSerializer(serializers.Serializer):
    """Wi-Fi connection state and the saved settings."""

    hasInterface = serializers.BooleanField()
    interfaceName = serializers.CharField(allow_null=True)
    connected = serializers.BooleanField()
    ssid = serializers.CharField(allow_null=True)
    config = WifiStatusConfigSerializer(allow_null=True)


class TailscaleStatusSerializer(serializers.Serializer):
    """Tailscale on the appliance."""

    installed = serializers.BooleanField()
    configured = serializers.BooleanField(help_text="Logged in to a tailnet")
    connected = serializers.BooleanField()
    state = serializers.CharField(help_text="Tailscale backend state, for example Running or Stopped")
    dns_name = serializers.CharField(help_text="Name of the appliance on the tailnet")
    addresses = serializers.ListField(child=serializers.CharField())
    online = serializers.BooleanField()
    health = serializers.ListField(child=serializers.CharField(), help_text="Warnings Tailscale reports")
    error = serializers.CharField()


class CloudflareStatusSerializer(serializers.Serializer):
    """The Cloudflare tunnel on the appliance."""

    installed = serializers.BooleanField()
    configured = serializers.BooleanField(help_text="Tunnel service enabled")
    active = serializers.BooleanField()
    connected = serializers.BooleanField()
    connections = serializers.IntegerField(help_text="Connections from the tunnel to Cloudflare")
    error = serializers.CharField()


class RemoteAccessStatusSerializer(serializers.Serializer):
    """Remote access set up on the appliance."""

    tailscale = TailscaleStatusSerializer()
    cloudflare = CloudflareStatusSerializer()


class ApplyWifiSerializer(serializers.Serializer):
    """Wi-Fi settings to save and apply."""

    config = WifiConfigSerializer()


class UploadWifiCertSerializer(serializers.Serializer):
    """PEM certificate or key for enterprise Wi-Fi, at most 64 KB."""

    cert_type = serializers.ChoiceField(choices=["ca", "client_cert", "client_key"])
    file = serializers.FileField()


class UploadWifiCertResponseSerializer(serializers.Serializer):
    """Name to use as caCertFilename, clientCertFilename or clientKeyFilename."""

    filename = serializers.CharField()


class PluginNameSerializer(serializers.Serializer):
    """Plugin to act on."""

    name = serializers.RegexField(r"^[a-zA-Z0-9_-]+$")


class PluginInstallSerializer(PluginNameSerializer):
    """Plugin to install and where to fetch it from."""

    source = serializers.CharField(help_text="URL or local path of the plugin")


class PluginControlSerializer(PluginNameSerializer):
    """Service command for a plugin."""

    command = serializers.ChoiceField(choices=["start", "stop", "restart", "enable", "disable"])


class InstalledPluginSerializer(serializers.Serializer):
    """A plugin installed on the appliance and the state of its service."""

    name = serializers.CharField()
    active = serializers.BooleanField()
    enabled = serializers.BooleanField()


class InstalledPluginListSerializer(serializers.Serializer):
    """Plugins installed on the appliance."""

    plugins = InstalledPluginSerializer(many=True)


class PluginServiceStatusSerializer(serializers.Serializer):
    """systemd state of a plugin service, as reported by the plugin manager."""

    ok = serializers.BooleanField()
    active = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)
    output = serializers.CharField(required=False, allow_blank=True)
    error = serializers.CharField(required=False)


class NetworkInfoSerializer(serializers.Serializer):
    """Hostname and routable IPv4 addresses of the appliance."""

    hostname = serializers.CharField()
    addresses = serializers.ListField(child=serializers.IPAddressField(protocol="IPv4"))


ErrorOrFieldErrors = PolymorphicProxySerializer(
    component_name="ErrorOrFieldErrors",
    serializers=[ErrorSerializer, FieldErrorsSerializer],
    resource_type_field_name=None,
)


class ActionMessageSerializer(serializers.Serializer):
    """Confirmation message of a completed action."""

    message = serializers.CharField()


class UserMessageSerializer(ActionMessageSerializer):
    """Confirmation message and the affected user."""

    user = UserSerializer()


class RegistrationStatusSerializer(serializers.Serializer):
    """Whether new users can register themselves."""

    registration_enabled = serializers.BooleanField()
    message = serializers.CharField()


class DefaultTokenLifetimesSerializer(serializers.Serializer):
    """Token lifetimes of a normal login."""

    access_token_minutes = serializers.IntegerField()
    refresh_token_days = serializers.IntegerField()


class RememberMeTokenLifetimesSerializer(serializers.Serializer):
    """Token lifetimes of a login with "remember me"."""

    access_token_hours = serializers.IntegerField()
    refresh_token_days = serializers.IntegerField()


class TokenLifetimesSerializer(serializers.Serializer):
    """Token lifetimes for both kinds of login."""

    default = DefaultTokenLifetimesSerializer()
    remember_me = RememberMeTokenLifetimesSerializer()


class AuthConfigSerializer(serializers.Serializer):
    """Sign-in methods the frontend should offer, and token lifetimes."""

    registration_enabled = serializers.BooleanField()
    orcid_login_enabled = serializers.BooleanField()
    regular_login_enabled = serializers.BooleanField()
    jwt_token_lifetimes = TokenLifetimesSerializer()


class OrcidLinkedSerializer(ActionMessageSerializer):
    """Result of linking an ORCID iD; profile is absent when it was already linked."""

    profile = UserOrcidProfileSerializer(required=False)


class DuplicateAccountsSerializer(serializers.Serializer):
    """Accounts that may belong to the same person."""

    potential_duplicates = UserSerializer(many=True)
    count = serializers.IntegerField()


class MergeRequestSubmittedSerializer(ActionMessageSerializer):
    """Confirmation and the submitted account merge request."""

    request = AccountMergeRequestSerializer()


class EmailChangeRequestedSerializer(ActionMessageSerializer):
    """Confirmation that a verification email was sent to the new address."""

    new_email = serializers.EmailField()


class AdminPasswordResetBodySerializer(BaseAdminPasswordResetSerializer):
    """New password set by an admin; the user is the one in the URL."""

    user_id = None


class FolderContentsSerializer(serializers.Serializer):
    """Folders and annotations directly inside a folder."""

    folders = AnnotationFolderSerializer(many=True)
    annotations = AnnotationSerializer(many=True)


class ScratchToggledSerializer(ActionMessageSerializer):
    """New scratch state of an annotation."""

    scratched = serializers.BooleanField()


class LabGroupInviteSerializer(serializers.Serializer):
    """Person to invite to a lab group by email."""

    invited_email = serializers.EmailField()
    message = serializers.CharField(required=False, allow_blank=True)


class LabGroupMembershipSerializer(serializers.Serializer):
    """Whether a user belongs to a lab group, directly or through a sub-group."""

    is_member = serializers.BooleanField()
    is_direct_member = serializers.BooleanField()
    user_id = serializers.IntegerField()
    user_username = serializers.CharField()


class RemoveMemberSerializer(serializers.Serializer):
    """Member to remove from a lab group."""

    user_id = serializers.IntegerField()


class InvitationAcceptedSerializer(ActionMessageSerializer):
    """Confirmation and the lab group that was joined."""

    lab_group = LabGroupReferenceSerializer()


class PublicSiteConfigSerializer(serializers.Serializer):
    """Site settings shown before signing in."""

    site_name = serializers.CharField()
    logo_url = serializers.CharField(allow_null=True, required=False)
    primary_color = serializers.CharField()
    show_powered_by = serializers.BooleanField()
    allow_user_registration = serializers.BooleanField()
    enable_orcid_login = serializers.BooleanField()
    booking_deletion_window_minutes = serializers.IntegerField()
    ui_features = serializers.DictField(child=serializers.BooleanField())
    installed_apps = serializers.DictField(child=InstalledAppSerializer())
    max_upload_size = serializers.IntegerField()
    max_chunked_upload_size = serializers.IntegerField()
    demo_mode = serializers.BooleanField()
    demo_cleanup_interval_minutes = serializers.IntegerField(allow_null=True)


class WhisperModelListSerializer(serializers.Serializer):
    """Whisper.cpp models found by the transcribe worker at its last scan."""

    models = WhisperModelSerializer(many=True)
    count = serializers.IntegerField()
    message = serializers.CharField(required=False)


class JobQueuedSerializer(serializers.Serializer):
    """A background job that was queued."""

    status = serializers.ChoiceField(choices=["queued"])
    message = serializers.CharField()
    job_id = serializers.CharField()


class WorkerJobSerializer(serializers.Serializer):
    """Job a worker is running."""

    id = serializers.CharField()
    func_name = serializers.CharField()
    created_at = serializers.DateTimeField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    description = serializers.CharField(allow_null=True)


class WorkerSerializer(serializers.Serializer):
    """A background job worker and what it is doing."""

    name = serializers.CharField()
    hostname = serializers.CharField(allow_null=True)
    pid = serializers.IntegerField(allow_null=True)
    state = serializers.CharField()
    queues = serializers.ListField(child=serializers.CharField())
    birth = serializers.DateTimeField(allow_null=True)
    successful_job_count = serializers.IntegerField()
    failed_job_count = serializers.IntegerField()
    total_working_time = serializers.FloatField()
    current_job = WorkerJobSerializer(allow_null=True)


class QueueStatsSerializer(serializers.Serializer):
    """Job counts of a queue, or the error that prevented reading them."""

    count = serializers.IntegerField(required=False)
    failed_count = serializers.IntegerField(required=False)
    scheduled_count = serializers.IntegerField(required=False)
    started_count = serializers.IntegerField(required=False)
    finished_count = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)


class WorkerStatusSerializer(serializers.Serializer):
    """Background job workers and the job counts of each queue."""

    workers = WorkerSerializer(many=True)
    worker_count = serializers.IntegerField()
    queues = serializers.DictField(child=QueueStatsSerializer())


class PluginRegisterSerializer(serializers.Serializer):
    """Plugin to register, or to update when one with the same name exists."""

    name = serializers.CharField()
    version = serializers.CharField()
    display_name = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    manifest = serializers.DictField(required=False, help_text="Plugin manifest, cached by the backend")
    base_url = serializers.CharField(required=False, allow_blank=True)


class PluginWithTokenSerializer(PluginSerializer):
    """Plugin record with its plain startup token, which is only returned once."""

    token = serializers.CharField(
        required=False,
        help_text="Present when the plugin is new or its token was reset; store it, it is not shown again",
    )

    class Meta(PluginSerializer.Meta):
        fields = PluginSerializer.Meta.fields + ["token"]


class PluginStartupSerializer(serializers.Serializer):
    """Address and manifest a plugin announces when it starts."""

    base_url = serializers.CharField(required=False, allow_blank=True)
    manifest = serializers.DictField(required=False)


class PluginProgressSerializer(serializers.Serializer):
    """Stage or progress a plugin reports about itself."""

    lifecycle_status = serializers.ChoiceField(choices=Plugin.LIFECYCLE_CHOICES, required=False)
    progress_message = serializers.CharField(required=False, allow_blank=True)
    progress_data = serializers.DictField(required=False)


class PluginPushSerializer(serializers.Serializer):
    """Data a running plugin sends to the frontends subscribed to it."""

    payload = serializers.DictField()


class PluginCallSerializer(serializers.Serializer):
    """A call to one of the POST endpoints a plugin's manifest declares."""

    endpoint = serializers.CharField(help_text="Endpoint as declared in the manifest, for example /api/submit")
    data = serializers.DictField(required=False, default=dict)


class PluginSentSerializer(serializers.Serializer):
    """Whether the message was handed to the websocket layer."""

    sent = serializers.BooleanField()


class PluginBroadcastSerializer(serializers.Serializer):
    """Message for the websocket subscribers of a plugin."""

    scope = serializers.ChoiceField(choices=["global", "user", "lab_group"], default="global")
    payload = serializers.DictField(required=False)
    user_id = serializers.IntegerField(required=False, help_text="user scope; the current user when omitted")
    lab_group_id = serializers.IntegerField(required=False, help_text="Required for lab_group scope")


class PluginBroadcastResultSerializer(PluginSentSerializer):
    """Whether the message was sent, and to which websocket group."""

    group = serializers.CharField()


class DeviceTokenRotatedSerializer(serializers.Serializer):
    """New value of a device token; the previous one stops working."""

    token = serializers.CharField()


class DeviceTokenToggledSerializer(serializers.Serializer):
    """Whether the device token is now enabled."""

    enabled = serializers.BooleanField()


class DeviceSummarySerializer(serializers.Serializer):
    """Counts shown on a device's home screen; module counts are 0 when that module is not installed."""

    instruments = serializers.IntegerField()
    active_jobs = serializers.IntegerField()
    low_reagents = serializers.IntegerField()
    active_timers = serializers.IntegerField()
    users = serializers.IntegerField()
    lab_groups = serializers.IntegerField()


class LogoutSerializer(serializers.Serializer):
    """Refresh token to revoke; refresh_token is accepted as another name for it."""

    refresh = serializers.CharField()


class CurrentUserDetailsSerializer(serializers.Serializer):
    """Account details of the signed-in user."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    date_joined = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)


class CurrentUserSerializer(serializers.Serializer):
    """The signed-in user."""

    user = CurrentUserDetailsSerializer()
