"""
Permission classes for CCM models.
"""

from django.db.models import Q

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import InstrumentPermission


def session_reader_q(user, prefix):
    """Rows linked to a session the user owns, edits or views, or a public session the user opened by its link."""
    return (
        Q(**{f"{prefix}owner": user})
        | Q(**{f"{prefix}editors": user})
        | Q(**{f"{prefix}viewers": user})
        | Q(**{f"{prefix}enabled": True, f"{prefix}link_unlocked_by": user})
    )


def booking_in_readable_session_q(user, prefix=""):
    """Bookings linked from step or session annotations of sessions the user can read."""
    return session_reader_q(user, f"{prefix}step_annotation_links__step_annotation__session__") | session_reader_q(
        user, f"{prefix}session_annotation_links__session_annotation__session__"
    )


def instrument_viewer_q(user, prefix=""):
    """Instruments the user can see: own vaulted ones, and enabled ones they own or hold view permission on."""
    permitted = InstrumentPermission.objects.filter(user=user, can_view=True).values("instrument_id")
    return Q(**{f"{prefix}user": user, f"{prefix}is_vaulted": True}) | (
        Q(**{f"{prefix}enabled": True}) & (Q(**{f"{prefix}user": user}) | Q(**{f"{prefix}id__in": permitted}))
    )


def instrument_manager_q(user, prefix=""):
    """Enabled instruments the user owns or holds manage permission on."""
    managed = InstrumentPermission.objects.filter(user=user, can_manage=True).values("instrument_id")
    return Q(**{f"{prefix}enabled": True}) & (Q(**{f"{prefix}user": user}) | Q(**{f"{prefix}id__in": managed}))


def reads_one_object(view):
    """Whether the request reads a single object."""
    return view.request.method in SAFE_METHODS and bool(view.detail)


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
