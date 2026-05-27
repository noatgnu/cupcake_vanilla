from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ccc.plugin.model import Plugin


class PluginTokenAuthentication(BaseAuthentication):
    """Authenticate a plugin process using its startup token.

    Expects the header:  Plugin-Token: <plain-token>
    The plain token is hashed via HMAC-SHA256 (keyed with SECRET_KEY) and
    compared against the stored hash via a direct DB lookup.
    Returns (None, plugin) so request.auth is the Plugin instance.
    """

    def authenticate(self, request):
        raw = request.META.get("HTTP_PLUGIN_TOKEN", "").strip()
        if not raw:
            return None
        token_hash = Plugin.hash_token(raw)
        try:
            plugin = Plugin.objects.get(token=token_hash, is_active=True)
        except Plugin.DoesNotExist:
            raise AuthenticationFailed("Invalid or inactive plugin token.")
        return (None, plugin)

    def authenticate_header(self, request):
        return "Plugin-Token"
