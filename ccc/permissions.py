from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOwnerOrReadOnly(BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    Assumes the model instance has an `owner` attribute.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the object.
        return obj.owner == request.user


class IsLabMemberOrReadOnly(BasePermission):
    """
    Custom permission to only allow members of a lab group to edit objects.
    Assumes the model instance has a `lab_group` attribute with a `members` ManyToMany field.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in SAFE_METHODS:
            return True

        # Write permissions are only allowed to members of the lab group (includes bubble-up from sub-groups).
        return obj.lab_group.is_member(request.user)


class IsEditorOrReadOnly(BasePermission):
    """
    Custom permission to only allow users with 'editor' role to edit objects.

    Assumes the model instance has an `editors` attribute.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in SAFE_METHODS:
            return True

        # Write permissions are only allowed to users with 'editor' role.
        return request.user in obj.editors.all()


class IsOwnerEditorViewerOrNoAccess(BasePermission):
    """
    Custom permission with role-based access control.

    Allows owners full access, editors read/write, viewers read-only, and others no access.
    Assumes the model instance has `owner`, `editors`, and `viewers` attributes.
    """

    def has_object_permission(self, request, view, obj):
        # Owners have full access
        if obj.owner == request.user:
            return True

        # Editors have read/write access
        if request.user in obj.editors.all():
            if request.method in SAFE_METHODS or request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                return True

        # Viewers have read-only access
        if request.user in obj.viewers.all():
            if request.method in SAFE_METHODS:
                return True

        # Others have no access
        return False


class IsAdminUser(BasePermission):
    """
    Custom permission to only allow admin users (staff + active) to access.

    This is a more robust version of DRF's IsAdminUser that ensures the user
    is both staff and active.
    """

    def has_permission(self, request, view):
        """
        Return True if user is authenticated, active, and staff.
        """
        return bool(request.user and request.user.is_authenticated and request.user.is_active and request.user.is_staff)

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission for admin users.
        """
        return self.has_permission(request, view)
