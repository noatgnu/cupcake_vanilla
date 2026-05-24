from django.utils import timezone

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from ccc.device_token.model import DeviceToken


class DeviceTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b"devicetoken":
            return None
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid DeviceToken header format.")
        try:
            token = DeviceToken.objects.select_related("user").get(token=auth[1].decode(), enabled=True)
        except DeviceToken.DoesNotExist:
            raise AuthenticationFailed("Invalid or disabled device token.")
        if token.is_expired():
            raise AuthenticationFailed("Device token has expired.")
        DeviceToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return (token.user, token)

    def authenticate_header(self, request):
        return "DeviceToken"
