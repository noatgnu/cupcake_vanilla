from rest_framework.permissions import SAFE_METHODS, BasePermission

from ccc.device_token.model import DeviceToken


class IsDeviceTokenAuthenticated(BasePermission):
    def has_permission(self, request, view):
        if not isinstance(request.auth, DeviceToken):
            return True
        if request.auth.permission == DeviceToken.PERMISSION_READ:
            return request.method in SAFE_METHODS
        return True
