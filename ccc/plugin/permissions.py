from rest_framework.permissions import BasePermission

from ccc.plugin.model import Plugin


class IsPluginAuthenticated(BasePermission):
    """Allow access only when the request is authenticated via a plugin token."""

    def has_permission(self, request, view):
        return isinstance(request.auth, Plugin)
