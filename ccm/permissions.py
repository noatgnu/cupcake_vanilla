"""
Permission classes for CCM models.
"""

from rest_framework.permissions import BasePermission


class InstrumentJobPermission(BasePermission):
    """
    Permission class for InstrumentJob model.

    Rules:
    - Draft status: Only job owner can edit/delete
    - After draft: Only assigned lab_group members or assigned staff can edit
    - View: Job owner, assigned staff, lab_group members, and system staff
    """

    def has_object_permission(self, request, view, obj):
        """
        Check permissions for InstrumentJob access.

        Args:
            request: HTTP request
            view: View instance
            obj: InstrumentJob instance

        Returns:
            bool: True if user has permission
        """
        user = request.user
        is_read_only = request.method in ["GET", "HEAD", "OPTIONS"]

        if is_read_only:
            return obj.can_view(user)
        elif request.method == "DELETE":
            return obj.can_delete(user)
        else:
            return obj.can_edit(user)
